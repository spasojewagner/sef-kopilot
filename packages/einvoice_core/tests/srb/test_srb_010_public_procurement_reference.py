"""SRB-010: a public-procurement buyer reference is JN-JBKJS: followed by five digits."""

from __future__ import annotations

import pytest

from einvoice_core.srb.rules.srb_010_public_procurement_reference import RULE

from .conftest import Case

BUYER_REFERENCE = "cbc:BuyerReference"


def test_satisfied_by_an_ordinary_buyer_reference(case: Case) -> None:
    assert case.violations(RULE) == []


def test_satisfied_without_a_buyer_reference(case: Case) -> None:
    assert case.remove(BUYER_REFERENCE).violations(RULE) == []


@pytest.mark.parametrize("value", ["JN-JBKJS:10521", "JN-JBKJS:10521-UGOVOR-7/2026"])
def test_satisfied_by_the_prefix_and_five_digits(case: Case, value: str) -> None:
    assert case.set_text(BUYER_REFERENCE, value).violations(RULE) == []


@pytest.mark.parametrize(
    "value",
    ["JN-JBKJS:1052", "JN-JBKJS:105210", "JN-JBKJS:10521/7", "JN-JBKJS 10521", "jn-jbkjs:10521"],
)
def test_broken_by_a_malformed_procurement_reference(case: Case, value: str) -> None:
    (violation,) = case.set_text(BUYER_REFERENCE, value).violations(RULE)

    assert violation.xpath == "/ubl:Invoice/cbc:BuyerReference"
    assert violation.message.endswith(f"found '{value}'.")
