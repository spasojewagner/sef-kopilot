"""An unexpected failure answered where a page can read it.

Starlette answers an exception that no handler took in its outermost middleware, outside every
middleware of the application: its 500 has no CORS headers, so a page of another origin sees no
answer at all, only a network error, and says that the API cannot be reached. Answered here,
inside the CORS middleware, the 500 carries them, and a JSON body like every other error. The
exception is raised again once the answer is sent, so that the server logs it as before.
"""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["AnswerUnexpectedErrors"]


class AnswerUnexpectedErrors:
    """ASGI middleware, innermost: an exception that no handler answered becomes a 500 with
    ``{"detail": "Internal Server Error"}``, unless the answer had begun, which nothing can
    replace; the exception goes on either way."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def sending(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, sending)
        except Exception:
            if not started:
                answer = JSONResponse({"detail": "Internal Server Error"}, status_code=500)
                await answer(scope, receive, sending)
            raise
