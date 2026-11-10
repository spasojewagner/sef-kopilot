"""An organization's key to SEF (ADR-0050): an owner sets, replaces and removes it, sealed under
``SEF_FERNET_KEY``; every member sees since when it is set, and nobody sees the key, in an
answer, a log line or the audit log. The keyring that seals it, its rotation, and the settings
it comes from. Who may call what, across organizations, is checked in ``test_access_control.py``.
"""

from __future__ import annotations

import base64
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Database, get_session
from sef_api.main import create_app
from sef_api.models import AuditAction, AuditEvent, SefKey
from sef_api.sef import rotate
from sef_api.sef.keys import Keyring, UnreadableKeyError
from sef_api.settings import Settings

from .conftest import TEST_FERNET_KEY, settings_for
from .factories import KEYRING, Office, office, sef_key

KEY = "4711-4711-4711-4711"
#: Another Fernet key, of 32 bytes all "next", which the tests rotate to.
NEXT_FERNET_KEY = base64.urlsafe_b64encode(b"next" * 8).decode()


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def stored(session: AsyncSession, primer: Office) -> SefKey | None:
    return await session.scalar(
        select(SefKey).where(SefKey.organization_id == primer.organization.id)
    )


async def recorded(session: AsyncSession) -> list[tuple[str, dict[str, Any]]]:
    events = await session.scalars(
        select(AuditEvent).where(
            AuditEvent.action.in_([AuditAction.SEF_KEY_SET, AuditAction.SEF_KEY_REMOVED])
        )
    )
    return sorted(((event.action, event.detail) for event in events), key=str)


# --- setting, replacing and removing -------------------------------------------------------------


