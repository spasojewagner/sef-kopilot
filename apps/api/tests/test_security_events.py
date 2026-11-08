"""The security events (ASVS V7): a line for each decision about who may do what, with the
fields that identify it and nothing a person wrote; and every line as JSON in a deployment."""

from __future__ import annotations

import json
import logging
import logging.config
import re
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.api_keys.service import PREFIX
from sef_api.logs import SECURITY, JsonFormatter, RequestIds, security_event

from .conftest import REPOSITORY_ROOT
from .factories import office
from .test_auth import PASSWORD, login, refresh, register
from .test_mcp import POSTED, Served, initialize, served
from .test_oauth_authorization import authorize, sent_to, server
from .test_oauth_tokens import consented, exchange, registered, renewal, token
from .test_repairs import TYPE_CODE, kept, path, proposed

DOCKER = REPOSITORY_ROOT / "apps" / "api" / "docker"

__all__ = ["served"]  # the fixture, shared with test_mcp


@pytest.fixture
def events(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """What the test logs, the security events at their level."""
    caplog.set_level(logging.INFO, logger=SECURITY.name)
    return caplog


def named(events: pytest.LogCaptureFixture, event: str) -> list[dict[str, Any]]:
    """The fields of each ``event`` logged so far."""
    return [
        dict(getattr(record, "fields", {}))
        for record in events.records
        if record.name == SECURITY.name and getattr(record, "event", None) == event
    ]


def logged(events: pytest.LogCaptureFixture) -> str:
    return " ".join(record.getMessage() for record in events.records)


# --- signing in -----------------------------------------------------------------------------------


async def test_a_sign_in_is_logged_with_who_and_from_where(
    api: AsyncClient, events: pytest.LogCaptureFixture
) -> None:
    registered = await register(api)
    signed_in = await login(api)

    assert signed_in.status_code == 200
    (fields,) = named(events, "sign-in.succeeded")
    assert fields == {
        "user": registered["user"]["id"],
        "organization": registered["organization"]["id"],
        "address": "127.0.0.1",
    }


async def test_a_refused_sign_in_says_why_and_never_what_was_typed(
    api: AsyncClient, events: pytest.LogCaptureFixture
) -> None:
    await register(api)
    typed = "ana@primer.example-wrong-password"

    wrong = await login(api, password=typed)
    unknown = await login(api, email="nobody@primer.example")

    assert (wrong.status_code, unknown.status_code) == (401, 401)
    assert named(events, "sign-in.refused") == [
        {"reason": "credentials", "address": "127.0.0.1"},
        {"reason": "credentials", "address": "127.0.0.1"},
    ]
    lines = logged(events)
    assert typed not in lines
    assert "nobody@primer.example" not in lines
    assert PASSWORD not in lines


async def test_too_many_attempts_and_a_stranger_to_the_organization_are_logged(
    api: AsyncClient, events: pytest.LogCaptureFixture
) -> None:
    await register(api)
    elsewhere = await login(api, organization_id=str(uuid.uuid4()))
    for _ in range(10):
        await login(api, password="not the password at all")
    held = await login(api)

    assert (elsewhere.status_code, held.status_code) == (403, 429)
    reasons = [fields["reason"] for fields in named(events, "sign-in.refused")]
    assert reasons[0] == "not-a-member"
    assert reasons[-1] == "too-many-attempts"


async def test_a_refresh_token_presented_again_ends_its_sessions_and_is_logged(
    api: AsyncClient, events: pytest.LogCaptureFixture
) -> None:
    registered = await register(api)
    first = registered["refresh_token"]
    assert (await refresh(api, first)).status_code == 200

    replayed = await refresh(api, first)

    assert replayed.status_code == 401
    (fields,) = named(events, "session.refresh-reused")
    assert (fields["user"], fields["organization"]) == (
        registered["user"]["id"],
        registered["organization"]["id"],
    )
    assert fields["family"]


# --- keys -----------------------------------------------------------------------------------------


async def test_a_key_that_does_not_work_is_logged_on_the_routes_and_the_mcp_endpoint(
    served: Served, events: pytest.LogCaptureFixture
) -> None:
    forged = {"Authorization": f"Bearer {PREFIX}" + "0" * 43}

    async with served.http(forged) as http:
        routed = await http.get("/invoices")
    async with served.http(forged | POSTED) as http:
        posted = await http.post("/mcp", json=initialize())

    assert (routed.status_code, posted.status_code) == (401, 401)
    assert named(events, "api-key.refused") == [{"address": "127.0.0.1"}] * 2


# --- the authorization server ---------------------------------------------------------------------


async def test_a_consent_decided_and_a_code_or_refresh_token_reused_are_logged(
    session: AsyncSession, events: pytest.LogCaptureFixture
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        first = (await token(api, exchange(client, code))).json()
        await token(api, exchange(client, code))
        other, again = await consented(api, primer)
        second = (await token(api, exchange(other, again))).json()
        await token(api, renewal(other, second["refresh_token"]))
        await token(api, renewal(other, second["refresh_token"]))
        stranger = await registered(api)
        _, query = sent_to(await authorize(api, stranger))
        refused = await api.post(
            f"/oauth/requests/{query['request']}/refusal", headers=primer.as_client()
        )

    approved = named(events, "oauth.consent-approved")
    assert [fields["client"] for fields in approved] == [client, other]
    assert approved[0]["user"] == str(primer.client.id)
    assert [fields["client"] for fields in named(events, "oauth.code-reused")] == [client]
    assert [fields["client"] for fields in named(events, "oauth.refresh-reused")] == [other]
    assert refused.status_code == 200
    assert named(events, "oauth.consent-refused") == [
        {"user": str(primer.client.id), "client": stranger, "consent": query["request"]}
    ]
    assert first["access_token"] not in logged(events)


# --- the lines ------------------------------------------------------------------------------------


def test_an_event_is_one_json_object_with_its_fields() -> None:
    record = logging.LogRecord(SECURITY.name, logging.INFO, __file__, 1, "%s %s", ("e", "f"), None)
    record.event = "sign-in.refused"
    record.fields = {"reason": "credentials", "address": "127.0.0.1"}

    line = json.loads(JsonFormatter().format(record))

    assert line["level"] == "info"
    assert line["logger"] == "sef_api.security"
    assert (line["event"], line["reason"], line["address"]) == (
        "sign-in.refused",
        "credentials",
        "127.0.0.1",
    )
    assert line["time"].endswith("+00:00")


def test_any_other_line_is_json_too_its_error_included() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed: č", (), sys.exc_info())

    line = json.loads(JsonFormatter().format(record))

    assert (line["message"], "event" in line) == ("failed: č", False)
    assert "RuntimeError: boom" in line["error"]


def test_the_text_of_an_event_names_its_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=SECURITY.name)

    security_event("api-key.refused", address="10.0.0.7")

    assert caplog.records[-1].getMessage() == "api-key.refused address=10.0.0.7"


@pytest.fixture
def restored() -> Iterator[None]:
    """The logging the suite had, again after a test that configures it."""
    names = ("", "uvicorn", "uvicorn.error", "uvicorn.access")
    kept = {
        name: (
            logging.getLogger(name).handlers[:],
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in names
    }
    yield
    for name, (handlers, level, propagate) in kept.items():
        logger = logging.getLogger(name)
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


def test_a_deployment_writes_every_line_as_json(restored: None) -> None:
    logging.config.dictConfig(json.loads((DOCKER / "logging.json").read_text()))

    for name in ("", "uvicorn", "uvicorn.access"):
        (handler,) = logging.getLogger(name).handlers
        assert isinstance(handler.formatter, JsonFormatter)
    start = (DOCKER / "start.sh").read_text()
    assert "--log-config /app/apps/api/docker/logging.json" in start


# --- repairs --------------------------------------------------------------------------------------


async def test_a_repair_decided_is_logged_with_who_decided_it(
    api: AsyncClient, session: AsyncSession, events: pytest.LogCaptureFixture
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    invoice = await kept(session, primer)
    approving = await proposed(api, invoice, primer.as_client(), TYPE_CODE)
    rejecting = await proposed(api, invoice, primer.as_client(), TYPE_CODE)

    rejected = await api.post(path(invoice, rejecting, "rejection"), headers=primer.as_owner())
    approved = await api.post(path(invoice, approving, "approval"), headers=primer.as_client())

    assert (rejected.status_code, approved.status_code) == (200, 200)
    assert named(events, "repair.rejected") == [
        {
            "user": str(primer.owner.id),
            "organization": str(primer.organization.id),
            "invoice": str(invoice.id),
            "repair": rejecting,
        }
    ]
    assert [fields["repair"] for fields in named(events, "repair.approved")] == [approving]


# --- request ids ----------------------------------------------------------------------------------


async def test_every_answer_names_its_request(api: AsyncClient) -> None:
    made = await api.get("/health")
    kept_id = await api.get("/health", headers={"X-Request-ID": "support-ticket.42"})
    replaced = await api.get("/health", headers={"X-Request-ID": "not a token\\n"})

    assert re.fullmatch(r"[0-9a-f]{32}", made.headers["X-Request-ID"])
    assert kept_id.headers["X-Request-ID"] == "support-ticket.42"
    assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["X-Request-ID"])


async def test_the_lines_of_a_request_carry_its_id() -> None:
    written: list[dict[str, Any]] = []

    async def answer(scope: Any, receive: Any, send: Any) -> None:
        record = logging.LogRecord("sef_api.x", logging.INFO, __file__, 1, "inside", (), None)
        written.append(json.loads(JsonFormatter().format(record)))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent: list[Any] = []

    async def send(message: Any) -> None:
        sent.append(message)

    async def receive() -> Any:
        return {"type": "http.request", "body": b""}

    scope = {"type": "http", "headers": [(b"x-request-id", b"abc-1")]}
    await RequestIds(answer)(scope, receive, send)
    outside = json.loads(
        JsonFormatter().format(
            logging.LogRecord("sef_api.x", logging.INFO, __file__, 1, "after", (), None)
        )
    )

    assert written[0]["request_id"] == "abc-1"
    assert (b"x-request-id", b"abc-1") in sent[0]["headers"]
    assert "request_id" not in outside
