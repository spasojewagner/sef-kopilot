"""Retrieval: the stored passages a violation concerns, found by its rule, its terms, its place,
its codes, its words and its meaning, among those that apply on the day."""

from __future__ import annotations

import re
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.schematron import RULE_SETS, RuleSet
from einvoice_core.violations import Severity, ValidationLayer, Violation
from sef_api.rag.embeddings import DIMENSIONS
from sef_api.rag.retrieval import PASSAGES, Retriever, document_path, meaning_text, query_text

from .corpora import repository_corpus, store_corpus

TODAY = date(2026, 11, 5)


def violation(
    rule_id: str, message: str, xpath: str | None = None, layer: ValidationLayer = "schematron"
) -> Violation:
    return Violation(
        rule_id=rule_id, severity=Severity.FATAL, message=message, xpath=xpath, layer=layer
    )


def short(passage_id: str) -> str:
    """``srb-cius/1-3-table-1-bt-31/2025-06-06`` is ``bt-31``: enough to read the lists by."""
    return passage_id.split("/")[1].removeprefix("1-3-table-1-").removeprefix("1-4-table-2-")


@pytest.fixture
async def stored(session: AsyncSession) -> AsyncSession:
    await store_corpus(session, repository_corpus())
    return session


async def found(
    session: AsyncSession, case: Violation, day: date = TODAY, **search: object
) -> list[str]:
    passages = await Retriever(session, day).passages(case, **search)  # type: ignore[arg-type]
    return [short(passage.id) for passage in passages]


async def test_a_rule_of_srb_cius_finds_the_passages_it_cites_first(stored: AsyncSession) -> None:
    case = violation(
        "SRB-009",
        "[SRB-009]-The PIB 100000025 in the seller VAT identifier (BT-31) cannot exist.",
        "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[1]/cbc:CompanyID",
        "srb-cius",
    )

    assert (await found(stored, case))[:3] == ["article-2", "bt-31", "bt-34"]


async def test_the_terms_a_message_names_find_the_rows_that_define_them(
    stored: AsyncSession,
) -> None:
    case = violation(
        "BR-CO-15",
        "[BR-CO-15]-Invoice total amount with VAT (BT-112) = Invoice total amount without VAT "
        "(BT-109) + Invoice total VAT amount (BT-110).",
    )

    assert (await found(stored, case))[:3] == ["bt-112", "bt-109", "bt-110"]


async def test_a_schema_error_finds_the_row_of_its_place_or_the_nearest_above_it(
    stored: AsyncSession,
) -> None:
    date_of_issue = violation(
        "XSD",
        "Element '{urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2}"
        "IssueDate': '2026-13-01' is not a valid value of the atomic type 'xs:date'.",
        "/ubl:Invoice/cbc:IssueDate",
        "xsd",
    )
    missing = violation(
        "XSD",
        "Element 'cac:PartyTaxScheme': Missing child element(s). Expected is ( cac:TaxScheme ).",
        "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme",
        "xsd",
    )

    assert await found(stored, date_of_issue) == ["bt-2"]
    assert await found(stored, missing) == ["bg-4"]  # the seller; the words name every party


async def test_a_rule_on_the_ministrys_list_finds_the_categories_and_codes_it_names(
    stored: AsyncSession,
) -> None:
    wrong_category = violation(
        "SRB-022",
        "[SRB-022]-The VAT exemption reason code 'PDV-RS-11-1' (BT-121) belongs to category S20 "
        "or AE10 in the Ministry's list, not to O.",
        layer="srb-cius",
    )
    a_code_alone = violation(
        "BR-E-10", "The exemption reason code PDV-RS-25-1-1 is not explained (BT-120)."
    )

    passages = await found(stored, wrong_category)
    assert passages[:5] == [
        "bt-121",
        "bt-118",
        "tax-category-s20",
        "tax-category-ae10",
        "tax-category-o",
    ]
    assert "tax-category-e" in await found(stored, a_code_alone)


async def test_a_rule_that_does_not_cite_the_list_brings_in_none_of_the_categories_it_names(
    stored: AsyncSession,
) -> None:
    allowed = violation(
        "SRB-020",
        "[SRB-020]-The VAT breakdown VAT category code (BT-118) must be one of S, Z, E, AE, R, O, "
        "OE, SS, N; found 'G'.",
        layer="srb-cius",
    )

    passages = await found(stored, allowed)

    assert passages[0] == "bt-118"
    assert [passage for passage in passages if passage.startswith("tax-category")] == []


async def test_an_exemption_code_finds_its_category_not_those_of_the_codes_it_begins(
    stored: AsyncSession,
) -> None:
    """PDV-RS-6 is a code of category R; PDV-RS-6-1-1, which begins with it, one of N."""
    case = violation("BR-E-10", "The exemption reason code PDV-RS-6 is not explained (BT-120).")

    passages = await found(stored, case)

    assert "tax-category-r" in passages
    assert "tax-category-n" not in passages


