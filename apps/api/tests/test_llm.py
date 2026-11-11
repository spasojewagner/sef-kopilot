"""Language models: Groq's and OpenAI's chat completions and Anthropic's Messages API as the
explainer's model, what they are sent, how their answers read and their failures end, and the
settings that choose them. Each provider answers here as its API reference shows an answer."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

import sef_api.llm as llm_module
from sef_api.llm import (
    AnthropicClient,
    GroqClient,
    LLMError,
    Message,
    OpenAIClient,
    Picture,
    client_for,
    last_usage,
    llm_for,
    reading_llm_for,
)

from .conftest import settings_for

KEY = SecretStr("gsk_test_key")
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
CONVERSATION = [Message("system", "Answer in JSON."), Message("user", "тајни рачун 4711")]


def answering[Client: (GroqClient, OpenAIClient, AnthropicClient)](
    handler: Callable[[dict[str, Any]], httpx.Response],
    requests: list[httpx.Request],
    *,
    model: str | None = None,
    provider: type[Client] = GroqClient,  # type: ignore[assignment]
) -> Client:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(json.loads(request.content))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return provider(KEY, model=model, client=client, backoff_seconds=0)


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


async def test_a_question_may_let_the_model_write_more() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: completion("{}"), requests)

    await client.answer(CONVERSATION, name="reply", schema=SCHEMA, max_tokens=2048)
    await client.answer(CONVERSATION, name="reply", schema=SCHEMA)

    sent = [json.loads(request.content)["max_completion_tokens"] for request in requests]
    assert sent == [2048, GroqClient.MAX_TOKENS]


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
        (
            httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Failed to generate JSON.",
                        "code": "json_validate_failed",
                        "failed_generation": '{"number": "4711", ' + " " * 50,
                    }
                },
            ),
            r"Groq answered 400 \(json_validate_failed; 69 characters, cut off, "
            r"the last 51 blank\)$",
        ),
        (
            httpx.Response(
                400,
                json={
                    "error": {
                        "code": "json_validate_failed",
                        "failed_generation": '{"number": 4711}',
                    }
                },
            ),
            r"Groq answered 400 \(json_validate_failed; 16 characters, whole JSON\)$",
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


def test_the_limits_of_asking_the_model_come_from_the_settings() -> None:
    settings = settings_for(
        SEF_MAX_EXPLANATIONS="3",
        SEF_EXPLANATION_SECONDS="12.5",
        SEF_REPAIR_SECONDS="7.5",
        SEF_EXPLANATIONS_PER_MINUTE="4",
        SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE="8",
    )

    assert (settings.max_explanations, settings.explanation_seconds) == (3, 12.5)
    assert (settings.repair_seconds, settings_for().repair_seconds) == (7.5, 20.0)
    assert (settings.explanations_per_minute, settings.organization_explanations_per_minute) == (
        4,
        8,
    )
    with pytest.raises(ValidationError):
        settings_for(SEF_MAX_EXPLANATIONS="0")
    with pytest.raises(ValidationError):
        settings_for(SEF_EXPLANATION_SECONDS="0")
    with pytest.raises(ValidationError):
        settings_for(SEF_REPAIR_SECONDS="0")


# --- OpenAI -------------------------------------------------------------------------------------


async def test_openai_is_asked_for_its_chat_completions_with_brief_reasoning() -> None:
    requests: list[httpx.Request] = []
    client = answering(
        lambda _body: completion('{"answer": "da"}'), requests, provider=OpenAIClient
    )

    answer = await client.answer(CONVERSATION, name="reply", schema=SCHEMA)

    assert answer == '{"answer": "da"}'
    assert client.model == "openai/gpt-6-luna"
    (request,) = requests
    assert request.url == "https://api.openai.com/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer gsk_test_key"
    assert json.loads(request.content) == {
        "model": "gpt-6-luna",
        "messages": [
            {"role": "system", "content": "Answer in JSON."},
            {"role": "user", "content": "тајни рачун 4711"},
        ],
        "max_completion_tokens": OpenAIClient.MAX_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "reply", "strict": True, "schema": SCHEMA},
        },
        "reasoning_effort": "low",
    }
    assert last_usage.get() == {"input": 120, "output": 40, "total": 160}


async def test_an_openai_model_that_does_not_reason_is_not_asked_how_hard_to() -> None:
    requests: list[httpx.Request] = []
    client = answering(
        lambda _body: completion("{}"), requests, model="gpt-4.1-mini", provider=OpenAIClient
    )

    await client.answer(CONVERSATION, name="reply", schema=SCHEMA)

    body = json.loads(requests[0].content)
    assert (body["model"], "reasoning_effort" in body, "temperature" in body) == (
        "gpt-4.1-mini",
        False,
        False,
    )
    assert client.model == "openai/gpt-4.1-mini"


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (
            httpx.Response(
                401,
                json={
                    "error": {
                        "message": "Incorrect API key provided: sk-...4711.",
                        "type": "invalid_request_error",
                        "param": None,
                        "code": "invalid_api_key",
                    }
                },
            ),
            r"OpenAI answered 401 \(invalid_api_key\)$",
        ),
        (httpx.Response(200, json={"object": "chat.completion"}), "OpenAI's answer is not a"),
        (completion(""), "OpenAI answered nothing"),
    ],
)
async def test_openai_s_failures_say_what_went_wrong_and_nothing_sent(
    answer: httpx.Response, problem: str
) -> None:
    with pytest.raises(LLMError, match=problem) as raised:
        await answering(lambda _body: answer, [], provider=OpenAIClient).answer(
            CONVERSATION, name="reply", schema=SCHEMA
        )
    assert "4711" not in str(raised.value)


# --- Anthropic ----------------------------------------------------------------------------------


def message(
    *blocks: dict[str, Any], stop_reason: str = "end_turn", usage: object = None
) -> httpx.Response:
    """A message as Anthropic's Messages API answers one."""
    return httpx.Response(
        200,
        json={
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": AnthropicClient.MODEL,
            "content": list(blocks),
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": usage if usage is not None else {"input_tokens": 210, "output_tokens": 35},
        },
    )


