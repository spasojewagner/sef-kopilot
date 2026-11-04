"""UBL 2.1 XML Schema validation.

The confinement of schema loading is tested with small synthetic schemas; everything else runs
against the official OASIS schemas fetched into ``third_party/ubl-2.1`` (``make rulesets``).
"""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from lxml import etree

from einvoice_core import xsd
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.violations import Severity, Violation, is_valid
from einvoice_core.xml import load_document

from .conftest import official_examples

# --- schema loading is confined to the schema directory ---------------------------------

_XS = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'


def _schema(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'<xs:schema {_XS} targetNamespace="urn:t">{body}</xs:schema>')
    return path


def test_schema_with_local_imports_loads(tmp_path: Path) -> None:
    _schema(tmp_path / "common" / "types.xsd", '<xs:element name="ID" type="xs:string"/>')
    main = _schema(
        tmp_path / "maindoc" / "doc.xsd",
        '<xs:include schemaLocation="../common/types.xsd"/>',
    )

    schema = xsd.load_schema(main, tmp_path)

    assert schema.validate(load_document(b'<ID xmlns="urn:t">1</ID>'))


@pytest.mark.parametrize(
    "location",
    ["http://attacker.invalid/x.xsd", "https://attacker.invalid/x.xsd", "../../outside.xsd"],
)
def test_references_outside_the_schema_directory_are_refused(tmp_path: Path, location: str) -> None:
    root = tmp_path / "schemas"
    _schema(tmp_path / "outside.xsd", '<xs:element name="X" type="xs:string"/>')
    main = _schema(root / "maindoc" / "doc.xsd", f'<xs:include schemaLocation="{location}"/>')

    with pytest.raises(xsd.SchemaLoadError, match="refused reference"):
        xsd.load_schema(main, root)


def test_a_file_url_inside_the_directory_is_allowed(tmp_path: Path) -> None:
    types = _schema(tmp_path / "types.xsd", '<xs:element name="ID" type="xs:string"/>')
    main = _schema(tmp_path / "doc.xsd", f'<xs:include schemaLocation="{types.as_uri()}"/>')

    assert xsd.load_schema(main, tmp_path) is not None


def test_a_missing_schema_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(xsd.SchemaLoadError, match="cannot load XML Schema"):
        xsd.load_schema(tmp_path / "missing.xsd", tmp_path)


def test_validator_needs_both_document_schemas(tmp_path: Path) -> None:
    with pytest.raises(xsd.SchemaLoadError):
        xsd.XsdValidator(tmp_path)


# --- locating the element an error refers to ------------------------------------------------


def _locator(xml: bytes) -> xsd._Locator:
    """A locator on a tree parsed as lxml does by default: unlike ``load_document``, it keeps
    comments, which any tree handed to the validator may have."""
    return xsd._Locator(etree.ElementTree(etree.fromstring(xml)))


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (None, "Element 'b': broken."),
        ("/a/b", "Something without a subject."),
        ("/a/b", "Element 'c': names another element than the path selects."),
        ("/a/*", "Element 'b': the path selects two elements."),
        ("/a/p:x", "Element '{urn:1}x': the prefix is bound to two namespaces."),
        ("/a/b/text()", "Element 'b': the path selects a text node."),
    ],
)
def test_uncertain_locations_are_reported_as_unknown(path: str | None, message: str) -> None:
    locator = _locator(
        b'<a xmlns:p="urn:1"><!-- c --><b>t</b><b/><p:x/><d xmlns:p="urn:2"><p:x/></d></a>'
    )

    assert locator.xpath(path, message) is None


def test_namespaced_attributes_locate_their_element_only() -> None:
    locator = _locator(b'<a><b xml:lang="x"/></a>')
    message = "Element 'b', attribute '{http://www.w3.org/XML/1998/namespace}lang': invalid."

    assert locator.xpath("/a/b", message) == "/a/b"


# --- the official UBL 2.1 schemas ------------------------------------------------------------


def _ubl_available() -> bool:
    try:
        ruleset_path(xsd.UBL_RULESET)
    except RulesetNotFoundError:
        return False
    return True


requires_ubl = pytest.mark.skipif(
    not _ubl_available(), reason="UBL 2.1 schemas not fetched (run `make rulesets`)"
)


@pytest.fixture(scope="module")
def validator() -> xsd.XsdValidator:
    return xsd.default_validator()


@pytest.fixture(scope="module")
def minimal_invoice(synthetic_dir: Path) -> str:
    return (synthetic_dir / "srb-minimal-invoice.xml").read_text(encoding="utf-8")


