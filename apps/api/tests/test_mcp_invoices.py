"""The MCP server's tools on stored invoices: storing one, listing them, reading one, explaining
one and validating them again, as the routes do, for the invoices the caller may see, with an API
key or an assistant's token."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from sef_api.db import Database

from .corpora import QuotingModel
from .test_mcp import (
    NO_MODEL,
    VALID,
    WRONG_PIB,
    WRONG_TOTALS,
    Served,
    connected,
    served,
    serving,
    text_of,
)
from .test_mcp_oauth import bearer, signed_in
from .test_mcp_oauth import connected as connected_with
from .test_oauth_authorization import SERVER
from .test_revalidation import NOTHING, Judging

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
        unexplained = await client.call_tool("explain_invoice", {"invoice_id": owners["id"]})

    assert listed is not None
    assert [invoice["id"] for invoice in listed["invoices"]] == [own["id"]]
    for refused in (other, nowhere):
        assert text_of(refused) == "Error executing tool get_invoice: no such invoice"
    assert text_of(unexplained) == "Error executing tool explain_invoice: no such invoice"


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


async def test_an_assistant_stores_as_its_person(
    committed_database: Database, database_url: str
) -> None:
    """With the scopes a client asks for when it names none; one that may only check invoices
    is asked to step up (``test_mcp_step_up``)."""
    async with serving(
        committed_database,
        database_url,
        SEF_PUBLIC_URL=SERVER["SEF_PUBLIC_URL"],
        SEF_WEB_ORIGINS=SERVER["SEF_WEB_ORIGINS"],
        SEF_WEB_URL=SERVER["SEF_WEB_URL"],
    ) as served:
        keeping = await signed_in(served)
        async with connected_with(served, bearer(keeping["access_token"])) as client:
            kept = await client.call_tool("store_invoice", {"xml": VALID})

    assert not kept.is_error
    assert kept.structured_content is not None
    assert kept.structured_content["submitted_by"] == str(served.primer.client.id)


async def test_a_stored_invoice_is_explained_as_the_route_explains_it_once(
    committed_database: Database, database_url: str
) -> None:
    """The model is asked once and its explanations kept: read again by the tool and the route
    alike, counting nothing, while another invoice waits for the caller's next minute."""
    model = QuotingModel()
    async with serving(
        committed_database, database_url, model=model, corpus=True, SEF_EXPLANATIONS_PER_MINUTE="1"
    ) as served:
        invoice = await stored(served, WRONG_PIB)
        other = await stored(served, WRONG_TOTALS)
        async with connected(served.app, served.key) as client:
            explained = await client.call_tool("explain_invoice", {"invoice_id": invoice["id"]})
            again = await client.call_tool("explain_invoice", {"invoice_id": invoice["id"]})
            waiting = await client.call_tool("explain_invoice", {"invoice_id": other["id"]})
        async with served.http(served.key.header()) as http:
            routed = await http.post(f"/invoices/{invoice['id']}/explanations")
            limited = await http.post(f"/invoices/{other['id']}/explanations")

    assert not explained.is_error
    answer = explained.structured_content
    assert answer is not None
    assert len(model.asked) == 1
    assert answer == again.structured_content == routed.json()
    # The stored report, not one of a validation again.
    assert answer["report"] == invoice["report"]
    (explanation,) = answer["explanations"]
    assert (explanation["rule_id"], explanation["problem"]) == ("SRB-009", None)
    assert explanation["citations"]
    assert limited.status_code == 429
    assert text_of(waiting) == f"Error executing tool explain_invoice: {limited.json()['detail']}"


async def test_a_server_without_a_model_says_so(
    committed_database: Database, database_url: str
) -> None:
    async with serving(committed_database, database_url, model=NO_MODEL) as served:
        invoice = await stored(served, WRONG_PIB)
        async with connected(served.app, served.key) as client:
            refused = await client.call_tool("explain_invoice", {"invoice_id": invoice["id"]})

    assert text_of(refused) == (
        "Error executing tool explain_invoice: no language model is configured on this server"
    )


async def test_stored_invoices_are_validated_again_in_a_job_the_assistant_follows(
    served: Served,
) -> None:
    """As the route does: the invoices the caller may see, one revalidation of theirs at a
    time, in a job they read and no one else's."""
    owner = served.primer.as_owner()
    async with served.http({**owner, "Content-Type": "application/xml"}) as http:
        await http.post("/invoices", content=VALID.encode())
    own = await stored(served, WRONG_PIB)
    validator, judging = served.app.state.validator, Judging(hold_from=1)
    served.app.state.validator = judging
    try:
        async with connected(served.app, served.key) as client:
            started = await client.call_tool("revalidate_invoices", {})
            await asyncio.wait_for(judging.holding.wait(), 5)
            again = await client.call_tool("revalidate_invoices", {})
            judging.release.set()
            await served.app.state.jobs.drain()
            async with served.http(owner) as http:
                owners = (await http.post("/invoices/revalidations")).json()
                await served.app.state.jobs.drain()
            assert started.structured_content is not None
            job_id = started.structured_content["id"]
            finished = await client.call_tool("get_job", {"job_id": job_id})
            elsewhere = await client.call_tool("get_job", {"job_id": owners["id"]})
            read = await client.call_tool("get_invoice", {"invoice_id": own["id"]})
        async with served.http(served.key.header()) as http:
            routed = await http.get(f"/jobs/{job_id}")
    finally:
        served.app.state.validator = validator

    begun = started.structured_content
    assert (begun["kind"], begun["status"]) == ("revalidation", "queued")
    assert begun["submitted_by"] == str(served.primer.client.id)
    assert text_of(again) == (
        "Error executing tool revalidate_invoices: a revalidation you started is under way: "
        f"job {job_id}, as get_job reads"
    )
    assert finished.structured_content == routed.json()
    assert finished.structured_content is not None
    # The member's one invoice, not the owner's, judged valid now.
    assert (finished.structured_content["status"], finished.structured_content["result"]) == (
        "succeeded",
        NOTHING | {"total": 1, "done": 1, "valid": 1},
    )
    assert read.structured_content is not None
    assert read.structured_content["valid"] is True
    assert text_of(elsewhere) == "Error executing tool get_job: no such job"


async def test_a_client_is_told_which_tools_only_read(served: Served) -> None:
    """What a client reads before it calls a tool on its own, or asks its person first."""
    async with connected(served.app, served.key) as client:
        offered = {tool.name: tool.annotations for tool in (await client.list_tools()).tools}

    hints = {
        name: (hint.read_only_hint, hint.idempotent_hint)
        for name, hint in offered.items()
        if hint is not None
    }
    assert hints["store_invoice"] == hints["revalidate_invoices"] == (False, False)
    assert hints["list_invoices"] == hints["get_invoice"] == hints["get_job"] == (True, True)
    # It keeps what it answered, and may ask the model again for what it could not explain.
    assert hints["explain_invoice"] == (True, False)
