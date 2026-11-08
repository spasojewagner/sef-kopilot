"""``propose_fix`` and ``get_repair``: a repair of a stored invoice proposed through MCP, with
the server's model writing the patches or the assistant giving its own, kept as the routes keep
it until a person decides on the web application's page the tool names (ADR-0024, ADR-0025)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import select

from sef_api.db import Database
from sef_api.models import AuditAction, AuditEvent
from sef_api.repairs.repairer import Repairer

from .corpora import ScriptedModel
from .test_mcp import VALID, Served, connected, served, serving, text_of
from .test_mcp_oauth import bearer, signed_in
from .test_mcp_oauth import connected as connected_with
from .test_oauth_authorization import SERVER
from .test_repairs import MISTAKE, PIB, TYPE_CODE

__all__ = ["served"]  # the fixture, shared with test_mcp

WEB = SERVER["SEF_WEB_URL"]


def answer(*patches: dict[str, str]) -> str:
    """What the model answers: these patches."""
    return json.dumps({"patches": list(patches)})


@asynccontextmanager
async def repairing(
    database: Database, database_url: str, model: Any = None
) -> AsyncIterator[Served]:
    """The application with a web application to send a person to, its repairer asking
    ``model``, or none."""
    async with serving(
        database,
        database_url,
        SEF_PUBLIC_URL=SERVER["SEF_PUBLIC_URL"],
        SEF_WEB_ORIGINS=SERVER["SEF_WEB_ORIGINS"],
        SEF_WEB_URL=SERVER["SEF_WEB_URL"],
    ) as served:
        served.app.state.repairer = None if model is None else Repairer(model)
        yield served


async def kept(served: Served, content: bytes = MISTAKE) -> dict[str, Any]:
    """An invoice stored through the MCP server with Primer's client's key."""
    async with connected(served.app, served.key) as client:
        stored = await client.call_tool("store_invoice", {"xml": content.decode()})
    assert stored.structured_content is not None
    return dict(stored.structured_content)


async def test_the_servers_model_proposes_a_fix_the_person_decides_on_the_web(
    committed_database: Database, database_url: str
) -> None:
    model = ScriptedModel(answer(TYPE_CODE))
    async with repairing(committed_database, database_url, model) as served:
        invoice = await kept(served)
        async with connected(served.app, served.key) as client:
            fixed = await client.call_tool("propose_fix", {"invoice_id": invoice["id"]})
            assert fixed.structured_content is not None
            repair = fixed.structured_content["repair"]
            still = await client.call_tool("get_invoice", {"invoice_id": invoice["id"]})
            async with served.http(served.primer.as_owner()) as http:
                routed = await http.get(f"/invoices/{invoice['id']}/repairs/{repair['id']}")
                approved = await http.post(
                    f"/invoices/{invoice['id']}/repairs/{repair['id']}/approval"
                )
            decided = await client.call_tool(
                "get_repair", {"invoice_id": invoice["id"], "repair_id": repair["id"]}
            )

    assert not fixed.is_error
    assert fixed.structured_content["decide_at"] == (
        f"{WEB}/sr-Latn/invoices/{invoice['id']}/repairs/{repair['id']}"
    )
    assert repair == routed.json()
    assert {key: repair[key] for key in ("status", "model", "valid", "applied")} == {
        "status": "proposed",
        "model": "test/scripted",
        "valid": True,
        "applied": 1,
    }
    assert (repair["proposed_by"], repair["proposed_with_key"]) == (
        str(served.primer.client.id),
        True,
    )
    # Nothing changes until a person decides, and then the repair says so.
    assert still.structured_content is not None
    assert still.structured_content["valid"] is False
    assert approved.status_code == 200
    assert decided.structured_content is not None
    assert decided.structured_content["status"] == "approved"


async def test_the_assistants_own_patches_are_applied_as_given_or_left_to_the_person(
    committed_database: Database, database_url: str
) -> None:
    """No model is asked: the assistant's patches meet the same guard as anyone's, and one on a
    tax identifier waits for the person."""
    async with repairing(committed_database, database_url) as served:
        invoice = await kept(served)
        async with connected(served.app, served.key) as client:
            fixed = await client.call_tool(
                "propose_fix",
                {"invoice_id": invoice["id"], "patches": [TYPE_CODE, PIB], "language": "en"},
            )

    assert not fixed.is_error
    assert fixed.structured_content is not None
    repair = fixed.structured_content["repair"]
    assert (repair["model"], repair["applied"], repair["needs_decision"]) == (None, 1, 1)
    assert [outcome["status"] for outcome in repair["outcomes"]] == ["applied", "needs-decision"]
    assert fixed.structured_content["decide_at"] == (
        f"{WEB}/en/invoices/{invoice['id']}/repairs/{repair['id']}"
    )


async def test_what_the_routes_refuse_the_tool_refuses_in_their_words(
    committed_database: Database, database_url: str
) -> None:
    owner = {"Content-Type": "application/xml"}
    async with repairing(committed_database, database_url) as served:
        invoice = await kept(served)
        async with served.http(served.primer.as_owner() | owner) as http:
            owners = (await http.post("/invoices", content=MISTAKE)).json()
        async with connected(served.app, served.key) as client:
            unasked = await client.call_tool("propose_fix", {"invoice_id": invoice["id"]})
            others = await client.call_tool(
                "propose_fix", {"invoice_id": owners["id"], "patches": [TYPE_CODE]}
            )
            nowhere = await client.call_tool(
                "get_repair", {"invoice_id": invoice["id"], "repair_id": str(uuid.uuid4())}
            )
            unseen = await client.call_tool(
                "get_repair", {"invoice_id": owners["id"], "repair_id": str(uuid.uuid4())}
            )

    assert text_of(unasked) == (
        "Error executing tool propose_fix: no language model is configured on this server"
    )
    assert text_of(others) == (
        "Error executing tool propose_fix: no such invoice in this organization"
    )
    assert text_of(nowhere) == "Error executing tool get_repair: no such repair of this invoice"
    assert text_of(unseen) == "Error executing tool get_repair: no such invoice"


async def test_a_valid_invoice_has_nothing_for_the_model_to_repair(
    committed_database: Database, database_url: str
) -> None:
    model = ScriptedModel(answer(TYPE_CODE))
    async with repairing(committed_database, database_url, model) as served:
        valid = await kept(served, VALID.encode())
        async with connected(served.app, served.key) as client:
            nothing = await client.call_tool("propose_fix", {"invoice_id": valid["id"]})
        async with served.http(served.key.header()) as http:
            routed = await http.post(f"/invoices/{valid['id']}/repairs/suggestion")

    assert routed.status_code == 409
    assert text_of(nothing) == f"Error executing tool propose_fix: {routed.json()['detail']}"
    assert model.asked == []


async def test_without_a_web_application_no_page_is_named(served: Served) -> None:
    invoice = await kept(served)
    async with connected(served.app, served.key) as client:
        fixed = await client.call_tool(
            "propose_fix", {"invoice_id": invoice["id"], "patches": [TYPE_CODE]}
        )

    assert fixed.structured_content is not None
    assert fixed.structured_content["decide_at"] is None


async def test_an_assistant_proposes_as_its_person_and_the_audit_names_it(
    committed_database: Database, database_url: str
) -> None:
    async with repairing(committed_database, database_url) as served:
        invoice = await kept(served)
        tokens = await signed_in(served)
        async with connected_with(served, bearer(tokens["access_token"])) as client:
            fixed = await client.call_tool(
                "propose_fix", {"invoice_id": invoice["id"], "patches": [TYPE_CODE]}
            )
        async with committed_database.sessions() as session:
            event = await session.scalar(
                select(AuditEvent).where(AuditEvent.action == AuditAction.REPAIR_PROPOSED)
            )

    assert fixed.structured_content is not None
    repair = fixed.structured_content["repair"]
    assert (repair["proposed_by"], repair["proposed_with_key"]) == (
        str(served.primer.client.id),
        False,
    )
    assert event is not None
    assert (event.actor, event.oauth_client_id) == (served.primer.client.id, tokens["client"])


async def test_an_assistants_token_cannot_approve_what_it_proposed(
    committed_database: Database, database_url: str
) -> None:
    """Issued for the MCP endpoint, signed with a key of its own: the routes, the approval's
    among them, do not take it at all."""
    async with repairing(committed_database, database_url) as served:
        invoice = await kept(served)
        tokens = await signed_in(served)
        async with connected_with(served, bearer(tokens["access_token"])) as client:
            fixed = await client.call_tool(
                "propose_fix", {"invoice_id": invoice["id"], "patches": [TYPE_CODE]}
            )
        assert fixed.structured_content is not None
        repair = fixed.structured_content["repair"]
        async with served.http(bearer(tokens["access_token"])) as http:
            approving = await http.post(
                f"/invoices/{invoice['id']}/repairs/{repair['id']}/approval"
            )
        async with connected(served.app, served.key) as client:
            waiting = await client.call_tool(
                "get_repair", {"invoice_id": invoice["id"], "repair_id": repair["id"]}
            )

    assert approving.status_code == 401
    assert waiting.structured_content is not None
    assert waiting.structured_content["status"] == "proposed"


async def test_a_client_is_told_proposing_writes_and_reading_does_not(served: Served) -> None:
    async with connected(served.app, served.key) as client:
        offered = {tool.name: tool.annotations for tool in (await client.list_tools()).tools}

    proposing, reading = offered["propose_fix"], offered["get_repair"]
    assert proposing is not None
    assert reading is not None
    # Nothing is lost by proposing: the invoice changes only when a person approves.
    assert (proposing.read_only_hint, proposing.destructive_hint) == (False, False)
    assert (reading.read_only_hint, reading.idempotent_hint) == (True, True)
