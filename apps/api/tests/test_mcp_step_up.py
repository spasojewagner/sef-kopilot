"""A call through an MCP client of a tool its scopes do not reach: answered 403
``insufficient_scope`` before the tool runs, with the scopes to ask the person for, while every
tool stays listed (ADR-0046)."""

from __future__ import annotations

import asyncio
import uuid
from types import MappingProxyType
from typing import Any

import pytest

from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.mcp import access, tools
from sef_api.models import Role

from .test_mcp import POSTED, VALID, Served, asking, text_of
from .test_mcp_oauth import METADATA, bearer, connected, served, signed_in

__all__ = ["served"]  # the fixture, shared with test_mcp_oauth

#: The challenge of a client let only check invoices that calls a tool on stored ones: what it
#: holds and what the tool needs, since a client need not remember what it was allowed before.
STEP_UP = (
    f'Bearer error="insufficient_scope", {METADATA}, scope="invoices:validate invoices:submit"'
)
#: Why it is refused.
NOT_ALLOWED = "a call needs invoices:submit, which the person has not allowed this client"


def calling(name: str, **arguments: Any) -> dict[str, Any]:
    """The message that calls the tool ``name`` with ``arguments``."""
    return asking("tools/call", name=name, arguments=arguments)


async def checking_only(served: Served) -> dict[str, str]:
    """The headers of a client its person let only check invoices."""
    tokens = await signed_in(served, scope="invoices:validate")
    return bearer(tokens["access_token"]) | POSTED


async def test_a_tool_beyond_the_clients_scopes_asks_for_them(served: Served) -> None:
    async with served.http(await checking_only(served)) as http:
        stepped = await http.post("/mcp", json=calling("store_invoice", xml=VALID))
    async with served.http(served.primer.as_client()) as http:
        stored = (await http.get("/invoices")).json()

    assert (stepped.status_code, stepped.json()) == (403, {"detail": NOT_ALLOWED})
    assert stepped.headers["WWW-Authenticate"] == STEP_UP
    # The tool never ran.
    assert stored["invoices"] == []


async def test_a_batch_with_one_such_call_asks_for_them(served: Served) -> None:
    """A client of the protocol's revision 2025-03-26 may post several messages at once."""
    batch = [calling("validate_invoice", xml=VALID), calling("list_invoices")]

    async with served.http(await checking_only(served)) as http:
        stepped = await http.post("/mcp", json=batch)

    assert (stepped.status_code, stepped.json()) == (403, {"detail": NOT_ALLOWED})
    assert stepped.headers["WWW-Authenticate"] == STEP_UP


async def test_every_tool_is_listed_and_those_in_scope_answer(served: Served) -> None:
    tokens = await signed_in(served, scope="invoices:validate")

    # A server that never got the body the endpoint read would wait for it for ever.
    async with asyncio.timeout(30), connected(served, bearer(tokens["access_token"])) as client:
        offered = sorted(tool.name for tool in (await client.list_tools()).tools)
        validated = await client.call_tool("validate_invoice", {"xml": VALID})

    # Listed whatever the scopes: a client hidden a tool would never ask for its scope.
    assert offered == sorted(tools.PERMISSIONS)
    assert not validated.is_error


async def test_once_the_person_allows_it_the_call_goes_through(served: Served) -> None:
    """Asked again, the person allows the client more; the same call then answers."""
    first = await signed_in(served, scope="invoices:validate")
    again = await signed_in(
        served, scope="invoices:validate invoices:submit", client=first["client"]
    )

    async with connected(served, bearer(again["access_token"])) as client:
        stored = await client.call_tool("store_invoice", {"xml": VALID})

    assert not stored.is_error
    assert stored.structured_content is not None
    assert stored.structured_content["submitted_by"] == str(served.primer.client.id)


@pytest.mark.parametrize(
    "posted",
    [
        b"{",
        b'{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": []}',
        b'{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": 7}}',
        b'{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "send_to_sef"}}',
        b"[1, null]",
    ],
)
async def test_what_calls_no_tool_of_the_server_is_the_servers_to_answer(
    posted: bytes, served: Served
) -> None:
    async with served.http(await checking_only(served)) as http:
        answered = await http.post("/mcp", content=posted)

    assert answered.status_code in (200, 400), answered.status_code
    assert "insufficient_scope" not in answered.headers.get("WWW-Authenticate", "")


async def test_a_scope_the_persons_role_would_not_allow_is_not_asked_for(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking the person again could not help: the tool refuses, as it refuses an API key."""
    grants = dict(ROLE_PERMISSIONS) | {Role.CLIENT: frozenset({Permission.INVOICES_VALIDATE})}
    monkeypatch.setattr(access, "ROLE_PERMISSIONS", MappingProxyType(grants))
    tokens = await signed_in(served, scope="invoices:validate")

    async with connected(served, bearer(tokens["access_token"])) as client:
        refused = await client.call_tool("get_invoice", {"invoice_id": str(uuid.uuid4())})

    assert text_of(refused) == (
        "Error executing tool get_invoice: requires the permission invoices:submit"
    )
