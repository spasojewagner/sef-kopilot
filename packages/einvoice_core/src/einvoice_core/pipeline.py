"""The validation pipeline: the layers a profile asks for, run in order, as one report.

:func:`validate` reads the document with hardened parsing, validates it against the UBL 2.1
schemas and, only when it is schema-valid — the business rules assume it is — runs the
profile's Schematron rule sets, the SRB-CIUS rules and the calculation rules (ADR-0008).

A profile also states which published rules do not apply to it, and why. Every profile hands
CEN's calculation rules to the arithmetic layer, which states the amounts (ADR-0007); the SRB
profile sets aside the EN 16931 rules that SRB-CIUS widens — Serbian VAT categories and
exemption codes, reverse charge at a rate, category O beside taxed supplies — and the reports
EN 16931's rules make about the Serbian extension and the RSD copy of the VAT breakdown, which
EN 16931 does not know. Set-aside violations stay in the report, apart, with their reason, so
that nothing disappears silently.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from einvoice_core import model
from einvoice_core.arithmetic import RULE_IDS as CALCULATION_RULES
from einvoice_core.arithmetic import validate_arithmetic
from einvoice_core.schematron import validate_schematron
from einvoice_core.srb import validate_srb
from einvoice_core.ubl import build_invoice
from einvoice_core.violations import Severity, ValidationLayer, Violation, is_valid
from einvoice_core.xml import NAMESPACES, ParseError, Source, load_document
from einvoice_core.xsd import validate_xsd

__all__ = [
    "DEFAULT_MAX_VIOLATIONS",
    "PROFILES",
    "LayerOutcome",
    "Profile",
    "SetAside",
    "SetAsideViolation",
    "ValidationReport",
    "validate",
]

#: How many violations a report lists; the rest are only counted.
DEFAULT_MAX_VIOLATIONS: Final = 1000

_FROZEN: Final = ConfigDict(strict=True, frozen=True, extra="forbid")
_COPY_OF_VAT_TOTAL: Final = re.compile(
    r"^/(?:ubl:Invoice|cn:CreditNote)/cac:TaxTotal(?:\[(\d+)\])?(?:/|$)"
)


# --- profiles ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class SetAside:
    """Published rules a profile does not apply, why, and what checks the matter instead.

    ``rule_ids`` of ``None`` means any Schematron rule; ``when``, if given, restricts the
    set-aside to the violations it accepts (it sees the violation and the document element).
    """

    rule_ids: frozenset[str] | None
    reason: str
    replaced_by: tuple[str, ...] = ()
    when: Callable[[Violation, etree._Element], bool] | None = None

    def applies_to(self, violation: Violation, root: etree._Element) -> bool:
        if self.rule_ids is not None and violation.rule_id not in self.rule_ids:
            return False
        return self.when is None or self.when(violation, root)


@dataclass(frozen=True)
class Profile:
    """What a validation checks: the Schematron rule sets, the Serbian rules, the set-asides."""

    name: str
    title: str
    rule_sets: tuple[str, ...]
    srb_rules: bool
    set_aside: tuple[SetAside, ...]


def _element_at(root: etree._Element, xpath: str | None) -> etree._Element | None:
    if xpath is None:
        return None
    found = root.xpath(xpath, namespaces=NAMESPACES)
    element = found[0] if isinstance(found, list) and found else None
    return element if isinstance(element, etree._Element) else None


def _in_extension(violation: Violation, _root: etree._Element) -> bool:
    return "/ext:UBLExtensions" in (violation.xpath or "")


def _in_vat_copy(violation: Violation, root: etree._Element) -> bool:
    """Whether the violation is about a VAT total in a currency other than the invoice's."""
    match = _COPY_OF_VAT_TOTAL.match(violation.xpath or "")
    currency = root.findtext("cbc:DocumentCurrencyCode", namespaces=NAMESPACES)
    if match is None or currency is None:
        return False
    totals = root.findall("cac:TaxTotal", NAMESPACES)
    position = int(match.group(1) or 1)
    if position > len(totals):
        return False
    amount = totals[position - 1].find("cbc:TaxAmount", NAMESPACES)
    return amount is not None and amount.get("currencyID") != currency.strip()


def _building_code(violation: Violation, root: etree._Element) -> bool:
    category = _element_at(root, violation.xpath)
    code = (
        None
        if category is None
        else category.findtext("cbc:TaxExemptionReasonCode", namespaces=NAMESPACES)
    )
    return (code or "").strip() == "PDV-RS-OBJ"


#: Every profile: CEN's calculation rules are computed again by the arithmetic layer.
CALCULATIONS: Final = SetAside(
    frozenset(CALCULATION_RULES),
    "computed again by the arithmetic layer, which states the expected amount (ADR-0007)",
    CALCULATION_RULES,
)

