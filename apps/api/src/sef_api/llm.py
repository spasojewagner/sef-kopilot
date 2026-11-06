"""Language models: what writes the explanations and proposes repairs, behind an adapter
(ADR-0021, ADR-0025).

An :class:`LLMClient` answers a conversation with JSON text that a JSON schema describes. The
provider is the one the settings name:

- ``LLM_PROVIDER=none``, the default: no model, and the API explains nothing;
- ``LLM_PROVIDER=groq`` calls Groq's chat completions with ``GROQ_API_KEY``, with the model that
  ``SEF_LLM_MODEL`` names, ``openai/gpt-oss-120b`` by default, whose structured outputs hold an
  answer to the schema while it is written.

The model is never trusted. Whoever asks it parses and checks the answer: the explainer checks
every citation against the passages it gave, the repairer every patch before code applies it.
What is sent may quote an invoice, so an error says what went wrong, never what the
conversation was.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol

import httpx

if TYPE_CHECKING:
    from pydantic import SecretStr

    from sef_api.settings import Settings

__all__ = ["LANGUAGES", "GroqClient", "LLMClient", "LLMError", "Language", "Message", "llm_for"]

#: The languages a model writes in for people: Serbian in the Latin script, or English.
Language = Literal["sr", "en"]
#: Each language as a prompt names it.
LANGUAGES: Final[dict[Language, str]] = {
    "sr": "Serbian, in the Latin script (latinica)",
    "en": "English",
}


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


class GroqClient:
    """Groq's OpenAI-compatible chat completions, with structured outputs in strict mode.

    An answer of 429 or 5xx, or a request that fails on the way, is tried again up to
    :attr:`ATTEMPTS` times, waiting longer each time or as long as ``Retry-After`` asks, at most
    :attr:`MAX_WAIT_SECONDS`; any other answer is an :class:`LLMError`. The GPT-OSS models
    reason before they answer: briefly, and without sending the reasoning back.
    """

    URL: Final = "https://api.groq.com/openai/v1/chat/completions"
    MODEL: Final = "openai/gpt-oss-120b"
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
        model: str = MODEL,
        client: httpx.AsyncClient | None = None,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        self._backoff = backoff_seconds

    @property
    def model(self) -> str:
        return f"groq/{self._model}"

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": message.role, "content": message.content} for message in messages
            ],
            "temperature": 0,
            "max_completion_tokens": max_tokens or self.MAX_TOKENS,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": dict(schema)},
            },
        }
        if self._model.startswith("openai/gpt-oss"):
            body |= {"reasoning_effort": "low", "include_reasoning": False}
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
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
                problem = f"Groq answered {response.status_code}"
                retry_after = response.headers.get("Retry-After")
                continue
            if response.status_code != httpx.codes.OK:
                raise LLMError(f"Groq answered {response.status_code}{_code(response)}")
            return _content(response)
        raise LLMError(f"{problem}, {self.ATTEMPTS} times")

    async def aclose(self) -> None:
        await self._client.aclose()

    def _wait(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), self.MAX_WAIT_SECONDS)
        return min(float(self._backoff * 2 ** (attempt - 1)), self.MAX_WAIT_SECONDS)


def _code(response: httpx.Response) -> str:
    """The error's code, which names what went wrong (``invalid_api_key``), and nothing of its
    message, which may repeat what was sent."""
    try:
        code = response.json()["error"]["code"]
    except (ValueError, KeyError, TypeError):
        return ""
    return f" ({code})" if isinstance(code, str) and code.isidentifier() else ""


def _content(response: httpx.Response) -> str:
    """The text of the first choice of a chat completion, which must be a whole answer."""
    try:
        choice = response.json()["choices"][0]
        content = choice["message"]["content"]
        finished = choice.get("finish_reason")
    except (ValueError, KeyError, IndexError, TypeError) as error:
        raise LLMError(f"Groq's answer is not a chat completion ({type(error).__name__})") from None
    if finished == "length":
        raise LLMError("the answer was cut off at the most tokens it may have")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("Groq answered nothing")
    return content


def llm_for(settings: Settings) -> LLMClient | None:
    """The model the settings name, or None when no model is to write anything."""
    if settings.llm_provider == "groq" and settings.groq_api_key is not None:
        model = settings.llm_model or GroqClient.MODEL
        return GroqClient(settings.groq_api_key, model=model)
    return None
