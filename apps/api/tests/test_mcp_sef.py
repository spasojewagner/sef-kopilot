"""The MCP tools that send a stored invoice to SEF's demo environment and read where it stands
(ADR-0051, ADR-0052): what the routes do, through an assistant its person allowed to send; the
step-up for a client not yet allowed; and the refusals that asking the person again could not
help. SEF answers through a mock transport, from before the application starts."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, select

from sef_api.db import Database
from sef_api.models import AuditAction, AuditEvent, SefKey, User

from .factories import sef_key, stored_invoice
from .test_mcp import POSTED, Served, asking, initialize, serving, text_of
from .test_mcp import connected as connected_by_key
from .test_mcp_oauth import METADATA, bearer, connected, signed_in
from .test_oauth_authorization import SERVER
from .test_sef_submissions import IMPORTED, INVALID, KEY, VALID, FakeSef

#: The scopes of an assistant its person let keep invoices and send them.
SENDING = "invoices:submit invoices:send"


@pytest.fixture
def sef() -> FakeSef:
    return FakeSef()


@pytest.fixture
async def served(
    committed_database: Database, database_url: str, sef: FakeSef
) -> AsyncIterator[Served]:
    """The application with an authorization server, whose SEF is ``sef``, and Primer's key to
    SEF set."""
    async with serving(
        committed_database,
        database_url,
        sef=httpx.MockTransport(sef),
        SEF_PUBLIC_URL=SERVER["SEF_PUBLIC_URL"],
        SEF_WEB_ORIGINS=SERVER["SEF_WEB_ORIGINS"],
        SEF_WEB_URL=SERVER["SEF_WEB_URL"],
    ) as running_app:
        async with committed_database.sessions() as setup:
            await sef_key(setup, running_app.primer.organization, KEY)
            await setup.commit()
        yield running_app


async def kept(database: Database, served: Served, by: User, content: bytes = VALID) -> str:
    """The id of an invoice ``by`` stored in Primer."""
    async with database.sessions() as session:
        invoice = await stored_invoice(session, served.primer.organization, by, content)
        await session.commit()
        return str(invoice.id)


async def owners_assistant(served: Served, scope: str | None = SENDING) -> dict[str, Any]:
    """The tokens of an assistant Primer's owner allowed ``scope``."""
    return await signed_in(served, scope=scope, as_owner=True)


# --- sent, and where it stands -----------------------------------------------------------------


async def test_an_assistant_its_person_allowed_sends_and_reads_where_the_invoice_stands(
    served: Served, committed_database: Database, sef: FakeSef
) -> None:
    invoice_id = await kept(committed_database, served, served.primer.owner)
    tokens = await owners_assistant(served)

    async with connected(served, bearer(tokens["access_token"])) as client:
        sent = await client.call_tool("send_to_sef_demo", {"invoice_id": invoice_id})
        status = await client.call_tool("get_sef_status", {"invoice_id": invoice_id})

    assert not sent.is_error, text_of(sent)
    submission = sent.structured_content
    assert submission is not None
    assert (
        submission["invoice_id"],
        submission["state"],
        submission["sales_invoice_id"],
        submission["sef_invoice_id"],
    ) == (invoice_id, "imported", IMPORTED["salesInvoiceId"], IMPORTED["invoiceId"])
    # SEF was asked once, with the organization's key and the submission as the request id.
    (asked,) = sef.asked
    assert asked.headers["ApiKey"] == KEY
    assert asked.url.params["requestId"] == submission["id"]
    assert status.structured_content == {"submissions": [submission]}
    # The audit log says which client the person's sending came through.
    async with committed_database.sessions() as session:
        event = await session.scalar(
            select(AuditEvent).where(AuditEvent.action == AuditAction.SEF_INVOICE_SENT)
        )
    assert event is not None
    assert (event.actor, event.oauth_client_id) == (served.primer.owner.id, tokens["client"])


async def test_sending_again_never_imports_an_invoice_twice(
    served: Served, committed_database: Database, sef: FakeSef
) -> None:
    invoice_id = await kept(committed_database, served, served.primer.owner)
    tokens = await owners_assistant(served)

    async with connected(served, bearer(tokens["access_token"])) as client:
        first = await client.call_tool("send_to_sef_demo", {"invoice_id": invoice_id})
        again = await client.call_tool("send_to_sef_demo", {"invoice_id": invoice_id})
        status = await client.call_tool("get_sef_status", {"invoice_id": invoice_id})

    assert not first.is_error
    assert again.is_error
    assert text_of(again).startswith("Error executing tool send_to_sef_demo: not sent (sent): ")
    assert len(sef.asked) == 1
    assert status.structured_content is not None
    assert len(status.structured_content["submissions"]) == 1


