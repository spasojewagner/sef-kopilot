"""Language models: what writes the explanations and proposes repairs, behind an adapter
(ADR-0021, ADR-0025).

An :class:`LLMClient` answers a conversation with JSON text that a JSON schema describes. The
provider is the one the settings name:

- ``LLM_PROVIDER=none``, the default: no model, and the API explains nothing;
- ``LLM_PROVIDER=groq`` calls Groq's chat completions with ``GROQ_API_KEY``,
  ``openai/gpt-oss-120b`` by default, on the free tier;
- ``LLM_PROVIDER=openai`` calls OpenAI's chat completions with ``OPENAI_API_KEY``,
  ``gpt-6-luna`` by default;
- ``LLM_PROVIDER=anthropic`` calls Anthropic's Messages API with ``ANTHROPIC_API_KEY``,
  ``claude-haiku-5-5`` by default.

``SEF_LLM_MODEL`` names another model of the provider. Each is asked for structured outputs, which
hold an answer to the schema while it is written (ADR-0057).

The model is never trusted. Whoever asks it parses and checks the answer: the explainer checks
every citation against the passages it gave, the repairer every patch before code applies it.
What is sent may quote an invoice, so an error says what went wrong, never what the
conversation was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Final, Literal, Protocol

import httpx

if TYPE_CHECKING:
    from pydantic import SecretStr

    from sef_api.settings import Settings

__all__ = [
    "LANGUAGES",
    "PROVIDERS",
    "AnthropicClient",
    "GroqClient",
    "LLMClient",
    "LLMError",
    "Language",
    "Message",
    "OpenAIClient",
    "client_for",
    "last_usage",
    "llm_for",
]

#: The languages a model writes in for people: Serbian in the Latin script, or English.
Language = Literal["sr", "en"]
#: Each language as a prompt names it.
LANGUAGES: Final[dict[Language, str]] = {
    "sr": "Serbian, in the Latin script (latinica)",
    "en": "English",
}


#: The tokens the last answer of this task read and wrote, as a model reports them (``input``,
#: ``output``, ``total``), for whoever traces the request; None if it said nothing.
last_usage: ContextVar[dict[str, int] | None] = ContextVar("last_usage", default=None)


class LLMError(Exception):
    """The model gave no answer to use; the message says why, never what was asked."""


@dataclass(frozen=True)
class Message:
    """One turn of a conversation with a model."""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMClient(Protocol):
    """Something that answers a conversation with JSON that a schema describes."""

    @property
    def model(self) -> str:
        """The provider and the model, as an answer names what wrote it."""
        ...

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        """The model's answer to ``messages``: JSON text meant to be what ``schema`` (named
        ``name``) describes, unparsed and unchecked, of at most ``max_tokens`` tokens with the
        model's reasoning, or of as many as the client allows."""
        ...

    async def aclose(self) -> None: ...


