# Patches at canonical paths: where a change goes, and why order matters

A repair is a list of patches, `{xpath, op, value, reason}`, that code applies to the invoice
and the validator then judges (ADR-0023). Three ideas make that safe.

## 1. A place is a path the validator already reports

Every violation carries a **canonical path**: child steps from the root, with a position only
where an element has siblings of its name.

```text
/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme[1]/cbc:CompanyID
/ubl:Invoice/cac:AccountingSupplierParty/cac:Party/cbc:EndpointID/@schemeID
```

A patch uses the same form, and the engine reads it with a grammar, not as XPath. XPath could
say `//cbc:Note`, `cbc:ID[last()]` or `contains(...)`: it selects any number of nodes, and the
guard would have to work out which. A canonical path names one place or none, and costs as many
steps as it has. If a step without a position matches two elements, the patch fails and asks
for a position. It never picks one.

## 2. UBL fixes the order of an element's children

Each aggregate's type is an `xsd:sequence`: its children must come in the schema's order, or
the schema refuses the document. So *adding* an element means finding its slot.

```text
cac:PostalAddress, as the schema orders it:   ... StreetName ... CityName, PostalZone ... Country ...
the invoice has:                              StreetName, PostalZone, Country
add cbc:CityName  →  after StreetName, before PostalZone (the first sibling ranked after it)
```

The engine reads that order from the UBL 2.1 schemas the validator already fetched (671
elements), instead of a table someone would have to keep in step with them. It also copies the
indentation of the neighbours, so the patched invoice looks like the original.

## 3. "Touches" is wider than "changes"

The guard refuses a patch that touches what a person decides: amounts, VAT, the PIB, company
identifiers, dates, the document's number. A patch touches

- the place it changes (`cbc:PayableAmount`);
- every element above it (`cac:TaxTotal/…/cbc:Percent` is inside VAT);
- for a removal, everything the element holds (removing `cac:InvoiceLine` removes its amounts).

UBL names a basic component by what it represents, so the suffixes `Amount`, `Quantity`,
`CurrencyCode`, `Date` and `Time` cover elements nobody listed one by one.

## Why no empty elements

`<cac:Delivery/>` says nothing, and Peppol refuses a document that has one. So an aggregate is
never added on its own: adding `cac:Contact/cbc:ElectronicMail` creates `cac:Contact` with it.
Removing the last thing an aggregate holds removes the aggregate too.

## In this repository

- `einvoice_core.places`, `schema_order`, `guard`, `patches` and `repair`; `einvoice patch`.
- The tests undo seven mutations by patch and get the original invoice back byte for byte.
