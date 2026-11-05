"""A client of server-sent events that speaks ASGI to the application itself, so that a test sees
each event when it is sent: httpx's ASGI transport hands a response over only once it is
complete."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from starlette.types import ASGIApp, Message

#: Seconds a test waits for the next part of a stream before it fails.
WAIT_SECONDS = 5.0


class EventStream:
    """A request for a stream of events, made by entering an ``async with`` block; leaving the
    block disconnects, as a client that goes away does, and waits for the application to let
    go of the request."""

    def __init__(self, app: ASGIApp, path: str, headers: Mapping[str, str]) -> None:
        self._app = app
        self._scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"test")]
            + [(name.lower().encode(), value.encode()) for name, value in headers.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("test", 80),
        }
        self._asked = False
        self._gone = asyncio.Event()
        self._sent: asyncio.Queue[Message] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None
        self._buffer = b""
        self._ended = False
        self.status = 0
        self.headers: dict[str, str] = {}

    async def __aenter__(self) -> EventStream:
        self._task = asyncio.create_task(self._call())
        start = await self._next_message()
        self.status = start["status"]
        for name, value in start["headers"]:  # repeated fields combined, as HTTP has it
            known = self.headers.get(name.decode())
            self.headers[name.decode()] = (
                value.decode() if known is None else f"{known}, {value.decode()}"
            )
        return self

    async def __aexit__(self, *_: object) -> None:
        self._gone.set()
        assert self._task is not None
        await asyncio.wait_for(self._task, WAIT_SECONDS)

    async def next_event(self) -> dict[str, str] | None:
        """The fields of the next event, comments left out; None once the stream has ended."""
        while True:
            if b"\n\n" in self._buffer:
                block, self._buffer = self._buffer.split(b"\n\n", 1)
                fields: dict[str, str] = {}
                for line in block.decode().splitlines():
                    if not line.startswith(":"):
                        name, _, value = line.partition(": ")
                        fields[name] = value
                if fields:
                    return fields
            elif self._ended:
                return None
            else:
                message = await self._next_message()
                self._buffer += message.get("body", b"")
                self._ended = not message.get("more_body", False)

    async def _call(self) -> None:
        await self._app(self._scope, self._receive, self._send)

    async def _receive(self) -> Message:
        if not self._asked:
            self._asked = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._gone.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: Message) -> None:
        await self._sent.put(message)

    async def _next_message(self) -> Message:
        return await asyncio.wait_for(self._sent.get(), WAIT_SECONDS)
