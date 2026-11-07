"""Repairs the language model proposes for a stored invoice: asked for by anyone who may submit
invoices, applied in the validator's process, kept and decided on as any repair is, and audited
with the model that wrote them (ADR-0025)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.permissions import Permission
from sef_api.db import get_session
from sef_api.llm import LLMClient, LLMError
from sef_api.main import create_app
from sef_api.models import Membership, Repair, StoredInvoice
from sef_api.repairs import store
from sef_api.repairs.repairer import ATTEMPTS, Repairer

from .conftest import REPOSITORY_ROOT, settings_for
from .corpora import ScriptedModel
from .factories import Office, api_key, office, stored_invoice
from .test_repairs import MISTAKE, VALID, events, path

DATE = (
    REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "mutations" / "xsd-date-format.xml"
).read_bytes()
FIX_TYPE = {
    "xpath": "/ubl:Invoice/cbc:InvoiceTypeCode",
    "op": "replace",
    "value": "380",
    "reason": "SEF prima samo kodove tipa koje poruka pravila navodi.",
}


def answer(*patches: dict[str, str]) -> str:
    return json.dumps({"patches": list(patches)})


def suggestion(invoice: StoredInvoice) -> str:
    return path(invoice, "suggestion")


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    return await office(session, "Primer Računovodstvo", "primer.example")


async def kept(session: AsyncSession, primer: Office, content: bytes = MISTAKE) -> StoredInvoice:
    return await stored_invoice(session, primer.organization, primer.client, content)


@asynccontextmanager
async def suggesting(
    session: AsyncSession, model: LLMClient | None, **variables: str
) -> AsyncIterator[AsyncClient]:
    """A client of an application whose repairer asks ``model``, with the test's session."""
    app = create_app(settings_for(**variables))
    app.state.repairer = None if model is None else Repairer(model)

    async def the_test_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = the_test_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


class Meanwhile(ScriptedModel):
    """A model during whose answer something else happens."""

    def __init__(self, happen: Callable[[], Awaitable[object]], *answers: str) -> None:
        super().__init__(*answers)
        self.happen = happen

    async def answer(self, *args: Any, **kwargs: Any) -> str:
        await self.happen()
        return await super().answer(*args, **kwargs)


