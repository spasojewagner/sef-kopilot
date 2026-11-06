"""The fields of an invoice around a place: what a repairer is shown of it (ADR-0025)."""

from __future__ import annotations

import copy

import pytest
from lxml import etree

from einvoice_core.fields import MAX_SHOWN, InvoiceField, fields_around
from einvoice_core.guard import AMOUNT, COMPANY_IDENTIFIER, DATE, NUMBER, TAX_IDENTIFIER
from einvoice_core.places import find, place_of
from einvoice_core.xml import CAC, CBC, UBL, canonical_xpath, load_document

from .conftest import SYNTHETIC_DIR

MINIMAL = SYNTHETIC_DIR / "srb-minimal-invoice.xml"
BUYER = "/ubl:Invoice/cac:AccountingCustomerParty/cac:Party"
ADDRESS = f"{BUYER}/cac:PostalAddress"
THE_ADDRESS = (
    InvoiceField(path=f"{ADDRESS}/cbc:StreetName", value="Bulevar Ogleda 22"),
    InvoiceField(path=f"{ADDRESS}/cbc:CityName", value="Beograd"),
    InvoiceField(path=f"{ADDRESS}/cbc:PostalZone", value="11000"),
    InvoiceField(path=f"{ADDRESS}/cac:Country/cbc:IdentificationCode", value="RS"),
)
THE_INVOICE = [
    ("cbc:CustomizationID", None),
    ("cbc:ProfileID", None),
    ("cbc:ID", NUMBER),
    ("cbc:IssueDate", DATE),
    ("cbc:DueDate", DATE),
    ("cbc:InvoiceTypeCode", None),
    ("cbc:Note", None),
    ("cbc:DocumentCurrencyCode", AMOUNT),
    ("cbc:BuyerReference", None),
]


def minimal() -> etree._ElementTree:
    return load_document(MINIMAL)


def two_lines() -> etree._ElementTree:
    """The minimal invoice with its line twice."""
    tree = minimal()
    root = tree.getroot()
    line = root.find(f"{{{CAC}}}InvoiceLine")
    assert line is not None
    root.append(copy.deepcopy(line))
    return tree


def test_around_a_basic_component_are_the_fields_of_the_aggregate_that_holds_it() -> None:
    assert fields_around(minimal(), [f"{ADDRESS}/cbc:CityName"], limit=100) == THE_ADDRESS


def test_around_an_aggregate_are_its_fields_and_attributes_with_what_a_person_decides() -> None:
    fields = fields_around(minimal(), [BUYER], limit=100)

    assert [(field.path, field.value, field.decided) for field in fields] == [
        (f"{BUYER}/cbc:EndpointID/@schemeID", "9948", TAX_IDENTIFIER),
        (f"{BUYER}/cbc:EndpointID", "100000016", TAX_IDENTIFIER),
        *((field.path, field.value, None) for field in THE_ADDRESS),
        (f"{BUYER}/cac:PartyTaxScheme/cbc:CompanyID", "RS100000016", TAX_IDENTIFIER),
        (f"{BUYER}/cac:PartyTaxScheme/cac:TaxScheme/cbc:ID", "VAT", TAX_IDENTIFIER),
        (
            f"{BUYER}/cac:PartyLegalEntity/cbc:RegistrationName",
            "Ogledni Kupac d.o.o.",
            COMPANY_IDENTIFIER,
        ),
        (f"{BUYER}/cac:PartyLegalEntity/cbc:CompanyID", "20000014", COMPANY_IDENTIFIER),
    ]


@pytest.mark.parametrize(
    "place",
    [
        None,
        "/ubl:Invoice",
        "/ubl:Invoice/cbc:InvoiceTypeCode",
        "/ubl:Invoice/cac:OrderReference/cbc:ID",  # the invoice has no order reference
    ],
)
def test_around_the_root_and_on_its_level_are_the_invoices_own_fields(place: str | None) -> None:
    fields = fields_around(minimal(), [place], limit=100)

    assert [(field.path.rsplit("/", 1)[1], field.decided) for field in fields] == THE_INVOICE
    assert {field.path.rsplit("/", 1)[0] for field in fields} == {"/ubl:Invoice"}


def test_where_the_invoice_does_not_go_as_far_as_a_place_the_last_element_on_the_way_counts() -> (
    None
):
    """The buyer has no contact: around its e-mail address are the buyer's fields."""
    tree = minimal()

    assert fields_around(tree, [f"{BUYER}/cac:Contact/cbc:ElectronicMail"], limit=100) == (
        fields_around(tree, [BUYER], limit=100)
    )


def test_an_aggregate_inside_another_is_listed_with_it_and_each_once() -> None:
    tree = minimal()
    places = [f"{ADDRESS}/cbc:CityName", BUYER, f"{BUYER}/cbc:EndpointID", BUYER]

    assert fields_around(tree, places, limit=100) == fields_around(tree, [BUYER], limit=100)


def test_the_fields_around_several_places_come_in_the_order_of_the_places() -> None:
    fields = fields_around(minimal(), [ADDRESS, "/ubl:Invoice/cbc:ID", ADDRESS], limit=100)

    assert fields[:4] == THE_ADDRESS
    assert [field.path.rsplit("/", 1)[1] for field in fields[4:]] == [
        name for name, _ in THE_INVOICE
    ]