async def test_the_words_find_a_row_by_the_term_in_either_language(stored: AsyncSession) -> None:
    english = violation(
        "PEPPOL-EN16931-R001", "[PEPPOL-EN16931-R001]-Business process MUST be provided."
    )
    serbian = violation("SRB-008", "Elektronska adresa prodavca nije ispravna.")

    assert (await found(stored, english))[0] == "bt-23"
    assert (await found(stored, serbian))[0] == "bt-34"


async def test_only_the_passages_that_apply_on_the_day_are_found(stored: AsyncSession) -> None:
    cross_border = violation("TEST", "lista carinskih deklaracija za uvoz")
    renumbered = date(2027, 1, 1)

    before = await Retriever(stored, date(2026, 12, 31)).passages(cross_border)
    after = await Retriever(stored, renumbered).passages(cross_border)

    assert before[0].id == "e-invoicing-law/article-4b/2026-04-01"
    assert after[0].id == "e-invoicing-law/article-4v/2027-01-01"  # 4b ends the day 4v starts
    assert all(passage.valid_from <= renumbered for passage in after)
    assert all(passage.valid_to is None or passage.valid_to > renumbered for passage in after)


async def test_the_passages_a_rule_cites_are_found_only_on_the_days_they_apply(
    stored: AsyncSession,
) -> None:
    case = violation("SRB-009", "[SRB-009]-The PIB 100000025 cannot exist.", layer="srb-cius")
    before_the_specification = date(2025, 1, 1)  # its edition applies from 6 June 2025

    passages = await Retriever(stored, before_the_specification).passages(case)

    assert short(passages[0].id) == "article-2"
    assert all(passage.valid_from <= before_the_specification for passage in passages)


async def test_the_meaning_finds_the_nearest_embedding_of_the_same_model(
    session: AsyncSession,
) -> None:
    def embed(passage: object) -> list[float] | None:
        key = getattr(passage, "key", "")
        if key == "1.3, Table 1, BT-20":  # payment terms
            return [1.0] + [0.0] * (DIMENSIONS - 1)
        if key == "1.3, Table 1, BT-9":  # the due date
            return [0.8, 0.6] + [0.0] * (DIMENSIONS - 2)
        return [0.0, 0.0, 1.0] + [0.0] * (DIMENSIONS - 3)

    await store_corpus(session, repository_corpus(), embed=embed, model="test/embedder")
    question = violation("BR-CO-25", "Nothing these words would find.")
    near_payment_terms = [1.0] + [0.0] * (DIMENSIONS - 1)

    by_meaning = await found(session, question, vector=near_payment_terms, model="test/embedder")
    other_model = await found(session, question, vector=near_payment_terms, model="another/one")

    assert by_meaning[:2] == ["bt-20", "bt-9"]
    assert other_model == []


async def test_the_meaning_finds_only_passages_that_apply_on_the_day(
    session: AsyncSession,
) -> None:
    def embed(passage: object) -> list[float] | None:
        if getattr(passage, "id", "") == "e-invoicing-law/article-4b/2027-07-01":  # farmers
            return [1.0] + [0.0] * (DIMENSIONS - 1)
        if getattr(passage, "key", "") == "1.3, Table 1, BT-20":
            return [0.8, 0.6] + [0.0] * (DIMENSIONS - 2)
        return [0.0, 0.0, 1.0] + [0.0] * (DIMENSIONS - 3)

    await store_corpus(session, repository_corpus(), embed=embed)
    question = violation("BR-CO-25", "Nothing these words would find.")
    nearest = [1.0] + [0.0] * (DIMENSIONS - 1)

    now = await found(session, question, vector=nearest, model="test/embedder")
    later = await found(session, question, date(2027, 7, 1), vector=nearest, model="test/embedder")

    assert now[0] == "bt-20"  # the farmers' Article 4b applies from 1 July 2027
    assert later[0] == "article-4b"


async def test_the_words_and_the_meaning_are_fused_by_their_ranks(session: AsyncSession) -> None:
    """By its words, "elektronska adresa prodavca" is BT-34 first and BT-49 second; by its
    meaning, as embedded here, BT-20 first and BT-49 second. BT-49, second in both, comes
    first; BT-20 and BT-34, each first in one, tie, and the id decides."""

    def embed(passage: object) -> list[float] | None:
        nearest = {"1.3, Table 1, BT-20": 1.0, "1.3, Table 1, BT-49": 0.9}
        weight = nearest.get(getattr(passage, "key", ""), 0.0)
        return [weight, (1 - weight**2) ** 0.5] + [0.0] * (DIMENSIONS - 2)

    await store_corpus(session, repository_corpus(), embed=embed)
    question = violation("TEST", "elektronska adresa prodavca")

    words = await found(session, question)
    passages = await found(
        session, question, vector=[1.0] + [0.0] * (DIMENSIONS - 1), model="test/embedder"
    )

    assert words[:2] == ["bt-34", "bt-49"]
    assert passages[:3] == ["bt-49", "bt-20", "bt-34"]


