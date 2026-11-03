# M1 — `feat/core-xsd-validation`

## Three questions a senior engineer would ask

**1. "libxml2 already gives you a path for each error. Why not just return it?"**

Because it is in the document's own prefixes and sometimes not even that: for elements in a
default namespace libxml2 prints `*`, so the same place reads `/*/cac:InvoiceLine[2]/cbc:…` in
one document and `/ubl:Invoice/…` in another. The rest of the system — explanations, the UI,
patches — speaks canonical XPath (ADR-0003). So the path is *evaluated* against the tree with
the prefixes the document binds unambiguously, and the result is accepted only if it is
exactly one element whose name matches the one in the message; then it is rendered with
`canonical_xpath`. If any of that fails, `xpath` is `null`. A wrong location is worse than none:
a patch would be applied to the wrong element.

**2. "How do you know loading the schemas never touches the network?"**

Two independent guards. The parser runs with `no_network=True`, `resolve_entities=False` and
`load_dtd=False`; and every `xsd:import` or `xsd:include` goes through a resolver that returns
only files inside the schema directory and raises for any URL or outside path. Tests build a
schema that imports `http://…`, `https://…` and `../../outside.xsd` and check each is refused.
The schemas themselves come from a pinned archive whose SHA-256 is checked before extraction.

**3. "Is the validator safe to call from many request handlers at once?"**

Yes, with one deliberate lock. The compiled schemas are immutable and shared (`default_validator`
is cached per process), but lxml stores the error log of the last validation on the schema
object, so validate-and-read-the-log runs under a `threading.Lock`. A validation takes a fraction
of a millisecond, so the lock costs nothing measurable; a test runs 80 validations from eight
threads and checks every result against the sequential one. The violation list is capped at 500
entries so a crafted document cannot produce an unbounded response.

## The one concept to explain unaided

**What XML Schema validation can and cannot tell you about an invoice** — it checks syntax:
element names, order, cardinality, datatypes and required attributes (`currencyID` on every
amount); it says nothing about whether totals add up, whether a VAT category matches its rate,
or whether a Serbian buyer has a valid PIB. That is why it is the *first* layer and why
Schematron, the SRB-CIUS rules and the Python arithmetic follow. And libxml2 stops checking an
element's content after the first content-model error, so one run may not show every structural
problem — the reason the repair loop always re-validates.

## Supporting facts worth remembering

- Source: `UBL-2.1.zip` from docs.oasis-open.org, SHA-256 `60b80d76…f86ed`, 55 MB, 1 715 members;
  17 files extracted.
- Compile both schemas ≈ 150 ms once; validate a typical invoice ≈ 0.2 ms; a 1 MB invoice with an
  attachment ≈ 20 ms.
- Common codes: `SCHEMAV_ELEMENT_CONTENT` (unexpected or missing element),
  `SCHEMAV_CVC_DATATYPE_VALID_1_2_1` (value of the wrong type, e.g. `05.10.2026` as a date),
  `SCHEMAV_CVC_COMPLEX_TYPE_4` (required attribute missing).
- UBL 2.1 credit notes have no `cac:ProjectReference`; BT-11 travels as an
  `AdditionalDocumentReference` with type code 50 — found because the synthetic credit note
  failed schema validation.
