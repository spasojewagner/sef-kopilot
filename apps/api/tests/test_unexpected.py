"""An unexpected failure: a 500 a page can read, and an exception the server still sees."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.responses import StreamingResponse

from sef_api.main import create_app

from .conftest import settings_for

WEB = "http://localhost:3000"


class UnexpectedError(RuntimeError):
    """A failure that no handler answers."""


def failing_app() -> FastAPI:
    app = create_app(settings_for(SEF_WEB_ORIGINS=WEB))

    @app.get("/test/fails")
    async def fails() -> None:
        raise UnexpectedError("a bug")

    @app.get("/test/fails-while-streaming")
    async def fails_while_streaming() -> StreamingResponse:
        async def chunks() -> AsyncIterator[bytes]:
            yield b"one "
            raise UnexpectedError("a bug, once the answer began")

        return StreamingResponse(chunks(), media_type="text/plain")

    return app


async def test_a_page_of_the_web_origin_reads_the_500_of_an_unexpected_failure() -> None:
    app = failing_app()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        answer = await client.get("/test/fails", headers={"Origin": WEB})
    await app.state.database.engine.dispose()

    assert answer.status_code == 500
    assert answer.headers["Access-Control-Allow-Origin"] == WEB
    assert answer.headers["Content-Type"] == "application/json; charset=utf-8"
    assert answer.json() == {"detail": "Internal Server Error"}


async def test_the_server_still_sees_the_exception() -> None:
    app = failing_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(UnexpectedError, match="a bug"):
            await client.get("/test/fails", headers={"Origin": WEB})
    await app.state.database.engine.dispose()


async def test_an_answer_that_had_begun_is_not_replaced() -> None:
    app = failing_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(UnexpectedError, match="once the answer began"):
            await client.get("/test/fails-while-streaming", headers={"Origin": WEB})
    await app.state.database.engine.dispose()


async def test_an_error_a_handler_answers_is_answered_as_before() -> None:
    app = failing_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        answer = await client.get("/no-such-page", headers={"Origin": WEB})
    await app.state.database.engine.dispose()

    assert answer.status_code == 404
    assert answer.headers["Access-Control-Allow-Origin"] == WEB
    assert answer.json() == {"detail": "Not Found"}
