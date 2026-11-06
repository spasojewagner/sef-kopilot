"""Places: the canonical paths a patch names, parsed by a grammar and walked step by step."""

from __future__ import annotations

import pytest
from lxml import etree

from einvoice_core.places import MAX_PATH, Place, PlaceError, Step, find, place_of, reach
from einvoice_core.xml import CAC, CBC, CN, UBL, load_document

from .conftest import SYNTHETIC_DIR

INVOICE = load_document(SYNTHETIC_DIR / "srb-minimal-invoice.xml")
CREDIT_NOTE = load_document(SYNTHETIC_DIR / "credit-note-full.xml")

SUPPLIER = "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party"
SCHEME = f"{SUPPLIER}/cbc:EndpointID/@schemeID"
SUPPLIER_VAT = f"{SUPPLIER}/cac:PartyTaxScheme[1]/cbc:CompanyID"


def test_a_path_is_its_root_its_steps_and_an_attribute() -> None:
    place = place_of(SCHEME)

    assert place.root == f"{{{UBL}}}Invoice"
    assert place.steps == (
        Step(f"{{{CAC}}}AccountingSupplierParty", None),
        Step(f"{{{CAC}}}Party", None),
        Step(f"{{{CBC}}}EndpointID", None),
    )
    assert place.attribute == "schemeID"


@pytest.mark.parametrize(
    "path",
    [
        "/ubl:Invoice",
        "/cn:CreditNote/cac:CreditNoteLine[2]/cbc:ID",
        SUPPLIER_VAT,
        SCHEME,
        "/ubl:Invoice/cbc:Note[999999]/@languageID",
    ],
)
def test_a_path_is_written_back_as_it_was_given(path: str) -> None:
    assert place_of(path).path == path


def test_a_step_keeps_its_position() -> None:
    step = place_of(SUPPLIER_VAT).steps[2]

    assert step == Step(f"{{{CAC}}}PartyTaxScheme", 1)
    assert step.written == "cac:PartyTaxScheme[1]"
    assert Step(f"{{{CBC}}}ID", None).written == "cbc:ID"


@pytest.mark.parametrize(
    "path",
    [
        "",
        "ubl:Invoice/cbc:ID",
        "/Invoice/cbc:ID",
        "/ubl:Invoice/",
        "/ubl:Invoice//cbc:ID",
        "/ubl:Invoice/cbc:*",
        "/ubl:Invoice/*:ID",
        "/ubl:Invoice/cbc:Note[0]",
        "/ubl:Invoice/cbc:Note[1234567]",
        "/ubl:Invoice/cbc:Note[last()]",
        "/ubl:Invoice/cbc:Note[@languageID='sr']",
        "/ubl:Invoice/cbc:Note/text()",
        "/ubl:Invoice/cbc:ID | /ubl:Invoice/cbc:Note",
        "/ubl:Invoice/cbc:ID/@cbc:schemeID",
        "/ubl:Invoice/cbc:ID/@schemeID/@listID",
        "/ubl:Invoice/descendant::cbc:ID",
        "/ubl:CreditNote/cbc:ID",
        "/ubl:Invoice/sbt:SrbDtExt",
        "/ubl:Invoice/cbc:ID\n",
    ],
)
def test_nothing_else_of_xpath_is_a_path(path: str) -> None:
    with pytest.raises(PlaceError, match=r"^the path is not a canonical path of an invoice: "):
        place_of(path)


def test_the_extensions_are_no_place_for_a_patch() -> None:
    with pytest.raises(PlaceError, match=r"^the extensions \(ext:\) are not places a patch may"):
        place_of("/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent")


def test_a_path_longer_than_the_limit_is_refused_before_it_is_read() -> None:
    with pytest.raises(PlaceError, match=f"^the path is longer than {MAX_PATH} characters$"):
        place_of("/ubl:Invoice" + "/cac:Party" * 100)


def test_the_parent_of_an_attribute_is_its_element() -> None:
    place = place_of(SCHEME)

    assert place.parent.path == f"{SUPPLIER}/cbc:EndpointID"
    assert place.parent.parent.path == SUPPLIER


def test_the_root_has_no_parent() -> None:
    with pytest.raises(PlaceError, match=r"^the document's root has no parent$"):
        _ = place_of("/ubl:Invoice").parent


def test_an_element_is_found_one_step_at_a_time() -> None:
    element = find(INVOICE, place_of(SUPPLIER_VAT))

    assert element is not None
    assert element.text == "RS100000024"


def test_an_attribute_is_found_on_its_element() -> None:
    element = find(INVOICE, place_of(SCHEME))

    assert element is not None
    assert element.get("schemeID") == "9948"


def test_the_root_is_found_by_the_root_alone() -> None:
    assert find(INVOICE, place_of("/ubl:Invoice")) is INVOICE.getroot()
    assert find(CREDIT_NOTE, place_of("/cn:CreditNote")) is CREDIT_NOTE.getroot()


def test_a_position_counts_only_the_siblings_of_the_same_name() -> None:
    element = find(CREDIT_NOTE, place_of("/cn:CreditNote/cbc:Note[2]"))

    assert element is not None
    assert element.text == "Druga napomena"
    assert etree.QName(element).namespace == CBC


@pytest.mark.parametrize(
    "path",
    [
        "/ubl:Invoice/cac:OrderReference/cbc:ID",
        "/ubl:Invoice/cbc:Note[2]",
        f"{SUPPLIER}/cac:PartyTaxScheme[3]/cbc:CompanyID",
        "/ubl:Invoice/cac:OrderReference/cbc:ID/@schemeID",
    ],
)
def test_a_place_the_document_does_not_have_is_none(path: str) -> None:
    assert find(INVOICE, place_of(path)) is None


def test_an_attribute_is_looked_for_on_its_element_whether_it_has_it_or_not() -> None:
    element = find(INVOICE, place_of(f"{SUPPLIER}/cbc:EndpointID/@listID"))

    assert element is not None
    assert element.get("listID") is None


def test_a_step_without_a_position_must_name_one_element() -> None:
    with pytest.raises(
        PlaceError,
        match=(
            r"^/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme names 2 "
            r"elements cac:PartyTaxScheme: give the position of one$"
        ),
    ):
        find(INVOICE, place_of(f"{SUPPLIER}/cac:PartyTaxScheme/cbc:CompanyID"))


def test_a_path_of_another_document_type_names_nothing_in_it() -> None:
    with pytest.raises(PlaceError, match=r"^the document is not the cn:CreditNote the path names$"):
        find(INVOICE, place_of("/cn:CreditNote/cbc:ID"))


def test_reach_says_how_far_the_document_goes_along_a_path() -> None:
    contact = "/ubl:Invoice/cac:AccountingCustomerParty/cac:Party/cac:Contact/cbc:ElectronicMail"

    element, depth = reach(INVOICE, place_of(contact))

    assert (etree.QName(element).localname, depth) == ("Party", 2)
    assert reach(INVOICE, place_of(SUPPLIER_VAT))[1] == 4


def test_a_credit_note_is_a_root_of_its_own() -> None:
    place = place_of("/cn:CreditNote/cac:CreditNoteLine[2]/cbc:ID")

    assert place == Place(
        f"{{{CN}}}CreditNote",
        (Step(f"{{{CAC}}}CreditNoteLine", 2), Step(f"{{{CBC}}}ID", None)),
        None,
    )
