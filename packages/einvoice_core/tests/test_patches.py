"""Patches: what one may say, how each operation applies, and what is refused (ADR-0023)."""

from __future__ import annotations

from typing import Any

import pytest
from lxml import etree
from pydantic import ValidationError

from einvoice_core.patches import MAX_PATCHES, MAX_VALUE, Outcome, Patch, apply
from einvoice_core.places import find, place_of
from einvoice_core.rulesets import RulesetNotFoundError, ruleset_path
from einvoice_core.xml import CAC, CBC, UBL, load_document
from einvoice_core.xsd import UBL_RULESET

from .conftest import SYNTHETIC_DIR

MUTATIONS = SYNTHETIC_DIR / "mutations"
MINIMAL = SYNTHETIC_DIR / "srb-minimal-invoice.xml"
ORIGINAL = etree.tostring(load_document(MINIMAL))

SELLER = "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party"
BUYER = "/ubl:Invoice/cac:AccountingCustomerParty/cac:Party"
LINE = "/ubl:Invoice/cac:InvoiceLine"


def _fetched() -> bool:
    try:
        ruleset_path(UBL_RULESET)
    except RulesetNotFoundError:
        return False
    return True


needs_ubl = pytest.mark.skipif(not _fetched(), reason="the UBL 2.1 schemas are not fetched")


def patch(xpath: str, op: str, value: str | None = None) -> Patch:
    return Patch.model_validate({"xpath": xpath, "op": op, "value": value, "reason": "why"})


def applied(tree: etree._ElementTree, *patches: Patch) -> list[Outcome]:
    return apply(tree, list(patches))


def one_line(*namespaces: tuple[str, str]) -> etree._ElementTree:
    declared = "".join(f' xmlns:{prefix}="{uri}"' for prefix, uri in namespaces)
    return load_document(f'<Invoice xmlns="{UBL}"{declared}><cbc:ID>1</cbc:ID></Invoice>'.encode())


def after_the_number(tree: etree._ElementTree) -> str:
    return etree.tostring(tree).decode().split("<cbc:ID>1</cbc:ID>", 1)[1]


def without(text: bytes, *lines: bytes) -> bytes:
    for line in lines:
        assert line in text, line
        text = text.replace(line, b"", 1)
    return text


