"""``POST /invoices/explain``: an invoice's report and the explanations of its rules, with
citations of stored passages; the limits that hold it back, and a server without a model."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.llm import GroqClient
from sef_api.main import create_app
from sef_api.models import CorpusPassage, StoredInvoice
from sef_api.rag.embeddings import JinaEmbedder
from sef_api.rag.explainer import Explainer
from sef_api.repairs.repairer import Repairer

from .conftest import settings_for
from .corpora import QuotingModel, ScriptedModel, repository_corpus, store_corpus
from .factories import Office, office
from .test_explainer import FakeEmbedder
from .test_invoices_validate import FIXTURES, VALID, XML, application

MUTATIONS = FIXTURES / "synthetic" / "mutations"
WRONG_PIB = (MUTATIONS / "srb-009-pib-check-digit.xml").read_bytes()
WRONG_TOTALS = (MUTATIONS / "br-co-15-total-with-vat.xml").read_bytes()


async def primer_office(session: AsyncSession) -> Office:
    await store_corpus(session, repository_corpus())
    return await office(session, "Primer Računovodstvo", "primer.example")


def explaining_with(model: Any) -> Callable[[FastAPI], None]:
    def change(app: FastAPI) -> None:
        app.state.explainer = Explainer(model)

    return change


@asynccontextmanager
async def explaining(
    session: AsyncSession, model: Any = None, **variables: str
) -> AsyncIterator[AsyncClient]:
    async with application(session, explaining_with(model or QuotingModel()), **variables) as api:
        yield api


async def explain(api: AsyncClient, caller: dict[str, str], content: bytes, **params: str) -> Any:
    return await api.post("/invoices/explain", params=params, content=content, headers=XML | caller)


async def test_each_rule_is_explained_with_citations_of_stored_passages(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)

    async with explaining(session) as api:
        response = await explain(api, primer.as_client(), WRONG_PIB)

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    answer = response.json()
    assert answer["report"]["valid"] is False
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
    assert explained["text"] == "Pravilo traži element koji faktura nema."
    cited = [citation["id"] for citation in explained["citations"]]
    assert cited == ["pib-rulebook/article-2/2018-10-01", "srb-cius/1-3-table-1-bt-31/2025-06-06"]
    stored = await session.scalars(select(CorpusPassage.id).where(CorpusPassage.id.in_(cited)))
    assert sorted(stored) == sorted(cited)
    assert explained["citations"][0] | {"source_url": "…"} == {
        "id": "pib-rulebook/article-2/2018-10-01",
        "document": "pib-rulebook",
        "title": "Pravilnik o poreskom identifikacionom broju",
        "label": "Члан 2.",
        "heading": "Поступак, начин и рокови одређивања и додељивања ПИБ-а",
        "version": "Službeni glasnik RS, br. 57/2003, 68/2003, 32/2009, 48/2010 i 44/2018",
        "valid_from": "2018-10-01",
        "valid_to": None,
        "source_url": "…",
    }
    assert answer["unexplained"] == []
    assert await session.scalar(select(func.count()).select_from(StoredInvoice)) == 0


async def test_explanations_in_english_are_asked_for_in_english(session: AsyncSession) -> None:
    primer = await primer_office(session)
    model = QuotingModel()

    async with explaining(session, model) as api:
        response = await explain(api, primer.as_client(), WRONG_PIB, language="en")

    assert response.json()["language"] == "en"
    ((name, (system, _)),) = model.asked
    assert name == "explanation"
    assert system.content.endswith("in English.")


async def test_a_valid_invoice_has_nothing_to_explain(session: AsyncSession) -> None:
    primer = await primer_office(session)
    model = ScriptedModel()

    async with explaining(session, model) as api:
        response = await explain(api, primer.as_client(), VALID)

    assert response.status_code == 200
    assert (response.json()["explanations"], response.json()["unexplained"]) == ([], [])
    assert model.asked == []


async def test_rules_beyond_the_limit_of_the_settings_are_named(session: AsyncSession) -> None:
    primer = await primer_office(session)

    async with explaining(session, SEF_MAX_EXPLANATIONS="1") as api:
        response = await explain(api, primer.as_client(), WRONG_TOTALS)

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
        response = await explain(api, primer.as_client(), WRONG_PIB)

    (explained,) = response.json()["explanations"]
    assert explained["problem"] == "not explained in the time allowed; ask again"
    assert embedder.queries == [
        "Every nine-digit PIB has a serial number in range and a valid check digit"
    ]


async def test_without_a_model_the_server_says_so_before_it_reads_the_invoice(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)

    async with application(session, SEF_VALIDATIONS_PER_MINUTE="1") as api:
        refused = await explain(api, primer.as_client(), b"x" * (6 * 1024 * 1024))
        validated = await api.post(
            "/invoices/validate", content=VALID, headers=XML | primer.as_client()
        )

    assert (refused.status_code, refused.json()) == (
        503,
        {"detail": "no language model is configured on this server"},
    )
    assert validated.status_code == 200  # the refusal counted no validation


async def test_requests_for_explanations_are_counted_and_count_as_validations(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)
    caller = primer.as_client()

    async with explaining(
        session, SEF_EXPLANATIONS_PER_MINUTE="1", SEF_VALIDATIONS_PER_MINUTE="2"
    ) as api:
        explained = await explain(api, caller, WRONG_PIB)
        held = await explain(api, caller, WRONG_PIB)
        validated = await api.post("/invoices/validate", content=VALID, headers=XML | caller)
        no_more = await api.post("/invoices/validate", content=VALID, headers=XML | caller)

    assert explained.status_code == 200
    assert (held.status_code, held.json(), held.headers["Retry-After"]) == (
        429,
        {"detail": "too many requests to the language model; try again in 60 s"},
        "60",
    )
    assert (validated.status_code, no_more.status_code) == (200, 429)


async def test_the_callers_of_an_organization_share_its_count_of_explanations(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)

    async with explaining(session, SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE="1") as api:
        await explain(api, primer.as_client(), VALID)
        held = await explain(api, primer.as_accountant(), VALID)

    assert (held.status_code, held.json()) == (
        429,
        {
            "detail": "too many requests to the language model in this organization; "
            "try again in 60 s"
        },
    )


async def test_no_invoice_content_reaches_a_log_when_explaining(
    session: AsyncSession,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The messages the model is sent quote the invoice; the logs name the rules, the model and
    the attempts, whether an explanation is written or not."""
    primer = await primer_office(session)
    quoted = "100000025"  # the PIB with the wrong check digit, which SRB-009's messages quote

    with caplog.at_level(logging.DEBUG):
        async with explaining(session) as api:
            written = await explain(api, primer.as_client(), WRONG_PIB)
        async with explaining(session, ScriptedModel(*["not JSON"] * 3)) as api:
            unusable = await explain(api, primer.as_client(), WRONG_PIB)

    assert quoted in json.dumps(written.json()["report"], ensure_ascii=False)
    assert unusable.json()["explanations"][0]["problem"] == (
        "none of the model's 3 answers could be used"
    )
    assert "explained SRB-009 with test/quoting in 1 attempts" in caplog.text
    assert "no explanation of SRB-009: none of the model's 3 answers" in caplog.text
    assert quoted not in caplog.text
    captured = capfd.readouterr()
    assert quoted not in captured.out + captured.err


