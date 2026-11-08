"""The MCP server at ``/mcp`` (ADR-0042): whom it admits, which tools it offers and what each
requires, and what they answer, compared with the routes they stand for.

The endpoint opens database sessions of its own, as in production, so these tests run on the
suite's database with real commits (``committed_database``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx2
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, TextContent
from sqlalchemy import update

from sef_api.auth.permissions import KEY_PERMISSIONS, Permission
from sef_api.db import Database
from sef_api.main import create_app
from sef_api.mcp import tools
from sef_api.models import ApiKey, User
from sef_api.rag.explainer import Explainer

from .conftest import REPOSITORY_ROOT, settings_for
from .corpora import QuotingModel, repository_corpus, store_corpus
from .factories import Key, Office, api_key, office
from .test_explainer import FakeEmbedder

FIXTURES = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
VALID = (FIXTURES / "srb-final-invoice.xml").read_text()
#: The seller's PIB has a wrong check digit, 100000025, which the violations quote.
WRONG_PIB = (FIXTURES / "mutations" / "srb-009-pib-check-digit.xml").read_text()
#: The total with VAT is wrong, and so the amount due: two rules, BR-CO-15 and BR-CO-16.
WRONG_TOTALS = (FIXTURES / "mutations" / "br-co-15-total-with-vat.xml").read_text()

#: The tools the server offers, what each requires, and arguments it accepts: the audit that a
#: tool cannot join the server without a permission of its own.
TOOLS: dict[str, tuple[Permission, dict[str, Any]]] = {
    "validate_invoice": (Permission.INVOICES_VALIDATE, {"xml": VALID}),
    "explain_errors": (Permission.INVOICES_VALIDATE, {"xml": WRONG_PIB}),
    "store_invoice": (Permission.INVOICES_SUBMIT, {"xml": VALID}),
    "list_invoices": (Permission.INVOICES_SUBMIT, {}),
    "get_invoice": (Permission.INVOICES_SUBMIT, {"invoice_id": str(uuid.uuid4())}),
    "explain_invoice": (Permission.INVOICES_SUBMIT, {"invoice_id": str(uuid.uuid4())}),
    "revalidate_invoices": (Permission.INVOICES_SUBMIT, {}),
    "get_job": (Permission.INVOICES_SUBMIT, {"job_id": str(uuid.uuid4())}),
    "propose_fix": (
        Permission.INVOICES_SUBMIT,
        {
            "invoice_id": str(uuid.uuid4()),
            "patches": [{"xpath": "/a", "op": "remove", "reason": "x"}],
        },
    ),
    "get_repair": (
        Permission.INVOICES_SUBMIT,
        {"invoice_id": str(uuid.uuid4()), "repair_id": str(uuid.uuid4())},
    ),
    "search_rules": (Permission.INVOICES_VALIDATE, {"query": "BR-01"}),
    "get_rule": (Permission.INVOICES_VALIDATE, {"rule_id": "BR-01"}),
}

#: What ``serving`` is given for a server without a language model.
NO_MODEL: Final = object()

#: The headers a client sends with every message it posts.
POSTED = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


@dataclass(frozen=True)
class Served:
    """The application, running, and Primer's office with its client's key, which holds every
    permission a key may hold."""

    app: FastAPI
    primer: Office
    key: Key

    def http(self, headers: Mapping[str, str] | None = None) -> AsyncClient:
        """A plain HTTP client of the application, for what the transport answers."""
        return AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://test", headers=headers
        )


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[None]:
    """The application's lifespan, in a task of its own: the MCP endpoint's task group must be
    entered and left in one task, and a fixture's setup and teardown may run in two."""
    started, stopping = asyncio.Event(), asyncio.Event()

    async def lifespan() -> None:
        async with app.router.lifespan_context(app):
            started.set()
            await stopping.wait()

    task = asyncio.create_task(lifespan())
    waiting = asyncio.create_task(started.wait())
    await asyncio.wait({task, waiting}, return_when=asyncio.FIRST_COMPLETED)
    if task.done():
        waiting.cancel()
        task.result()  # the lifespan's failure
    try:
        yield
    finally:
        stopping.set()
        await task