# --- what a patch may say ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"op": "remove", "value": "x"}, "a patch that removes has no value"),
        ({"op": "replace"}, "a patch that does replace has a value"),
        ({"op": "add"}, "a patch that does add has a value"),
        ({"op": "replace", "value": " \n"}, "the value is blank: a patch that takes a field out"),
        ({"op": "replace", "value": "a\x00b"}, "the value holds a character XML does not allow"),
        ({"op": "add", "value": "\x1b[31m"}, "the value holds a character XML does not allow"),
        ({"op": "add", "value": "￾"}, "the value holds a character XML does not allow"),
        ({"op": "add", "value": "\ud800"}, "Input should be a valid string"),
        ({"op": "remove", "reason": "\x07"}, "the reason holds a character XML does not allow"),
        ({"op": "remove", "reason": ""}, "at least 1 character"),
        ({"op": "replace", "value": "x" * (MAX_VALUE + 1)}, f"at most {MAX_VALUE} characters"),
        ({"op": "move", "value": "x"}, "Input should be 'replace', 'add' or 'remove'"),
        ({"op": "remove", "xpath": ""}, "at least 1 character"),
        ({"op": "remove", "where": "x"}, "Extra inputs are not permitted"),
        ({"op": "replace", "value": 380}, "Input should be a valid string"),
    ],
)
def test_a_patch_that_cannot_mean_one_change_is_refused(
    fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Patch.model_validate({"xpath": "/ubl:Invoice/cbc:Note", "reason": "why", **fields})


def test_a_patch_keeps_tabs_line_ends_and_any_language() -> None:
    value = "Napomena:\tčćšžđ\r\n“quoted” 😀"

    assert patch("/ubl:Invoice/cbc:Note", "replace", value).value == value


def test_more_patches_than_one_repair_needs_are_refused() -> None:
    patches = [patch("/ubl:Invoice/cbc:Note", "remove")] * (MAX_PATCHES + 1)

    with pytest.raises(ValueError, match=f"at most {MAX_PATCHES} patches apply at once"):
        apply(load_document(MINIMAL), patches, order={})


# --- applied ------------------------------------------------------------------------------------


@needs_ubl
@pytest.mark.parametrize(
    ("mutation", "fix"),
    [
        (
            "srb-001-invoice-type-code.xml",
            patch("/ubl:Invoice/cbc:InvoiceTypeCode", "replace", "380"),
        ),
        (
            "srb-005-specification-identifier.xml",
            patch(
                "/ubl:Invoice/cbc:CustomizationID",
                "replace",
                "urn:cen.eu:en16931:2017#compliant#urn:mfin.gov.rs:srbdt:2022",
            ),
        ),
        (
            "srb-019-payment-model.xml",
            patch(
                "/ubl:Invoice/cac:PaymentMeans/cbc:PaymentID", "replace", "(mod97) 12-345678-00123"
            ),
        ),
        (
            "br-cl-14-country-code.xml",
            patch(f"{BUYER}/cac:PostalAddress/cac:Country/cbc:IdentificationCode", "replace", "RS"),
        ),
        # an element added between two of its siblings, after one and at the start
        ("srb-015-city.xml", patch(f"{BUYER}/cac:PostalAddress/cbc:CityName", "add", "Beograd")),
        (
            "srb-016-post-code.xml",
            patch(f"{SELLER}/cac:PostalAddress/cbc:PostalZone", "add", "32000"),
        ),
        ("br-25-item-name.xml", patch(f"{LINE}/cac:Item/cbc:Name", "add", "Konsultantski sat")),
    ],
)
def test_a_patch_undoes_the_mistake_a_mutation_made_to_the_byte(mutation: str, fix: Patch) -> None:
    tree = load_document(MUTATIONS / mutation)

    (outcome,) = applied(tree, fix)

    assert (outcome.status, outcome.problem) == ("applied", None)
    assert etree.tostring(tree) == ORIGINAL


@needs_ubl
def test_a_replacement_says_what_was_there_and_what_is_now() -> None:
    tree = load_document(MINIMAL)

    text, attribute = applied(
        tree,
        patch("/ubl:Invoice/cbc:InvoiceTypeCode", "replace", "386"),
        patch("/ubl:Invoice/cac:PaymentMeans/cbc:PaymentMeansCode/@name", "replace", "Uplata"),
    )

    assert (text.before, text.after) == ("380", "386")
    assert (attribute.before, attribute.after) == ("Prenos na račun", "Uplata")
    code = find(tree, place_of("/ubl:Invoice/cac:PaymentMeans/cbc:PaymentMeansCode"))
    assert code is not None
    assert (code.text, code.get("name")) == ("30", "Uplata")


@needs_ubl
def test_an_element_is_added_with_the_aggregates_on_its_way_indented_as_the_rest() -> None:
    tree = load_document(MINIMAL)
    mail = "nabavka@ogledni-kupac.example"

    (outcome,) = applied(tree, patch(f"{BUYER}/cac:Contact/cbc:ElectronicMail", "add", mail))

    assert (outcome.status, outcome.before, outcome.after) == ("applied", None, mail)
    entity = b"        <cbc:CompanyID>20000014</cbc:CompanyID>\n      </cac:PartyLegalEntity>\n"
    contact = (
        b"      <cac:Contact>\n"
        b"        <cbc:ElectronicMail>nabavka@ogledni-kupac.example</cbc:ElectronicMail>\n"
        b"      </cac:Contact>\n"
    )
    assert etree.tostring(tree) == ORIGINAL.replace(entity, entity + contact)


@needs_ubl
def test_an_element_is_added_after_the_last_of_its_name() -> None:
    tree = load_document(MINIMAL)

    applied(tree, patch("/ubl:Invoice/cbc:Note[2]", "add", "Druga napomena"))

    note = b"  <cbc:Note>Rok za pla&#263;anje je 15 dana od datuma prometa.</cbc:Note>\n"
    second = b"  <cbc:Note>Druga napomena</cbc:Note>\n"
    assert etree.tostring(tree) == ORIGINAL.replace(note, note + second)


@needs_ubl
def test_an_element_first_in_the_schema_is_added_before_every_other() -> None:
    tree = load_document(MINIMAL)

    applied(tree, patch("/ubl:Invoice/cbc:UBLVersionID", "add", "2.1"))

    first = b"  <cbc:CustomizationID>"
    version = b"  <cbc:UBLVersionID>2.1</cbc:UBLVersionID>\n"
    assert etree.tostring(tree) == ORIGINAL.replace(first, version + first, 1)


@needs_ubl
def test_an_attribute_is_added_to_its_element() -> None:
    tree = load_document(MINIMAL)

    (outcome,) = applied(tree, patch("/ubl:Invoice/cbc:Note/@languageID", "add", "sr"))

    assert (outcome.status, outcome.after) == ("applied", "sr")
    note = tree.getroot().find(f"{{{CBC}}}Note")
    assert note is not None
    assert note.get("languageID") == "sr"


@needs_ubl
def test_a_credit_note_is_patched_in_the_order_of_its_own_schema() -> None:
    tree = load_document(SYNTHETIC_DIR / "credit-note-full.xml")

    (outcome,) = applied(tree, patch("/cn:CreditNote/cbc:Note[3]", "add", "Treća napomena"))

    assert outcome.status == "applied"
    third = find(tree, place_of("/cn:CreditNote/cbc:Note[3]"))
    assert third is not None
    following = third.getnext()
    assert following is not None
    assert etree.QName(following).localname == "DocumentCurrencyCode"


@needs_ubl
def test_a_document_written_on_one_line_stays_on_one_line() -> None:
    tree = one_line(("cac", CAC), ("cbc", CBC))

    applied(tree, patch("/ubl:Invoice/cac:OrderReference/cbc:ID", "add", "PO-1"))

    assert after_the_number(tree) == (
        "<cac:OrderReference><cbc:ID>PO-1</cbc:ID></cac:OrderReference></Invoice>"
    )


@needs_ubl
def test_a_namespace_the_document_does_not_declare_is_declared_with_its_usual_prefix() -> None:
    tree = one_line(("cbc", CBC))

    applied(tree, patch("/ubl:Invoice/cac:OrderReference/cbc:ID", "add", "PO-1"))

    assert after_the_number(tree) == (
        f'<cac:OrderReference xmlns:cac="{CAC}">'
        "<cbc:ID>PO-1</cbc:ID></cac:OrderReference></Invoice>"
    )


@needs_ubl
def test_an_element_is_removed_with_its_line() -> None:
    tree = load_document(MINIMAL)

    (outcome,) = applied(tree, patch("/ubl:Invoice/cbc:BuyerReference", "remove"))

    assert (outcome.status, outcome.before, outcome.after) == ("applied", "NAB-77", None)
    assert etree.tostring(tree) == without(
        ORIGINAL, b"  <cbc:BuyerReference>NAB-77</cbc:BuyerReference>\n"
    )


@needs_ubl
def test_an_aggregate_left_holding_nothing_is_removed_with_what_it_held() -> None:
    tree = load_document(MINIMAL)

    (outcome,) = applied(tree, patch("/ubl:Invoice/cac:PaymentTerms/cbc:Note", "remove"))

    assert (outcome.status, outcome.before) == ("applied", "15 dana")
    assert etree.tostring(tree) == without(
        ORIGINAL,
        b"  <cac:PaymentTerms>\n    <cbc:Note>15 dana</cbc:Note>\n  </cac:PaymentTerms>\n",
    )


@needs_ubl
def test_an_aggregate_is_removed_with_all_it_holds_and_an_attribute_on_its_own() -> None:
    tree = load_document(MINIMAL)

    terms, name = applied(
        tree,
        patch("/ubl:Invoice/cac:PaymentTerms", "remove"),
        patch("/ubl:Invoice/cac:PaymentMeans/cbc:PaymentMeansCode/@name", "remove"),
    )

    assert (terms.status, terms.before) == ("applied", None)
    assert (name.status, name.before) == ("applied", "Prenos na račun")
    assert etree.tostring(tree) == without(
        ORIGINAL,
        b"  <cac:PaymentTerms>\n    <cbc:Note>15 dana</cbc:Note>\n  </cac:PaymentTerms>\n",
        b' name="Prenos na ra&#269;un"',
    )


@needs_ubl
def test_patches_apply_in_order_each_to_what_the_ones_before_left() -> None:
    tree = load_document(MINIMAL)

    added, replaced, ambiguous = applied(
        tree,
        patch("/ubl:Invoice/cbc:Note[2]", "add", "Druga napomena"),
        patch("/ubl:Invoice/cbc:Note[2]", "replace", "Izmenjena napomena"),
        patch("/ubl:Invoice/cbc:Note", "replace", "Koja?"),
    )

    assert [added.status, replaced.status, ambiguous.status] == ["applied", "applied", "failed"]
    assert (replaced.before, replaced.after) == ("Druga napomena", "Izmenjena napomena")
    assert ambiguous.problem == (
        "/ubl:Invoice/cbc:Note names 2 elements cbc:Note: give the position of one"
    )


# --- needs a decision ----------------------------------------------------------------------------


@needs_ubl
@pytest.mark.parametrize(
    ("mutation", "refused", "problem"),
    [
        (
            "srb-008-electronic-address-scheme.xml",
            patch(f"{SELLER}/cbc:EndpointID/@schemeID", "replace", "9948"),
            "it touches a tax identifier (cbc:EndpointID): a person decides it",
        ),
        (
            "srb-009-pib-check-digit.xml",
            patch(f"{SELLER}/cac:PartyTaxScheme[1]/cbc:CompanyID", "replace", "RS100000024"),
            "it touches a tax identifier (cac:PartyTaxScheme): a person decides it",
        ),
        (
            "br-co-15-total-with-vat.xml",
            patch(
                "/ubl:Invoice/cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount", "replace", "14400.00"
            ),
            "it touches an amount, or what one is computed from (cac:LegalMonetaryTotal): a person "
            "decides it",
        ),
        (
            "br-cl-23-unit-code.xml",
            patch(f"{LINE}/cbc:InvoicedQuantity/@unitCode", "replace", "HUR"),
            "it touches an amount, or what one is computed from (cbc:InvoicedQuantity): a person "
            "decides it",
        ),
        (
            "srb-018-actual-delivery-date.xml",
            patch("/ubl:Invoice/cac:Delivery/cbc:ActualDeliveryDate", "add", "2026-10-05"),
            "it touches a date or a time (cbc:ActualDeliveryDate): a person decides it",
        ),
        (
            "srb-003-vat-point-date.xml",
            patch("/ubl:Invoice/cbc:TaxPointDate", "remove"),
            "it touches a date or a time (cbc:TaxPointDate): a person decides it",
        ),
        (
            "srb-006-public-funds-identifier.xml",
            patch(f"{BUYER}/cac:PartyIdentification", "remove"),
            "it touches a company identifier or account (cac:PartyIdentification): a person "
            "decides it",
        ),
        (
            "srb-013-seller-vat-status-missing.xml",
            patch(f"{SELLER}/cac:PartyTaxScheme[2]/cbc:CompanyID", "add", "VAT"),
            "it touches a tax identifier (cac:PartyTaxScheme): a person decides it",
        ),
        (
            "srb-minimal-invoice.xml",
            patch("/ubl:Invoice/cac:Delivery", "remove"),
            "it touches a date or a time (cbc:ActualDeliveryDate): a person decides it",
        ),
    ],
)
def test_a_patch_a_person_must_decide_is_not_applied(
    mutation: str, refused: Patch, problem: str
) -> None:
    source = MINIMAL if mutation == MINIMAL.name else MUTATIONS / mutation
    tree = load_document(source)
    before = etree.tostring(tree)

    (outcome,) = applied(tree, refused)

    assert (outcome.status, outcome.problem) == ("needs-decision", problem)
    assert (outcome.before, outcome.after) == (None, None)
    assert etree.tostring(tree) == before


# --- failed --------------------------------------------------------------------------------------


@needs_ubl
@pytest.mark.parametrize(
    ("failing", "problem"),
    [
        (
            patch("/ubl:Invoice/cbc:Note[last()]", "remove"),
            "the path is not a canonical path of an invoice: /ubl:Invoice or /cn:CreditNote, then "
            "cac: and cbc: steps, then @attribute if any",
        ),
        (
            patch("/ubl:Invoice/ext:UBLExtensions", "remove"),
            "the extensions (ext:) are not places a patch may name",
        ),
        (
            patch("/cn:CreditNote/cbc:Note", "remove"),
            "the document is not the cn:CreditNote the path names",
        ),
        (
            patch(f"{SELLER}/cac:PartyName/cbc:Name[2]", "replace", "Primer"),
            "there is no cbc:Name[2] at /ubl:Invoice/cac:AccountingSupplierParty/cac:Party/"
            "cac:PartyName",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference/cbc:ID/@schemeID", "replace", "x"),
            "there is no cbc:ID at /ubl:Invoice/cac:OrderReference",
        ),
        (
            patch("/ubl:Invoice/cbc:Note/@languageID", "replace", "sr"),
            "/ubl:Invoice/cbc:Note has no attribute languageID: add it",
        ),
        (
            patch("/ubl:Invoice/cac:PaymentTerms", "replace", "15 dana"),
            "/ubl:Invoice/cac:PaymentTerms holds elements: replace what it holds, one by one",
        ),
        (
            patch("/ubl:Invoice/cbc:BuyerReference", "add", "NAB-78"),
            "/ubl:Invoice/cbc:BuyerReference is there already: replace it",
        ),
        (
            patch("/ubl:Invoice/cac:PaymentMeans/cbc:PaymentMeansCode/@name", "add", "Uplata"),
            "/ubl:Invoice/cac:PaymentMeans/cbc:PaymentMeansCode/@name is there already: replace it",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference/cbc:ID/@schemeID", "add", "x"),
            "there is no /ubl:Invoice/cac:OrderReference/cbc:ID to add the attribute to: add it "
            "first",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference", "add", "PO-1"),
            "an aggregate (cac:) is not added on its own: add a basic component (cbc:) it holds, "
            "and the aggregate comes with it",
        ),
        (
            patch("/ubl:Invoice/cbc:Note[3]", "add", "Treća"),
            "/ubl:Invoice has 1 cbc:Note: an element is added after the last of its name, at "
            "position 2",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference[2]/cbc:ID", "add", "PO-1"),
            "/ubl:Invoice has 0 cac:OrderReference: an element is added after the last of its "
            "name, at position 1",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference/cbc:ID[2]", "add", "PO-1"),
            "/ubl:Invoice/cac:OrderReference has 0 cbc:ID: an element is added after the last of "
            "its name, at position 1",
        ),
        (
            patch("/ubl:Invoice/cac:PaymentTerms/cbc:CityName", "add", "Beograd"),
            "UBL allows no cbc:CityName in /ubl:Invoice/cac:PaymentTerms",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference/cbc:CityName", "add", "Beograd"),
            "UBL allows no cbc:CityName in /ubl:Invoice/cac:OrderReference",
        ),
        (
            patch("/ubl:Invoice/cbc:BuyerReference/cbc:ID", "add", "1"),
            "UBL allows no cbc:ID in /ubl:Invoice/cbc:BuyerReference",
        ),
        (
            patch("/ubl:Invoice/cac:OrderReference", "remove"),
            "there is nothing at /ubl:Invoice/cac:OrderReference to remove",
        ),
        (
            patch("/ubl:Invoice/cbc:Note/@languageID", "remove"),
            "/ubl:Invoice/cbc:Note has no attribute languageID",
        ),
    ],
)
def test_a_patch_that_cannot_apply_fails_and_changes_nothing(failing: Patch, problem: str) -> None:
    tree = load_document(MINIMAL)

    (outcome,) = applied(tree, failing)

    assert (outcome.status, outcome.problem) == ("failed", problem)
    assert etree.tostring(tree) == ORIGINAL


@needs_ubl
def test_an_empty_document_is_filled_and_emptied_without_whitespace() -> None:
    tree = load_document(f'<Invoice xmlns="{UBL}"/>'.encode())

    added, removed = applied(
        tree,
        patch("/ubl:Invoice/cbc:Note", "add", "Napomena"),
        patch("/ubl:Invoice/cbc:Note", "remove"),
    )

    assert (added.status, removed.status) == ("applied", "applied")
    assert etree.tostring(tree).decode() == f'<Invoice xmlns="{UBL}"/>'


@needs_ubl
def test_the_only_element_of_a_document_takes_no_indentation_with_it() -> None:
    indented = "\n  <cbc:Note>Napomena</cbc:Note>\n"
    tree = load_document(f'<Invoice xmlns="{UBL}" xmlns:cbc="{CBC}">{indented}</Invoice>'.encode())

    applied(tree, patch("/ubl:Invoice/cbc:Note", "remove"))

    assert etree.tostring(tree).decode() == f'<Invoice xmlns="{UBL}" xmlns:cbc="{CBC}"/>'


@needs_ubl
def test_the_root_is_not_removed() -> None:
    tree = load_document(f'<Invoice xmlns="{UBL}" xmlns:cbc="{CBC}"/>'.encode())

    (outcome,) = applied(tree, patch("/ubl:Invoice", "remove"))

    assert (outcome.status, outcome.problem) == ("failed", "the document's root cannot be removed")
