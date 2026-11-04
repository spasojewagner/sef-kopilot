"""The ``einvoice`` command line: output, exit status, errors."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

from einvoice_core import __version__, cli, schematron
from einvoice_core.cli import EXIT_ERROR, EXIT_INVALID, EXIT_VALID, main
from einvoice_core.pipeline import ValidationReport
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path

from .conftest import SYNTHETIC_DIR

INVOICE = SYNTHETIC_DIR / "srb-minimal-invoice.xml"


def _fetched() -> bool:
    try:
        for package in ("ubl-2.1", "en16931", schematron.COMPILER_PACKAGE):
            ruleset_path(package)
    except RulesetNotFoundError:
        return False
    return True


needs_rule_sets = pytest.mark.skipif(not _fetched(), reason="rule sets not fetched")


def run(*argv: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    status = main(list(argv), out=out, err=err)
    return status, out.getvalue(), err.getvalue()


def variant(tmp_path: Path, name: str, *edits: tuple[str, str]) -> Path:
    source = INVOICE.read_text(encoding="utf-8")
    for old, new in edits:
        assert old in source, old
        source = source.replace(old, new, 1)
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def validated(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the documents the command validates, without running the pipeline."""
    seen: list[str] = []

    def record(source: str, profile: str, **_options: object) -> ValidationReport:
        seen.append(source)
        Path(source).stat()  # a file that cannot be opened raises, as in the pipeline
        return ValidationReport(profile=profile, valid=True, violations=(), layers=())

    monkeypatch.setattr(cli, "validate", record)
    return seen


def files(root: Path, *names: str) -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("<Invoice/>", encoding="utf-8")


WRONG_PIB = (
    '<cbc:EndpointID schemeID="9948">100000024',
    '<cbc:EndpointID schemeID="9948">100000025',
)
SERBIAN_CODE = (
    "<cbc:Percent>20</cbc:Percent>",
    "<cbc:Percent>20</cbc:Percent><cbc:TaxExemptionReasonCode>PDV-RS-OBJ</cbc:TaxExemptionReasonCode>",
)


def test_the_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out == f"einvoice {__version__}\n"


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["validate"],
        ["validate", "a.xml", "--profile", "xrechnung"],
        ["validate", "a.xml", "--max-violations", "0"],
    ],
)
def test_usage_errors_exit_with_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(argv)

    assert exit_info.value.code == EXIT_ERROR
    assert "usage: einvoice" in capsys.readouterr().err


def test_a_missing_file_exits_with_2(tmp_path: Path) -> None:
    status, out, err = run("validate", str(tmp_path / "missing.xml"))

    assert status == EXIT_ERROR
    assert out == ""
    assert err.startswith(f"einvoice: cannot read {tmp_path / 'missing.xml'}:")


def test_a_directory_stands_for_the_xml_files_under_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = validated(monkeypatch)
    files(tmp_path, "b/two.XML", "a.xml", "b/notes.txt", "c/d/three.xml")

    status, out, _ = run("validate", str(tmp_path))

    assert status == EXIT_VALID
    assert seen == [str(tmp_path / name) for name in ("a.xml", "b/two.XML", "c/d/three.xml")]
    assert out.splitlines()[-1] == "3 documents: 3 valid, 0 invalid"


def test_a_pattern_the_shell_left_alone_is_expanded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = validated(monkeypatch)
    files(tmp_path, "one.xml", "two.xml", "three.txt", "sub/four.xml")

    run("validate", str(tmp_path / "*.xml"), str(tmp_path / "s?b"))

    assert seen == [str(tmp_path / name) for name in ("one.xml", "two.xml", "sub/four.xml")]


def test_an_existing_file_is_taken_as_named_even_with_pattern_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = validated(monkeypatch)
    files(tmp_path, "invoice[1].xml", "invoice1.xml")

    run("validate", str(tmp_path / "invoice[1].xml"))

    assert seen == [str(tmp_path / "invoice[1].xml")]


@pytest.mark.parametrize(
    ("name", "message"), [("empty", "no .xml file in"), ("missing-*.xml", "nothing matches")]
)
def test_a_path_that_names_no_document_exits_with_2_before_any_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, message: str
) -> None:
    seen = validated(monkeypatch)
    files(tmp_path, "a.xml", "empty/notes.txt")

    status, out, err = run("validate", str(tmp_path / "a.xml"), str(tmp_path / name))

    assert (status, out, seen) == (EXIT_ERROR, "", [])
    assert err == f"einvoice: {message} {tmp_path / name}\n"


def test_text_reports_are_written_as_the_documents_are_judged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validated(monkeypatch)
    files(tmp_path, "a.xml")

    status, out, err = run("validate", str(tmp_path / "a.xml"), str(tmp_path / "missing.xml"))

    assert status == EXIT_ERROR
    assert out == f"{tmp_path / 'a.xml'}: valid (srb)\n"
    assert err.startswith(f"einvoice: cannot read {tmp_path / 'missing.xml'}:")


def test_missing_rule_sets_exit_with_2_and_say_how_to_fetch_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def not_fetched(*_args: object, **_kwargs: object) -> None:
        raise RulesetNotFoundError("ubl-2.1 has not been fetched")

    monkeypatch.setattr(cli, "validate", not_fetched)

    status, _, err = run("validate", str(INVOICE))

    assert status == EXIT_ERROR
    assert "ubl-2.1 has not been fetched" in err
    assert "make rulesets" in err
    assert "EINVOICE_RULESETS_DIR" in err