class _HTTPClient:
    """A provider's HTTP API that answers a conversation, asked again when it is busy.

    An answer of 429 or 5xx, or a request that fails on the way, is tried again up to
    :attr:`ATTEMPTS` times, waiting longer each time or as long as ``Retry-After`` asks, at most
    :attr:`MAX_WAIT_SECONDS`; any other answer is an :class:`LLMError` that names the provider,
    the status and the error's code, never its message, which may repeat what was sent.
    A provider says where it answers (:attr:`URL`), how it is named (:attr:`NAME`,
    :attr:`PREFIX`), its default model (:attr:`MODEL`), and how a request and an answer read.
    """

    URL: ClassVar[str]
    NAME: ClassVar[str]
    PREFIX: ClassVar[str]
    MODEL: ClassVar[str]
    ATTEMPTS: Final = 3
    TIMEOUT_SECONDS: Final = 30.0
    MAX_WAIT_SECONDS: Final = 10.0
    #: Tokens the model may write, its reasoning included, unless a question asks for more: an
    #: explanation needs a few hundred.
    MAX_TOKENS: Final = 1024

    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._model = model or self.MODEL
        self._client = client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        self._backoff = backoff_seconds

    @property
    def model(self) -> str:
        return f"{self.PREFIX}/{self._model}"

    def _body(
        self,
        messages: Sequence[Message],
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        raise NotImplementedError

    def _read(self, answer: Any) -> tuple[str, dict[str, int] | None]:
        """The answer's text and the tokens it counted, or :class:`LLMError`."""
        raise NotImplementedError

    def _code(self, error: Any) -> object:
        """The code an error's body names, which says what went wrong."""
        raise NotImplementedError

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        body = self._body(messages, name, schema, max_tokens or self.MAX_TOKENS)
        headers = self._headers()
        problem = "no answer"
        retry_after: str | None = None
        for attempt in range(self.ATTEMPTS):
            if attempt:
                await asyncio.sleep(self._wait(attempt, retry_after))
                retry_after = None
            try:
                response = await self._client.post(self.URL, json=body, headers=headers)
            except httpx.HTTPError as error:
                problem = f"the request failed ({type(error).__name__})"
                continue
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS or response.is_server_error:
                problem = f"{self.NAME} answered {response.status_code}"
                retry_after = response.headers.get("Retry-After")
                continue
            if response.status_code != httpx.codes.OK:
                raise LLMError(
                    f"{self.NAME} answered {response.status_code}{self._named(response)}"
                )
            try:
                answer = response.json()
            except ValueError:
                answer = None
            text, usage = self._read(answer)
            last_usage.set(usage)
            return text
        raise LLMError(f"{problem}, {self.ATTEMPTS} times")

    async def aclose(self) -> None:
        await self._client.aclose()

    def _wait(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), self.MAX_WAIT_SECONDS)
        return min(float(self._backoff * 2 ** (attempt - 1)), self.MAX_WAIT_SECONDS)

    def _named(self, response: httpx.Response) -> str:
        """The error's code, which names what went wrong (``invalid_api_key``), and nothing of
        its message, which may repeat what was sent."""
        try:
            code = self._code(response.json())
        except (ValueError, KeyError, TypeError):
            return ""
        return f" ({code})" if isinstance(code, str) and code.isidentifier() else ""


class _ChatCompletions(_HTTPClient):
    """OpenAI's chat completions, with structured outputs in strict mode, as Groq offers them
    too."""

    def _body(
        self,
        messages: Sequence[Message],
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        return {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "max_completion_tokens": max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": dict(schema)},
            },
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}

    def _code(self, error: Any) -> object:
        return error["error"]["code"]

    def _read(self, answer: Any) -> tuple[str, dict[str, int] | None]:
        """The text of the first choice of a chat completion, which must be a whole answer."""
        try:
            choice = answer["choices"][0]
            content = choice["message"]["content"]
            finished = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError(
                f"{self.NAME}'s answer is not a chat completion ({type(error).__name__})"
            ) from None
        if finished == "length":
            raise LLMError("the answer was cut off at the most tokens it may have")
        if not isinstance(content, str) or not content.strip():
            raise LLMError(f"{self.NAME} answered nothing")
        return content, _usage(answer)