@asynccontextmanager
async def serving(
    database: Database,
    database_url: str,
    *,
    model: Any = None,
    embedder: Any = None,
    corpus: bool = False,
    **variables: str,
) -> AsyncIterator[Served]:
    """The application with ``variables`` set, running, on a database with Primer's office and,
    if asked, the repository's corpus; explaining with ``model``, a stand-in that quotes the
    passages unless another is given, and with ``embedder`` if one is."""
    async with database.sessions() as setup:
        if corpus:
            await store_corpus(setup, repository_corpus())
        primer = await office(setup, "Primer Računovodstvo", "primer.example")
        key = await api_key(setup, primer.organization, primer.client)
        await setup.commit()
    app = create_app(settings_for(database_url, **variables))
    app.state.explainer = None if model is NO_MODEL else Explainer(model or QuotingModel())
    app.state.embedder = embedder
    async with running(app):
        yield Served(app, primer, key)


@pytest.fixture
async def served(committed_database: Database, database_url: str) -> AsyncIterator[Served]:
    async with serving(committed_database, database_url) as running_app:
        yield running_app


@asynccontextmanager
async def connected(app: FastAPI, key: Key) -> AsyncIterator[Client]:
    """A client of the SDK, connected to the application with ``key``."""
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app), base_url="http://test", headers=key.header()
    )
    async with http, Client(streamable_http_client("http://test/mcp", http_client=http)) as client:
        yield client


async def key_with(database: Database, served: Served, *permissions: Permission) -> Key:
    """Another key of Primer's client, holding ``permissions``."""
    async with database.sessions() as setup:
        key = await api_key(setup, served.primer.organization, served.primer.client, *permissions)
        await setup.commit()
    return key


def initialize(version: str = "2025-06-18") -> dict[str, Any]:
    """The message with which a client of the protocol's revision ``version`` begins."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }


def asking(method: str, **params: Any) -> dict[str, Any]:
    """A message that asks the server for ``method`` with ``params``."""
    return {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}


def text_of(result: CallToolResult) -> str:
    """The text of a tool's answer, whose one content is text."""
    (content,) = result.content
    assert isinstance(content, TextContent)
    return content.text


# --- whom the endpoint admits ------------------------------------------------------------------


async def test_a_client_of_an_earlier_revision_is_answered_without_a_session(
    served: Served,
) -> None:
    async with served.http(served.key.header() | POSTED) as http:
        started = await http.post("/mcp", json=initialize("2025-06-18"))
        listed = await http.post(
            "/mcp", headers={"MCP-Protocol-Version": "2025-06-18"}, json=asking("tools/list")
        )

    assert started.status_code == listed.status_code == 200
    assert started.json()["result"]["protocolVersion"] == "2025-06-18"
    assert started.json()["result"]["serverInfo"]["name"] == "SEF Kopilot"
    assert "mcp-session-id" not in started.headers
    assert sorted(tool["name"] for tool in listed.json()["result"]["tools"]) == sorted(TOOLS)


async def test_a_client_of_the_current_revision_is_answered(served: Served) -> None:
    async with connected(served.app, served.key) as client:
        offered = (await client.list_tools()).tools

    assert sorted(tool.name for tool in offered) == sorted(TOOLS)


async def test_a_request_without_an_api_key_is_refused(served: Served) -> None:
    async with served.http(POSTED) as http:
        anonymous = await http.post("/mcp", json=initialize())
        signed_in = await http.post("/mcp", json=initialize(), headers=served.primer.as_client())
        unknown = await http.post(
            "/mcp", json=initialize(), headers={"Authorization": "Bearer sefk_unknown"}
        )

    assert (anonymous.status_code, anonymous.json()) == (401, {"detail": "not signed in"})
    assert anonymous.headers["WWW-Authenticate"] == "Bearer"
    # An access token is the web application's, issued for the API's routes.
    assert (signed_in.status_code, signed_in.json()) == (
        401,
        {"detail": "the MCP endpoint takes an API key"},
    )
    assert (unknown.status_code, unknown.json()) == (
        401,
        {"detail": "invalid, expired or revoked API key"},
    )
    assert signed_in.headers["WWW-Authenticate"] == unknown.headers["WWW-Authenticate"]
    assert unknown.headers["WWW-Authenticate"] == 'Bearer error="invalid_token"'


