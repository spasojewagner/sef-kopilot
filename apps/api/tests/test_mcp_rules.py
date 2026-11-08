"""``search_rules`` and ``get_rule``: the rules of a profile and the passages that concern them,
through MCP, as ``/rules`` answers them (ADR-0047)."""

from __future__ import annotations

from sef_api.db import Database

from .test_mcp import Served, connected, served, serving, text_of

__all__ = ["served"]  # the fixture, shared with test_mcp


async def test_rules_are_found_as_the_route_finds_them(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, corpus=True) as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        searched = await client.call_tool("search_rules", {"query": "BT-31", "limit": 5})
        routed = await http.get("/rules", params={"q": "BT-31", "limit": 5})

    assert not searched.is_error
    assert searched.structured_content == routed.json()
    rules = [rule["id"] for rule in routed.json()["rules"]]
    assert (len(rules), rules[:2]) == (5, ["SRB-007", "SRB-009"])


async def test_a_rule_is_read_with_its_passages_as_the_route_reads_it(
    committed_database: Database, database_url: str
) -> None:
    async with (
        serving(committed_database, database_url, corpus=True) as served,
        connected(served.app, served.key) as client,
        served.http(served.key.header()) as http,
    ):
        read = await client.call_tool("get_rule", {"rule_id": "SRB-009", "day": "2026-10-05"})
        routed = await http.get("/rules/SRB-009", params={"day": "2026-10-05"})
        peppol = await client.call_tool(
            "get_rule", {"rule_id": "PEPPOL-EN16931-R001", "profile": "peppol"}
        )
        unknown = await client.call_tool("get_rule", {"rule_id": "BR-99999"})

    assert read.structured_content == routed.json()
    assert read.structured_content is not None
    assert read.structured_content["passages"][0]["id"] == "pib-rulebook/article-2/2018-10-01"
    assert peppol.structured_content is not None
    assert peppol.structured_content["rule"]["source"] == "peppol"
    assert text_of(unknown) == "Error executing tool get_rule: no such rule in the profile srb"


async def test_looking_rules_up_only_reads(served: Served) -> None:
    async with connected(served.app, served.key) as client:
        offered = {tool.name: tool.annotations for tool in (await client.list_tools()).tools}

    for name in ("search_rules", "get_rule"):
        hints = offered[name]
        assert hints is not None
        assert (hints.read_only_hint, hints.idempotent_hint) == (True, True)
