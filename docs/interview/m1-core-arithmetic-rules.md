# M1 — `feat/core-arithmetic-rules`

## Three questions a senior engineer would ask

**1. "CEN's Schematron already checks BR-CO-10 to BR-CO-17. Why implement them twice?"**

For three things the XSLT cannot give. The numbers: an SVRL failure says which rule broke,
not what the total should have been, and the explainer may never compute amounts (ADR-0002) —
this layer puts "expected 12000.00, found 12000.01" in the violation. The scope: CEN's rule
contexts are relative, so they also judge the totals the Serbian extension repeats; on the
Ministry's final-invoice examples BR-CO-10 and BR-CO-13 fire on `sbt:ReducedTotals`, which is
not the invoice's total. The model-based layer reads BG-22 only. And speed: 6–10 µs per invoice,
cheap enough for every step of the repair loop.

**2. "Two implementations of one rule — how do you know they never disagree?"**

By a differential test. Hypothesis generates the money part of an invoice — lines, allowances,
charges, VAT totals, document totals — consistent or with one amount nudged by a cent, half a
cent or a unit, or left out, with three decimals to exercise rounding, odd tax-scheme spellings
and duplicate VAT totals; both layers judge the same document and must report the same rules
the same number of times. 400 examples run in CI; 1 500 locally found no disagreement, and
every rule fired at least 89 times, so the test is not vacuous.

**3. "BR-CO-17 accepts a VAT amount one dinar off. Why keep such a loose rule?"**

Because it is CEN's rule, and the id `BR-CO-17` must mean what CEN means: a stricter check
under the same id would reject invoices CEN accepts, and two layers would contradict each
other. If we want stricter arithmetic, it gets a rule id of its own and its own justification.
The same goes for XPath's rounding of halves towards positive infinity (`-0.125` → `-0.12`),
which we reproduce rather than "correct".

## The one concept to explain unaided

**Differential testing.** When you re-implement something that already has a trusted
implementation, you do not test the new one against hand-written expectations alone — you
generate many inputs and require both implementations to agree on every one. The trusted one
becomes the oracle; property-based generation finds the corners (rounding halves, missing
elements, negative amounts) that hand-written examples miss; and the agreement rate is a
number you can report, here 1 500 out of 1 500.

## Supporting facts worth remembering

- Rules: BR-CO-10 (lines), 11 (allowances), 12 (charges), 13 (total without VAT), 14 (VAT
  total), 15 (total with VAT), 16 (amount due), 17 (VAT per category).
- `cents(x)` = CEN's `round(x * 10 * 10) div 100`; XPath `round()` takes halves towards +∞.
- BR-CO-13 and BR-CO-16 have four formulas each, chosen by which optional amounts are present;
  BR-CO-15 needs exactly one VAT total in the invoice currency.
- All 17 Ministry examples and the synthetic fixtures: no arithmetic violation.
