# 7. EN 16931 calculation rules: recomputed in Python with CEN's semantics, proven equivalent

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-arithmetic-rules`

## Context and problem statement

The brief requires the EN 16931 calculation rules (`BR-CO-*`) to be checked in Python, never
by a language model. The Schematron layer already runs them as CEN publishes them (ADR-0005),
so we had to decide why a second implementation is worth having, with which semantics, and how
to keep two implementations of the same rule from ever disagreeing.

## Decision drivers

- An explanation of a wrong total must show the numbers — expected, found — and those must be
  computed by code (ADR-0002). SVRL reports carry the rule text, not the values.
- Scope. CEN's rule contexts are relative (`cac:LegalMonetaryTotal`, `cac:TaxTotal/
  cac:TaxSubtotal`), so they also match the totals that the Serbian extension repeats inside
  `ext:UBLExtensions`: on the Ministry's two final-invoice examples BR-12, BR-CO-10 and
  BR-CO-13 fire on `sbt:ReducedTotals/cac:LegalMonetaryTotal`, which is not BG-22.
- The repair loop re-validates often; amounts should be re-checkable without an XSLT run.
- Fidelity: a rule id must mean one thing. Two layers may not judge the same rule differently.

## Considered options

1. **Python on the typed model, with CEN's exact semantics, and a differential test against
   CEN's XSLT** — chosen.
2. CEN's XSLT only, with the values recovered from the document for each SVRL failure.
3. Python with "textbook" arithmetic: exact equality everywhere, banker's rounding.
4. Edit CEN's rule contexts so that they do not reach into extensions.

## Decision outcome

Option 1. Concretely:

- **API.** `einvoice_core.arithmetic.validate_arithmetic(tree, invoice=None)` returns
  violations with `layer = "arithmetic"` and CEN's rule ids `BR-CO-10` to `BR-CO-17`. The
  message is CEN's statement followed by the computation: `…: expected 12000.00, found
  12000.01.` The XPath points at the amount (`…/cac:LegalMonetaryTotal/cbc:LineExtensionAmount`),
  or at its group when the amount is missing.
- **Semantics are CEN's, case by case.** Amounts are compared after CEN's
  `round(x * 10 * 10) div 100`, with XPath's `round()` — halves go towards positive infinity, so
  `-0.125` becomes `-0.12` — and shown with two decimals. BR-CO-17 accepts a VAT amount within
  one currency unit of the computed one and requires a VAT amount that rounds to 0 when the rate
  rounds to 0 or there is no VAT rate (a tax scheme other than VAT). The presence cases are
  CEN's too: a missing allowance total is fine only without allowances (BR-CO-11), a missing
  charge or allowance total selects one of BR-CO-13's four formulas, a paid amount and a
  rounding amount select one of BR-CO-16's four, BR-CO-15 needs exactly one VAT total in the
  invoice currency and checks nothing without an invoice currency code.
- **Scope is the model's.** The document totals (BG-22), the VAT totals that are children of
  the document element, the document level allowances and charges, the invoice lines — never
  the copies inside the Serbian extension. How a profile combines this layer with CEN's
  arithmetic rules is the validation pipeline's decision (`feat/core-cli`); for SRB, CEN's
  arithmetic rules misfire on the extension and this layer is the one to keep.
- **Proof.** A differential test generates the money part of an invoice with Hypothesis —
  lines, allowances, charges, VAT totals and document totals, consistent or with one amount
  changed by a few cents or a unit or left out, with two or three decimals so that rounding is
  exercised, VAT, ` vat ` or another tax scheme, a second VAT total in the same or another
  currency — and requires both layers to report the same BR-CO rules the same number of times.
  It runs 400 examples in CI; a local run of 1 500 found no disagreement while every rule fired
  between 89 and 581 times. Unit tests cover each rule's cases and messages (100 % branches).
  The 17 Ministry examples and our synthetic fixtures produce no arithmetic violation.

### Measured (container, Python 3.12)

- 6–10 µs per invoice once the model is built; building the model takes 1–1.5 ms.

### Consequences

Good:

- Every arithmetic violation carries the numbers a person needs; the explainer copies them.
- SRB final invoices are judged on their real totals, not on the extension's copies.
- Negligible cost; usable in the repair loop without Saxon.

Bad / accepted:

- Two implementations of the same rules. When CEN changes one, the differential test fails on
  the rule-set upgrade and the Python version follows; until then the upgrade does not merge.
- CEN's tolerance of one currency unit in BR-CO-17 is kept, although stricter arithmetic would
  catch more errors: a stricter rule under the same id would contradict CEN. A stricter check
  would need a rule id of its own.
- Only BR-CO-10 to BR-CO-17. The per-category taxable amounts (BR-S-08, BR-Z-08, …) stay in
  the Schematron layer for now.

## Pros and cons of the options

### CEN's XSLT only

- Good: one implementation, nothing to keep in step.
- Bad: the values for the explanation would be recomputed somewhere anyway, without a guarantee
  that they match the verdict; the extension problem stays.

### Textbook arithmetic

- Good: simpler code, stricter checks.
- Bad: the same rule id would mean different things in two layers; documents CEN accepts would
  fail here.

### Edited CEN contexts

- Bad: third-party rule sets are never modified (ADR-0005).