async def test_an_invoice_the_validator_does_not_pass_or_without_a_key_is_not_sent(
    served: Served, committed_database: Database, sef: FakeSef
) -> None:
    invalid = await kept(committed_database, served, served.primer.owner, INVALID)
    valid = await kept(committed_database, served, served.primer.owner)
    tokens = await owners_assistant(served)

    async with connected(served, bearer(tokens["access_token"])) as client:
        refused = await client.call_tool("send_to_sef_demo", {"invoice_id": invalid})
        async with committed_database.sessions() as session:
            await session.execute(delete(SefKey))
            await session.commit()
        keyless = await client.call_tool("send_to_sef_demo", {"invoice_id": valid})
        status = await client.call_tool("get_sef_status", {"invoice_id": valid})

    assert text_of(refused).startswith(
        "Error executing tool send_to_sef_demo: not sent (invalid): "
    )
    assert text_of(keyless).startswith("Error executing tool send_to_sef_demo: not sent (no-key): ")
    assert sef.asked == []
    assert status.structured_content == {"submissions": []}


async def test_an_assistant_sends_only_its_persons_own_invoices(
    served: Served, committed_database: Database, sef: FakeSef
) -> None:
    """No scope reaches every invoice of the organization: the client's invoice is not the
    owner's assistant's to send, nor to read about."""
    clients = await kept(committed_database, served, served.primer.client)
    tokens = await owners_assistant(served)

    async with connected(served, bearer(tokens["access_token"])) as client:
        sent = await client.call_tool("send_to_sef_demo", {"invoice_id": clients})
        status = await client.call_tool("get_sef_status", {"invoice_id": clients})
        unknown = await client.call_tool("get_sef_status", {"invoice_id": str(uuid.uuid4())})

    for answer, tool in ((sent, "send_to_sef_demo"), (status, "get_sef_status")):
        assert (
            text_of(answer) == f"Error executing tool {tool}: no such invoice in this organization"
        )
    assert unknown.is_error
    assert sef.asked == []


# --- who may send ------------------------------------------------------------------------------


async def test_a_client_not_yet_allowed_to_send_is_asked_to_step_up(
    served: Served, committed_database: Database, sef: FakeSef
) -> None:
    """The owner allowed the scopes a client asks for first: sending is asked for when the
    assistant first sends, for what it holds and sending."""
    invoice_id = await kept(committed_database, served, served.primer.owner)
    tokens = await owners_assistant(served, scope=None)

    async with served.http(bearer(tokens["access_token"]) | POSTED) as http:
        stepped = await http.post(
            "/mcp",
            json=asking(
                "tools/call", name="send_to_sef_demo", arguments={"invoice_id": invoice_id}
            ),
        )

    assert (stepped.status_code, stepped.json()) == (
        403,
        {"detail": "a call needs invoices:send, which the person has not allowed this client"},
    )
    assert stepped.headers["WWW-Authenticate"] == (
        f'Bearer error="insufficient_scope", {METADATA}, '
        'scope="invoices:validate invoices:submit invoices:send"'
    )
    assert sef.asked == []


async def test_whom_asking_again_could_not_help_gets_the_tools_error(
    served: Served, committed_database: Database, sef: FakeSef
) -> None:
    """A client of the office may not send, whatever its assistant asks; nor may an API key,
    which cannot hold the permission. The permission is checked first: the invoice, which the
    validator would not pass, is not validated for a caller who may not send it."""
    invoice_id = await kept(committed_database, served, served.primer.client, INVALID)
    tokens = await signed_in(served, scope="invoices:submit invoices:send")

    async with connected(served, bearer(tokens["access_token"])) as client:
        by_assistant = await client.call_tool("send_to_sef_demo", {"invoice_id": invoice_id})
    async with connected_by_key(served.app, served.key) as client:
        by_key = await client.call_tool("send_to_sef_demo", {"invoice_id": invoice_id})

    assert tokens["scope"] == "invoices:submit"
    for answer in (by_assistant, by_key):
        assert text_of(answer) == (
            "Error executing tool send_to_sef_demo: requires the permission invoices:send"
        )
    assert sef.asked == []


async def test_a_client_is_told_that_sending_reaches_outside_and_may_be_repeated(
    served: Served,
) -> None:
    """What a client reads before it calls a tool, or asks its person first."""
    async with connected_by_key(served.app, served.key) as client:
        offered = {tool.name: tool.annotations for tool in (await client.list_tools()).tools}

    sending, reading = offered["send_to_sef_demo"], offered["get_sef_status"]
    assert sending is not None
    assert reading is not None
    assert (
        sending.read_only_hint,
        sending.destructive_hint,
        sending.idempotent_hint,
        sending.open_world_hint,
    ) == (False, False, True, True)
    assert (reading.read_only_hint, reading.open_world_hint) == (True, False)


async def test_the_server_tells_an_assistant_to_send_only_when_asked(served: Served) -> None:
    """What every assistant reads as it connects, before any tool."""
    async with served.http(served.key.header() | POSTED) as http:
        answered = await http.post("/mcp", json=initialize())

    instructions = answered.json()["result"]["instructions"]
    assert "SEF's demo environment only" in instructions
    assert "send one only when the person asks" in instructions