async def test_each_passage_is_found_once_and_no_more_than_the_limit(stored: AsyncSession) -> None:
    case = violation(
        "SRB-007",
        "[SRB-007]-The seller VAT identifier (BT-31) RS100000024 and the buyer's (BT-48) and "
        "the tax representative's (BT-63) need the prefix RS (BT-31, BT-48).",
        "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
        "srb-cius",
    )

    passages = await found(stored, case)

    assert len(passages) == PASSAGES
    assert len(set(passages)) == len(passages)
    assert passages[:4] == ["bt-31", "bt-48", "bt-63", "article-2"]


async def test_one_retriever_finds_the_passages_of_every_violation_of_a_report(
    stored: AsyncSession,
) -> None:
    retriever = Retriever(stored, TODAY)

    number = await retriever.passages(violation("BR-02", "[BR-02]-An Invoice number (BT-1)."))
    issued = await retriever.passages(violation("BR-03", "[BR-03]-An issue date (BT-2)."))

    assert (short(number[0].id), short(issued[0].id)) == ("bt-1", "bt-2")


async def test_a_violation_nothing_concerns_finds_nothing(stored: AsyncSession) -> None:
    unreadable = violation("XML", "xmlParseEntityRef: no name", None, "xml")

    assert await found(stored, unreadable) == []
    assert await found(stored, violation("BR-01", "  ")) == []


def test_a_place_is_written_as_the_specification_writes_paths() -> None:
    assert (
        document_path("/ubl:Invoice/cac:InvoiceLine[2]/cbc:ID") == "/Invoice/cac:InvoiceLine/cbc:ID"
    )
    assert document_path("/cn:CreditNote/cbc:IssueDate") == "/CreditNote/cbc:IssueDate"
    assert document_path("/other:Order/cbc:ID") is None
    assert document_path(None) is None
    assert document_path("") is None


def test_the_words_search_with_the_message_without_its_rule() -> None:
    assert query_text(
        violation("BR-02", "[BR-02]-An Invoice shall have an Invoice number (BT-1).")
    ) == ("An Invoice shall have an Invoice number (BT-1).")
    assert query_text(violation("SRB-001", "The type code 386 is not one SEF accepts.")) == (
        "The type code 386 is not one SEF accepts."
    )


def test_the_meaning_searches_with_what_the_rule_says_never_with_what_the_invoice_has() -> None:
    assert meaning_text(
        violation("BR-CO-15", "[BR-CO-15]-Invoice total amount with VAT (BT-112) = (BT-109).")
    ) == ("Invoice total amount with VAT (BT-112) = (BT-109).")
    assert meaning_text(
        violation("SRB-009", "[SRB-009]-The PIB 100000025 cannot exist.", layer="srb-cius")
    ) == ("Every nine-digit PIB has a serial number in range and a valid check digit")
    assert meaning_text(
        violation(
            "BR-CO-16", "[BR-CO-16]-Amount due (BT-115): 1200.00 ≠ 1000.00", layer="arithmetic"
        )
    ) == (
        "Amount due for payment (BT-115) = Invoice total amount with VAT (BT-112) - Paid amount "
        "(BT-113) + Rounding amount (BT-114)"
    )
    assert meaning_text(violation("SRB-999", "[SRB-999]-RS100000024", layer="srb-cius")) is None
    assert meaning_text(violation("XSD", "'RS100000024' is not valid.", layer="xsd")) is None
    assert meaning_text(violation("XML", "Opening and ending tag mismatch", layer="xml")) is None


_SCHEMATRON_MESSAGE = re.compile(
    r"<(?:\w+:)?(?:assert|report)\b[^>]*>(.*?)</(?:\w+:)?(?:assert|report)>", re.S
)
_COMPILED_MESSAGE = re.compile(r"<svrl:text>(.*?)</svrl:text>", re.S)


@pytest.mark.parametrize("rule_set", RULE_SETS.values(), ids=RULE_SETS)
def test_the_messages_of_the_rule_sets_quote_nothing_of_a_document(rule_set: RuleSet) -> None:
    """A Schematron rule's message is what an embedder is sent to search by its meaning: it may
    be, because the rule sets' messages are fixed words, never computed from the document."""
    try:
        path = ruleset_path(rule_set.package) / rule_set.path
    except RulesetNotFoundError:
        pytest.skip(f"{rule_set.package} not fetched (run `make rulesets`)")
    source = path.read_text(encoding="utf-8")
    pattern = _SCHEMATRON_MESSAGE if rule_set.is_source else _COMPILED_MESSAGE

    messages = pattern.findall(source)

    assert len(messages) > 50
    assert [message for message in messages if "<" in message] == []
