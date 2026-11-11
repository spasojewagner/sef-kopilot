"""An organization's own key to a language model's provider (ADR-0058): an owner sets, replaces
and removes it, sealed under ``SEF_FERNET_KEY`` for that purpose; every member sees whose model
writes; the organization's explanations and repairs are then asked of that model, never of the
server's, and a key that cannot be opened stops them rather than send the invoice elsewhere."""

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

from sef_api import model_choice
from sef_api.db import Database, get_session
from sef_api.main import create_app
from sef_api.models import AuditAction, AuditEvent, ModelKey
from sef_api.rag.explainer import Explainer
from sef_api.repairs.repairer import Repairer
from sef_api.sef import rotate
from sef_api.sef.keys import Keyring, UnreadableKeyError

from .conftest import TEST_FERNET_KEY, settings_for
from .corpora import QuotingModel, ScriptedModel, repository_corpus, store_corpus
from .documents import picture
from .factories import KEYRING, Office, model_key, office, sef_key, stored_invoice
from .test_invoices_explain import WRONG_PIB
from .test_invoices_validate import XML
from .test_mcp import NO_MODEL, connected, serving, text_of
from .test_repair_suggestions import FIX_TYPE, answer, suggestion
from .test_repairs import MISTAKE

KEY = "sk-own-4711-4711-4711"
OTHER_FERNET_KEY = base64.urlsafe_b64encode(b"else" * 8).decode()


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


class OwnModel(QuotingModel):
    """The organization's own model, as a stand-in: it explains as the test application's model
    does, repairs as it is told, and notes the key and the model it was made with."""

    def __init__(self, provider: str, api_key: SecretStr, model: str | None) -> None:
        super().__init__()
        self.model = f"{provider}/{model or 'its-default'}"
        self.made_with = (provider, api_key.get_secret_value(), model)
        self.closed = False

    async def answer(self, messages: Any, *, name: str, schema: Any, max_tokens: Any = None) -> str:
        if name == "repair":
            return answer(FIX_TYPE)
        if name == "invoice_fields":
            return json.dumps({"number": "RF-2026-000123"})
        return await super().answer(messages, name=name, schema=schema, max_tokens=max_tokens)

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def own_models(monkeypatch: pytest.MonkeyPatch) -> list[OwnModel]:
    """The organizations' models made while the test runs, each a stand-in."""
    made: list[OwnModel] = []

    def make(provider: str, api_key: SecretStr | None, model: str | None) -> OwnModel:
        assert api_key is not None
        own = OwnModel(provider, api_key, model)
        made.append(own)
        return own

    monkeypatch.setattr(model_choice, "client_for", make)
    return made


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


# --- whose model writes ------------------------------------------------------------------------


async def test_the_organization_s_explanations_are_written_by_its_own_model(
    session: AsyncSession, primer: Office, own_models: list[OwnModel]
) -> None:
    await store_corpus(session, repository_corpus())
    await model_key(session, primer.organization, KEY, provider="anthropic", model="claude-x")
    elsewhere = await office(session, "Ogledni Kupac", "kupac.example")

    async with application(session) as api:
        own = await api.post(
            "/invoices/explain", content=WRONG_PIB, headers=XML | primer.as_accountant()
        )
        servers = await api.post(
            "/invoices/explain", content=WRONG_PIB, headers=XML | elsewhere.as_accountant()
        )

    assert (own.status_code, servers.status_code) == (200, 200)
    assert own.json()["model"] == "anthropic/claude-x"
    assert servers.json()["model"] == "test/quoting"
    assert [explanation["text"] for explanation in own.json()["explanations"]]
    assert [(own.made_with, own.closed) for own in own_models] == [
        (("anthropic", KEY, "claude-x"), True)
    ]


