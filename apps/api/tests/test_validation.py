"""One validation as the validator's process runs it: profiles, rule sets, the warm-up, the
budget of elements, and every kind of outcome."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args

import pytest

from einvoice_core import schematron, xsd
from einvoice_core.pipeline import PROFILES, validate
from einvoice_core.rulesets import ENV_VAR, RulesetNotFoundError
from einvoice_core.schematron import SchematronError
from sef_api.invoices import validation
from sef_api.invoices.validation import InvoiceSummary, Validation

from .conftest import REPOSITORY_ROOT

INVOICE = (
    REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "srb-final-invoice.xml"
).read_bytes()
CREDIT_NOTE = (
    REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "credit-note-full.xml"
).read_bytes()
BUDGET = 20_000


def test_the_api_offers_the_validators_profiles() -> None:
    assert set(get_args(validation.ProfileName)) == set(PROFILES)


def test_the_rule_sets_are_present_here() -> None:
    assert validation.rule_sets_missing() is None


def test_missing_rule_sets_are_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))

    missing = validation.rule_sets_missing()

    assert missing is not None
    assert "'ubl-2.1' is not present" in missing


# --- warming up -------------------------------------------------------------------------------


def test_warming_up_compiles_the_schemas_and_every_profiles_rule_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled: list[str] = []
    monkeypatch.setattr(xsd, "default_validator", lambda: compiled.append("xsd"))
    monkeypatch.setattr(schematron, "default_validator", compiled.append)

    assert validation.warm_up() is None
    assert compiled == ["xsd", "en16931", "en16931-peppol", "peppol"]


def test_warming_up_without_rule_sets_says_which_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))

    problem = validation.warm_up()

    assert problem is not None
    assert "'ubl-2.1' is not present" in problem


def test_a_rule_set_that_does_not_load_is_named_by_the_type_of_its_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(name: str) -> None:
        raise SchematronError(f"cannot compile {name}: /some/private/path")

    monkeypatch.setattr(schematron, "default_validator", broken)

    assert validation.warm_up() == "the validator's rule sets cannot be loaded (SchematronError)"


# --- the budget of elements -------------------------------------------------------------------


def test_elements_are_counted_up_to_one_more_than_the_limit() -> None:
    document = b"<a>" + b"<b/>" * 10 + b"</a>"

    assert validation.count_elements(document, limit=100) == 11
    assert validation.count_elements(document, limit=5) == 6


def test_malformed_xml_counts_what_was_read_before_it() -> None:
    assert validation.count_elements(b"<a><b/><c></a>", limit=100) == 1


def test_counting_expands_no_entity() -> None:
    """The "billion laughs" is refused by the parser at once (libxml2 bounds the amplification
    of entities), or counted as the two elements it has: never expanded."""
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 10)
    )
    document = f"<!DOCTYPE a [{entities}]><a><b>&a9;</b></a>".encode()

    started = time.perf_counter()
    counted = validation.count_elements(document, limit=BUDGET)

    assert counted <= 2
    assert time.perf_counter() - started < 1


def test_a_million_elements_are_counted() -> None:
    document = b"<a>" + b"<b><c/></b>" * 500_000 + b"</a>"

    assert validation.count_elements(document, limit=2_000_000) == 1_000_001


#: Counts a million elements in a process of its own, and prints by how much its peak grew. The
#: peak is the process's own: ``getrusage`` would also report the one of the process it forked.
COUNT_A_MILLION = r"""
import re

from sef_api.invoices.validation import count_elements


def peak() -> int:
    with open("/proc/self/status", encoding="ascii") as status:
        return int(re.search(r"VmHWM:\s+(\d+) kB", status.read())[1]) // 1024