def text(content: str) -> dict[str, Any]:
    return {"type": "text", "text": content}


async def test_anthropic_is_sent_the_system_apart_and_asked_for_the_schema() -> None:
    requests: list[httpx.Request] = []
    client = answering(
        lambda _body: message(text('{"answer": "da"}')), requests, provider=AnthropicClient
    )
    conversation = [
        *CONVERSATION,
        Message("assistant", '{"answer": "ne"}'),
        Message("user", "That answer cannot be used. Answer again."),
    ]

    answer = await client.answer(conversation, name="reply", schema=SCHEMA, max_tokens=2048)

    assert answer == '{"answer": "da"}'
    assert client.model == "anthropic/claude-haiku-5-5"
    (request,) = requests
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "gsk_test_key"
    assert request.headers["anthropic-version"] == "2026-10-21"
    assert "Authorization" not in request.headers
    assert json.loads(request.content) == {
        "model": "claude-haiku-5-5",
        "max_tokens": 2048,
        "system": "Answer in JSON.",
        "messages": [
            {"role": "user", "content": "тајни рачун 4711"},
            {"role": "assistant", "content": '{"answer": "ne"}'},
            {"role": "user", "content": "That answer cannot be used. Answer again."},
        ],
        "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}},
    }
    assert last_usage.get() == {"input": 210, "output": 35, "total": 245}


async def test_anthropic_without_a_system_message_is_sent_none() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: message(text("{}")), requests, provider=AnthropicClient)

    await client.answer(CONVERSATION[1:], name="reply", schema=SCHEMA)

    assert "system" not in json.loads(requests[0].content)


@pytest.mark.parametrize(
    "usage", [{"input_tokens": "many", "output_tokens": 3}, {"input_tokens": 210}, []]
)
async def test_anthropic_s_answer_is_its_first_text_block_and_its_count_if_it_gives_one(
    usage: object,
) -> None:
    client = answering(
        lambda _body: message(
            {"type": "thinking", "thinking": "…", "signature": "s"},
            text('{"answer": "da"}'),
            text("{}"),
            usage=usage,
        ),
        [],
        provider=AnthropicClient,
    )

    assert await client.answer(CONVERSATION, name="reply", schema=SCHEMA) == '{"answer": "da"}'
    assert last_usage.get() is None


async def test_anthropic_overloaded_is_asked_again() -> None:
    answers = iter([httpx.Response(529, json={"type": "error", "error": {"type": "x"}})])
    requests: list[httpx.Request] = []
    client = answering(
        lambda _body: next(answers, None) or message(text("{}")),
        requests,
        provider=AnthropicClient,
    )

    assert await client.answer(CONVERSATION, name="reply", schema=SCHEMA) == "{}"
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (
            httpx.Response(
                401,
                json={
                    "type": "error",
                    "error": {"type": "authentication_error", "message": "invalid x-api-key"},
                },
            ),
            r"Anthropic answered 401 \(authentication_error\)$",
        ),
        (
            httpx.Response(
                400,
                json={
                    "type": "error",
                    "error": {"type": "invalid_request_error", "message": "тајни рачун 4711"},
                },
            ),
            r"Anthropic answered 400 \(invalid_request_error\)$",
        ),
        (message(text('{"answer": "da'), stop_reason="max_tokens"), "cut off"),
        (message(text("{}"), stop_reason="refusal"), "declined to answer"),
        (message(), "Anthropic answered nothing"),
        (message(text("  ")), "Anthropic answered nothing"),
        (httpx.Response(200, json={"type": "message"}), "Anthropic's answer is not a message"),
        (httpx.Response(200, text="<html>"), "Anthropic's answer is not a message"),
    ],
)
async def test_anthropic_s_failures_say_what_went_wrong_and_nothing_sent(
    answer: httpx.Response, problem: str
) -> None:
    requests: list[httpx.Request] = []
    with pytest.raises(LLMError, match=problem) as raised:
        await answering(lambda _body: answer, requests, provider=AnthropicClient).answer(
            CONVERSATION, name="reply", schema=SCHEMA
        )
    assert "4711" not in str(raised.value)
    assert len(requests) == 1


