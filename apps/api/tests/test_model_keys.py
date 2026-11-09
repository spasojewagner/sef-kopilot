"""An organization's own key to a language model's provider (ADR-0058): an owner sets, replaces
and removes it, sealed under ``SEF_FERNET_KEY`` for that purpose and rotated with it; every
member sees which provider and model are set, and nobody the key."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Database, get_session
from sef_api.main import create_app
from sef_api.models import AuditAction, AuditEvent, ModelKey
from sef_api.rag.explainer import Explainer
from sef_api.repairs.repairer import Repairer
from sef_api.sef import rotate
from sef_api.sef.keys import Keyring, UnreadableKeyError

from .conftest import TEST_FERNET_KEY, settings_for
from .corpora import QuotingModel, ScriptedModel
from .factories import KEYRING, Office, model_key, office, sef_key

KEY = "sk-own-4711-4711-4711"
OTHER_FERNET_KEY = base64.urlsafe_b64encode(b"else" * 8).decode()


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


@asynccontextmanager
async def application(
    session: AsyncSession, *, servers_model: bool = True, fernet_keys: bool = True
) -> AsyncIterator[AsyncClient]:
    """A client of an application with the test's session: with or without a model of its own,
    and with or without ``SEF_FERNET_KEY``."""
    app = create_app(settings_for())
    app.state.explainer = Explainer(QuotingModel()) if servers_model else None
    app.state.repairer = Repairer(ScriptedModel()) if servers_model else None
    if not fernet_keys:
        app.state.sef_keys = None

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


async def recorded(session: AsyncSession) -> list[str]:
    """The model key's audit events, each as its action and detail, in a stable order: the test's
    requests share a transaction, and so the time they record."""
    events = await session.scalars(
        select(AuditEvent).where(
            AuditEvent.action.in_([AuditAction.MODEL_KEY_SET, AuditAction.MODEL_KEY_REMOVED])
        )
    )
    return sorted(f"{event.action} {json.dumps(event.detail, sort_keys=True)}" for event in events)


def events(*recorded: tuple[str, dict[str, Any]]) -> list[str]:
    return sorted(f"{action} {json.dumps(detail, sort_keys=True)}" for action, detail in recorded)


# --- the keyring -------------------------------------------------------------------------------


def test_a_key_opens_only_for_what_it_was_sealed_for() -> None:
    organization = uuid.uuid4()
    for_model = KEYRING.seal(organization, SecretStr(KEY), "model")
    for_sef = KEYRING.seal(organization, SecretStr(KEY))

    assert KEYRING.open(organization, for_model, "model").get_secret_value() == KEY
    assert KEYRING.open(organization, for_sef).get_secret_value() == KEY
    with pytest.raises(UnreadableKeyError, match="the SEF key was sealed for another purpose"):
        KEYRING.open(organization, for_model)
    with pytest.raises(UnreadableKeyError, match="model's provider was sealed for another purpose"):
        KEYRING.open(organization, for_sef, "model")
    with pytest.raises(UnreadableKeyError, match="model's provider was sealed for another org"):
        KEYRING.open(uuid.uuid4(), for_model, "model")
    with pytest.raises(UnreadableKeyError, match="model's provider cannot be opened"):
        Keyring((OTHER_FERNET_KEY,)).open(organization, for_model, "model")


# --- setting, replacing and removing -----------------------------------------------------------


async def test_an_owner_sets_the_key_sealed_and_every_member_sees_whose_model_writes(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    setting = await api.put(
        "/organization/model-key",
        json={"provider": "openai", "model": "gpt-6.1-sol", "api_key": f" {KEY}\n"},
        headers=primer.as_owner(),
    )
    shown = await api.get("/organization", headers=primer.as_client())

    assert setting.status_code == 200
    assert setting.json()["provider"] == "openai"
    assert shown.json()["model_key"] == setting.json()
    assert set(setting.json()) == {"provider", "model", "set_at"}
    sealed = await session.get(ModelKey, primer.organization.id)
    assert sealed is not None
    assert (sealed.provider, sealed.model) == ("openai", "gpt-6.1-sol")
    assert KEY not in sealed.token
    assert KEYRING.open(primer.organization.id, sealed.token, "model").get_secret_value() == KEY
    assert await recorded(session) == events(
        ("model.key_set", {"provider": "openai", "model": "gpt-6.1-sol", "replaced": False})
    )


async def test_a_new_key_replaces_the_one_before_and_removing_it_twice_records_once(
    api: AsyncClient, session: AsyncSession, primer: Office
) -> None:
    for provider in ("openai", "anthropic"):
        response = await api.put(
            "/organization/model-key",
            json={"provider": provider, "api_key": KEY},
            headers=primer.as_owner(),
        )
        assert response.status_code == 200
    replaced = await session.get(ModelKey, primer.organization.id)
    assert replaced is not None
    assert (replaced.provider, replaced.model) == ("anthropic", None)

    removals = [
        await api.delete("/organization/model-key", headers=primer.as_owner()) for _ in range(2)
    ]

    assert [removal.status_code for removal in removals] == [204, 204]
    shown = await api.get("/organization", headers=primer.as_owner())
    assert shown.json()["model_key"] is None
    assert await recorded(session) == events(
        ("model.key_set", {"provider": "openai", "model": None, "replaced": False}),
        ("model.key_set", {"provider": "anthropic", "model": None, "replaced": True}),
        ("model.key_removed", {"provider": "anthropic"}),
    )


@pytest.mark.parametrize("role", ["accountant", "client"])
async def test_only_an_owner_sets_or_removes_it(
    api: AsyncClient, session: AsyncSession, primer: Office, role: str
) -> None:
    headers = getattr(primer, f"as_{role}")()
    setting = await api.put(
        "/organization/model-key", json={"provider": "groq", "api_key": KEY}, headers=headers
    )
    removing = await api.delete("/organization/model-key", headers=headers)

    assert (setting.status_code, removing.status_code) == (403, 403)
    assert await session.get(ModelKey, primer.organization.id) is None


@pytest.mark.parametrize(
    ("body", "where"),
    [
        ({"provider": "mistral", "api_key": KEY}, ["body", "provider"]),
        ({"provider": "groq", "model": "gpt 6", "api_key": KEY}, ["body", "model"]),
        ({"provider": "groq", "model": "", "api_key": KEY}, ["body", "model"]),
        ({"provider": "groq", "api_key": "short"}, ["body", "api_key"]),
        ({"provider": "groq", "api_key": "a key with spaces 4711"}, ["body", "api_key"]),
        ({"provider": "groq", "api_key": "k" * 301}, ["body", "api_key"]),
        ({"provider": "groq", "api_key": KEY, "temperature": 0}, ["body", "temperature"]),
    ],
)
async def test_what_is_no_key_is_refused_without_repeating_it(
    api: AsyncClient, primer: Office, body: dict[str, Any], where: list[str]
) -> None:
    response = await api.put("/organization/model-key", json=body, headers=primer.as_owner())

    assert response.status_code == 422
    assert [problem["loc"] for problem in response.json()["detail"]] == [where]
    assert KEY not in response.text
    assert "4711" not in response.text


async def test_a_key_of_up_to_three_hundred_characters_is_taken(
    api: AsyncClient, primer: Office
) -> None:
    response = await api.put(
        "/organization/model-key",
        json={"provider": "openai", "api_key": "k" * 300},
        headers=primer.as_owner(),
    )
    assert response.status_code == 200


async def test_without_fernet_keys_the_server_keeps_no_key(
    session: AsyncSession, primer: Office
) -> None:
    async with application(session, fernet_keys=False) as api:
        response = await api.put(
            "/organization/model-key",
            json={"provider": "groq", "api_key": KEY},
            headers=primer.as_owner(),
        )
    assert response.status_code == 503
    assert response.json()["detail"] == (
        "keys to a model cannot be set on this server: SEF_FERNET_KEY is not set"
    )


# --- rotation ----------------------------------------------------------------------------------


async def test_rotating_the_fernet_key_seals_the_model_keys_again(
    committed_database: Database,
) -> None:
    async with committed_database.sessions() as session:
        primer = await office(session, "Primer Računovodstvo", "primer.example")
        await model_key(session, primer.organization, KEY)
        await sef_key(session, primer.organization, "4711-4711-4711-4711")
        await session.commit()
    rotating = Keyring((OTHER_FERNET_KEY, TEST_FERNET_KEY))

    assert await rotate.reseal_every_key(committed_database, rotating) == 2

    async with committed_database.sessions() as session:
        sealed = await session.get(ModelKey, primer.organization.id)
        assert sealed is not None
        opened = Keyring((OTHER_FERNET_KEY,)).open(primer.organization.id, sealed.token, "model")
        assert opened.get_secret_value() == KEY