document = b"<a>" + b"<b><c/></b>" * 500_000 + b"</a>"
before = peak()
count_elements(document, limit=2_000_000)
print(peak() - before)
"""


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the peak is read from /proc")
def test_counting_keeps_nothing_it_has_counted() -> None:
    """Kept, the million elements would take more than 100 MiB; counted, they take none."""
    finished = subprocess.run(
        [sys.executable, "-c", COUNT_A_MILLION],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )

    assert int(finished.stdout) < 32  # MiB


# --- outcomes ---------------------------------------------------------------------------------


def test_a_report_is_the_validators_own_with_what_it_read() -> None:
    kind, detail = validation.outcome(INVOICE, "srb", max_elements=BUDGET)

    assert kind == "report"
    assert json.loads(detail)["report"] == json.loads(validate(INVOICE, "srb").model_dump_json())
    assert Validation.model_validate_json(detail).summary == InvoiceSummary(
        document_type="Invoice",
        number="RF-2026-000124",
        issue_date=date(2026, 10, 5),
        currency="RSD",
        seller="Primer Softver d.o.o.",
        buyer="Ogledni Kupac d.o.o.",
        payable_amount=Decimal("8400.00"),
    )


def test_a_credit_note_is_summarized_as_one() -> None:
    _, detail = validation.outcome(CREDIT_NOTE, "en16931", max_elements=BUDGET)

    summary = Validation.model_validate_json(detail).summary
    assert summary is not None
    assert (summary.document_type, summary.number, summary.currency) == (
        "CreditNote",
        "KO-2026-7",
        "EUR",
    )


@pytest.mark.parametrize(
    "document",
    [
        b"<Invoice><cbc:ID>",  # not XML
        INVOICE.replace(b"<cbc:Note>", b"<cbc:Unknown/><cbc:Note>", 1),  # not schema-valid
        INVOICE.replace(
            b">8400.00</cbc:PayableAmount>", b">" + b"9" * 30 + b"</cbc:PayableAmount>"
        ),
    ],
    ids=["unreadable", "schema-invalid", "amount-too-long"],
)
def test_nothing_is_summarized_from_what_the_model_cannot_read(document: bytes) -> None:
    kind, detail = validation.outcome(document, "srb", max_elements=BUDGET)

    assert kind == "report"
    result = Validation.model_validate_json(detail)
    assert not result.report.valid
    assert result.summary is None


def test_a_summary_keeps_so_much_of_each_text() -> None:
    long_name = "Primer " * 1000
    document = INVOICE.replace(
        b"<cbc:RegistrationName>Primer Softver d.o.o.</cbc:RegistrationName>",
        f"<cbc:RegistrationName>{long_name}</cbc:RegistrationName>".encode(),
        1,
    )

    summary = Validation.model_validate_json(
        validation.outcome(document, "srb", max_elements=BUDGET)[1]
    ).summary

    assert summary is not None
    assert summary.seller == long_name[: validation.SUMMARY_TEXT_LIMIT]


def test_a_document_over_the_budget_is_not_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validation, "validate", lambda *_: pytest.fail("validated anyway"))

    assert validation.outcome(INVOICE, "srb", max_elements=100) == (
        "too-many-elements",
        "the invoice has more than 100 elements",
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            RulesetNotFoundError("rule set 'ubl-2.1' is not present"),
            ("unavailable", "the validator's rule sets are not installed"),
        ),
        (
            SchematronError("rule set 'peppol' failed: quoted-from-the-invoice"),
            ("refused", "the rule sets could not be applied to this invoice"),
        ),
        (
            RuntimeError("the validator choked on quoted-from-the-invoice"),
            ("failed", "RuntimeError"),
        ),
    ],
)
def test_what_goes_wrong_is_a_kind_of_outcome_without_document_content(
    monkeypatch: pytest.MonkeyPatch, error: Exception, expected: tuple[str, str]
) -> None:
    def failing(*_: Any) -> None:
        raise error

    monkeypatch.setattr(validation, "validate", failing)

    assert validation.outcome(INVOICE, "srb", max_elements=BUDGET) == expected