#: The SRB profile: EN 16931 rules that SRB-CIUS widens, and reports about Serbian copies.
SRB_SET_ASIDE: Final = (
    SetAside(
        frozenset({"BR-CL-17", "BR-CL-18"}),
        "SRB-CIUS allows VAT categories (R, OE, SS, N) outside EN 16931's subset of UNCL 5305",
        ("SRB-020",),
    ),
    SetAside(
        frozenset({"BR-CL-22"}),
        "VAT exemption reason codes come from the Ministry's list (PDV-RS-...), not from VATEX",
        ("SRB-022", "SRB-023"),
    ),
    SetAside(
        frozenset({"BR-AE-05", "BR-AE-06", "BR-AE-07", "BR-AE-09"}),
        "reverse charge (AE) in SEF states the rate the recipient owes, 20 or 10 percent, and "
        "the VAT at that rate",
        ("SRB-021",),
    ),
    SetAside(
        frozenset({"BR-Z-10"}),
        "a Serbian exemption with the right to deduct (Z) states one of the Ministry's codes",
        ("SRB-022", "SRB-024"),
    ),
    SetAside(
        frozenset({"BR-S-10"}),
        "the Ministry's list gives S the code PDV-RS-OBJ for the first transfer of newly built "
        "buildings",
        ("SRB-022",),
        when=_building_code,
    ),
    SetAside(
        frozenset({"BR-O-02", "BR-O-03", "BR-O-04"}),
        "SRB-CIUS requires the VAT identifiers of seller and buyer on every invoice",
        ("SRB-007",),
    ),
    SetAside(
        frozenset({"BR-O-05", "BR-O-06", "BR-O-07"}),
        "SEF writes the rate 0 for supplies not subject to VAT (O), as the Ministry's examples do",
    ),
    SetAside(
        frozenset({"BR-O-11", "BR-O-12", "BR-O-13", "BR-O-14"}),
        "supplies not subject to VAT (O) appear beside taxed supplies on Serbian invoices, as in "
        "the Ministry's examples",
    ),
    SetAside(
        frozenset({"UBL-CR-001"}),
        "SRB-CIUS defines its own extension (SrbDtExt) in ext:UBLExtensions",
        ("SRB-029",),
    ),
    SetAside(
        None,
        "about the Serbian extension (SrbDtExt), which EN 16931 does not know; its totals are "
        "checked by SRB-025 to SRB-028",
        ("SRB-025", "SRB-026", "SRB-027", "SRB-028"),
        when=_in_extension,
    ),
    SetAside(
        None,
        "about the RSD copy of the VAT breakdown (SRB-CIUS 1.4, BG-E7), which is not BG-23",
        ("SRB-028",),
        when=_in_vat_copy,
    ),
)

#: The profiles a document can be validated against.
PROFILES: Final[dict[str, Profile]] = {
    "srb": Profile(
        name="srb",
        title="SRB-CIUS: EN 16931 as SEF applies it, with the Serbian rules",
        rule_sets=("en16931",),
        srb_rules=True,
        set_aside=(CALCULATIONS, *SRB_SET_ASIDE),
    ),
    "en16931": Profile(
        name="en16931",
        title="EN 16931",
        rule_sets=("en16931",),
        srb_rules=False,
        set_aside=(CALCULATIONS,),
    ),
    "peppol": Profile(
        name="peppol",
        title="Peppol BIS Billing 3.0",
        rule_sets=("en16931-peppol", "peppol"),
        srb_rules=False,
        set_aside=(CALCULATIONS,),
    ),
}


# --- the report --------------------------------------------------------------------------------


class LayerOutcome(BaseModel):
    """Whether a layer ran, what it found, and why it did not run."""

    model_config = _FROZEN

    layer: ValidationLayer
    ran: bool
    violations: int = Field(description="Violations the layer reported and the report keeps.")
    note: str | None = Field(
        default=None, description="The rule sets a layer ran, or why it did not run."
    )


class SetAsideViolation(BaseModel):
    """A violation a published rule set reported that the profile does not apply."""

    model_config = _FROZEN

    violation: Violation
    reason: str
    replaced_by: tuple[str, ...] = Field(
        description=(
            "The rules that check the matter instead, if any; a rule recomputed under its own "
            "id (BR-CO-*) is replaced by that rule alone."
        )
    )


class ValidationReport(BaseModel):
    """The verdict on one document under one profile."""

    model_config = _FROZEN

    profile: str
    valid: bool = Field(description="True when no violation is fatal; warnings do not block.")
    violations: tuple[Violation, ...] = Field(
        description="In layer order: XML, XSD, Schematron, SRB-CIUS, arithmetic."
    )
    set_aside: tuple[SetAsideViolation, ...] = ()
    layers: tuple[LayerOutcome, ...]
    omitted: int = Field(default=0, description="Violations beyond the limit, counted only.")