def _validate(validator: xsd.XsdValidator, text: str) -> tuple[Violation, ...]:
    return validator.validate(load_document(text.encode("utf-8")))


_VALID = official_examples() + sorted(
    (Path(__file__).resolve().parents[3] / "fixtures" / "invoices" / "synthetic").glob("*.xml")
)


@requires_ubl
@pytest.mark.parametrize("path", _VALID, ids=[path.name for path in _VALID])
def test_official_examples_and_synthetic_fixtures_are_schema_valid(
    validator: xsd.XsdValidator, path: Path
) -> None:
    assert validator.validate(load_document(path)) == ()


@requires_ubl
@pytest.mark.parametrize(
    ("old", "new", "code", "xpath", "message"),
    [
        pytest.param(
            "<cbc:IssueDate>2026-10-05</cbc:IssueDate>",
            "<cbc:IssueDate>05.10.2026</cbc:IssueDate>",
            "SCHEMAV_CVC_DATATYPE_VALID_1_2_1",
            "/ubl:Invoice/cbc:IssueDate",
            "Element 'cbc:IssueDate': '05.10.2026' is not a valid value of the atomic type "
            "'xs:date'.",
            id="invalid-date",
        ),
        pytest.param(
            '<cbc:PayableAmount currencyID="RSD">',
            "<cbc:PayableAmount>",
            "SCHEMAV_CVC_COMPLEX_TYPE_4",
            "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount",
            "Element 'cbc:PayableAmount': The attribute 'currencyID' is required but missing.",
            id="missing-currency",
        ),
        pytest.param(
            "<cbc:ID>RF-2026-000123</cbc:ID>",
            "",
            "SCHEMAV_ELEMENT_CONTENT",
            "/ubl:Invoice/cbc:IssueDate",
            "Element 'cbc:IssueDate': This element is not expected. Expected is one of "
            "( cbc:ProfileExecutionID, cbc:ID ).",
            id="missing-invoice-number",
        ),
        pytest.param(
            '<cbc:PriceAmount currencyID="RSD">1500.00',
            '<cbc:PriceAmount currencyID="RSD">1.500,00',
            "SCHEMAV_CVC_DATATYPE_VALID_1_2_1",
            "/ubl:Invoice/cac:InvoiceLine/cac:Price/cbc:PriceAmount",
            "Element 'cbc:PriceAmount': '1.500,00' is not a valid value of the local atomic type.",
            id="localised-decimal",
        ),
    ],
)
def test_schema_errors_become_located_violations(
    validator: xsd.XsdValidator,
    minimal_invoice: str,
    old: str,
    new: str,
    code: str,
    xpath: str,
    message: str,
) -> None:
    assert old in minimal_invoice
    (violation,) = _validate(validator, minimal_invoice.replace(old, new, 1))

    assert violation.rule_id == "XSD"
    assert violation.layer == "xsd"
    assert violation.severity is Severity.FATAL
    assert violation.code == code
    assert violation.xpath == xpath
    assert violation.message == message
    assert violation.line is not None


@requires_ubl
def test_invalid_attribute_values_point_at_the_attribute(
    validator: xsd.XsdValidator, minimal_invoice: str
) -> None:
    text = minimal_invoice.replace("<cbc:Note>", '<cbc:Note languageID="not a language!">')

    first, second = _validate(validator, text)

    assert first.xpath == "/ubl:Invoice/cbc:Note/@languageID"
    assert second.xpath == "/ubl:Invoice/cac:PaymentTerms/cbc:Note/@languageID"
    assert "attribute 'languageID'" in first.message


@requires_ubl
def test_errors_in_repeated_elements_get_positional_xpaths(
    validator: xsd.XsdValidator, minimal_invoice: str
) -> None:
    second_line = (
        "<cac:InvoiceLine><cbc:ID>2</cbc:ID>"
        '<cbc:LineExtensionAmount currencyID="RSD">abc</cbc:LineExtensionAmount>'
        "<cac:Item><cbc:Name>x</cbc:Name></cac:Item>"
        '<cac:Price><cbc:PriceAmount currencyID="RSD">1</cbc:PriceAmount></cac:Price>'
        "</cac:InvoiceLine>"
    )
    text = minimal_invoice.replace("</Invoice>", f"{second_line}</Invoice>")

    (violation,) = _validate(validator, text)

    assert violation.xpath == "/ubl:Invoice/cac:InvoiceLine[2]/cbc:LineExtensionAmount"


