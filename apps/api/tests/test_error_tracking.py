"""Unexpected errors reported to Sentry, only where a DSN is set, and nothing a person sent
with them (ADR-0048)."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import sentry_sdk
from fastapi import FastAPI, Request
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from sef_api.error_tracking import RELEASE, scrubbed, track_errors
from sef_api.jobs import worker
from sef_api.main import create_app

from .conftest import settings_for
from .test_invoices_validate import Scripted

#: A DSN of no project: the transport below keeps what would be sent.
DSN = "https://public@o0.ingest.de.sentry.io/0"
#: What a person sent, which no report may hold.
SENT = ("Primer d.o.o.", "101134702", "Bearer sefk_", "q=PIB", "<Invoice>")


class Kept(Transport):
    """What would be sent to Sentry, kept."""

    def __init__(self) -> None:
        super().__init__({"dsn": DSN})
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(dict(event))


@pytest.fixture
def kept() -> Iterator[Kept]:
    """Reports kept rather than sent; no client once the test is done."""
    transport = Kept()
    yield transport
    sentry_sdk.get_global_scope().set_client(None)


def failing(transport: Kept) -> FastAPI:
    """The API with a route that fails as nothing should, while holding what a person sent."""
    # The application of a deployment without a DSN, then reports kept, not sent.
    app = create_app(settings_for())
    assert track_errors(settings_for(SENTRY_DSN=DSN), transport=transport)

    async def fail(q: str, request: Request) -> None:
        invoice = (await request.body()).decode()
        raise ValueError(f"could not read {invoice} for {q}")

    app.add_api_route("/fails", fail, methods=["POST"])
    return app


async def test_an_unexpected_error_is_reported_with_where_but_nothing_sent(kept: Kept) -> None:
    app = failing(kept)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        answer = await http.post(
            "/fails?q=PIB",
            content=b"<Invoice>Primer d.o.o., PIB 101134702</Invoice>",
            headers={"Authorization": "Bearer sefk_secret", "Cookie": "session=x"},
        )
    sentry_sdk.flush()

    assert answer.status_code == 500
    (event,) = kept.events
    (exception,) = event["exception"]["values"]
    assert exception["type"] == "ValueError"
    assert exception["value"].startswith("(the message is not sent")
    frames = exception["stacktrace"]["frames"]
    assert frames[-1]["function"] == "fail"
    assert all("vars" not in frame for frame in frames)
    assert event["request"] == {"method": "POST", "url": "http://test/fails"}
    assert (event["release"], event["environment"]) == (RELEASE, "test")
    assert not {"user", "breadcrumbs", "extra"} & set(event)
    reported = json.dumps(event)
    for sent in SENT:
        assert sent not in reported


async def test_a_line_logged_at_error_is_reported_without_what_it_was_given(kept: Kept) -> None:
    failing(kept)

    logging.getLogger("sef_api.test").error("could not store %s", "<Invoice>Primer d.o.o.")
    logging.getLogger("sef_api.test").warning("not reported")
    sentry_sdk.flush()

    (event,) = kept.events
    assert event["logentry"] == {"message": "could not store %s"}
    assert "Primer" not in json.dumps(event)


def test_without_a_dsn_nothing_is_sent_anywhere() -> None:
    """A self-hosted deployment calls out to nothing it did not choose."""
    assert track_errors(settings_for()) is False
    assert not sentry_sdk.get_client().is_active()


def test_whatever_an_integration_adds_is_taken_out() -> None:
    event: Any = {
        "request": {
            "method": "GET",
            "url": "https://api.example/invoices/1?after=x#top",
            "headers": {"Authorization": "Bearer x"},
            "cookies": {"session": "x"},
            "data": "<Invoice/>",
            "query_string": "after=x",
            "env": {"REMOTE_ADDR": "10.0.0.7"},
        },
        "user": {"ip_address": "10.0.0.7"},
        "breadcrumbs": {"values": [{"message": "x"}]},
        "extra": {"invoice": "x"},
        "logentry": {"message": "failed: %s", "params": ["x"], "formatted": "failed: x"},
        "exception": {
            "values": [{"type": "E", "value": "x", "stacktrace": {"frames": [{"vars": {"a": 1}}]}}]
        },
    }

    cleaned: Any = scrubbed(event, {})

    assert cleaned["request"] == {"method": "GET", "url": "https://api.example/invoices/1"}
    assert cleaned["logentry"] == {"message": "failed: %s"}
    assert cleaned["exception"]["values"][0]["stacktrace"]["frames"] == [{}]
    assert not {"user", "breadcrumbs", "extra"} & set(cleaned)


async def test_a_worker_reports_as_the_api_does(monkeypatch: pytest.MonkeyPatch) -> None:
    tracked: list[object] = []
    monkeypatch.setattr(worker, "track_errors", tracked.append)
    monkeypatch.setattr(worker, "validator_for", lambda _: Scripted())
    settings = settings_for(SENTRY_DSN=DSN)
    ctx: dict[str, Any] = {"settings": settings}

    await worker.startup(ctx)
    await worker.shutdown(ctx)

    assert tracked == [settings]


def test_the_sdk_is_asked_to_collect_nothing_a_person_sent(kept: Kept) -> None:
    """The first wall, before the scrubber: what the SDK would collect of a request is off."""
    failing(kept)

    options = sentry_sdk.get_client().options
    collected = options["data_collection"]
    assert collected["user_info"] is False
    assert collected["stack_frame_variables"] is False
    assert collected["http_bodies"] == []
    for category in ("cookies", "url_query_params"):
        assert collected[category] == {"mode": "off"}
    assert collected["http_headers"] == {"request": {"mode": "off"}}
    assert (options["max_breadcrumbs"], options["traces_sample_rate"]) == (0, None)