# --- the pipeline ------------------------------------------------------------------------------


def _xml_violation(code: str, message: str, xpath: str | None = None) -> Violation:
    return Violation(
        rule_id="XML",
        severity=Severity.FATAL,
        message=message,
        xpath=xpath,
        layer="xml",
        code=code,
    )


def _split(
    violations: tuple[Violation, ...], profile: Profile, root: etree._Element
) -> tuple[list[Violation], list[SetAsideViolation]]:
    kept: list[Violation] = []
    set_aside: list[SetAsideViolation] = []
    for violation in violations:
        rule = next((rule for rule in profile.set_aside if rule.applies_to(violation, root)), None)
        if rule is None:
            kept.append(violation)
        else:
            same_rule = violation.rule_id in rule.replaced_by
            set_aside.append(
                SetAsideViolation(
                    violation=violation,
                    reason=rule.reason,
                    replaced_by=(violation.rule_id,) if same_rule else rule.replaced_by,
                )
            )
    return kept, set_aside


_Layer = Callable[[etree._ElementTree, model.Invoice], tuple[Violation, ...]]


def _not_run(layer: ValidationLayer, why: str) -> LayerOutcome:
    return LayerOutcome(layer=layer, ran=False, violations=0, note=why)


def validate(
    source: Source | etree._ElementTree,
    profile: str = "srb",
    *,
    max_violations: int = DEFAULT_MAX_VIOLATIONS,
) -> ValidationReport:
    """Validate one invoice or credit note under ``profile`` (``srb``, ``en16931``, ``peppol``).

    ``source`` is anything :func:`einvoice_core.xml.load_document` accepts, or a tree it
    returned. The function does not raise for a bad document: what is wrong with it is the
    report. It raises :class:`ValueError` for an unknown profile.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose one of {', '.join(PROFILES)}")
    chosen = PROFILES[profile]
    violations: list[Violation] = []
    set_aside: list[SetAsideViolation] = []
    layers: list[LayerOutcome] = []
    rules_layers: tuple[ValidationLayer, ...] = ("schematron", "srb-cius", "arithmetic")

    try:
        tree = source if isinstance(source, etree._ElementTree) else load_document(source)
    except ParseError as error:
        violations.append(_xml_violation("UNREADABLE", error.message, error.xpath))
        layers.append(LayerOutcome(layer="xml", ran=True, violations=1))
        layers += [
            _not_run(layer, "the document could not be read") for layer in ("xsd", *rules_layers)
        ]
        return _report(chosen, violations, set_aside, layers, max_violations)
    root = tree.getroot()

    invoice: model.Invoice | None = None
    xsd = validate_xsd(tree)
    if is_valid(xsd):
        try:
            invoice = build_invoice(root)
        except ParseError as error:
            message = (
                f"The document is schema-valid but cannot be read as an invoice: {error.message}"
            )
            violations.append(_xml_violation("MODEL", message, error.xpath))
    layers.append(LayerOutcome(layer="xml", ran=True, violations=len(violations)))
    violations += xsd
    layers.append(LayerOutcome(layer="xsd", ran=True, violations=len(xsd)))
    if not is_valid(xsd):
        layers += [_not_run(layer, "the document is not schema-valid") for layer in rules_layers]
        return _report(chosen, violations, set_aside, layers, max_violations)

    kept, set_aside = _split(validate_schematron(tree, chosen.rule_sets), chosen, root)
    violations += kept
    layers.append(
        LayerOutcome(
            layer="schematron", ran=True, violations=len(kept), note=", ".join(chosen.rule_sets)
        )
    )
    steps: tuple[tuple[ValidationLayer, bool, _Layer], ...] = (
        ("srb-cius", chosen.srb_rules, validate_srb),
        ("arithmetic", True, validate_arithmetic),
    )
    for layer, wanted, run in steps:
        if not wanted:
            layers.append(_not_run(layer, f"not part of the {chosen.name} profile"))
        elif invoice is None:
            layers.append(_not_run(layer, "the document could not be read as an invoice"))
        else:
            found = run(tree, invoice)
            violations += found
            layers.append(LayerOutcome(layer=layer, ran=True, violations=len(found)))
    return _report(chosen, violations, set_aside, layers, max_violations)


def _report(
    profile: Profile,
    violations: list[Violation],
    set_aside: list[SetAsideViolation],
    layers: list[LayerOutcome],
    max_violations: int,
) -> ValidationReport:
    return ValidationReport(
        profile=profile.name,
        valid=is_valid(violations),
        violations=tuple(violations[:max_violations]),
        set_aside=tuple(set_aside),
        layers=tuple(layers),
        omitted=max(0, len(violations) - max_violations),
    )
