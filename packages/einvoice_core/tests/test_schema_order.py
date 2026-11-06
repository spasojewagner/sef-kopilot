"""The order UBL 2.1 puts each element's children in, read from its schemas."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from einvoice_core.rulesets import ENV_VAR, RulesetNotFoundError, ruleset_path
from einvoice_core.schema_order import schema_order
from einvoice_core.xml import CAC, CBC, CN, EXT, UBL
from einvoice_core.xsd import UBL_RULESET


def _fetched() -> bool:
    try:
        ruleset_path(UBL_RULESET)
    except RulesetNotFoundError:
        return False
    return True


needs_ubl = pytest.mark.skipif(not _fetched(), reason="the UBL 2.1 schemas are not fetched")


def names(tags: tuple[str, ...]) -> list[str]:
    return [etree.QName(tag).localname for tag in tags]


@needs_ubl
def test_an_invoice_holds_its_children_in_the_order_of_its_schema() -> None:
    invoice = schema_order()[f"{{{UBL}}}Invoice"]

    assert invoice[0] == f"{{{EXT}}}UBLExtensions"
    assert names(invoice[1:4]) == ["UBLVersionID", "CustomizationID", "ProfileID"]
    order = names(invoice)
    assert order.index("ID") < order.index("IssueDate") < order.index("DueDate")
    assert order.index("InvoiceTypeCode") < order.index("Note") < order.index("BuyerReference")
    assert order[-1] == "InvoiceLine"


@needs_ubl
def test_an_address_names_the_city_after_the_street_and_before_the_post_code() -> None:
    address = names(schema_order()[f"{{{CAC}}}PostalAddress"])

    assert address.index("StreetName") < address.index("CityName") < address.index("PostalZone")
    assert address.index("PostalZone") < address.index("Country")


@needs_ubl
def test_an_aggregate_is_ordered_by_its_type_whatever_its_name() -> None:
    order = schema_order()

    assert order[f"{{{CAC}}}PostalAddress"] == order[f"{{{CAC}}}Address"]
    assert order[f"{{{CAC}}}PayeeParty"] == order[f"{{{CAC}}}Party"]


@needs_ubl
def test_a_credit_note_has_an_order_of_its_own() -> None:
    credit_note = schema_order()[f"{{{CN}}}CreditNote"]

    assert f"{{{CAC}}}CreditNoteLine" in credit_note
    assert f"{{{CAC}}}InvoiceLine" not in credit_note
    assert f"{{{CBC}}}CreditNoteTypeCode" in credit_note


@needs_ubl
def test_a_basic_component_holds_no_elements() -> None:
    order = schema_order()

    assert f"{{{CBC}}}ID" not in order
    assert len(order) > 500  # every aggregate of UBL 2.1, both document types


@needs_ubl
def test_the_schemas_are_read_once() -> None:
    assert schema_order() is schema_order()


SCHEMA = """<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="{target}"
    xmlns:cac="{cac}" xmlns:cbc="{cbc}" targetNamespace="{target}">
  <xsd:element name="{root}" type="{root}Type"/>
  <xsd:complexType name="{root}Type">
    <xsd:sequence>
      <xsd:element ref="cbc:ID"/>
      <xsd:element ref="cac:Delivery" minOccurs="0"/>
    </xsd:sequence>
  </xsd:complexType>
</xsd:schema>
"""
AGGREGATES = f"""<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns="{CAC}"
    xmlns:cbc="{CBC}" targetNamespace="{CAC}">
  <xsd:element name="Delivery" type="DeliveryType"/>
  <xsd:element name="Shipment" type="ShipmentType"/>
  <xsd:complexType name="DeliveryType">
    <xsd:sequence>
      <xsd:element ref="cbc:ActualDeliveryDate" minOccurs="0"/>
      <xsd:element ref="Shipment" minOccurs="0"/>
    </xsd:sequence>
  </xsd:complexType>
  <xsd:complexType name="ShipmentType">
    <xsd:sequence>
      <xsd:element ref="cbc:ID"/>
    </xsd:sequence>
  </xsd:complexType>
</xsd:schema>
"""


def write_schemas(root: Path) -> None:
    (root / "xsd" / "maindoc").mkdir(parents=True)
    (root / "xsd" / "common").mkdir()
    for name, target in (("Invoice", UBL), ("CreditNote", CN)):
        schema = SCHEMA.format(target=target, cac=CAC, cbc=CBC, root=name)
        (root / "xsd" / "maindoc" / f"UBL-{name}-2.1.xsd").write_text(schema, encoding="utf-8")
    common = root / "xsd" / "common" / "UBL-CommonAggregateComponents-2.1.xsd"
    common.write_text(AGGREGATES, encoding="utf-8")


def test_the_order_is_each_sequence_of_references_named_in_clark_notation(tmp_path: Path) -> None:
    write_schemas(tmp_path)

    order = schema_order(root=tmp_path)

    assert dict(order) == {
        f"{{{UBL}}}Invoice": (f"{{{CBC}}}ID", f"{{{CAC}}}Delivery"),
        f"{{{CN}}}CreditNote": (f"{{{CBC}}}ID", f"{{{CAC}}}Delivery"),
        f"{{{CAC}}}Delivery": (f"{{{CBC}}}ActualDeliveryDate", f"{{{CAC}}}Shipment"),
        f"{{{CAC}}}Shipment": (f"{{{CBC}}}ID",),
    }


def test_schemas_that_have_not_been_fetched_are_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))

    with pytest.raises(RulesetNotFoundError, match=r"rule set 'ubl-2\.1' is not present"):
        schema_order()
