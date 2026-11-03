# 5. Schematron rule sets: executed as published with Saxon-HE, Peppol compiled with the ISO pipeline

- Status: accepted
- Date: 2026-11-03
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-schematron-runner`

## Context and problem statement

The second wall of the deterministic validator (ADR-0002) is the business rules of EN 16931
(about 980 assertions: `BR-*`, `BR-CO-*`, `BR-CL-*` and the UBL binding rules `UBL-*`) and of
Peppol BIS Billing 3.0 (166 assertions, `PEPPOL-*`). Both are published as Schematron with
`queryBinding="xslt2"`: the tests are XPath 2.0 and the rules need an XSLT 2.0 processor.
CEN/TC 434 also publishes a compiled XSLT for EN 16931; OpenPeppol publishes Schematron only.
We had to decide how to run the rules, how to compile the ones that have no official XSLT,
how to turn the results into the shared violation model (ADR-0002, ADR-0004), and how to prove
that what we run is what the publishers intend.

## Decision drivers

- Fidelity: an invoice must get exactly the verdict the publishers' own tooling gives it.
  The rules are never re-implemented or edited (`third_party/` is fetched, never modified).
- One runtime: the validator is a Python library that also runs in the CLI, the API and a
  self-hosted container; no second service, no network calls.
- Every violation needs the canonical XPath and the source line (ADR-0003, ADR-0004).
- Budget (brief §5): < 500 ms warm for all layers together; the API validates concurrently.
- Licences that allow redistribution of our code under Apache-2.0.

## Considered options

1. **Saxon-HE via `saxonche` in process; the official CEN XSLT as is; the Peppol Schematron
   compiled with the ISO Schematron reference pipeline, pinned by commit** — chosen.
2. lxml's `isoschematron` (libxslt).
3. A Java validator (phive / ph-schematron) as a sidecar service.
4. Compile the Peppol rules with SchXslt instead of the ISO pipeline.
5. Re-implement the rules in Python.

## Decision outcome

Option 1. Concretely:

- **Processor.** `saxonche` 13.1 (SaxonC-HE, MPL-2.0), the C/Python build of Saxon, which is
  also the XSLT 2.0 engine of the Java tooling built around these rules (ph-schematron,
  phive). One `PySaxonProcessor` per process; each stylesheet is compiled once
  (`default_validator(name)` is cached).
- **Rule sets.** `en16931` is CEN's `EN16931-UBL-validation.xslt` (validation-1.3.17).
  `en16931-peppol` is the EN 16931 Schematron in the version Peppol BIS 3.0.21 bundles
  (1.3.16), and `peppol` is `PEPPOL-EN16931-UBL.sch`; a Peppol invoice is checked with both,
  exactly as OpenPeppol specifies. Which rule sets apply to which profile (SRB-CIUS, Peppol) is
  decided by the validation pipeline, not here.
- **Compiling Schematron.** The ISO reference pipeline (`iso_dsdl_include.xsl` →
  `iso_abstract_expand.xsl` → `iso_svrl_for_xslt2.xsl`, fetched as `iso-schematron` at its
  final commit) with `allow-foreign=true` (the Peppol rules define XSLT functions such as
  `u:mod11`) and `generate-fired-rule=false` (smaller reports). This is the lineage that
  produced the official XSLT — its header reads "Created with ph-schematron version of ISO
  Schematron XSLTs" — so both rule sets write SVRL in the same conventions and one mapper
  serves both. The generated stylesheet is cached in `third_party/_compiled/`, named by a
  SHA-256 over the compiler files, the parameters and every file in the source's directory
  tree (where inclusions live). The file is written atomically and world-readable; a
  read-only directory only means compiling in memory.
- **Running.** The lxml tree is serialised and handed to Saxon as UTF-8 text, set as the
  global context item (the Peppol rules read `$profile` and similar global variables) and
  transformed under one process-wide lock, because an XSLT executable carries per-call state.
- **Violations.** Each `svrl:failed-assert` and `svrl:successful-report` becomes a violation:
  `rule_id` = `@id`, severity from `@flag` (`warning`, otherwise fatal), the normalised
  `svrl:text` as message, `layer = "schematron"`, no `code` (the rule id already selects the
  explanation). Order is report order; nothing is merged or de-duplicated, because the
  published tests count repeated failures.
- **Locations.** SVRL locations use the "full path" notation
  (`/*:Invoice[namespace-uri()='…'][1]/*:InvoiceLine[namespace-uri()='…'][2]/@currencyID`).
  The location is parsed step by step, every step is resolved against the tree, and only a
  complete match becomes a canonical XPath (plus the element's line). Anything else gives
  `xpath = null`: a namespace-qualified attribute (line kept), or a location that is not a
  path at all — the generated stylesheets write an attribute's *value* when a rule's context
  is an attribute; none of the pinned rules has such a context.
- **Failures.** `SchematronError` for a stylesheet that does not compile, a dynamic error
  while applying it (the rules assume a schema-valid document: `xs:decimal('12,50')` is an
  error, not a failed assertion, so the pipeline runs this layer only after XSD passes) and a
  report that is not SVRL. Saxon's text can quote document values, so it is never logged.
- **Proof.** Unit tests drive every branch with stylesheets written for the tests (100 %
  coverage). The conformance suite applies the rule sets to everything the publishers ship:
  all 277 CEN unit-test sets (1 131 tests) against `en16931`; all 62 Peppol unit-test sets
  (340 tests) against `peppol`; the 11 CEN and 10 Peppol example invoices; our synthetic
  fixtures, which must produce no violation at all. And the flattened EN 16931 Schematron of
  release 1.3.17, compiled by our pipeline, must report exactly what CEN's XSLT reports — same
  rule ids, severities, locations and messages — on all 1 131 CEN test documents. That is the
  evidence that compiling the Peppol rules, which have no official XSLT, is faithful.

### Measured (container, Python 3.12, SaxonC-HE 13.1)

- First use, Saxon start included: `en16931` 0.35 s; `en16931-peppol` 0.9 s without the cache,
  0.4 s with it; `peppol` 0.3 s / 0.1 s (the very first run on a fresh machine took ~5 s).
  The compiled Peppol stylesheets are 1.0 MB and 0.2 MB.
- Warm validation per rule set: 2.5–3.5 ms for a 5–10 KB invoice, ~6 ms for a 21 KB one.
- The whole conformance suite (643 tests) runs in about 11 s.

### Consequences

Good:

- Verdicts match the publishers' on every published test, and the claim is re-checked in CI
  whenever a rule set is upgraded, a one-line change in `third_party/manifest.json`.
- No JVM, no service: the same `pip`-installable wheel works in the CLI, the API and the
  container, on Linux, macOS and Windows.
- Violations from Schematron look like every other violation, with canonical XPaths.

Bad / accepted:

- `saxonche` adds a 37–39 MB native wheel and has no type information; `stubs/saxonche.pyi`
  declares the part we use. Its documentation lists an `encoding` argument for
  `transform_to_string` that version 13.1 rejects; output is decoded as UTF-8, which is what
  every stylesheet here declares.
- The ISO pipeline is archived upstream (2020). Schematron is a stable standard, the pinned
  files never change, and the equivalence test would expose a defect; SchXslt is the fallback
  if a future rule-set release needs something the skeleton cannot compile.
- Abstract-pattern expansion in the ISO pipeline is slow on large sources: the unflattened
  EN 16931 Schematron (with its includes and abstract patterns) takes ~80 s to compile. It was
  compiled once and gave identical results; the suite uses CEN's flattened file, and both CEN
  and OpenPeppol distribute flattened sources, so production never pays this cost.
- One lock serialises transforms (≈3 ms each), which caps a single process at a few hundred
  validations per second per rule set. `PyXsltExecutable.clone()` per thread is the path if
  that ever matters.
- Violations are not capped in this layer (the XSD layer caps at 500); the SVRL report is
  bounded at 64 MiB. A cap across all layers belongs to the validation pipeline.

## Pros and cons of the options

### lxml `isoschematron`

- Good: already a dependency; no native wheel to add.
- Bad: libxslt implements XSLT 1.0 only, and both rule sets require XSLT 2.0 (typed casts,
  `every … satisfies`, regular expressions). Not possible.

### Java validator as a sidecar

- Good: phive and ph-schematron are mature Java implementations built for these rule sets.
- Bad: a second runtime and a second service in every deployment, more memory on free tiers,
  and an HTTP hop for every validation; the CLI would need a JVM too.

### SchXslt

- Good: a modern, maintained Schematron compiler.
- Bad: a different implementation lineage from the one that built the official XSLT; reports
  could differ in location notation and details, and it would add a second compiler to trust.

### Re-implement the rules in Python

- Good: no XSLT at all; full control over messages and locations.
- Bad: over a thousand assertions to translate and maintain against every upstream release,
  with no guarantee of identical verdicts — the opposite of what a validator must offer.