async def test_a_revoked_key_or_a_member_who_left_is_refused(
    served: Served, committed_database: Database
) -> None:
    revoked = await key_with(committed_database, served, Permission.INVOICES_VALIDATE)
    async with committed_database.sessions() as session:
        await session.execute(
            update(ApiKey).where(ApiKey.id == revoked.row.id).values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    async with served.http(POSTED) as http:
        with_revoked = await http.post("/mcp", json=initialize(), headers=revoked.header())
    async with committed_database.sessions() as session:
        await session.execute(
            update(User).where(User.id == served.primer.client.id).values(is_active=False)
        )
        await session.commit()
    async with served.http(POSTED) as http:
        after_leaving = await http.post("/mcp", json=initialize(), headers=served.key.header())

    assert (with_revoked.status_code, with_revoked.json()) == (
        401,
        {"detail": "invalid, expired or revoked API key"},
    )
    assert (after_leaving.status_code, after_leaving.json()) == (
        401,
        {"detail": "the account or its membership is no longer active"},
    )


@pytest.mark.parametrize("method", ["GET", "DELETE", "PUT"])
async def test_only_posts_are_answered(method: str, served: Served) -> None:
    # A GET would open a stream of the server's own messages, of which it has none.
    async with served.http(served.key.header()) as http:
        answered = await http.request(method, "/mcp", headers={"Accept": "text/event-stream"})

    assert (answered.status_code, answered.json()) == (405, {"detail": "Method Not Allowed"})
    assert answered.headers["Allow"] == "POST"


async def test_a_page_of_another_origin_is_refused(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_WEB_ORIGINS="https://app.example") as served,
        served.http(served.key.header() | POSTED) as http,
    ):
        foreign = await http.post(
            "/mcp", json=initialize(), headers={"Origin": "https://elsewhere.example"}
        )
        own = await http.post("/mcp", json=initialize(), headers={"Origin": "https://app.example"})
        without = await http.post("/mcp", json=initialize())

    assert (foreign.status_code, foreign.json()) == (
        403,
        {"detail": "requests from this origin are not accepted"},
    )
    assert own.status_code == without.status_code == 200


async def test_a_message_over_the_limit_on_bodies_is_refused(
    committed_database: Database, database_url: str
) -> None:
    padded = initialize() | {"padding": "x" * 70_000}
    async with (
        serving(committed_database, database_url, SEF_MAX_BODY_BYTES="65536") as served,
        served.http(served.key.header() | POSTED) as http,
    ):
        answered = await http.post("/mcp", json=padded)

    assert answered.status_code == 413


# --- the tools and what they require --------------------------------------------------------


async def test_the_server_offers_its_tools_with_what_each_does(served: Served) -> None:
    async with connected(served.app, served.key) as client:
        offered = {tool.name: tool for tool in (await client.list_tools()).tools}

    assert set(offered) == set(TOOLS)
    validating = offered["validate_invoice"]
    assert validating.annotations is not None
    assert (
        validating.annotations.read_only_hint,
        validating.annotations.destructive_hint,
        validating.annotations.idempotent_hint,
        validating.annotations.open_world_hint,
    ) == (True, False, True, False)
    assert validating.input_schema["required"] == ["xml"]
    assert validating.output_schema is not None
    assert validating.output_schema["title"] == "ValidationReport"
    explaining = offered["explain_errors"]
    assert explaining.annotations is not None
    # Each call asks the model, whose answers may differ.
    assert (explaining.annotations.read_only_hint, explaining.annotations.idempotent_hint) == (
        True,
        False,
    )
    assert explaining.input_schema["required"] == ["xml"]
    assert explaining.output_schema is not None
    assert explaining.output_schema["title"] == "Explained"


def test_the_endpoint_knows_what_each_tool_requires() -> None:
    """What the endpoint reads to ask a client to step up is what each tool checks."""
    assert dict(tools.PERMISSIONS) == {name: needed for name, (needed, _) in TOOLS.items()}


