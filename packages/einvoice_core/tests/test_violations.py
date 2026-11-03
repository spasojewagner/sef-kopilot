"""The shared violation value."""

import pytest
from pydantic import ValidationError

from einvoice_core.violations import Severity, Violation, is_valid


def _violation(severity: Severity, **overrides: object) -> Violation:
    fields: dict[str, object] = {
        "rule_id": "BR-CO-15",
        "severity": severity,
        "message": "Invoice total amount with VAT = total without VAT + total VAT.",
        "xpath": "/ubl:Invoice/cac:LegalMonetaryTotal",
        "layer": "schematron",
    }
    fields.update(overrides)
    return Violation.model_validate(fields)


def test_severity_values_match_the_schematron_flags() -> None:
    assert [severity.value for severity in Severity] == ["fatal", "warning"]


def test_a_document_without_fatal_violations_is_valid() -> None:
    assert is_valid(())
    assert is_valid([_violation(Severity.WARNING)])
    assert not is_valid((_violation(Severity.WARNING), _violation(Severity.FATAL)))


def test_optional_details_default_to_none() -> None:
    violation = _violation(Severity.FATAL)

    assert violation.code is None
    assert violation.line is None


def test_xpath_may_be_null_for_document_level_problems() -> None:
    assert _violation(Severity.FATAL, xpath=None).xpath is None


def test_layer_is_one_of_the_known_validation_layers() -> None:
    with pytest.raises(ValidationError, match="layer"):
        _violation(Severity.FATAL, layer="llm")


def test_violations_are_immutable_and_closed() -> None:
    violation = _violation(Severity.FATAL)
    with pytest.raises(ValidationError, match="frozen"):
        violation.rule_id = "BR-01"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _violation(Severity.FATAL, hint="try harder")


def test_serialises_to_the_documented_json_shape() -> None:
    violation = _violation(Severity.FATAL, code="X", line=12)

    assert violation.model_dump(mode="json") == {
        "rule_id": "BR-CO-15",
        "severity": "fatal",
        "message": "Invoice total amount with VAT = total without VAT + total VAT.",
        "xpath": "/ubl:Invoice/cac:LegalMonetaryTotal",
        "layer": "schematron",
        "code": "X",
        "line": 12,
    }
