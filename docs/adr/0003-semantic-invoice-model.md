# 3. The invoice model follows the EN 16931 semantic model, not the XML syntax

- Status: accepted
- Date: 2026-11-03
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-ubl-parser`

## Context and problem statement

Every layer above the parser needs a typed view of an invoice: the SRB-CIUS rules and the
EN 16931 arithmetic checks read amounts and codes, the explainer cites business terms, the
repairer addresses the place to patch, the API serialises the document for the UI. The
question is what shape that typed view has: a faithful mirror of the UBL 2.1 XML, or the
semantic model that the standard itself is written in. A related question is how a rule
that works on the typed view points back at the XML it came from.

## Decision drivers

- Rules, regulations and error messages are written in EN 16931 business terms (`BT-116`
  "VAT category taxable amount"), not in UBL element names.
- UBL is the first syntax but not the only one: SEF also accepts CII-like inputs through
  other channels, and PDF extraction (M7) produces semantics, not XML.
- Amounts must never pass through binary floating point.
- A violation must name an exact location in the original document; a patch must be
  applicable to the original document.
- Partial documents must still be representable: the parser runs on anything well-formed,
  and the rule layer decides what is missing.

## Considered options

1. **Semantic model keyed to EN 16931 business terms, with canonical XPaths per group** — chosen.
2. A 1:1 mirror of the UBL schema (generated classes, one per complex type).
3. No model: rules evaluated directly as XPath over the lxml tree.

## Decision outcome

Option 1. Concretely (`packages/einvoice_core/model.py`, `xml.py`, `ubl.py`):

- **One `Invoice` model for invoices and credit notes.** Field names are the business terms'
  plain-English names and every field description carries the `BT-n` / `BG-n` identifier.
  A credit note is an invoice with a different type code, exactly as the standard sees it;
  the parser maps the few UBL elements that differ (`CreditNoteLine`, `CreditedQuantity`,
  `CreditNoteTypeCode`, due date on `PaymentMeans`).
- **`Decimal` for amounts, quantities and rates; `date` for dates; strings for codes.** The
  parser converts text strictly (no exponents, no partial dates) and preserves the exact
  decimal text, so `20` stays `20` and `2400.00` keeps its two decimals.
- **Required only what the UBL schema requires.** `cbc:ID`, `cbc:IssueDate`, the two
  parties, `cac:LegalMonetaryTotal/cbc:PayableAmount`, at least one line with `cbc:ID`,
  `cbc:LineExtensionAmount` and `cac:Item`. Everything EN 16931 additionally mandates
  (currency, type code, seller name, VAT breakdown, ...) is optional in the model and its
  absence is a *business rule violation* reported by the rule layer, with a rule id and a
  citation, not a parse exception. The pipeline runs XSD first, so a document that reaches
  the parser normally satisfies the schema; the parser still raises a structured
  `ParseError` with an XPath when it does not.
- **Canonical XPath on every business group**, computed by `canonical_xpath`: absolute,
  canonical prefixes (`ubl`, `cn`, `cac`, `cbc`, `ext`), positional predicates only on steps
  whose element has same-named siblings (`/ubl:Invoice/cac:InvoiceLine[2]/cbc:ID`). Leaf
  values are addressed as `group.xpath + "/cbc:Element"` by the rule that reports them.
  A property-based test guarantees that an expression selects exactly its element.
- **The lxml tree is kept alongside the model, not inside it.** `load_document` returns the
  tree; `build_invoice` builds the model from it. Schematron, XPath-addressed violations and
  patching work on the tree; arithmetic and SRB-CIUS rules work on the model; both agree on
  locations because the model's XPaths were computed from that same tree.
- **Models are strict, frozen and closed** (`strict=True`, `frozen=True`, `extra="forbid"`):
  the parser does the conversion once, the rest of the system treats a parsed document as an
  immutable value.

### Consequences

Good:

- Rules read like the standard: `invoice.vat_breakdown[i].taxable_amount` is `BT-116`, and the
  explanation layer can cite `BT-116` without a lookup table.
- A second syntax (CII) or an extracted PDF only needs a new `build_*` function; every rule,
  explanation and UI screen stays untouched.
- Violations carry an exact, human-readable location that survives round trips through the
  API and the UI; patches can target it.
- Partial and non-compliant documents are representable, so the product can explain what is
  missing instead of failing to load.

Bad / accepted:

- The mapping is hand-written (~500 lines) and must follow the EN 16931-3-2 binding
  precisely; the official example corpus and exact-value tests on synthetic documents are
  the guard.
- Syntax-level information that the semantic model has no term for (element order,
  `currencyID` on every amount, UBL extensions) is not in the model; those checks stay in
  XSD and Schematron, which is where the standard puts them anyway.
- Optional-by-schema fields mean `None` checks in rule code. The alternative, raising on every
  EN-mandatory element, would make the parser the judge of validity, which ADR-0002
  reserves for the rule layer.

## Pros and cons of the options

### 1:1 mirror of the UBL schema

- Good: nothing is lost; generated code is cheap to produce.
- Bad: hundreds of classes (`PartyTaxSchemeType`, `TaxSubtotalType`, ...) that mean nothing
  to an accountant; rule code becomes `invoice.tax_total[0].tax_subtotal[i].taxable_amount.value`
  with no link to `BT-116`; every other syntax needs its own mirror and its own rules.

### No model, XPath only

- Good: zero mapping code; Schematron already works this way.
- Bad: arithmetic in XPath 2.0 is exactly what the brief forbids delegating ("BR-CO rules are
  checked in Python"); no static typing, no IDE help, no serialisation for the API without
  another mapping anyway.
