"""Each request to the language model traced to Langfuse, where its keys are set, without the
conversation (ADR-0049).

A trace says what the model was asked to write and how it went: the schema it answered (an
explanation, a repair), the model, when it began and how long it took, the tokens it read and
wrote, and whether it answered or why not. It never holds what was sent or answered, which
quote an invoice. The requests of one API request share a trace, named by the request's id
(``X-Request-ID``), so a slow answer is found from its log lines and back.

A span is sent as OTLP over HTTP, in JSON, to Langfuse's endpoint, in the background: a trace
that cannot be sent is logged and given up, and the model's answer goes on regardless. Without
``LANGFUSE_PUBLIC_KEY`` and ``LANGFUSE_SECRET_KEY`` nothing is sent anywhere.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any, Final

import httpx
from pydantic import SecretStr

from sef_api import __version__
from sef_api.llm import LLMClient, LLMError, Message, last_usage
from sef_api.logs import current_request_id

__all__ = ["TRACES_PATH", "ModelTraces", "TracedClient"]

logger = logging.getLogger(__name__)

#: Where Langfuse takes spans, under its host.
TRACES_PATH: Final = "/api/public/otel/v1/traces"
#: The longest a span may take to be sent.
SEND_SECONDS: Final = 10.0
#: OTLP's span status codes.
_OK: Final = 1
_ERROR: Final = 2


class ModelTraces:
    """Spans sent to one Langfuse project, each in a task of its own."""

    def __init__(
        self,
        host: str,
        public_key: str,
        secret_key: SecretStr,
        *,
        environment: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        pair = f"{public_key}:{secret_key.get_secret_value()}".encode()
        self._client = httpx.AsyncClient(
            base_url=host.rstrip("/"),
            transport=transport,
            timeout=SEND_SECONDS,
            headers={
                "Authorization": f"Basic {base64.b64encode(pair).decode()}",
                "x-langfuse-ingestion-version": "4",
            },
        )
        self._environment = environment
        self._sending: set[asyncio.Task[None]] = set()

    def send(self, span: Mapping[str, Any]) -> None:
        """Send ``span`` in the background."""
        task = asyncio.create_task(self._send(span))
        self._sending.add(task)
        task.add_done_callback(self._sending.discard)

    async def _send(self, span: Mapping[str, Any]) -> None:
        body = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": _attributes(
                            {
                                "service.name": "sef-kopilot-api",
                                "service.version": __version__,
                                "deployment.environment": self._environment,
                            }
                        )
                    },
                    "scopeSpans": [{"scope": {"name": "sef_api.model_traces"}, "spans": [span]}],
                }
            ]
        }
        try:
            answer = await self._client.post(TRACES_PATH, json=body)
        except httpx.HTTPError as error:
            logger.warning("a model's trace was not sent (%s)", type(error).__name__)
            return
        if not answer.is_success:
            logger.warning(
                "a model's trace was not taken: Langfuse answered %d", answer.status_code
            )

    async def aclose(self) -> None:
        """Send what is under way, then close."""
        if self._sending:
            await asyncio.gather(*self._sending, return_exceptions=True)
        await self._client.aclose()


class TracedClient:
    """A language model whose every answer is traced, as :mod:`sef_api.model_traces` says."""

    def __init__(self, inner: LLMClient, traces: ModelTraces) -> None:
        self._inner = inner
        self._traces = traces

    @property
    def model(self) -> str:
        return self._inner.model

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        last_usage.set(None)
        began = time.time_ns()
        failure: str | None = None
        try:
            return await self._inner.answer(
                messages, name=name, schema=schema, max_tokens=max_tokens
            )
        except LLMError as error:
            # An LLMError says what went wrong, never what was asked (sef_api.llm).
            failure = str(error)
            raise
        except BaseException as error:
            failure = type(error).__name__
            raise
        finally:
            self._traces.send(
                self._span(
                    name,
                    messages=len(messages),
                    max_tokens=max_tokens,
                    began=began,
                    ended=time.time_ns(),
                    failure=failure,
                )
            )

    def _span(
        self,
        name: str,
        *,
        messages: int,
        max_tokens: int | None,
        began: int,
        ended: int,
        failure: str | None,
    ) -> dict[str, Any]:
        request_id = current_request_id()
        fields: dict[str, object] = {
            "langfuse.observation.type": "generation",
            "langfuse.observation.model.name": self._inner.model,
            "langfuse.observation.model.parameters": json.dumps({"max_tokens": max_tokens}),
            "langfuse.observation.metadata.schema": name,
            "langfuse.observation.metadata.messages": messages,
            "langfuse.release": f"sef-kopilot-api@{__version__}",
            "langfuse.version": __version__,
        }
        usage = last_usage.get()
        if usage is not None:
            fields["langfuse.observation.usage_details"] = json.dumps(usage)
        if request_id is not None:
            fields["langfuse.trace.metadata.request_id"] = request_id
        if failure is not None:
            fields |= {
                "langfuse.observation.level": "ERROR",
                "langfuse.observation.status_message": failure,
            }
        return {
            # The requests of one API request share a trace; a request without an id has its own.
            "traceId": _trace_id(request_id),
            "spanId": secrets.token_hex(8),
            "name": f"model.{name}",
            "kind": 3,  # client
            "startTimeUnixNano": str(began),
            "endTimeUnixNano": str(ended),
            "attributes": _attributes(fields),
            "status": ({"code": _OK} if failure is None else {"code": _ERROR, "message": failure}),
        }

    async def aclose(self) -> None:
        await self._traces.aclose()
        await self._inner.aclose()


def _trace_id(request_id: str | None) -> str:
    """32 hex digits: the request's id, digested, so that its spans share a trace."""
    if request_id is None:
        return secrets.token_hex(16)
    return hashlib.sha256(request_id.encode()).hexdigest()[:32]


def _attributes(fields: Mapping[str, object]) -> list[dict[str, Any]]:
    """``fields`` as OTLP's JSON writes attributes."""
    written: list[dict[str, Any]] = []
    for key, value in fields.items():
        if isinstance(value, bool) or not isinstance(value, int):
            written.append({"key": key, "value": {"stringValue": str(value)}})
        else:
            written.append({"key": key, "value": {"intValue": str(value)}})
    return written