@pytest.mark.parametrize("name", sorted(TOOLS))
async def test_each_tool_requires_its_permission(
    name: str, served: Served, committed_database: Database
) -> None:
    permission, arguments = TOOLS[name]
    lacking = await key_with(committed_database, served, *sorted(KEY_PERMISSIONS - {permission}))
    holding = await key_with(committed_database, served, permission)

    async with connected(served.app, lacking) as client:
        refused = await client.call_tool(name, arguments)
    async with connected(served.app, holding) as client:
        admitted = await client.call_tool(name, arguments)

    assert refused.is_error
    assert text_of(refused) == f"Error executing tool {name}: requires the permission {permission}"
    # Admitted, the tool does its work: an invoice or a job it cannot find is another matter.
    assert not admitted.is_error or any(
        missing in text_of(admitted) for missing in ("no such invoice", "no such job")
    )


# --- validate_invoice --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("document", "profile"),
    [(VALID, "srb"), (WRONG_PIB, "srb"), (WRONG_PIB, "en16931")],
    ids=["valid", "wrong PIB", "wrong PIB under EN 16931"],
)
async def test_an_invoice_is_validated_as_the_route_validates_it(
    document: str, profile: str, served: Served
) -> None:
    async with connected(served.app, served.key) as client:
        answered = await client.call_tool("validate_invoice", {"xml": document, "profile": profile})
    async with served.http(served.key.header()) as http:
        routed = await http.post(
            "/invoices/validate",
            params={"profile": profile},
            content=document.encode(),
            headers={"Content-Type": "application/xml"},
        )

    assert not answered.is_error
    assert answered.structured_content == routed.json()


async def test_a_wrong_pib_is_reported_by_its_rule(served: Served) -> None:
    async with connected(served.app, served.key) as client:
        answered = await client.call_tool("validate_invoice", {"xml": WRONG_PIB})

    report = answered.structured_content
    assert report is not None
    assert report["valid"] is False
    assert {violation["rule_id"] for violation in report["violations"]} == {"SRB-009"}


async def test_validations_are_counted_with_the_routes(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_VALIDATIONS_PER_MINUTE="2") as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        first = await client.call_tool("validate_invoice", {"xml": VALID})
        routed = await http.post(
            "/invoices/validate",
            content=VALID.encode(),
            headers={"Content-Type": "application/xml"},
        )
        third = await client.call_tool("validate_invoice", {"xml": VALID})

    # The key's two validations a minute are spent by the tool and the route together.
    assert not first.is_error
    assert routed.status_code == 200
    assert third.is_error
    assert text_of(third).startswith(
        "Error executing tool validate_invoice: too many validations; try again in "
    )


async def test_an_invoice_over_the_limit_on_invoices_is_refused(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_MAX_INVOICE_BYTES="1024") as served,
        connected(served.app, served.key) as client,
    ):
        answered = await client.call_tool("validate_invoice", {"xml": VALID})

    assert answered.is_error
    assert text_of(answered) == (
        "Error executing tool validate_invoice: the invoice is larger than 1024 bytes"
    )


async def test_a_document_the_validator_refuses_is_refused_in_the_routes_words(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, SEF_MAX_INVOICE_ELEMENTS="100") as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        answered = await client.call_tool("validate_invoice", {"xml": VALID})
        routed = await http.post(
            "/invoices/validate",
            content=VALID.encode(),
            headers={"Content-Type": "application/xml"},
        )

    assert routed.status_code == 413
    assert answered.is_error
    assert text_of(answered) == f"Error executing tool validate_invoice: {routed.json()['detail']}"


# --- explain_errors ----------------------------------------------------------------------------