async def test_a_server_without_a_model_explains_with_the_organization_s(
    session: AsyncSession, primer: Office, own_models: list[OwnModel]
) -> None:
    await store_corpus(session, repository_corpus())
    await model_key(session, primer.organization, KEY, provider="groq")
    invoice = await stored_invoice(session, primer.organization, primer.client, WRONG_PIB)

    async with application(session, servers_model=False) as api:
        explained = await api.post(
            f"/invoices/{invoice.id}/explanations", headers=primer.as_client()
        )

    assert explained.status_code == 200, explained.text
    assert explained.json()["model"] == "groq/its-default"
    assert len(own_models) == 1


async def test_the_organization_s_documents_are_read_by_its_provider_s_reading_model(
    session: AsyncSession, primer: Office, own_models: list[OwnModel]
) -> None:
    # The model the organization chose writes; reading pictures takes its provider's reading
    # model, with the organization's key.
    await model_key(session, primer.organization, KEY, provider="groq", model="openai/gpt-oss-20b")

    async with application(session, servers_model=False) as api:
        read = await api.post(
            "/invoices/extract",
            content=picture(),
            headers={"Content-Type": "image/jpeg"} | primer.as_client(),
        )

    assert read.status_code == 200, read.text
    assert read.json()["model"] == "groq/qwen/qwen3.8-27b"
    assert read.json()["fields"]["number"] == "RF-2026-000123"
    assert [(own.made_with, own.closed) for own in own_models] == [
        (("groq", KEY, "qwen/qwen3.8-27b"), True)
    ]


async def test_the_organization_s_repairs_are_proposed_by_its_own_model(
    session: AsyncSession, primer: Office, own_models: list[OwnModel]
) -> None:
    await model_key(session, primer.organization, KEY, provider="openai")
    invoice = await stored_invoice(session, primer.organization, primer.client, MISTAKE)

    async with application(session) as api:
        proposed = await api.post(suggestion(invoice), headers=primer.as_client())

    assert proposed.status_code == 201, proposed.text
    assert proposed.json()["model"] == "openai/its-default"
    assert own_models[0].closed


async def test_a_key_the_server_cannot_open_stops_the_model_rather_than_send_elsewhere(
    session: AsyncSession, primer: Office, own_models: list[OwnModel]
) -> None:
    await store_corpus(session, repository_corpus())
    await model_key(session, primer.organization, KEY, keyring=Keyring((OTHER_FERNET_KEY,)))
    invoice = await stored_invoice(session, primer.organization, primer.client, MISTAKE)

    async with application(session) as api:
        explaining = await api.post(
            "/invoices/explain", content=WRONG_PIB, headers=XML | primer.as_accountant()
        )
        repairing = await api.post(suggestion(invoice), headers=primer.as_client())
    async with application(session, fernet_keys=False) as api:
        unkept = await api.post(
            "/invoices/explain", content=WRONG_PIB, headers=XML | primer.as_accountant()
        )

    detail = (
        "the organization's key to its model cannot be opened on this server: an owner sets it "
        "again"
    )
    for answered in (explaining, repairing, unkept):
        assert (answered.status_code, answered.json()["detail"]) == (503, detail)
    assert own_models == []


async def test_an_mcp_client_of_the_organization_is_answered_by_its_own_model(
    committed_database: Database, database_url: str, own_models: list[OwnModel]
) -> None:
    async with (
        serving(committed_database, database_url, model=NO_MODEL, corpus=True) as served,
        connected(served.app, served.key) as client,
    ):
        refused = await client.call_tool("explain_errors", {"xml": WRONG_PIB})
        async with committed_database.sessions() as setup:
            primer = served.primer.organization
            await model_key(setup, primer, KEY, provider="openai", model="gpt-x")
            await setup.commit()
        answered = await client.call_tool("explain_errors", {"xml": WRONG_PIB})

    assert text_of(refused) == (
        "Error executing tool explain_errors: no language model is configured on this server"
    )
    assert not answered.is_error, text_of(answered)
    assert answered.structured_content is not None
    assert answered.structured_content["model"] == "openai/gpt-x"
    assert [own.closed for own in own_models] == [True]


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
