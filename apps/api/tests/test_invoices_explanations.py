"""``POST /invoices/{invoice_id}/explanations``: the explanations of a stored invoice's report,
which is not validated again; who may ask for them, and how they are counted."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.models import StoredInvoice
from sef_api.rag.explainer import Explainer

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
        held = await explain_stored(api, caller, stored["id"])
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