class GroqClient(_ChatCompletions):
    """Groq's OpenAI-compatible chat completions. The GPT-OSS models reason before they answer:
    briefly, and without sending the reasoning back."""

    URL: ClassVar[str] = "https://api.groq.com/openai/v1/chat/completions"
    NAME: ClassVar[str] = "Groq"
    PREFIX: ClassVar[str] = "groq"
    MODEL: ClassVar[str] = "openai/gpt-oss-120b"

    def _body(
        self,
        messages: Sequence[Message],
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        body = super()._body(messages, name, schema, max_tokens) | {"temperature": 0}
        if self._model.startswith("openai/gpt-oss"):
            body |= {"reasoning_effort": "low", "include_reasoning": False}
        return body


class OpenAIClient(_ChatCompletions):
    """OpenAI's chat completions. Its reasoning models (:attr:`REASONING`) are asked to reason
    briefly, as their reasoning counts against the tokens an answer may have, and take no
    temperature; others are sent neither."""

    URL: ClassVar[str] = "https://api.openai.com/v1/chat/completions"
    NAME: ClassVar[str] = "OpenAI"
    PREFIX: ClassVar[str] = "openai"
    MODEL: ClassVar[str] = "gpt-6-luna"
    #: The beginnings of the names of the models that reason before they answer.
    REASONING: ClassVar[tuple[str, ...]] = ("gpt-6", "gpt-5", "o3", "o4")

    def _body(
        self,
        messages: Sequence[Message],
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        body = super()._body(messages, name, schema, max_tokens)
        if self._model.startswith(self.REASONING):
            body["reasoning_effort"] = "low"
        return body


class AnthropicClient(_HTTPClient):
    """Anthropic's Messages API, with structured outputs (``output_config.format``): the
    system's messages go to ``system``, the others in turn, and the answer is the text of its
    first text block. API version :attr:`VERSION` takes no temperature."""

    URL: ClassVar[str] = "https://api.anthropic.com/v1/messages"
    NAME: ClassVar[str] = "Anthropic"
    PREFIX: ClassVar[str] = "anthropic"
    MODEL: ClassVar[str] = "claude-haiku-5-5"
    VERSION: ClassVar[str] = "2026-10-21"

    def _body(
        self,
        messages: Sequence[Message],
        name: str,  # noqa: ARG002  # the schema needs no name here
        schema: Mapping[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
                if message.role != "system"
            ],
            "output_config": {"format": {"type": "json_schema", "schema": dict(schema)}},
        }
        if system := [message.content for message in messages if message.role == "system"]:
            body["system"] = "\n\n".join(system)
        return body

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key.get_secret_value(),
            "anthropic-version": self.VERSION,
        }

    def _code(self, error: Any) -> object:
        return error["error"]["type"]

    def _read(self, answer: Any) -> tuple[str, dict[str, int] | None]:
        """The text of the answer's first text block, which must be a whole answer."""
        try:
            stopped = answer["stop_reason"]
            texts = [block["text"] for block in answer["content"] if block["type"] == "text"]
        except (KeyError, TypeError) as error:
            raise LLMError(
                f"Anthropic's answer is not a message ({type(error).__name__})"
            ) from None
        if stopped == "max_tokens":
            raise LLMError("the answer was cut off at the most tokens it may have")
        if stopped == "refusal":
            raise LLMError("Anthropic's model declined to answer")
        if not texts or not isinstance(texts[0], str) or not texts[0].strip():
            raise LLMError("Anthropic answered nothing")
        try:
            read, written = answer["usage"]["input_tokens"], answer["usage"]["output_tokens"]
        except (KeyError, TypeError):
            return texts[0], None
        if not (isinstance(read, int) and isinstance(written, int)):
            return texts[0], None
        return texts[0], {"input": read, "output": written, "total": read + written}


def _usage(answer: Any) -> dict[str, int] | None:
    """The tokens a chat completion read and wrote, if it says."""
    try:
        usage = answer["usage"]
        counted = {
            "input": usage["prompt_tokens"],
            "output": usage["completion_tokens"],
            "total": usage["total_tokens"],
        }
    except (KeyError, TypeError):
        return None
    return counted if all(isinstance(count, int) for count in counted.values()) else None


#: The providers a deployment may name (``LLM_PROVIDER``), each with its client.
PROVIDERS: Final[dict[str, type[_HTTPClient]]] = {
    "groq": GroqClient,
    "openai": OpenAIClient,
    "anthropic": AnthropicClient,
}


def client_for(provider: str, api_key: SecretStr | None, model: str | None) -> LLMClient | None:
    """The model of ``provider`` named ``model``, or its default, asked with ``api_key``; None
    when the provider is none, or no key is given."""
    client = PROVIDERS.get(provider)
    if client is None or api_key is None:
        return None
    return client(api_key, model=model)


def llm_for(settings: Settings) -> LLMClient | None:
    """The model the settings name, or None when no model is to write anything."""
    keys = {
        "groq": settings.groq_api_key,
        "openai": settings.openai_api_key,
        "anthropic": settings.anthropic_api_key,
    }
    provider = settings.llm_provider
    return client_for(provider, keys.get(provider), settings.llm_model)
