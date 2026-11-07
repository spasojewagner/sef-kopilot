"""``POST /invoices/{invoice_id}/explanations``: the explanations of a stored invoice's report,
which is not validated again; who may ask for them, and how they are counted. They are kept with
the invoice, and read again by ``GET`` as by ``POST``, until its report is another (ADR-0040)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from sef_api.invoices import explanations as kept_explanations
from sef_api.invoices import store as invoice_store
from sef_api.models import KeptExplanations, StoredInvoice
from sef_api.rag.explainer import Explainer

from . import factories
from .corpora import QuotingModel, ScriptedModel
from .test_explainer import FakeEmbedder
from .test_invoices_explain import WRONG_PIB, WRONG_TOTALS, explaining, primer_office
from .test_invoices_validate import VALID, XML, application


async def store(api: AsyncClient, caller: dict[str, str], content: bytes) -> Any:
    response = await api.post("/invoices", content=content, headers=XML | caller)
    assert response.status_code == 201
    return response.json()


async def explain_stored(
    api: AsyncClient, caller: dict[str, str], invoice_id: str, **params: str
) -> Any:
    return await api.post(f"/invoices/{invoice_id}/explanations", params=params, headers=caller)


async def test_the_stored_report_is_explained_without_validating_the_invoice_again(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    async with explaining(session) as api:
        stored = await store(api, caller, WRONG_PIB)
        # Were the document validated again, the report would be this one's, with no SRB-009.
        other = b"<Invoice/>"
        await session.execute(
            update(StoredInvoice)
            .where(StoredInvoice.id == stored["id"])
            .values(content=other, size=len(other))
        )
        response = await explain_stored(api, caller, stored["id"])

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    answer = response.json()
    assert answer["report"] == stored["report"]
    assert (answer["day"], answer["language"], answer["model"]) == (
        "2026-10-05",
        "sr",
        "test/quoting",
    )
    (explained,) = answer["explanations"]
    assert (explained["rule_id"], explained["violations"], explained["problem"]) == (
        "SRB-009",
        2,
        None,
    )
    assert explained["fix"] == "Dodajte element sa ispravnom vrednošću."
    assert [citation["id"] for citation in explained["citations"]] == [
        "pib-rulebook/article-2/2018-10-01",
        "srb-cius/1-3-table-1-bt-31/2025-06-06",
    ]
    assert answer["unexplained"] == []
    assert await session.scalar(select(func.count()).select_from(StoredInvoice)) == 1


async def test_a_stored_invoice_is_explained_in_the_language_asked_for(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    model = QuotingModel()

    async with explaining(session, model) as api:
        stored = await store(api, primer.as_client(), WRONG_PIB)
        response = await explain_stored(api, primer.as_client(), stored["id"], language="en")

    assert response.json()["language"] == "en"
    ((name, (system, _)),) = model.asked
    assert name == "explanation"
    assert system.content.endswith("in English.")


async def test_a_valid_stored_invoice_has_nothing_to_explain(session: AsyncSession) -> None:
    primer = await primer_office(session)
    model = ScriptedModel()

    async with explaining(session, model) as api:
        stored = await store(api, primer.as_client(), VALID)
        response = await explain_stored(api, primer.as_client(), stored["id"])

    assert response.status_code == 200
    assert (response.json()["explanations"], response.json()["unexplained"]) == ([], [])
    assert model.asked == []


async def test_rules_beyond_the_limit_of_the_settings_are_named(session: AsyncSession) -> None:
    primer = await primer_office(session)

    async with explaining(session, SEF_MAX_EXPLANATIONS="1") as api:
        stored = await store(api, primer.as_client(), WRONG_TOTALS)
        response = await explain_stored(api, primer.as_client(), stored["id"])

    answer = response.json()
    assert [each["rule_id"] for each in answer["explanations"]] == ["BR-CO-15"]
    assert answer["unexplained"] == ["BR-CO-16"]


async def test_the_explanations_take_the_time_and_the_embedder_of_the_application(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    embedder = FakeEmbedder()

    class Late(QuotingModel):
        async def answer(self, messages: Any, *, name: str, schema: Any, **_: Any) -> str:
            await asyncio.sleep(10)
            return await super().answer(messages, name=name, schema=schema)

    def change(app: FastAPI) -> None:
        app.state.explainer = Explainer(Late())
        app.state.embedder = embedder

    async with application(session, change, SEF_EXPLANATION_SECONDS="1") as api:
        stored = await store(api, primer.as_client(), WRONG_PIB)
        response = await explain_stored(api, primer.as_client(), stored["id"])

    (explained,) = response.json()["explanations"]
    assert explained["problem"] == "not explained in the time allowed; ask again"
    assert embedder.queries == [
        "Every nine-digit PIB has a serial number in range and a valid check digit"
    ]


async def test_a_client_finds_no_invoice_another_member_submitted(session: AsyncSession) -> None:
    primer = await primer_office(session)
    model = QuotingModel()

    async with explaining(session, model) as api:
        stored = await store(api, primer.as_owner(), WRONG_PIB)
        response = await explain_stored(api, primer.as_client(), stored["id"])

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such invoice in this organization"},
    )
    assert model.asked == []


async def test_without_a_model_the_server_says_so(session: AsyncSession) -> None:
    primer = await primer_office(session)

    async with application(session) as api:
        stored = await store(api, primer.as_client(), WRONG_PIB)
        response = await explain_stored(api, primer.as_client(), stored["id"])

    assert (response.status_code, response.json()) == (
        503,
        {"detail": "no language model is configured on this server"},
    )


async def test_explanations_of_a_stored_invoice_count_as_requests_to_the_model_alone(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    async with explaining(
        session, SEF_EXPLANATIONS_PER_MINUTE="1", SEF_VALIDATIONS_PER_MINUTE="2"
    ) as api:
        stored = await store(api, caller, WRONG_PIB)
        explained = await explain_stored(api, caller, stored["id"])
        # In another language: the explanations kept in Serbian are not these.
        held = await explain_stored(api, caller, stored["id"], language="en")
        validated = await api.post("/invoices/validate", content=VALID, headers=XML | caller)
        no_more = await api.post("/invoices/validate", content=VALID, headers=XML | caller)

    assert explained.status_code == 200
    assert (held.status_code, held.json(), held.headers["Retry-After"]) == (
        429,
        {"detail": "too many requests to the language model; try again in 60 s"},
        "60",
    )
    # The store and one validation: the explanations counted none.
    assert (validated.status_code, no_more.status_code) == (200, 429)


async def read_kept(
    api: AsyncClient, caller: dict[str, str], invoice_id: str, **params: str
) -> Any:
    return await api.get(f"/invoices/{invoice_id}/explanations", params=params, headers=caller)


async def kept_rows(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(
        select(KeptExplanations.language, KeptExplanations.report_sha256).order_by(
            KeptExplanations.language
        )
    )
    return [(language, digest) for language, digest in rows]


async def test_explanations_are_kept_and_read_again_without_asking_the_model(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()
    model = QuotingModel()

    async with explaining(session, model, SEF_EXPLANATIONS_PER_MINUTE="1") as api:
        stored = await store(api, caller, WRONG_PIB)
        nothing_yet = await read_kept(api, caller, stored["id"])
        written = await explain_stored(api, caller, stored["id"])
        # Counted, the second request would be one too many.
        again = await explain_stored(api, caller, stored["id"])
        # Another member who may see the invoice reads the same.
        read = await read_kept(api, primer.as_owner(), stored["id"])

    assert (nothing_yet.status_code, nothing_yet.content) == (204, b"")
    assert (written.status_code, again.status_code, read.status_code) == (200, 200, 200)
    assert again.json() == written.json() == read.json()
    assert nothing_yet.headers["Cache-Control"] == read.headers["Cache-Control"] == "no-store"
    assert len(model.asked) == 1
    report = await session.scalar(select(StoredInvoice.report))
    assert await kept_rows(session) == [
        (
            "sr",
            kept_explanations.report_digest(ValidationReport.model_validate(report, strict=False)),
        )
    ]


async def test_each_language_is_kept_apart(session: AsyncSession) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    async with explaining(session) as api:
        stored = await store(api, caller, WRONG_PIB)
        await explain_stored(api, caller, stored["id"], language="en")
        english = await read_kept(api, caller, stored["id"], language="en")
        serbian = await read_kept(api, caller, stored["id"], language="sr")

    assert (english.status_code, english.json()["language"]) == (200, "en")
    assert serbian.status_code == 204
    assert [language for language, _ in await kept_rows(session)] == ["en"]


async def test_the_explanations_of_another_report_are_written_again(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()
    model = QuotingModel()

    async with explaining(session, model) as api:
        stored = await store(api, caller, WRONG_PIB)
        await explain_stored(api, caller, stored["id"])
        # The invoice's report is another now, as after a repair or a new validation.
        other = (await store(api, caller, WRONG_TOTALS))["report"]
        await session.execute(
            update(StoredInvoice).where(StoredInvoice.id == stored["id"]).values(report=other)
        )
        stale = await read_kept(api, caller, stored["id"])
        rewritten = await explain_stored(api, caller, stored["id"])

    assert stale.status_code == 204
    assert [each["rule_id"] for each in rewritten.json()["explanations"]] == [
        "BR-CO-15",
        "BR-CO-16",
    ]
    assert len(model.asked) == 3
    # One set a language: the new one took the old one's place.
    assert await kept_rows(session) == [
        (
            "sr",
            kept_explanations.report_digest(ValidationReport.model_validate(other, strict=False)),
        )
    ]


async def test_a_set_with_a_rule_left_unexplained_is_not_kept(session: AsyncSession) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    class Late(QuotingModel):
        async def answer(self, messages: Any, *, name: str, schema: Any, **_: Any) -> str:
            await asyncio.sleep(10)
            return await super().answer(messages, name=name, schema=schema)

    async with explaining(session, Late(), SEF_EXPLANATION_SECONDS="1") as api:
        stored = await store(api, caller, WRONG_PIB)
        written = await explain_stored(api, caller, stored["id"])
        kept = await read_kept(api, caller, stored["id"])

    assert written.json()["explanations"][0]["problem"] is not None
    assert kept.status_code == 204
    assert await kept_rows(session) == []


async def test_kept_explanations_are_read_on_a_server_without_a_model(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    async with explaining(session) as api:
        stored = await store(api, caller, WRONG_PIB)
        written = await explain_stored(api, caller, stored["id"])
    async with application(session) as api:
        again = await explain_stored(api, caller, stored["id"])

    assert (again.status_code, again.json()) == (200, written.json())


async def test_kept_explanations_go_with_their_invoice(session: AsyncSession) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    async with explaining(session) as api:
        stored = await store(api, caller, WRONG_PIB)
        await explain_stored(api, caller, stored["id"])
        deleted = await api.delete(f"/invoices/{stored['id']}", headers=caller)

    assert deleted.status_code == 204
    assert await kept_rows(session) == []


async def test_kept_explanations_go_with_an_invoice_past_its_retention(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()
    async with explaining(session) as api:
        stored = await store(api, caller, WRONG_PIB)
        await explain_stored(api, caller, stored["id"])
    primer.organization.invoice_retention_days = 30
    await session.flush()

    forgotten = await invoice_store.forget_past_retention(
        session, now=datetime.now(UTC) + timedelta(days=31)
    )

    assert forgotten == 1
    assert await kept_rows(session) == []


async def test_a_kept_set_is_the_invoices_for_its_report_and_its_day_alone(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    invoice = await factories.stored_invoice(session, primer.organization, primer.client)
    day = date(2026, 11, 7)
    await kept_explanations.keep(
        session,
        invoice.id,
        "sr",
        report_sha256="a" * 64,
        day=day,
        model="test/quoting",
        explanations=[],
        unexplained=["BR-CO-16"],
    )

    async def found(digest: str, on: date) -> kept_explanations.Kept | None:
        return await kept_explanations.kept(session, invoice.id, "sr", report_sha256=digest, day=on)

    kept = await found("a" * 64, day)
    assert kept is not None
    assert (kept.model, kept.unexplained) == ("test/quoting", ["BR-CO-16"])
    assert await found("b" * 64, day) is None
    assert await found("a" * 64, date(2026, 11, 8)) is None


async def test_a_kept_set_in_a_form_of_the_past_is_written_again(
    session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    primer = await primer_office(session)
    invoice = await factories.stored_invoice(session, primer.organization, primer.client)
    day = date(2026, 11, 7)
    await kept_explanations.keep(
        session,
        invoice.id,
        "sr",
        report_sha256="a" * 64,
        day=day,
        model="test/quoting",
        explanations=[],
        unexplained=[],
    )
    # As an earlier version might have written it: no rule, no count.
    await session.execute(
        update(KeptExplanations).values(explanations=[{"text": "Pravilo traži element."}])
    )
    caplog.set_level(logging.WARNING, logger=kept_explanations.__name__)

    kept = await kept_explanations.kept(session, invoice.id, "sr", report_sha256="a" * 64, day=day)

    assert kept is None
    assert [record.getMessage() for record in caplog.records] == [
        "kept explanations not read: ValidationError"
    ]


async def test_a_client_reads_no_explanations_of_an_invoice_another_member_submitted(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)

    async with explaining(session) as api:
        stored = await store(api, primer.as_owner(), WRONG_PIB)
        await explain_stored(api, primer.as_owner(), stored["id"])
        response = await read_kept(api, primer.as_client(), stored["id"])

    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such invoice in this organization"},
    )


async def test_nothing_is_kept_for_an_invoice_deleted_meanwhile(session: AsyncSession) -> None:
    kept = await kept_explanations.keep(
        session,
        uuid.uuid4(),
        "sr",
        report_sha256="0" * 64,
        day=date(2026, 11, 7),
        model="test/quoting",
        explanations=[],
        unexplained=[],
    )

    assert kept is None
    assert await kept_rows(session) == []


async def test_openapi_documents_the_explanations_of_a_stored_invoice(
    client: AsyncClient,
) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    operation = paths["/invoices/{invoice_id}/explanations"]["post"]

    assert operation["tags"] == ["invoices"]
    assert {"200", "404", "422", "429", "503"} <= set(operation["responses"])
    assert "requestBody" not in operation
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "invoice_id",
        "language",
    ]
    reading = paths["/invoices/{invoice_id}/explanations"]["get"]
    assert {"200", "204", "404", "422"} == set(reading["responses"])