@needs_rule_sets
def test_a_valid_invoice_exits_with_0() -> None:
    status, out, err = run("validate", str(INVOICE))

    assert (status, out, err) == (EXIT_VALID, f"{INVOICE}: valid (srb)\n", "")


@needs_rule_sets
def test_an_invalid_invoice_lists_its_violations_and_exits_with_1(tmp_path: Path) -> None:
    path = variant(tmp_path, "wrong-pib.xml", WRONG_PIB)

    status, out, _ = run("validate", str(path))

    assert status == EXIT_INVALID
    lines = out.splitlines()
    source_line = next(
        number
        for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "100000025" in text
    )
    assert lines[0] == f"{path}: invalid (srb): 1 fatal"
    assert lines[1].split() == [
        "fatal",
        "SRB-009",
        "line",
        str(source_line),
        "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    ]
    assert lines[2].strip().startswith("[SRB-009]-The PIB 100000025 in the seller electronic")


@needs_rule_sets
def test_warnings_alone_keep_the_exit_status_0(tmp_path: Path) -> None:
    path = variant(tmp_path, "no-post-code.xml", ("<cbc:PostalZone>11000</cbc:PostalZone>", ""))

    status, out, _ = run("validate", str(path))

    assert status == EXIT_VALID
    assert out.splitlines()[0] == f"{path}: valid (srb): 1 warning"


@needs_rule_sets
def test_set_aside_reports_are_counted_or_listed(tmp_path: Path) -> None:
    path = variant(tmp_path, "building.xml", SERBIAN_CODE)

    _, counted, _ = run("validate", str(path))
    _, listed, _ = run("validate", str(path), "--show-set-aside")

    assert "2 published rule report(s) set aside by the srb profile" in counted
    assert "set aside BR-CL-22" in listed
    assert "(checked by SRB-022, SRB-023)" in listed


@needs_rule_sets
def test_layers_that_did_not_run_are_named(tmp_path: Path) -> None:
    path = variant(tmp_path, "broken.xml", ("<cbc:Note>", "<cbc:Unknown/><cbc:Note>"))

    status, out, _ = run("validate", str(path))

    assert status == EXIT_INVALID
    assert out.splitlines()[-1] == (
        "  not run: schematron, srb-cius, arithmetic (the document is not schema-valid)"
    )


@needs_rule_sets
def test_the_violation_limit_is_reported(tmp_path: Path) -> None:
    wrong_total = ("14400.00</cbc:TaxInclusiveAmount>", "14400.02</cbc:TaxInclusiveAmount>")
    path = variant(tmp_path, "wrong-total.xml", wrong_total)

    _, out, _ = run("validate", str(path), "--profile", "en16931", "--max-violations", "1")

    assert "  ... 1 more not listed (--max-violations)" in out.splitlines()


@needs_rule_sets
def test_several_files_end_with_a_summary(tmp_path: Path) -> None:
    status, out, _ = run("validate", str(INVOICE), str(variant(tmp_path, "b.xml", WRONG_PIB)))

    assert status == EXIT_INVALID
    assert out.splitlines()[-1] == "2 documents: 1 valid, 1 invalid"


@needs_rule_sets
def test_json_output_is_the_report_of_every_file(tmp_path: Path) -> None:
    path = variant(tmp_path, "wrong-pib.xml", WRONG_PIB)

    status, out, _ = run("validate", str(INVOICE), str(path), "--format", "json")

    documents = json.loads(out)
    assert status == EXIT_INVALID
    assert [document["file"] for document in documents] == [str(INVOICE), str(path)]
    assert [document["report"]["valid"] for document in documents] == [True, False]
    assert documents[1]["report"]["violations"][0]["rule_id"] == "SRB-009"


def test_the_rules_of_the_srb_profile() -> None:
    status, out, _ = run("rules")

    lines = out.splitlines()
    assert status == EXIT_VALID
    assert lines[0].startswith("srb: SRB-CIUS")
    assert "Schematron rule sets: en16931" in lines
    assert "SRB-CIUS rules (29):" in lines
    assert any(line.startswith("  SRB-009  fatal") for line in lines)
    calculations = next(line for line in lines if line.startswith("  BR-CO-10, "))
    assert calculations.endswith("which states the expected amount (ADR-0007)")
    assert any(
        line.startswith("  any rule, in some cases: about the Serbian extension") for line in lines
    )


def test_the_rules_of_a_profile_as_json() -> None:
    status, out, _ = run("rules", "--profile", "peppol", "--format", "json")

    data = json.loads(out)
    assert status == EXIT_VALID
    assert data["rule_sets"] == ["en16931-peppol", "peppol"]
    assert data["srb_rules"] == []
    assert data["set_aside"][0]["rule_ids"][0] == "BR-CO-10"


def test_the_console_script(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["einvoice", "rules", "--profile", "en16931"])
    monkeypatch.setattr(sys, "stderr", io.StringIO())  # a stream that cannot be reconfigured

    with pytest.raises(SystemExit) as exit_info:
        cli.console()

    assert exit_info.value.code == EXIT_VALID
    assert capsys.readouterr().out.startswith("en16931: EN 16931")