@pytest.mark.parametrize("language", ["sr", "en"])
async def test_errors_are_explained_as_the_route_explains_them(
    language: str, committed_database: Database, database_url: str
) -> None:
    model = QuotingModel()
    async with (
        serving(committed_database, database_url, model=model, corpus=True) as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        answered = await client.call_tool(
            "explain_errors", {"xml": WRONG_PIB, "language": language}
        )
        routed = await http.post(
            "/invoices/explain",
            params={"language": language},
            content=WRONG_PIB.encode(),
            headers={"Content-Type": "application/xml"},
        )

    assert not answered.is_error
    explained, expected = answered.structured_content, routed.json()
    assert explained is not None
    # Written a moment apart; nothing else differs.
    del explained["written_at"], expected["written_at"]
    assert explained == expected
    (explanation,) = explained["explanations"]
    assert explanation["rule_id"] == "SRB-009"
    assert explanation["citations"]
    assert explained["language"] == language
    # The model was asked the same by the tool and by the route.
    by_tool, by_route = model.asked
    assert by_tool == by_route


async def test_the_rules_beyond_a_calls_share_are_left_as_the_route_leaves_them(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, corpus=True, SEF_MAX_EXPLANATIONS="1") as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        answered = await client.call_tool("explain_errors", {"xml": WRONG_TOTALS})
        routed = await http.post(
            "/invoices/explain",
            content=WRONG_TOTALS.encode(),
            headers={"Content-Type": "application/xml"},
        )

    explained = answered.structured_content
    assert explained is not None
    assert [explanation["rule_id"] for explanation in explained["explanations"]] == ["BR-CO-15"]
    assert explained["unexplained"] == routed.json()["unexplained"] == ["BR-CO-16"]


async def test_the_servers_embedder_finds_passages_by_their_meaning(
    committed_database: Database, database_url: str
) -> None:
    embedder = FakeEmbedder()
    async with (
        serving(committed_database, database_url, corpus=True, embedder=embedder) as served,
        connected(served.app, served.key) as client,
    ):
        answered = await client.call_tool("explain_errors", {"xml": WRONG_PIB})

    assert not answered.is_error
    # What SRB-009 says, never what the violation found.
    assert embedder.queries
    assert not [query for query in embedder.queries if "100000025" in query]


async def test_a_server_without_a_model_says_so_and_counts_nothing(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(
            committed_database, database_url, model=NO_MODEL, SEF_VALIDATIONS_PER_MINUTE="1"
        ) as served,
        connected(served.app, served.key) as client,
    ):
        refused = await client.call_tool("explain_errors", {"xml": WRONG_PIB})
        validated = await client.call_tool("validate_invoice", {"xml": WRONG_PIB})

    assert refused.is_error
    assert text_of(refused) == (
        "Error executing tool explain_errors: no language model is configured on this server"
    )
    # The validation a minute was not spent on the refused explanation.
    assert not validated.is_error


async def test_requests_to_the_model_are_counted_with_the_routes(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(
            committed_database, database_url, corpus=True, SEF_EXPLANATIONS_PER_MINUTE="1"
        ) as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        first = await client.call_tool("explain_errors", {"xml": WRONG_PIB})
        routed = await http.post(
            "/invoices/explain",
            content=WRONG_PIB.encode(),
            headers={"Content-Type": "application/xml"},
        )
        again = await client.call_tool("explain_errors", {"xml": WRONG_PIB})

    assert not first.is_error
    assert routed.status_code == 429
    assert again.is_error
    assert text_of(again) == f"Error executing tool explain_errors: {routed.json()['detail']}"


# --- what the server logs ----------------------------------------------------------------------


async def test_nothing_of_the_invoice_reaches_a_log(
    committed_database: Database, database_url: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    async with (
        serving(committed_database, database_url, corpus=True) as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header() | POSTED) as http,
    ):
        validated = await client.call_tool("validate_invoice", {"xml": WRONG_PIB})
        explained = await client.call_tool("explain_errors", {"xml": WRONG_PIB})
        # A client of an earlier revision takes another path through the server, which logs more.
        await http.post("/mcp", json=initialize())
        earlier = await http.post(
            "/mcp", json=asking("tools/call", name="validate_invoice", arguments={"xml": WRONG_PIB})
        )

    # The answers quote the wrong PIB; no line the server logs does, nor the invoice's number.
    # The SDK's client logs what it sends, which is the test's to log, not the server's.
    logged = [
        record.getMessage()
        for record in caplog.records
        if not record.name.startswith(("mcp.client", "httpx"))
    ]
    assert "100000025" in str(validated.structured_content)
    assert "100000025" in str(explained.structured_content)
    assert "100000025" in earlier.text
    assert logged
    assert not [line for line in logged if "100000025" in line or "RF-2026-000123" in line]


# --- the process -------------------------------------------------------------------------------


def test_making_the_application_leaves_the_root_logger_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = logging.getLogger()
    # As in production, where nothing has configured it: pytest's handlers would hide a change.
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(root, "level", logging.WARNING)

    create_app(settings_for())

    assert (root.handlers, root.level) == ([], logging.WARNING)
