"""Each request to the language model traced to Langfuse where its keys are set, without the
conversation (ADR-0049)."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from sef_api.llm import LLMError, last_usage
from sef_api.logs import RequestIds
from sef_api.main import create_app
from sef_api.model_traces import TRACES_PATH, ModelTraces, TracedClient
from sef_api.settings import Settings

from .conftest import settings_for
from .corpora import ScriptedModel
from .test_llm import CONVERSATION, SCHEMA, answering, completion

HOST = "https://cloud.langfuse.com"


class Langfuse:
    """Langfuse's endpoint, as a test plays it: what it was sent, and how it answers."""

    def __init__(self, answer: int = 200) -> None:
        self.status = answer
        self.sent: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request)
        return httpx.Response(self.status, json={})

    def traces(self) -> ModelTraces:
        return ModelTraces(
            HOST,
            "pk-lf-test",
            SecretStr("sk-lf-test"),
            environment="test",
            transport=httpx.MockTransport(self.handle),
        )

    def spans(self) -> list[dict[str, Any]]:
        return [
            span
            for request in self.sent
            for resource in json.loads(request.content)["resourceSpans"]
            for scope in resource["scopeSpans"]
            for span in scope["spans"]
        ]


def attributes(span: dict[str, Any]) -> dict[str, str]:
    return {
        attribute["key"]: next(iter(attribute["value"].values()))
        for attribute in span["attributes"]
    }