async def test_an_owner_sets_the_key_sealed_and_every_member_sees_since_when(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    setting = await api.put(
        "/organization/sef-key", json={"api_key": f"  {KEY}\n"}, headers=primer.as_owner()
    )
    shown = await api.get("/organization", headers=primer.as_client())

    assert setting.status_code == 200
    assert shown.json()["sef_key_set_at"] == setting.json()["set_at"]
    sealed = await stored(session, primer)
    assert sealed is not None
    assert KEY not in sealed.token
    assert KEYRING.open(primer.organization.id, sealed.token).get_secret_value() == KEY
    event = await session.scalar(select(AuditEvent))
    assert event is not None
    assert (event.action, event.actor, event.detail) == (
        AuditAction.SEF_KEY_SET,
        primer.owner.id,
        {"replaced": False},
    )


async def test_a_new_key_replaces_the_one_before(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    for key in (KEY, "0815-0815-0815-0815"):
        response = await api.put(
            "/organization/sef-key", json={"api_key": key}, headers=primer.as_owner()
        )
        assert response.status_code == 200

    sealed = await stored(session, primer)
    assert sealed is not None
    assert KEYRING.open(primer.organization.id, sealed.token).get_secret_value() == (
        "0815-0815-0815-0815"
    )
    assert await recorded(session) == [
        (AuditAction.SEF_KEY_SET, {"replaced": False}),
        (AuditAction.SEF_KEY_SET, {"replaced": True}),
    ]


async def test_an_owner_removes_the_key_and_removing_none_records_nothing(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    await sef_key(session, primer.organization, KEY)

    removals = [
        await api.delete("/organization/sef-key", headers=primer.as_owner()) for _ in range(2)
    ]
    shown = await api.get("/organization", headers=primer.as_owner())

    assert [removal.status_code for removal in removals] == [204, 204]
    assert shown.json()["sef_key_set_at"] is None
    assert await stored(session, primer) is None
    assert await recorded(session) == [(AuditAction.SEF_KEY_REMOVED, {})]


async def test_an_organization_without_a_key_shows_none(api: AsyncClient, primer: Office) -> None:
    response = await api.get("/organization", headers=primer.as_accountant())

    assert response.json()["sef_key_set_at"] is None


async def test_the_key_is_answered_logged_and_recorded_nowhere(
    api: AsyncClient,
    session: AsyncSession,
    primer: Office,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)

    answers = [
        await api.put("/organization/sef-key", json={"api_key": KEY}, headers=primer.as_owner()),
        await api.put("/organization/sef-key", json={"api_key": KEY}, headers=primer.as_owner()),
        await api.get("/organization", headers=primer.as_owner()),
        await api.delete("/organization/sef-key", headers=primer.as_owner()),
    ]

    assert [KEY in answer.text for answer in answers] == [False] * 4
    assert KEY not in caplog.text
    events = [
        (getattr(record, "event", None), getattr(record, "fields", {}))
        for record in caplog.records
        if record.name == "sef_api.security"
    ]
    who = {"organization": str(primer.organization.id), "user": str(primer.owner.id)}
    assert events == [
        ("sef-key.set", who | {"replaced": False}),
        ("sef-key.set", who | {"replaced": True}),
        ("sef-key.removed", who),
    ]
    assert KEY not in str(await recorded(session))


@pytest.mark.parametrize(
    "body",
    [
        {"api_key": "ab-4711"},
        {"api_key": "primer sef 4711"},
        {"api_key": "primer-ključ-4711"},
        {"api_key": "primer-4711-" + "x" * 189},
        {"api_key": 47114711},
        {"key": KEY},
    ],
    ids=["too short", "a space within", "not ASCII", "too long", "not a string", "misnamed"],
)
async def test_a_key_that_is_no_key_is_refused_without_repeating_it(
    api: AsyncClient, session: AsyncSession, primer: Office, body: dict[str, Any]
) -> None:
    response = await api.put("/organization/sef-key", json=body, headers=primer.as_owner())

    assert response.status_code == 422
    assert "4711" not in response.text
    assert await stored(session, primer) is None
    assert await recorded(session) == []


async def test_without_sef_fernet_key_no_key_can_be_set(
    session: AsyncSession, primer: Office
) -> None:
    app = create_app(settings_for())
    app.state.sef_keys = None  # as without SEF_FERNET_KEY

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        setting = await api.put(
            "/organization/sef-key", json={"api_key": KEY}, headers=primer.as_owner()
        )
        shown = await api.get("/organization", headers=primer.as_owner())
    await app.state.database.engine.dispose()

    assert (setting.status_code, setting.json()) == (
        503,
        {"detail": "SEF keys cannot be set on this server: SEF_FERNET_KEY is not set"},
    )
    assert (shown.status_code, shown.json()["sef_key_set_at"]) == (200, None)


async def test_the_table_holds_no_key_in_the_clear(session: AsyncSession, primer: Office) -> None:
    session.add(SefKey(organization_id=primer.organization.id, token=KEY))

    with pytest.raises(IntegrityError, match="ck_sef_keys_token_is_fernet"):
        await session.flush()


# --- the keyring -------------------------------------------------------------------------------

PRIMER_ID, OGLED_ID = uuid.uuid4(), uuid.uuid4()


def test_a_key_opens_for_its_own_organization_only() -> None:
    primer_id, ogled_id = PRIMER_ID, OGLED_ID
    token = KEYRING.seal(primer_id, SecretStr(KEY))

    assert KEYRING.open(primer_id, token).get_secret_value() == KEY
    with pytest.raises(UnreadableKeyError, match="sealed for another organization"):
        KEYRING.open(ogled_id, token)


@pytest.mark.parametrize(
    "token",
    ["gAAAAABnot-a-token", "", "4711-4711-4711-4711", "ključ"],
    ids=["damaged", "empty", "in the clear", "not ASCII"],
)
def test_a_token_that_is_none_does_not_open(token: str) -> None:
    with pytest.raises(UnreadableKeyError, match="cannot be opened with SEF_FERNET_KEY"):
        KEYRING.open(PRIMER_ID, token)


def test_a_key_under_another_secret_does_not_open() -> None:
    token = Keyring((NEXT_FERNET_KEY,)).seal(PRIMER_ID, SecretStr(KEY))

    with pytest.raises(UnreadableKeyError, match="cannot be opened"):
        KEYRING.open(PRIMER_ID, token)


def test_while_rotating_the_first_key_seals_and_each_opens() -> None:
    primer_id = PRIMER_ID
    old = KEYRING.seal(primer_id, SecretStr(KEY))
    rotating = Keyring((NEXT_FERNET_KEY, TEST_FERNET_KEY))
    only_the_next = Keyring((NEXT_FERNET_KEY,))

    assert rotating.open(primer_id, old).get_secret_value() == KEY
    assert only_the_next.open(primer_id, rotating.seal(primer_id, SecretStr(KEY)))
    assert only_the_next.open(primer_id, rotating.reseal(old)).get_secret_value() == KEY
    with pytest.raises(UnreadableKeyError):
        only_the_next.reseal(old)


# --- rotation of the stored keys -----------------------------------------------------------------


@pytest.fixture
async def two_keys(committed_database: Database) -> dict[uuid.UUID, str]:
    """Primer's and Ogled's keys, sealed under the test key, committed."""
    async with committed_database.sessions() as session:
        primer = await office(session, "Primer Računovodstvo", "primer.example")
        ogled = await office(session, "Ogled", "ogled.example")
        await sef_key(session, primer.organization, KEY)
        await sef_key(session, ogled.organization, "0815-0815-0815-0815")
        await session.commit()
    return {primer.organization.id: KEY, ogled.organization.id: "0815-0815-0815-0815"}


async def opened(database: Database, keyring: Keyring) -> dict[Any, str]:
    async with database.sessions() as session:
        rows = await session.execute(select(SefKey.organization_id, SefKey.token))
        return {
            organization_id: keyring.open(organization_id, token).get_secret_value()
            for organization_id, token in rows.all()
        }


async def test_rotation_seals_every_stored_key_again_under_the_first(
    committed_database: Database, two_keys: dict[uuid.UUID, str]
) -> None:
    resealed = await rotate.reseal_every_key(
        committed_database, Keyring((NEXT_FERNET_KEY, TEST_FERNET_KEY))
    )

    assert resealed == 2
    assert await opened(committed_database, Keyring((NEXT_FERNET_KEY,))) == two_keys


async def test_a_key_that_does_not_open_stops_the_rotation_and_nothing_changes(
    committed_database: Database, two_keys: dict[uuid.UUID, str]
) -> None:
    """One organization's row holds a key sealed for the other."""
    primer_id, ogled_id = two_keys
    async with committed_database.sessions() as session:
        row = await session.get(SefKey, primer_id)
        assert row is not None
        row.token = KEYRING.seal(ogled_id, SecretStr(KEY))
        await session.commit()
    before = await stored_tokens(committed_database)

    with pytest.raises(UnreadableKeyError, match="1 of 2 stored keys cannot be opened"):
        await rotate.reseal_every_key(
            committed_database, Keyring((NEXT_FERNET_KEY, TEST_FERNET_KEY))
        )

    assert await stored_tokens(committed_database) == before


async def stored_tokens(database: Database) -> dict[Any, str]:
    async with database.sessions() as session:
        return dict((await session.execute(select(SefKey.organization_id, SefKey.token))).all())


def test_the_rotation_command_says_what_it_did(
    database_url: str,
    two_keys: dict[uuid.UUID, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    rotating = f"{NEXT_FERNET_KEY}, {TEST_FERNET_KEY}"
    monkeypatch.setattr(
        rotate, "Settings", lambda: settings_for(database_url, SEF_FERNET_KEY=rotating)
    )

    assert rotate.main() == 0
    assert capsys.readouterr().out == (
        "sealed 2 keys again under the first key of SEF_FERNET_KEY\n"
    )


def test_the_rotation_command_needs_the_secret(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    without = Settings.from_values({"SEF_ENVIRONMENT": "test"})
    monkeypatch.setattr(rotate, "Settings", lambda: without)

    assert rotate.main() == 1
    assert capsys.readouterr().err == "error: SEF_FERNET_KEY is not set\n"


# --- the settings ------------------------------------------------------------------------------


def test_the_settings_take_one_key_or_several_and_refuse_what_is_none() -> None:
    assert settings_for().fernet_keys == (TEST_FERNET_KEY,)
    rotating = settings_for(SEF_FERNET_KEY=f"{NEXT_FERNET_KEY} , {TEST_FERNET_KEY}")
    assert rotating.fernet_keys == (NEXT_FERNET_KEY, TEST_FERNET_KEY)
    assert Settings.from_values({"SEF_ENVIRONMENT": "test"}).fernet_keys == ()
    for wrong in ("not-a-fernet-key-4711", f"{TEST_FERNET_KEY},", "4711" * 11):
        with pytest.raises(ValidationError, match="SEF_FERNET_KEY must be a Fernet key") as raised:
            settings_for(SEF_FERNET_KEY=wrong)
        assert "4711" not in str(raised.value)
