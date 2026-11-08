"""The MCP server's tools on stored invoices: storing one, listing them and reading one, as the
routes do, for the invoices the caller may see, with an API key or an assistant's token."""

from __future__ import annotations

import uuid
from typing import Any

from sef_api.db import Database

from .test_mcp import VALID, WRONG_PIB, Served, connected, served, serving, text_of
from .test_mcp_oauth import bearer, signed_in
from .test_mcp_oauth import connected as connected_with
from .test_oauth_authorization import SERVER

__all__ = ["served"]  # the fixture, shared with test_mcp


async def stored(served: Served, xml: str = VALID) -> dict[str, Any]:
    """An invoice stored through the MCP server with Primer's client's key."""
    async with connected(served.app, served.key) as client:
        answered = await client.call_tool("store_invoice", {"xml": xml})
    assert not answered.is_error, text_of(answered)
    assert answered.structured_content is not None
    return dict(answered.structured_content)


async def test_an_invoice_is_stored_as_the_route_stores_it(served: Served) -> None:
    invoice = await stored(served, WRONG_PIB)

    async with served.http(served.key.header()) as http:
        routed = await http.get(f"/invoices/{invoice['id']}")
    async with connected(served.app, served.key) as client:
        read = await client.call_tool("get_invoice", {"invoice_id": invoice["id"]})

    assert routed.status_code == 200
    # The same invoice, the same report, whichever way it is read.
    assert invoice == routed.json() == read.structured_content
    assert (invoice["valid"], invoice["submitted_by"]) == (False, str(served.primer.client.id))
    assert any(v["rule_id"] == "SRB-009" for v in invoice["report"]["violations"])


async def test_stored_invoices_are_listed_newest_first_a_page_at_a_time(served: Served) -> None:
    older = await stored(served, VALID)
    newer = await stored(served, WRONG_PIB)

    async with connected(served.app, served.key) as client:
        first = (await client.call_tool("list_invoices", {"limit": 1})).structured_content
        assert first is not None
        second = (
            await client.call_tool("list_invoices", {"limit": 1, "after": first["next"]})
        ).structured_content
        valid = (await client.call_tool("list_invoices", {"valid": True})).structured_content
        lost = await client.call_tool("list_invoices", {"after": "not-a-cursor"})

    assert second is not None
    assert valid is not None
    assert [page["invoices"][0]["id"] for page in (first, second)] == [newer["id"], older["id"]]
    assert second["next"] is None
    assert [invoice["id"] for invoice in valid["invoices"]] == [older["id"]]
    assert text_of(lost) == (
        "Error executing tool list_invoices: after is not a cursor this server gave"
    )


async def test_a_member_sees_only_the_invoices_they_submitted(served: Served) -> None:
    """An assistant or a machine client acting for Primer's client sees what they submitted,
    not what the owner did, as the routes answer them."""
    async with served.http({**served.primer.as_owner(), "Content-Type": "application/xml"}) as http:
        owners = (await http.post("/invoices", content=VALID.encode())).json()
    own = await stored(served)

    async with connected(served.app, served.key) as client:
        listed = (await client.call_tool("list_invoices", {})).structured_content
        other = await client.call_tool("get_invoice", {"invoice_id": owners["id"]})
        nowhere = await client.call_tool("get_invoice", {"invoice_id": str(uuid.uuid4())})

    assert listed is not None
    assert [invoice["id"] for invoice in listed["invoices"]] == [own["id"]]
    for refused in (other, nowhere):
        assert text_of(refused) == "Error executing tool get_invoice: no such invoice"


async def test_an_organization_that_stores_as_much_as_it_may_stores_no_more(
    committed_database: Database, database_url: str
) -> None:
    async with serving(
        committed_database, database_url, SEF_MAX_STORED_BYTES=str(1024 * 1024)
    ) as served:
        padded = VALID.replace("</Invoice>", "<!--" + "x" * (700 * 1024) + "--></Invoice>")
        async with connected(served.app, served.key) as client:
            first = await client.call_tool("store_invoice", {"xml": padded})
            second = await client.call_tool("store_invoice", {"xml": padded})

    assert not first.is_error
    assert text_of(second) == (
        "Error executing tool store_invoice: the organization stores as much as it may"
    )


async def test_an_assistant_stores_only_with_the_scope_for_it(
    committed_database: Database, database_url: str
) -> None:
    """The person decides: an assistant let only check invoices may not keep them."""
    async with serving(
        committed_database,
        database_url,
        SEF_PUBLIC_URL=SERVER["SEF_PUBLIC_URL"],
        SEF_WEB_ORIGINS=SERVER["SEF_WEB_ORIGINS"],
        SEF_WEB_URL=SERVER["SEF_WEB_URL"],
    ) as served:
        checking = await signed_in(served, scope="invoices:validate")
        keeping = await signed_in(served)
        async with connected_with(served, bearer(checking["access_token"])) as client:
            refused = await client.call_tool("store_invoice", {"xml": VALID})
        async with connected_with(served, bearer(keeping["access_token"])) as client:
            kept = await client.call_tool("store_invoice", {"xml": VALID})

    assert text_of(refused) == (
        "Error executing tool store_invoice: requires the permission invoices:submit"
    )
    assert not kept.is_error
    assert kept.structured_content is not None
    assert kept.structured_content["submitted_by"] == str(served.primer.client.id)