async def test_an_answer_is_traced_as_a_generation_without_the_conversation() -> None:
    langfuse = Langfuse()
    requests: list[httpx.Request] = []
    groq = answering(lambda _: completion('{"answer": "da"}'), requests)
    traced = TracedClient(groq, langfuse.traces())

    answer = await traced.answer(CONVERSATION, name="explanation", schema=SCHEMA, max_tokens=512)
    await traced.aclose()

    assert answer == '{"answer": "da"}'
    (request,) = langfuse.sent
    assert str(request.url) == HOST + TRACES_PATH
    assert request.headers["Authorization"] == (
        "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    )
    assert request.headers["x-langfuse-ingestion-version"] == "4"
    (span,) = langfuse.spans()
    assert span["name"] == "model.explanation"
    assert span["status"] == {"code": 1}
    assert int(span["endTimeUnixNano"]) >= int(span["startTimeUnixNano"])
    fields = attributes(span)
    assert fields["langfuse.observation.type"] == "generation"
    assert fields["langfuse.observation.model.name"] == "groq/openai/gpt-oss-120b"
    assert json.loads(fields["langfuse.observation.usage_details"]) == {
        "input": 120,
        "output": 40,
        "total": 160,
    }
    assert json.loads(fields["langfuse.observation.model.parameters"]) == {"max_tokens": 512}
    assert (
        fields["langfuse.observation.metadata.schema"],
        fields["langfuse.observation.metadata.messages"],
    ) == ("explanation", "2")
    # Neither the conversation nor the answer.
    sent = request.content.decode()
    for private in ("тајни рачун 4711", "4711", '{\\"answer\\": \\"da\\"}', "Answer in JSON"):
        assert private not in sent
    assert not [key for key in fields if key.endswith((".input", ".output"))]


async def test_a_failed_answer_is_traced_with_why_and_still_fails() -> None:
    langfuse = Langfuse()
    traced = TracedClient(ScriptedModel(LLMError("Groq answered 429, 3 times")), langfuse.traces())

    with pytest.raises(LLMError, match="429"):
        await traced.answer(CONVERSATION, name="repair", schema=SCHEMA)
    await traced.aclose()

    (span,) = langfuse.spans()
    assert span["status"] == {"code": 2, "message": "Groq answered 429, 3 times"}
    fields = attributes(span)
    assert fields["langfuse.observation.level"] == "ERROR"
    assert "langfuse.observation.usage_details" not in fields


async def test_the_answers_of_one_request_share_a_trace() -> None:
    langfuse = Langfuse()
    traced = TracedClient(ScriptedModel("{}", "{}", "{}"), langfuse.traces())

    async def asking(scope: Any, receive: Any, send: Any) -> None:
        for _ in range(2):
            await traced.answer(CONVERSATION, name="explanation", schema=SCHEMA)
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def ignore(message: Any) -> None:
        del message

    async def nothing() -> Any:
        return {"type": "http.request", "body": b""}

    await RequestIds(asking)(
        {"type": "http", "headers": [(b"x-request-id", b"r-1")]}, nothing, ignore
    )
    await traced.answer(CONVERSATION, name="explanation", schema=SCHEMA)
    await traced.aclose()

    first, second, alone = langfuse.spans()
    assert first["traceId"] == second["traceId"] != alone["traceId"]
    assert len(first["traceId"]) == 32
    assert attributes(first)["langfuse.trace.metadata.request_id"] == "r-1"
    assert "langfuse.trace.metadata.request_id" not in attributes(alone)


async def test_a_trace_that_cannot_be_sent_never_holds_up_the_answer(
    caplog: pytest.LogCaptureFixture,
) -> None:
    langfuse = Langfuse(answer=401)
    traced = TracedClient(ScriptedModel('{"answer": "da"}'), langfuse.traces())

    with caplog.at_level(logging.WARNING, logger="sef_api.model_traces"):
        answer = await traced.answer(CONVERSATION, name="explanation", schema=SCHEMA)
        await traced.aclose()

    assert answer == '{"answer": "da"}'
    assert "a model's trace was not taken: Langfuse answered 401" in caplog.text


async def test_unreachable_langfuse_is_logged_without_what_was_sent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    traces = ModelTraces(
        HOST, "pk", SecretStr("sk"), environment="test", transport=httpx.MockTransport(refuse)
    )
    traced = TracedClient(ScriptedModel("{}"), traces)

    with caplog.at_level(logging.WARNING, logger="sef_api.model_traces"):
        await traced.answer(CONVERSATION, name="explanation", schema=SCHEMA)
        await traced.aclose()

    assert "a model's trace was not sent (ConnectError)" in caplog.text
    assert "4711" not in caplog.text


def test_the_model_is_traced_only_where_both_keys_are_set() -> None:
    model = {"LLM_PROVIDER": "groq", "GROQ_API_KEY": "gsk_test_key"}
    plain = create_app(settings_for(**model)).state.explainer
    traced = create_app(
        settings_for(**model, LANGFUSE_PUBLIC_KEY="pk-lf-x", LANGFUSE_SECRET_KEY="sk-lf-x")
    ).state.explainer

    assert not isinstance(plain._llm, TracedClient)
    assert isinstance(traced._llm, TracedClient)
    with pytest.raises(ValueError, match="set together"):
        Settings.from_values({"LANGFUSE_PUBLIC_KEY": "pk-lf-x"})


async def test_the_tokens_of_an_answer_are_read_from_groq() -> None:
    requests: list[httpx.Request] = []
    groq = answering(lambda _: completion("{}"), requests)

    await groq.answer(CONVERSATION, name="reply", schema=SCHEMA)

    assert last_usage.get() == {"input": 120, "output": 40, "total": 160}


async def test_an_answer_that_reports_no_tokens_is_not_given_anothers() -> None:
    langfuse = Langfuse()
    requests: list[httpx.Request] = []
    counted = TracedClient(answering(lambda _: completion("{}"), requests), langfuse.traces())
    uncounted = TracedClient(ScriptedModel("{}"), langfuse.traces())

    await counted.answer(CONVERSATION, name="explanation", schema=SCHEMA)
    await uncounted.answer(CONVERSATION, name="explanation", schema=SCHEMA)
    await counted.aclose()
    await uncounted.aclose()

    first, second = langfuse.spans()
    assert "langfuse.observation.usage_details" in attributes(first)
    assert "langfuse.observation.usage_details" not in attributes(second)