async def test_a_completion_that_counts_nothing_is_traced_without_a_count() -> None:
    answer = completion("{}")
    body = json.loads(answer.content)
    del body["usage"]
    client = answering(lambda _body: httpx.Response(200, json=body), [])

    await client.answer(CONVERSATION, name="reply", schema=SCHEMA)

    assert last_usage.get() is None


def test_each_provider_is_chosen_by_its_name_and_its_key() -> None:
    openai = llm_for(settings_for(LLM_PROVIDER="openai", OPENAI_API_KEY="openai-test-key"))
    assert isinstance(openai, OpenAIClient)
    assert openai.model == "openai/gpt-6-luna"
    anthropic = llm_for(
        settings_for(
            LLM_PROVIDER="anthropic",
            ANTHROPIC_API_KEY="anthropic-test-key",
            SEF_LLM_MODEL="claude-x",
        )
    )
    assert isinstance(anthropic, AnthropicClient)
    assert anthropic.model == "anthropic/claude-x"
    # The other providers' keys send nothing.
    assert (
        llm_for(
            settings_for(OPENAI_API_KEY="openai-test-key", ANTHROPIC_API_KEY="anthropic-test-key")
        )
        is None
    )
    with pytest.raises(ValidationError, match="OPENAI_API_KEY must be set"):
        settings_for(LLM_PROVIDER="openai", ANTHROPIC_API_KEY="anthropic-test-key")
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY must be set"):
        settings_for(LLM_PROVIDER="anthropic")
    with pytest.raises(ValidationError):
        settings_for(LLM_PROVIDER="mistral")
    assert client_for("mistral", KEY, None) is None
    assert client_for("groq", None, None) is None


PAGE = Picture("image/jpeg", b"\xff\xd8\xff page one")
SHOWING = [
    Message("system", "Answer in JSON."),
    Message("user", "Read the fields.", pictures=(PAGE, Picture("image/png", b"\x89PNG two"))),
]


def test_a_picture_is_its_bytes_in_a_data_url() -> None:
    assert PAGE.data_url == "data:image/jpeg;base64,/9j/IHBhZ2Ugb25l"


async def test_chat_completions_are_shown_pictures_after_the_text() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: completion("{}"), requests, model="qwen/qwen3.8-27b")

    await client.answer(SHOWING, name="reply", schema=SCHEMA)

    assert json.loads(requests[0].content)["messages"] == [
        {"role": "system", "content": "Answer in JSON."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Read the fields."},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,/9j/IHBhZ2Ugb25l"},
                },
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORyB0d28="}},
            ],
        },
    ]


async def test_openai_is_shown_pictures_as_groq_is() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: completion("{}"), requests, provider=OpenAIClient)

    await client.answer(SHOWING, name="reply", schema=SCHEMA)

    parts = json.loads(requests[0].content)["messages"][1]["content"]
    assert [part["type"] for part in parts] == ["text", "image_url", "image_url"]


async def test_anthropic_is_shown_pictures_before_the_text() -> None:
    requests: list[httpx.Request] = []
    client = answering(lambda _body: message(text("{}")), requests, provider=AnthropicClient)

    await client.answer(SHOWING, name="reply", schema=SCHEMA)

    assert json.loads(requests[0].content)["messages"] == [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": "/9j/IHBhZ2Ugb25l",
                    },
                },
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "iVBORyB0d28="},
                },
                {"type": "text", "text": "Read the fields."},
            ],
        }
    ]


def test_the_reading_model_is_the_provider_s_unless_the_settings_name_another() -> None:
    assert reading_llm_for(settings_for()) is None
    groq = reading_llm_for(settings_for(LLM_PROVIDER="groq", GROQ_API_KEY="gsk_key"))
    assert isinstance(groq, GroqClient)
    assert groq.model == "groq/qwen/qwen3.8-27b"
    openai = reading_llm_for(settings_for(LLM_PROVIDER="openai", OPENAI_API_KEY="openai-key"))
    assert openai is not None
    assert openai.model == "openai/gpt-6-luna"
    anthropic = reading_llm_for(
        settings_for(LLM_PROVIDER="anthropic", ANTHROPIC_API_KEY="anthropic-key")
    )
    assert anthropic is not None
    assert anthropic.model == "anthropic/claude-haiku-5-5"
    chosen = reading_llm_for(
        settings_for(
            LLM_PROVIDER="groq",
            GROQ_API_KEY="gsk_key",
            SEF_LLM_MODEL="openai/gpt-oss-20b",
            SEF_EXTRACTION_MODEL="meta-models/muse-spark-open",
        )
    )
    assert chosen is not None
    # The model that writes explanations does not read pictures; the reading model is apart.
    assert chosen.model == "groq/meta-models/muse-spark-open"
