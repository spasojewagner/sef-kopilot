# M1 — `feat/core-ubl-parser`

## Three questions a senior engineer would ask

**1. "Your model makes the invoice currency optional. EN 16931 says BT-5 is mandatory. Why?"**

Because the parser is not the judge of validity (ADR-0002). The model requires only what the
UBL *schema* requires; everything EN 16931 adds on top is a business rule, and a business rule
violation must come out as a violation with a rule id (`BR-05`), a location and a citation —
not as a parse exception that hides every other problem in the document. The pipeline runs
XSD first anyway, so a document that reaches the parser satisfies the schema; the parser still
raises a structured `ParseError` with an XPath if it does not. The cost is `None` checks in
rule code; the alternative would make the explainer useless for exactly the invoices people
need it for.

**2. "How does a rule evaluated on the Python model point back into the XML, and why not
just use lxml's `getpath`?"**

Every business group carries the canonical XPath of the element it was read from, computed
by `canonical_xpath`: absolute, canonical prefixes (`ubl`, `cn`, `cac`, `cbc`), a positional
predicate only where the element has same-named siblings — `/ubl:Invoice/cac:InvoiceLine[2]`.
Leaf values are addressed as `group.xpath + "/cbc:Element"`. lxml's `getpath` uses whatever
prefixes the document happened to declare (or none), and adds `[1]` everywhere, so the same
location would print differently for two documents that only differ in prefix names. A
property-based test (Hypothesis) generates random trees and checks the invariant everything
else relies on: each expression selects exactly its own node.

**3. "What stops a malicious invoice from hurting the server?"**

Four things, in `xml.py`: a byte limit before parsing (10 MiB default, the API applies a
stricter one); an lxml parser with `resolve_entities=False`, `no_network=True`,
`load_dtd=False` and `huge_tree=False`; outright rejection of any document with a DOCTYPE
(invoices never need one, and it is the entry point for XXE and entity expansion attacks —
the tests include an XXE and a "billion laughs" prolog); and `str` arguments being treated as
paths only, so user-controlled text can never be parsed by accident through the path branch.
Everything after that works on an in-memory tree with no I/O.

## The one concept to explain unaided

**Semantic model vs. syntax binding vs. CIUS** — that EN 16931 defines business terms, that
UBL and CII are two syntaxes those terms are bound to, that Peppol BIS and SRB-CIUS can only
*restrict* the core, and therefore why one `Invoice` model with BT-named fields plus one
`build_*` function per syntax is the right shape (ADR-0003, learning note 02).

## Supporting facts worth remembering

- Schema-mandatory in UBL: `cbc:ID`, `cbc:IssueDate`, both parties, `PayableAmount`, ≥ 1 line
  with `cbc:ID`, `cbc:LineExtensionAmount`, `cac:Item`. Everything else is optional in XSD.
- Credit note differences: `CreditNoteLine`, `CreditedQuantity`, `CreditNoteTypeCode`, BT-9 on
  `PaymentMeans/PaymentDueDate`.
- Two `cac:TaxTotal` elements are legal: one in the document currency (BT-110 + BG-23), one
  in the VAT accounting currency (BT-111, no breakdown). The model picks the document-currency
  one for `vat_breakdown`.
- All 29 official CEN and OpenPeppol examples parse in ~150 ms total (≈ 5 ms each).