@requires_ubl
def test_foreign_elements_keep_their_own_namespace(
    validator: xsd.XsdValidator, minimal_invoice: str
) -> None:
    text = minimal_invoice.replace(
        "<cbc:DueDate>", '<x:Foo xmlns:x="urn:example:x">1</x:Foo><cbc:DueDate>'
    )

    (violation,) = _validate(validator, text)

    assert violation.message.startswith(
        "Element '{urn:example:x}Foo': This element is not expected."
    )
    assert "cbc:DueDate" in violation.message
    assert violation.xpath == "/ubl:Invoice/x:Foo"


@requires_ubl
def test_violations_from_another_prefix_convention_are_canonical(
    validator: xsd.XsdValidator, minimal_invoice: str
) -> None:
    """A document that uses its own prefixes still gets canonical XPaths and messages."""
    text = (
        minimal_invoice.replace("xmlns:cbc=", "xmlns:b=")
        .replace("<cbc:", "<b:")
        .replace("</cbc:", "</b:")
        .replace("2026-10-05</b:IssueDate>", "yesterday</b:IssueDate>")
    )

    (violation,) = _validate(validator, text)

    assert violation.xpath == "/ubl:Invoice/cbc:IssueDate"
    assert violation.message.startswith("Element 'cbc:IssueDate': 'yesterday'")


@requires_ubl
def test_documents_other_than_invoice_and_credit_note_are_unsupported(
    validator: xsd.XsdValidator,
) -> None:
    tree = load_document(b'<Order xmlns="urn:oasis:names:specification:ubl:schema:xsd:Order-2"/>')

    (violation,) = validator.validate(tree)

    assert violation.code == xsd.UNSUPPORTED_DOCUMENT
    assert violation.severity is Severity.FATAL
    assert "neither a UBL 2.1 Invoice nor a UBL 2.1 CreditNote" in violation.message
    assert violation.line == 1


@requires_ubl
def test_the_number_of_reported_violations_is_capped(minimal_invoice: str) -> None:
    broken_line = (
        "<cac:InvoiceLine><cbc:ID>{n}</cbc:ID>"
        '<cbc:LineExtensionAmount currencyID="RSD">x{n}</cbc:LineExtensionAmount>'
        "<cac:Item><cbc:Name>x</cbc:Name></cac:Item>"
        '<cac:Price><cbc:PriceAmount currencyID="RSD">1</cbc:PriceAmount></cac:Price>'
        "</cac:InvoiceLine>"
    )
    lines = "".join(broken_line.format(n=n) for n in range(2, 12))  # 10 broken lines
    text = minimal_invoice.replace("</Invoice>", f"{lines}</Invoice>")
    capped = xsd.XsdValidator(ruleset_path(xsd.UBL_RULESET), max_violations=3)

    violations = _validate(capped, text)

    assert len(violations) == 4
    assert [v.code for v in violations[:3]] == ["SCHEMAV_CVC_DATATYPE_VALID_1_2_1"] * 3
    assert violations[3].code == xsd.TRUNCATED
    assert violations[3].message.startswith("7 further schema errors are not listed")
    assert not is_valid(violations)


@requires_ubl
def test_validation_is_safe_to_share_between_threads(
    validator: xsd.XsdValidator, minimal_invoice: str
) -> None:
    invalid = minimal_invoice.replace("2026-10-05</cbc:IssueDate>", "nope</cbc:IssueDate>", 1)
    documents = [minimal_invoice, invalid] * 40
    expected = [len(_validate(validator, text)) for text in documents]

    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda text: len(_validate(validator, text)), documents))

    assert counts == expected
    assert set(counts) == {0, 1}


@requires_ubl
def test_default_validator_is_compiled_once(validator: xsd.XsdValidator) -> None:
    assert xsd.default_validator() is validator
    assert xsd.validate_xsd(load_document(_VALID[0])) == ()


@requires_ubl
def test_warm_validation_stays_within_the_performance_budget(
    validator: xsd.XsdValidator, minimal_invoice: str
) -> None:
    """Brief §5: validating a typical invoice takes < 500 ms warm (XSD is a small part of it)."""
    tree = load_document(minimal_invoice.encode("utf-8"))
    durations = []
    for _ in range(20):
        start = time.perf_counter()
        validator.validate(tree)
        durations.append(time.perf_counter() - start)

    assert statistics.median(durations) < 0.05  # 50 ms: a tenth of the whole budget
