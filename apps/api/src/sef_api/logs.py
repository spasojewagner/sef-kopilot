"""The process's log lines as JSON, for a platform to index, and the security events (ASVS V7).

A deployment's server starts with ``--log-config`` naming ``apps/api/docker/logging.json``,
which writes every line, the server's own included, as one JSON object: its time, level,
logger and message, and, for a security event, the event's name and fields. In development
the server's default lines stay.

A security event is a decision about who may do what: a sign-in, a credential refused, a token
presented twice, a consent or a repair decided. It is logged under ``sef_api.security`` with
fields that identify (ids, an address, a reason), never what a person wrote or an invoice
holds.

Every line written while a request is answered names the request (``request_id``), which the
answer's ``X-Request-ID`` names too, so that a person who reports a failure gives the id that
finds its lines. A client may send its own id, which is kept if it is a plain token.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = [
    "REQUEST_ID",
    "SECURITY",
    "JsonFormatter",
    "RequestIds",
    "current_request_id",
    "security_event",
]

#: The header that names a request, in the request and in its answer.
REQUEST_ID: Final = "X-Request-ID"
#: An id a client may choose: a plain token, short enough for a log line.
_CHOSEN: Final = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
#: The id of the request being answered, if any.
_REQUEST: ContextVar[str | None] = ContextVar("request_id", default=None)

#: The logger of the security events.
SECURITY: Final = logging.getLogger("sef_api.security")

#: A field of an event: an id, an address, a reason, a count or a flag.
Field = str | int | bool | None


def current_request_id() -> str | None:
    """The id of the request being answered, if any."""
    return _REQUEST.get()


def security_event(event: str, **fields: Field) -> None:
    """Log the security event ``event`` with ``fields``, as one line."""
    shown = " ".join(f"{name}={value}" for name, value in fields.items())
    SECURITY.info(
        "%s %s", event, shown, extra={"event": event, "fields": dict(fields)}, stacklevel=2
    )


class JsonFormatter(logging.Formatter):
    """A log record as one JSON object on one line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = _REQUEST.get()
        if request_id is not None:
            entry["request_id"] = request_id
        event = getattr(record, "event", None)
        if isinstance(event, str):
            fields = getattr(record, "fields", {})
            entry |= {"event": event, **(fields if isinstance(fields, dict) else {})}
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class RequestIds:
    """ASGI middleware: each HTTP request gets an id, its client's if it is a plain token, a new
    one otherwise, which its log lines carry and its answer's ``X-Request-ID`` names."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        chosen = Headers(scope=scope).get(REQUEST_ID, "")
        request_id = chosen if _CHOSEN.fullmatch(chosen) else uuid.uuid4().hex
        token = _REQUEST.set(request_id)

        async def named(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID] = request_id
            await send(message)

        try:
            await self.app(scope, receive, named)
        finally:
            _REQUEST.reset(token)