async def test_the_model_proposes_a_repair_that_is_kept_audited_and_decided_as_any_other(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    model = ScriptedModel(answer(FIX_TYPE))

    async with suggesting(session, model) as api:
        proposed = await api.post(suggestion(invoice), headers=primer.as_client())
        listed = await api.get(path(invoice), headers=primer.as_client())
        stored = await session.get(StoredInvoice, invoice.id)
        assert stored is not None
        before = stored.sha256
        approved = await api.post(
            path(invoice, proposed.json()["id"], "approval"), headers=primer.as_owner()
        )

    assert proposed.status_code == 201
    body = proposed.json()
    assert proposed.headers["Location"] == path(invoice, body["id"])
    assert {key: body[key] for key in ("status", "model", "changed", "valid", "applied")} == {
        "status": "proposed",
        "model": "test/scripted",
        "changed": True,
        "valid": True,
        "applied": 1,
    }
    assert (body["proposed_by"], body["proposed_with_key"]) == (str(primer.client.id), False)
    assert [outcome["patch"] for outcome in body["outcomes"]] == [FIX_TYPE]
    assert "rule: SRB-001" in model.asked[0][1].content
    assert '/ubl:Invoice/cbc:InvoiceTypeCode = "393"' in model.asked[0][1].content
    assert [repair["model"] for repair in listed.json()] == ["test/scripted"]
    repair = await session.get(Repair, uuid.UUID(body["id"]))
    assert repair is not None
    assert (repair.model, repair.based_on) == ("test/scripted", before)
    proposal, approval = await events(session)
    assert (proposal.action, proposal.actor, proposal.key_id) == (
        "repair.proposed",
        primer.client.id,
        None,
    )
    assert proposal.detail == {
        "based_on": before,
        "patched_sha256": repair.patched_sha256,
        "changed": True,
        "valid": True,
        "patches": [
            {"xpath": "/ubl:Invoice/cbc:InvoiceTypeCode", "op": "replace", "status": "applied"}
        ],
        "model": "test/scripted",
        "rounds": 1,
    }
    for quoted in ("380", "393", FIX_TYPE["reason"]):
        assert quoted not in json.dumps(proposal.detail)
    assert (approved.status_code, approved.json()["status"], approval.action) == (
        200,
        "approved",
        "repair.approved",
    )


async def test_the_reasons_are_asked_for_in_the_language_of_the_request(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    model = ScriptedModel(answer(FIX_TYPE))

    async with suggesting(session, model) as api:
        english = await api.post(f"{suggestion(invoice)}?language=en", headers=primer.as_client())
        unknown = await api.post(f"{suggestion(invoice)}?language=de", headers=primer.as_client())

    assert (english.status_code, unknown.status_code) == (201, 422)
    assert model.asked[0][0].content.endswith("Write the reasons in English.")


async def test_a_patch_a_person_decides_is_kept_for_them_and_changes_nothing_to_approve(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer, DATE)
    date = {
        "xpath": "/ubl:Invoice/cbc:IssueDate",
        "op": "replace",
        "value": "2026-10-05",
        "reason": "Datum 05.10.2026. se piše kao 2026-10-05.",
    }

    async with suggesting(session, ScriptedModel(answer(date), answer())) as api:
        proposed = await api.post(suggestion(invoice), headers=primer.as_client())
        approved = await api.post(
            path(invoice, proposed.json()["id"], "approval"), headers=primer.as_owner()
        )

    body = proposed.json()
    assert (proposed.status_code, body["changed"], body["needs_decision"]) == (201, False, 1)
    assert body["outcomes"][0]["problem"] == (
        "it touches a date or a time (cbc:IssueDate): a person decides it"
    )
    assert (approved.status_code, approved.json()) == (
        409,
        {
            "detail": "the repair changes nothing: there is nothing to approve",
            "reason": "changes-nothing",
        },
    )


@pytest.mark.parametrize(
    ("model", "status", "detail"),
    [
        (
            ScriptedModel(answer()),
            422,
            "the language model proposes no patch for these violations: a person must",
        ),
        # A patch that writes the type code the invoice has: it applies, and changes nothing.
        (
            ScriptedModel(*[answer({**FIX_TYPE, "value": "393"})] * 2),
            422,
            "none of the patches the language model proposes changes the invoice",
        ),
        (
            ScriptedModel(LLMError("Groq answered 401 (invalid_api_key)")),
            502,
            "the language model gave no answer (Groq answered 401 (invalid_api_key))",
        ),
        (
            ScriptedModel(*["not JSON"] * ATTEMPTS),
            502,
            "none of the language model's 3 answers could be used",
        ),
    ],
)
async def test_without_a_patch_to_keep_no_repair_is_kept_and_the_answer_says_why(
    session: AsyncSession, primer: Office, model: ScriptedModel, status: int, detail: str
) -> None:
    invoice = await kept(session, primer)

    async with suggesting(session, model) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (status, {"detail": detail})
    assert await session.scalar(select(Repair.id)) is None
    assert await events(session) == []


async def test_a_model_that_answers_too_late_proposes_nothing(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    late = Meanwhile(lambda: asyncio.sleep(10), answer(FIX_TYPE))

    async with suggesting(session, late, SEF_REPAIR_SECONDS="0.5") as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (
        504,
        {"detail": "the language model proposed no repair within 0.5 s"},
    )


async def test_a_valid_invoice_is_not_sent_to_the_model(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer, VALID)
    model = ScriptedModel()

    async with suggesting(session, model) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (
        409,
        {
            "detail": "the invoice is valid: there is nothing to repair",
            "reason": "nothing-to-repair",
        },
    )
    assert model.asked == []


async def test_without_a_model_the_server_proposes_no_repair(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    async with suggesting(session, None) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (
        503,
        {"detail": "no language model is configured on this server"},
    )


async def test_a_machine_client_asks_for_a_repair_with_its_key(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    key = await api_key(session, primer.organization, primer.client, Permission.INVOICES_SUBMIT)

    async with suggesting(session, ScriptedModel(answer(FIX_TYPE))) as api:
        response = await api.post(suggestion(invoice), headers=key.header())

    assert (response.status_code, response.json()["proposed_with_key"]) == (201, True)
    (event,) = await events(session)
    assert (event.actor, event.key_id) == (primer.client.id, key.row.id)


async def test_asking_counts_as_a_validation_and_as_a_request_to_the_model(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    other = await kept(session, primer)
    model = ScriptedModel(*[answer(FIX_TYPE)] * 3)

    async with suggesting(session, model, SEF_EXPLANATIONS_PER_MINUTE="1") as api:
        first = await api.post(suggestion(invoice), headers=primer.as_client())
        held = await api.post(suggestion(other), headers=primer.as_client())
    async with suggesting(session, model, SEF_VALIDATIONS_PER_MINUTE="1") as api:
        await api.post(suggestion(other), headers=primer.as_client())
        validating = await api.post(
            path(invoice), json={"patches": [FIX_TYPE]}, headers=primer.as_client()
        )

    assert first.status_code == 201
    assert (held.status_code, held.json()) == (
        429,
        {"detail": "too many requests to the language model; try again in 60 s"},
    )
    assert (validating.status_code, validating.json()) == (
        429,
        {"detail": "too many validations; try again in 60 s"},
    )
    assert len(model.asked) == 2


async def test_no_model_is_asked_while_as_many_repairs_as_allowed_wait(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)
    model = ScriptedModel()

    async with suggesting(session, ScriptedModel(*[answer(FIX_TYPE)] * store.MAX_WAITING)) as api:
        for _ in range(store.MAX_WAITING):
            assert (await api.post(suggestion(invoice), headers=primer.as_client())).is_success
    async with suggesting(session, model) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (
        409,
        {
            "detail": "10 repairs of this invoice wait for a decision: decide on them first",
            "reason": "too-many-waiting",
        },
    )
    assert model.asked == []


async def test_an_invoice_that_changes_while_the_model_works_keeps_no_repair(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await kept(session, primer)

    async def replaced() -> None:
        await session.execute(
            update(StoredInvoice).where(StoredInvoice.id == invoice.id).values(sha256="0" * 64)
        )

    async with suggesting(session, Meanwhile(replaced, answer(FIX_TYPE))) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (
        409,
        {
            "detail": "the invoice changed while the model's patches were applied to it: ask again",
            "reason": "invoice-changed",
        },
    )
    assert await session.scalar(select(Repair.id)) is None


@pytest.mark.parametrize(
    ("happened", "status", "body"),
    [
        (
            store.TooManyWaitingError(),
            409,
            {
                "detail": "10 repairs of this invoice wait for a decision: decide on them first",
                "reason": "too-many-waiting",
            },
        ),
        (None, 404, {"detail": "no such invoice in this organization"}),
    ],
)
async def test_what_happened_while_the_model_worked_is_answered(
    session: AsyncSession,
    primer: Office,
    monkeypatch: pytest.MonkeyPatch,
    happened: Exception | None,
    status: int,
    body: dict[str, str],
) -> None:
    invoice = await kept(session, primer)

    async def meanwhile(*_args: object, **_kwargs: object) -> None:
        if happened is not None:
            raise happened

    monkeypatch.setattr(store, "propose", meanwhile)

    async with suggesting(session, ScriptedModel(answer(FIX_TYPE))) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert (response.status_code, response.json()) == (status, body)


async def test_a_member_removed_while_the_model_works_keeps_no_repair(
    session: AsyncSession, primer: Office
) -> None:
    """Asking the model outlasts the permission check's transaction, so the membership is
    checked again where the repair is kept."""
    invoice = await kept(session, primer)

    async def removed() -> None:
        await session.execute(delete(Membership).where(Membership.user_id == primer.client.id))

    async with suggesting(session, Meanwhile(removed, answer(FIX_TYPE))) as api:
        response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert response.status_code == 401
    assert await session.scalar(select(Repair.id)) is None
    assert await events(session) == []


async def test_an_invoice_the_caller_may_not_see_is_not_sent_to_the_model(
    session: AsyncSession, primer: Office
) -> None:
    invoice = await stored_invoice(session, primer.organization, primer.accountant, MISTAKE)
    stranger = await kept(session, await office(session, "Drugi Ured", "drugi.example"))
    model = ScriptedModel()

    async with suggesting(session, model) as api:
        for headers, target in ((primer.as_client(), invoice), (primer.as_owner(), stranger)):
            response = await api.post(suggestion(target), headers=headers)
            assert (response.status_code, response.json()) == (
                404,
                {"detail": "no such invoice in this organization"},
            )

    assert model.asked == []


async def test_no_invoice_content_reaches_a_log_when_the_model_repairs(
    session: AsyncSession, primer: Office, caplog: pytest.LogCaptureFixture
) -> None:
    invoice = await kept(session, primer)
    note = {
        "xpath": "/ubl:Invoice/cbc:Note",
        "op": "replace",
        "value": "quoted-from-the-model",
        "reason": "reason-quoting-the-invoice",
    }
    unusable = answer({**FIX_TYPE, "reason": "Rok je 31. 12. 2026."})

    with caplog.at_level(logging.DEBUG):
        async with suggesting(session, ScriptedModel(unusable, answer(FIX_TYPE, note))) as api:
            response = await api.post(suggestion(invoice), headers=primer.as_client())

    assert response.status_code == 201
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for quoted in ("quoted-from-the-model", "reason-quoting-the-invoice", "31. 12. 2026"):
        assert quoted not in logged
    for quoted in ("RF-2026-000123", "Rok za plaćanje", "393", "NAB-77"):
        assert quoted not in logged
    assert "suggested a repair of 2 patches with test/scripted in 1 rounds and 2 answers" in logged
