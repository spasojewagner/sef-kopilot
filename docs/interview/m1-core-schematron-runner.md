# M1 — `feat/core-schematron-runner`

## Three questions a senior engineer would ask

**1. "OpenPeppol publishes no XSLT. How do you know your compiled Peppol rules behave like
theirs?"**

By measuring the compiler on a rule set where the official answer is known. CEN publishes
both the EN 16931 Schematron and the XSLT built from it. We compile CEN's flattened Schematron
of the same release with our pipeline and require it to report exactly what CEN's XSLT
reports — the same rule ids, severities, locations and messages — on all 1 131 documents of
CEN's own unit tests. It does. The Peppol rules go through the same pipeline (the ISO
reference implementation, pinned by commit, the lineage CEN's XSLT was generated with), and
on top of that all 340 Peppol unit tests and all ten Peppol examples pass. The rules
themselves are never edited.

**2. "Why not just run a Java validator? phive exists."**

Because it would put a JVM service next to every deployment — the CLI, the API, the
self-hosted container — and an HTTP hop in front of every validation, on free-tier hosts with
little memory. `saxonche` is the same Saxon engine as a Python wheel: in process, ~3 ms per
rule set for a typical invoice, nothing to operate. The equivalence and conformance tests are
what give us confidence that "in process" does not mean "different results".

**3. "Saxon behind a multi-threaded web server — is that safe?"**

There is one processor per process and every stylesheet is compiled once. A compiled
executable carries per-call state (the global context item, parameters), so transforms run
under one lock. At ~3 ms per transform that is a few hundred validations per second per
process, far above the expected load; `PyXsltExecutable.clone()` per thread is the documented
next step if it ever is not. A test runs 64 validations of 16 different documents from eight
threads and checks that each answer belongs to its own document.

## The one concept to explain unaided

**How a Schematron rule becomes a located violation.** A rule has a *context* (an XPath that
selects nodes) and *assertions* (XPath tests on each selected node). The `.sch` file is
compiled to XSLT; the XSLT is applied to the invoice and writes an SVRL report with one
`failed-assert` per failing node — rule id, flag, message and the node's path in a verbose
"full path" notation. We turn that path back into a canonical XPath by resolving it step by
step against the document, or say `null` when that is not certain. The location is the rule's
*context*: BR-CO-15 points at the invoice element, not at the wrong total, which is why the
explainer must name the business terms.

## Supporting facts worth remembering

- Rule sets: `en16931` (CEN XSLT, validation-1.3.17), `en16931-peppol` (the 1.3.16 copy Peppol
  BIS 3.0.21 bundles) and `peppol` (`PEPPOL-EN16931-UBL.sch`, 166 assertions). A Peppol invoice
  needs both Peppol sets; an SRB invoice needs `en16931` plus the SRB-CIUS rules (next branch).
- Compiler parameters: `allow-foreign=true` (Peppol defines XSLT functions like `u:mod11` inside
  the Schematron), `generate-fired-rule=false` (smaller reports).
- Cache: `third_party/_compiled/<rule set>-<digest>.xslt`, digest over the compiler, its
  parameters and the source's directory tree; written atomically and world-readable.
- Numbers: first use 0.3–0.9 s per rule set; validation 2.5–3.5 ms per rule set for a 5–10 KB
  invoice; 643 conformance tests in ~11 s. The unflattened EN 16931 source takes ~80 s to
  compile because of abstract-pattern expansion — the reason the flattened files exist.
- Found on the way: the synthetic credit note had two different payment means codes
  (UBL-SR-47, fatal) and a UBL extension (UBL-CR-001, warning); both fixed, with the parser
  coverage moved to focused tests.
