"""Language models: Groq's chat completions as the explainer's model, what they are sent, how
their failures end, and the settings that choose them."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

import sef_api.llm as llm_module
from sef_api.llm import GroqClient, LLMError, Message, llm_for

from .conftest import settings_for

KEY = SecretStr("gsk_test_key")
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
CONVERSATION = [Message("system", "Answer in JSON."), Message("user", "тајни рачун 4711")]


def answering(
    handler: Callable[[dict[str, Any]], httpx.Response],
    requests: list[httpx.Request],
    *,
    model: str = GroqClient.MODEL,
) -> GroqClient:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(json.loads(request.content))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return GroqClient(KEY, model=model, client=client, backoff_seconds=0)


def completion(content: str, *, finish_reason: str = "stop") -> httpx.Response:
    """A chat completion as Groq answers one."""
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-1",
            "object": "chat.completion",
            "model": GroqClient.MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160},
        },
    )


async def test_the_conversation_is_sent_with_the_schema_the_answer_must_keep() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: completion('{"answer": "da"}'), requests)

    answer = await client.answer(CONVERSATION, name="reply", schema=SCHEMA)

    assert answer == '{"answer": "da"}'
    assert client.model == "groq/openai/gpt-oss-120b"
    (request,) = requests
    assert request.url == GroqClient.URL
    assert request.headers["Authorization"] == "Bearer gsk_test_key"
    assert json.loads(request.content) == {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {"role": "system", "content": "Answer in JSON."},
            {"role": "user", "content": "тајни рачун 4711"},
        ],
        "temperature": 0,
        "max_completion_tokens": GroqClient.MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "reply", "strict": True, "schema": SCHEMA},
        },
        "reasoning_effort": "low",
        "include_reasoning": False,
    }


async def test_a_model_that_does_not_reason_is_not_asked_how_hard_to() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: completion("{}"), requests, model="qwen/qwen3.8-27b")

    await client.answer(CONVERSATION, name="reply", schema=SCHEMA)

    body = json.loads(requests[0].content)
    assert body["model"] == "qwen/qwen3.8-27b"
    assert "reasoning_effort" not in body
    assert "include_reasoning" not in body
    assert client.model == "groq/qwen/qwen3.8-27b"


async def test_a_busy_or_failing_service_is_asked_again_after_the_wait_it_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    class Clock:
        @staticmethod
        async def sleep(seconds: float) -> None:
            waits.append(seconds)

    monkeypatch.setattr(llm_module, "asyncio", Clock)
    answers = iter([httpx.Response(429, headers={"Retry-After": "3600"}), httpx.Response(503)])
    requests: list[httpx.Request] = []
    client = answering(
        lambda _body: next(answers, None) or completion('{"answer": "da"}'), requests
    )

    assert await client.answer(CONVERSATION, name="reply", schema=SCHEMA) == '{"answer": "da"}'
    assert len(requests) == 3
    assert waits == [GroqClient.MAX_WAIT_SECONDS, 0.0]  # at most ten seconds, then the backoff


async def test_without_a_wait_named_the_wait_doubles_up_to_ten_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    class Clock:
        @staticmethod
        async def sleep(seconds: float) -> None:
            waits.append(seconds)

    monkeypatch.setattr(llm_module, "asyncio", Clock)
    failing = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    client = GroqClient(KEY, client=failing, backoff_seconds=6)

    with pytest.raises(LLMError, match="Groq answered 503, 3 times"):
        await client.answer(CONVERSATION, name="reply", schema=SCHEMA)
    assert waits == [6.0, GroqClient.MAX_WAIT_SECONDS]  # 6, then 12 held to ten


async def test_a_request_that_fails_on_the_way_is_tried_again() -> None:
    failures = iter([httpx.ConnectError("refused")])

    def handle(body: dict[str, Any]) -> httpx.Response:
        if (failure := next(failures, None)) is not None:
            raise failure
        return completion('{"answer": "da"}')

    assert await answering(handle, []).answer(CONVERSATION, name="reply", schema=SCHEMA)


async def test_a_service_that_keeps_failing_is_given_up_after_three_attempts() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: httpx.Response(502), requests)

    with pytest.raises(LLMError, match="Groq answered 502, 3 times"):
        await client.answer(CONVERSATION, name="reply", schema=SCHEMA)
    assert len(requests) == GroqClient.ATTEMPTS


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (
            httpx.Response(
                401, json={"error": {"message": "Invalid API Key", "code": "invalid_api_key"}}
            ),
            r"Groq answered 401 \(invalid_api_key\)$",
        ),
        (
            httpx.Response(400, json={"error": {"message": "тајни рачун 4711", "code": "a b"}}),
            "Groq answered 400$",
        ),
        (httpx.Response(404, text="not found"), "Groq answered 404$"),
        (httpx.Response(200, json={"choices": []}), "not a chat completion"),
        (httpx.Response(200, text="<html>"), "not a chat completion"),
        (completion('{"answer": "da', finish_reason="length"), "cut off"),
        (completion("  "), "answered nothing"),
    ],
)
async def test_an_answer_that_is_not_a_whole_completion_is_an_error(
    answer: httpx.Response, problem: str
) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(LLMError, match=problem) as raised:
        await answering(lambda _body: answer, requests).answer(
            CONVERSATION, name="reply", schema=SCHEMA
        )
    assert "4711" not in str(raised.value)  # what was sent is never repeated
    assert len(requests) == 1  # and an answer of 4xx is not asked again


async def test_the_client_closes_its_connections() -> None:
    client = answering(lambda _body: completion("{}"), [])

    await client.aclose()

    with pytest.raises(RuntimeError):
        await client.answer(CONVERSATION, name="reply", schema=SCHEMA)


def test_the_settings_choose_the_model() -> None:
    assert llm_for(settings_for()) is None
    assert llm_for(settings_for(GROQ_API_KEY="gsk_key")) is None  # a key alone sends nothing
    groq = llm_for(settings_for(LLM_PROVIDER="groq", GROQ_API_KEY="gsk_key"))
    assert isinstance(groq, GroqClient)
    assert groq.model == "groq/openai/gpt-oss-120b"
    chosen = llm_for(
        settings_for(
            LLM_PROVIDER="groq", GROQ_API_KEY="gsk_key", SEF_LLM_MODEL="openai/gpt-oss-20b"
        )
    )
    assert chosen is not None
    assert chosen.model == "groq/openai/gpt-oss-20b"
    with pytest.raises(ValidationError, match="GROQ_API_KEY must be set"):
        settings_for(LLM_PROVIDER="groq")
    with pytest.raises(ValidationError):
        settings_for(LLM_PROVIDER="openai")


def test_the_limits_of_explaining_come_from_the_settings() -> None:
    settings = settings_for(
        SEF_MAX_EXPLANATIONS="3",
        SEF_EXPLANATION_SECONDS="12.5",
        SEF_EXPLANATIONS_PER_MINUTE="4",
        SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE="8",
    )

    assert (settings.max_explanations, settings.explanation_seconds) == (3, 12.5)
    assert (settings.explanations_per_minute, settings.organization_explanations_per_minute) == (
        4,
        8,
    )
    with pytest.raises(ValidationError):
        settings_for(SEF_MAX_EXPLANATIONS="0")
    with pytest.raises(ValidationError):
        settings_for(SEF_EXPLANATION_SECONDS="0")