def test_at_most_as_many_fields_as_the_limit_are_listed() -> None:
    tree = minimal()

    assert fields_around(tree, [ADDRESS, None], limit=3) == THE_ADDRESS[:3]
    assert fields_around(tree, [ADDRESS], limit=0) == ()


def test_a_value_longer_than_is_shown_is_cut_and_says_so() -> None:
    tree = minimal()
    note = tree.getroot().find(f"{{{CBC}}}Note")
    assert note is not None

    shown = {}
    for length in (MAX_SHOWN, MAX_SHOWN + 1):
        note.text = "x" * length
        (field,) = [
            field
            for field in fields_around(tree, [None], limit=100)
            if field.path == "/ubl:Invoice/cbc:Note"
        ]
        shown[length] = (len(field.value), field.cut)

    assert shown == {MAX_SHOWN: (MAX_SHOWN, False), MAX_SHOWN + 1: (MAX_SHOWN, True)}


def test_a_field_among_same_named_siblings_has_its_position_in_its_path() -> None:
    fields = fields_around(
        two_lines(), ["/ubl:Invoice/cac:InvoiceLine[2]/cac:Item/cbc:Name"], limit=100
    )

    assert [field.path for field in fields] == [
        "/ubl:Invoice/cac:InvoiceLine[2]/cac:Item/cbc:Name",
        "/ubl:Invoice/cac:InvoiceLine[2]/cac:Item/cac:ClassifiedTaxCategory/cbc:ID",
        "/ubl:Invoice/cac:InvoiceLine[2]/cac:Item/cac:ClassifiedTaxCategory/cbc:Percent",
        "/ubl:Invoice/cac:InvoiceLine[2]/cac:Item/cac:ClassifiedTaxCategory/cac:TaxScheme/cbc:ID",
    ]


@pytest.mark.parametrize(
    "place",
    [
        "/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent",
        "/ubl:Invoice/cac:InvoiceLine/cbc:ID",  # of which of the two lines
        "/cn:CreditNote/cbc:ID",  # the document is an invoice
        "cbc:ID",
    ],
)
def test_a_place_no_patch_may_name_has_no_fields_around_it(place: str) -> None:
    tree = two_lines()

    assert fields_around(tree, [place], limit=100) == ()
    assert fields_around(tree, [place, ADDRESS], limit=100) == THE_ADDRESS


@pytest.mark.parametrize(
    ("invoice", "extended"),
    [
        ("srb-final-invoice.xml", True),
        ("srb-final-invoice-in-euro.xml", True),
        ("credit-note-full.xml", False),
    ],
)
def test_every_field_is_a_place_a_patch_may_name_and_none_is_in_the_extensions(
    invoice: str, extended: bool
) -> None:
    """Around the root and every aggregate of documents that use almost every business group,
    or the Serbian extension: each field's path names it, and its value is what is there."""
    tree = load_document(SYNTHETIC_DIR / invoice)
    aggregates = [
        canonical_xpath(element)
        for element in tree.getroot().iter()
        if isinstance(element.tag, str) and etree.QName(element).namespace == CAC
    ]
    assert any("/ext:" in path for path in aggregates) == extended  # aggregates in it, too

    fields = fields_around(tree, [None, *aggregates], limit=10_000)

    assert len(fields) > 50
    assert len({field.path for field in fields}) == len(fields)
    for field in fields:
        place = place_of(field.path)  # never in the extensions: the grammar refuses them
        element = find(tree, place)
        assert element is not None, field.path
        value = element.get(place.attribute) if place.attribute is not None else element.text
        assert (value or "")[:MAX_SHOWN] == field.value


def test_comments_and_attributes_of_other_namespaces_are_not_fields() -> None:
    """The validator's parser drops comments; a tree read by another one may hold them."""
    document = (
        f'<Invoice xmlns="{UBL}" xmlns:cbc="{CBC}"><!-- a comment -->'
        '<cbc:Note xml:lang="sr" languageID="sr">Rok<!-- a comment --></cbc:Note></Invoice>'
    ).encode()
    tree = etree.ElementTree(etree.fromstring(document))

    assert fields_around(tree, [None], limit=100) == (
        InvoiceField(path="/ubl:Invoice/cbc:Note/@languageID", value="sr"),
        InvoiceField(path="/ubl:Invoice/cbc:Note", value="Rok"),
    )


def test_an_element_of_another_namespace_is_no_field_nor_is_anything_in_it() -> None:
    """An invoice need not be schema-valid to be shown: what is not UBL inside an aggregate has
    no canonical path a patch may name, and is left out with all it holds."""
    document = (
        f'<Invoice xmlns="{UBL}" xmlns:cac="{CAC}" xmlns:cbc="{CBC}" xmlns:x="urn:example">'
        "<cac:AccountingSupplierParty><x:Wrap><cbc:Name>Skriveno</cbc:Name></x:Wrap>"
        "<cac:Party><cbc:EndpointID>100000024</cbc:EndpointID></cac:Party>"
        "</cac:AccountingSupplierParty></Invoice>"
    ).encode()
    tree = etree.ElementTree(etree.fromstring(document))

    fields = fields_around(tree, ["/ubl:Invoice/cac:AccountingSupplierParty"], limit=100)

    assert [field.path for field in fields] == [
        "/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
    ]
