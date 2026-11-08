"""``/rules``: the rules of a profile, found by id, term or words, and a rule with the passages
that concern it on a day (ADR-0047)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.rulesets import RulesetNotFoundError
from sef_api.rules import routes as rules

from .factories import Office
from .test_invoices_explain import primer_office
from .test_invoices_validate import application


@pytest.fixture
async def primer(session: AsyncSession) -> Office:
    """Primer's office, on a database that holds the repository's corpus."""
    return await primer_office(session)


async def asked(session: AsyncSession, path: str, caller: dict[str, str], **params: Any) -> Any:
    async with application(session) as api:
        return await api.get(path, params=params, headers=caller)


async def test_rules_are_found_by_id_term_or_words_with_passages_that_share_them(
    session: AsyncSession, primer: Office
) -> None:
    answer = await asked(session, "/rules", primer.as_client(), q="PIB check digit")
    in_serbian = await asked(session, "/rules", primer.as_client(), q="kontrolni broj PIB")

    assert answer.status_code == 200
    assert answer.headers["Cache-Control"] == "no-store"
    found = answer.json()
    assert found["rules"][0]["id"] == "SRB-009"
    assert found["rules"][0]["layer"] == "srb-cius"
    # The statements are the rule sets' English; the law is found in its own words.
    law = in_serbian.json()
    assert law["rules"] == []
    assert law["passages"][0]["id"] == "pib-rulebook/article-2/2018-10-01"
    assert all(passage["text"] and passage["source_url"] for passage in law["passages"])


async def test_each_profile_has_its_own_rules(session: AsyncSession, primer: Office) -> None:
    serbian = await asked(session, "/rules", primer.as_client(), q="SRB-009")
    european = await asked(session, "/rules", primer.as_client(), q="SRB-009", profile="en16931")
    peppol = await asked(session, "/rules", primer.as_client(), q="PEPPOL-EN16931-R001", limit=1)

    assert [rule["id"] for rule in serbian.json()["rules"]] == ["SRB-009"]
    assert european.json()["rules"] == []
    assert peppol.json()["rules"] == []


async def test_a_rule_comes_with_the_passages_an_explanation_would_cite(
    session: AsyncSession, primer: Office
) -> None:
    answer = await asked(session, "/rules/srb-009", primer.as_client(), day="2026-10-05")

    assert answer.status_code == 200
    read = answer.json()
    assert (read["rule"]["id"], read["day"]) == ("SRB-009", "2026-10-05")
    # Those it is authored from first, as an explanation of a violation of it cites them.
    assert [passage["id"] for passage in read["passages"][:2]] == [
        "pib-rulebook/article-2/2018-10-01",
        "srb-cius/1-3-table-1-bt-31/2025-06-06",
    ]


async def test_a_published_rule_finds_the_rows_of_the_terms_it_names(
    session: AsyncSession, primer: Office
) -> None:
    answer = await asked(session, "/rules/BR-01", primer.as_client(), profile="en16931")

    read = answer.json()
    assert read["rule"]["statement"] == (
        "An Invoice shall have a Specification identifier (BT-24)."
    )
    assert any(passage["label"] == "BT-24" for passage in read["passages"])


async def test_what_is_no_rule_of_the_profile_is_not_found(
    session: AsyncSession, primer: Office
) -> None:
    unknown = await asked(session, "/rules/BR-99999", primer.as_client())
    elsewhere = await asked(session, "/rules/SRB-009", primer.as_client(), profile="peppol")
    nameless = await asked(session, "/rules", primer.as_client(), q="")

    assert (unknown.status_code, unknown.json()) == (
        404,
        {"detail": "no such rule in the profile srb"},
    )
    assert elsewhere.status_code == 404
    assert nameless.status_code == 422


async def test_rules_are_for_whoever_may_have_an_invoice_validated(
    session: AsyncSession, primer: Office
) -> None:
    anonymous = await asked(session, "/rules", {}, q="BR-01")
    keyless = await asked(session, "/rules/BR-01", {})

    assert (anonymous.status_code, keyless.status_code) == (401, 401)


async def test_without_the_rule_sets_the_server_says_so(
    session: AsyncSession, primer: Office, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(profile: str) -> Any:
        raise RulesetNotFoundError("en16931")

    monkeypatch.setattr(rules, "catalogue", missing)

    answer = await asked(session, "/rules", primer.as_client(), q="BR-01")

    assert (answer.status_code, answer.json()) == (
        503,
        {"detail": "the rule sets are not available on this server"},
    )
