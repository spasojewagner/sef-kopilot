"""Shared fixtures: the repository the evaluations measure, a small one to run them in, and a
stand-in for the language model."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from sef_api.llm import LLMError, Message
from sef_evals.database import DatabaseError, server_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_DIR = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic"
MUTATIONS_DIR = SYNTHETIC_DIR / "mutations"
DOCUMENTS_DIR = REPOSITORY_ROOT / "evals" / "golden" / "documents"
#: The golden case the small repository reads, as the repository's golden set has it.
READ_CASE: dict[str, Any] = next(
    case
    for case in yaml.safe_load(
        (REPOSITORY_ROOT / "evals" / "golden" / "extraction.yaml").read_text(encoding="utf-8")
    )["cases"]
    if case["name"] == "consulting-hours"
)


def _fetched() -> bool:
    try:
        for name in ("ubl-2.1", "en16931", "peppol-bis-billing-3"):
            ruleset_path(name)
    except RulesetNotFoundError:
        return False
    return True


def _server() -> str | None:
    try:
        return server_url(REPOSITORY_ROOT / ".env")
    except DatabaseError:
        return None


#: For tests that validate documents: the rule sets must have been fetched (``make rulesets``).
needs_rulesets = pytest.mark.skipif(
    not _fetched(), reason="rule sets not fetched (run `make rulesets`)"
)
#: The PostgreSQL server the explanations are measured on, as the API's tests name it.
SERVER = _server()
#: For tests that explain: they make a database of their own on the tests' server.
needs_database = pytest.mark.skipif(
    SERVER is None or not _fetched(),
    reason="SEF_TEST_DATABASE_URL not set, or rule sets not fetched",
)


#: What the stand-in writes for the rules it repairs, at each violation's place.
REPAIRS: dict[str, str] = {
    "SRB-001": "380",
    "BR-CL-14": "RS",
    "SRB-009": "RS100000024",
    "SRB-014": "VAT",
}
_VIOLATION = re.compile(r"<violation>\nrule: (?P<rule>\S+)\nlayer: \S+\nplace: (?P<place>.+)")


class Explaining:
    """A stand-in for the language model: it explains every rule in the same words and cites
    the first passage it may; it repairs the rules of :data:`REPAIRS` by writing their value
    at each violation's place, and nothing else; it reads every document as the fields of
    :data:`READ_CASE`; or it fails as ``failures`` say, in turn."""

    model = "test/explaining"

    def __init__(self, *failures: str) -> None:
        self.failures = list(failures)
        self.asked = 0

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        self.asked += 1
        if self.failures:
            raise LLMError(self.failures.pop(0))
        if name == "invoice_fields":
            return json.dumps(READ_CASE["fields"])
        if name == "repair":
            patches = [
                {
                    "xpath": found["place"],
                    "op": "replace",
                    "value": REPAIRS[found["rule"]],
                    "reason": "Pravilo traži ovu vrednost.",
                }
                for found in _VIOLATION.finditer(messages[-1].content)
                if found["rule"] in REPAIRS
            ]
            return json.dumps({"patches": patches})
        allowed = schema["properties"]["citations"]["items"]["enum"]
        return json.dumps(
            {
                "explanation": "Pravilo nije ispunjeno na mestu koje izveštaj navodi.",
                "fix": "Ispravite podatak koji pravilo navodi.",
                "citations": allowed[:1],
            }
        )

    async def aclose(self) -> None:
        pass


THRESHOLDS = """\
agreement: {min: 1.0}
false_accept_rate: {max: 0.0}
detection: {min: 1.0}
citation_relevance: {min: 1.0}
repair_success: {min: 1.0}
overreach_rate: {max: 0.0}
extraction_photo: {min: 1.0}
extraction_invented: {max: 0.0}
"""

DOCUMENTS = """\
groups:
  - name: valid
    title: A valid Serbian invoice
    documents: docs/srb-minimal-invoice.xml
    profile: srb
    expect: accept
  - name: mistaken
    title: An invoice with a wrong check digit in its PIB
    documents: docs/srb-009-pib-check-digit.xml
    profile: srb
    expect: reject
    reports: header
"""

REPAIRS_GOLDEN = """\
language: sr
cases:
  - name: proforma-type-code
    document: docs/srb-minimal-invoice.xml
    mistake: the type code is 325.
    edits: [["<cbc:InvoiceTypeCode>380<", "<cbc:InvoiceTypeCode>325<"]]
    expect: repaired
  - name: pib-check-digit
    document: docs/srb-009-pib-check-digit.xml
    mistake: a typo in the seller's PIB.
    expect: refused
"""

EXTRACTION = yaml.safe_dump({"cases": [READ_CASE]}, allow_unicode=True, sort_keys=False)

EXPLANATIONS = """\
day: 2026-11-09
languages: [sr]
documents: [docs/srb-009-pib-check-digit.xml]
rules:
  SRB-009:
    relevant: [pib-rulebook/article-2/2018-10-01]
"""


@pytest.fixture
def small_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with two documents, the corpus, golden sets of them and thresholds, and an
    invoice printed three ways to be read, in which the runner can be run and its report
    written. Its database server is the tests'."""
    (tmp_path / "docs").mkdir()
    shutil.copy(SYNTHETIC_DIR / "srb-minimal-invoice.xml", tmp_path / "docs")
    shutil.copy(MUTATIONS_DIR / "srb-009-pib-check-digit.xml", tmp_path / "docs")
    (tmp_path / "third_party").mkdir()
    shutil.copy(REPOSITORY_ROOT / "third_party" / "manifest.json", tmp_path / "third_party")
    shutil.copytree(
        REPOSITORY_ROOT / "corpus", tmp_path / "corpus", ignore=shutil.ignore_patterns("raw")
    )
    golden = tmp_path / "evals" / "golden"
    golden.mkdir(parents=True)
    (tmp_path / "evals" / "thresholds.yaml").write_text(THRESHOLDS, encoding="utf-8")
    (golden / "documents.yaml").write_text(DOCUMENTS, encoding="utf-8")
    (golden / "explanations.yaml").write_text(EXPLANATIONS, encoding="utf-8")
    (golden / "repairs.yaml").write_text(REPAIRS_GOLDEN, encoding="utf-8")
    (golden / "extraction.yaml").write_text(EXTRACTION, encoding="utf-8")
    (golden / "documents").mkdir()
    for document in DOCUMENTS_DIR.glob(f"{READ_CASE['name']}.*"):
        shutil.copy(document, golden / "documents")
    if SERVER is not None:
        monkeypatch.setenv("SEF_TEST_DATABASE_URL", SERVER)
    return tmp_path
