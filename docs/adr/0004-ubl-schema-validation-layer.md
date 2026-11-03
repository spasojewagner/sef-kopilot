# 4. UBL 2.1 schema validation: official schemas, confined loading, located violations

- Status: accepted
- Date: 2026-11-03
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-xsd-validation`

## Context and problem statement

The first wall of the deterministic validator (ADR-0002) is XML Schema validation: SEF and
every Peppol access point reject a UBL document that is not valid against the UBL 2.1 schemas
before any business rule is evaluated. Four questions had to be answered: which schema files,
obtained how; how to load them safely; how to turn libxml2's errors into the shared violation
model with a location the rest of the system can use; and how the layer behaves under load.

## Decision drivers

- The schemas must be the official ones, byte for byte, and verifiably so.
- Loading schemas must not depend on the network or on files outside the pinned set.
- Every violation needs a location in the canonical XPath form used by the parser, the
  explainer and the repairer (ADR-0003), and a message a person can read.
- The API will validate concurrently and must not be exhausted by a crafted document.
- Budget (brief §5): validate a typical invoice in < 500 ms warm, for all layers together.

## Considered options

1. **Official OASIS `UBL-2.1.zip`, pinned by SHA-256, fetched like the other rule sets;
   libxml2 via lxml; errors mapped to canonical XPaths** — chosen.
2. Vendor the schema files into the repository.
3. Take the schemas from a third-party repackaging (a Java library on Maven Central, a GitHub
   mirror).
4. Skip XSD and rely on the Schematron rule sets alone.

## Decision outcome

Option 1. Concretely:

- **Source.** `https://docs.oasis-open.org/ubl/os-UBL-2.1/UBL-2.1.zip`, the package the
  EN 16931 artefacts name, pinned in `third_party/manifest.json` by its SHA-256. The fetcher
  gained an *archive* source kind for it (streamed download, size limit, digest check,
  extraction of listed paths only, refusal of member paths that could escape). Only the
  Invoice and CreditNote schemas, the common schemas they import and `UBL-2.1.html` (which
  carries the OASIS notices) are extracted. The complete schemas in `xsd/` are used rather
  than the annotation-free run-time copies in `xsdrt/`: both validate identically, compile
  time differs by ~30 ms, and the annotated files are the normative ones.
- **Confined loading.** Schemas are parsed without network access, entity expansion or DTD
  loading, and every `xsd:import`/`xsd:include` goes through a resolver that only returns
  files inside the schema directory and raises for anything else. The UBL copy of the W3C
  XML Signature schema keeps an internal DTD subset (OASIS removed its external identifiers);
  it is ignored because no DTD is loaded.
- **One rule id, a detail code.** Every schema violation has `rule_id = "XSD"` — for the
  explainer and the evaluation harness there is one rule, "the document must be valid against
  UBL 2.1" — and `code` carries libxml2's error type (`SCHEMAV_ELEMENT_CONTENT`,
  `SCHEMAV_CVC_DATATYPE_VALID_1_2_1`, `SCHEMAV_CVC_COMPLEX_TYPE_4`, …) to choose an
  explanation template. A document that is neither Invoice nor CreditNote gets one violation
  with code `UNSUPPORTED_DOCUMENT`.
- **Locations.** libxml2 reports a path in the document's own prefixes (`/*/cac:InvoiceLine[2]/
  cbc:LineExtensionAmount`). The path is evaluated against the tree with the prefixes the
  document binds unambiguously; the result is accepted only if it is exactly one element and
  its name equals the one in the message, then rendered with `canonical_xpath`. An existing
  attribute with an invalid value is addressed as `…/@attribute`. When the location cannot be
  established with certainty, `xpath` is `null` — never a guess.
- **Readable messages.** `{urn:oasis:…:CommonBasicComponents-2}IssueDate` becomes
  `cbc:IssueDate`; namespaces outside UBL keep Clark notation.
- **Operation.** `default_validator()` compiles both schemas once per process (~150 ms);
  validation takes ~0.2 ms for a typical invoice and ~20 ms for one carrying a large
  attachment. Validation runs under a lock because lxml stores the error log on the schema
  object. At most 500 violations are returned, followed by a truncation notice.

### Consequences

Good:

- Schema validity is decided by the official schemas with a verifiable provenance, and a
  changed upstream file fails the fetch instead of silently changing behaviour.
- Violations from this layer have the same shape and the same location language as every
  other layer, so the UI, the explainer and the repairer need no XSD-specific handling.
- The layer is fast enough to run on every keystroke-sized change in the repair loop.

Bad / accepted:

- libxml2 stops validating an element's content after its first content-model error, so one
  run does not list every structural problem; fixing one can reveal the next. The repair loop
  re-validates after each change, and the UI says that more errors may appear.
- libxml2 messages are English and technical; turning them into accountant-friendly text is
  the explainer's job (M2), keyed by `code`.
- CI downloads 55 MB from OASIS whenever the rule-set cache misses (manifest changed or cache
  expired); the cache key is the manifest hash, so this is rare.
- Writing this layer surfaced a mapping bug in the parser (BT-11 on credit notes) and an
  invalid synthetic fixture; both were fixed in the same branch, in their own commit.

## Pros and cons of the options

### Vendor the schemas

- Good: no download; works offline from the first clone.
- Bad: OASIS terms forbid modification and require the notices to travel with the files,
  mixing their terms into the Apache-2.0 tree; 3 MB of generated XML in every clone and diff.

### Third-party repackaging

- Good: reachable from more networks, smaller downloads.
- Bad: provenance is one step removed from the publisher; a repackager can lag, patch or
  rename files. The digest pin would still prove *consistency*, not *authenticity*.

### Schematron only

- Good: one fewer layer.
- Bad: the EN 16931 and Peppol Schematron assume a schema-valid document and say nothing about
  element order or datatypes; SEF rejects schema-invalid documents first, so the product has
  to explain those rejections too.