async def test_a_document_the_validator_refuses_is_answered_as_a_validation_is(
    session: AsyncSession,
) -> None:
    primer = await primer_office(session)

    async with explaining(session) as api:
        response = await api.post(
            "/invoices/explain",
            content=b"{}",
            headers={"Content-Type": "application/json"} | primer.as_client(),
        )

    assert response.status_code == 415


async def test_the_application_explains_with_the_model_the_settings_name() -> None:
    app = create_app(
        settings_for(
            LLM_PROVIDER="groq",
            GROQ_API_KEY="gsk_test_key",
            EMBEDDINGS_PROVIDER="jina",
            JINA_API_KEY="jina_test_key",
        )
    )

    assert isinstance(app.state.explainer, Explainer)
    assert app.state.explainer.model == f"groq/{GroqClient.MODEL}"
    assert isinstance(app.state.repairer, Repairer)  # with the same model, closed once
    assert app.state.repairer.model == f"groq/{GroqClient.MODEL}"
    assert isinstance(app.state.embedder, JinaEmbedder)
    without = create_app(settings_for())
    assert (without.state.explainer, without.state.repairer) == (None, None)


async def test_shutting_down_closes_the_model_and_the_embedder() -> None:
    closed: list[str] = []

    class Closing(QuotingModel):
        async def aclose(self) -> None:
            closed.append("model")

    class ClosingEmbedder:
        model = "test/embedder"

        async def aclose(self) -> None:
            closed.append("embedder")

    app = create_app(settings_for())
    app.state.explainer = Explainer(Closing())
    app.state.embedder = ClosingEmbedder()

    async with app.router.lifespan_context(app):
        pass

    assert closed == ["model", "embedder"]


async def test_openapi_documents_the_explanation_endpoint(client: AsyncClient) -> None:
    operation = (await client.get("/openapi.json")).json()["paths"]["/invoices/explain"]["post"]

    assert operation["tags"] == ["invoices"]
    assert {"200", "413", "415", "422", "429", "503"} <= set(operation["responses"])
    assert "application/xml" in operation["requestBody"]["content"]
    assert [parameter["name"] for parameter in operation["parameters"]] == ["profile", "language"]
