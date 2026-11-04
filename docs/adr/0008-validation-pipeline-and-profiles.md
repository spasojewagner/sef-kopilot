# 8. The validation pipeline: fixed layer order, profiles that set aside published rules with reasons

- Status: accepted; amended by [0014](0014-hostile-documents-in-the-core.md), under which
  the set-aside list is cut at the violation limit too, and the rest counted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M1, branch `feat/core-validation-pipeline`

## Context and problem statement

The validator has four layers — UBL 2.1 schemas (ADR-0004), Schematron (ADR-0005), SRB-CIUS
(ADR-0006), calculation rules (ADR-0007) — and the CLI, the API and the MCP server each need one
verdict per document and profile. Three questions had to be settled. In which order do the
layers run, and when does one stop the next? What does a profile contain? And what do we do
with the EN 16931 rules that SEF's own documents break: run against the 17 example documents
the Ministry publishes, CEN's rules reject eight of them — Serbian VAT categories and exemption
codes, category O beside taxed supplies, reverse charge at a rate, and the totals of the
Serbian extension and of the RSD copy of the VAT breakdown, which CEN's relative rule contexts
also reach.

## Decision drivers

- A correct Serbian invoice must come out valid under the SEF profile; anything else blocks the
  product's main use (nothing leaves without a green validator).
- No decision may be silent: when a published rule is not applied, the report says which, why,
  and what checks the matter instead.
- Published rule sets are never modified (ADR-0005).
- One call that never raises for a bad document: a bad document is a report.
- Budget (brief §5): < 500 ms warm for all layers.

## Considered options

1. **One pipeline with a fixed layer order and profiles as data; a profile's set-asides are
   rule ids plus an optional condition, each with a reason, and set-aside violations stay in
   the report** — chosen.
2. Run every rule set and let the reader interpret the result.
3. Set aside by rule id only.
4. A Serbian fork of CEN's Schematron with the conflicting rules removed or rewritten.
5. Drop the set-aside violations from the report.

## Decision outcome

Option 1. Concretely:

- **API.** `einvoice_core.pipeline.validate(source, profile="srb", *, max_violations=1000)`
  returns a frozen `ValidationReport`: `profile`, `valid` (no fatal violation), `violations`,
  `set_aside` (each the violation, the reason and the rules that replace it), `layers` (for
  each layer whether it ran, how many violations it kept, and the rule sets it ran or why it did
  not) and `omitted`. It raises only `ValueError` for an unknown profile.
- **Order and stops.** `xml` → `xsd` → `schematron` → `srb-cius` → `arithmetic`. A document
  that cannot be read (not well-formed, a DOCTYPE, too large) gets one `XML`/`UNREADABLE`
  violation and nothing else runs. The business rules run only on a schema-valid document,
  because they assume one (`xs:decimal('12,50')` is an XSLT error, not a failed assertion). The
  SRB and calculation rules need the typed model; should a schema-valid document not build one,
  an `XML`/`MODEL` violation says so and those two layers do not run. The violation model gains
  the layer `xml` for these two cases.
- **Profiles.** `srb`: CEN's `en16931`, the SRB-CIUS rules and the calculation rules. `en16931`:
  `en16931` and the calculation rules. `peppol`: `en16931-peppol`, `peppol` and the calculation
  rules.
- **Set-asides.** Every profile hands CEN's BR-CO-10 to BR-CO-17 to the arithmetic layer,
  which states the amounts and is proven equivalent (ADR-0007). The SRB profile also sets aside:

  | EN 16931 rules | Reason | Checked instead by |
  | --- | --- | --- |
  | BR-CL-17, BR-CL-18 | SRB-CIUS allows R, OE, SS, N outside EN 16931's UNCL 5305 subset | SRB-020 |
  | BR-CL-22 | exemption codes come from the Ministry's list, not VATEX | SRB-022, SRB-023 |
  | BR-AE-05 to 07, BR-AE-09 | SEF's reverse charge states the rate the recipient owes and the VAT at it | SRB-021 |
  | BR-Z-10 | a Serbian Z breakdown states one of the Ministry's codes | SRB-022, SRB-024 |
  | BR-S-10, only with `PDV-RS-OBJ` | the list gives S that code for newly built buildings | SRB-022 |
  | BR-O-02 to 04 | SRB-CIUS requires the seller's and buyer's VAT identifiers | SRB-007 |
  | BR-O-05 to 07 | SEF writes the rate 0 for O, as the Ministry's examples do | — |
  | BR-O-11 to 14 | O appears beside taxed supplies, as in the Ministry's examples | — |
  | UBL-CR-001 | SRB-CIUS defines its own extension | SRB-029 |
  | any rule, located in `ext:UBLExtensions` | EN 16931 does not know the Serbian extension | SRB-025 to SRB-028 |
  | any rule, located in a VAT total in another currency | the RSD copy (BG-E7) is not BG-23 | SRB-028 |

  The last two are conditions on the location, so the same EN 16931 rules keep judging the
  invoice's own totals and breakdown. Set-aside violations are listed apart, never counted
  towards validity, never dropped.
- **Limit.** At most `max_violations` are listed; validity is computed on all of them, and the
  rest are counted in `omitted`.

### Checked against the official examples

With the 17 Ministry examples as published, the SRB profile reports their placeholder PIBs
(SRB-009) and nothing else fatal except two genuine problems. With the placeholders given valid
check digits, 15 of the 17 are valid, with warnings only (SRB-013, SRB-017, SRB-023, SRB-029);
`faktura-sa-popustom.xml` has an allowance without a reason (BR-33, BR-CO-21 — a real EN 16931
error that SRB-CIUS does not relax) and `faktura-sa-prilogom.xml` is not schema-valid. Every
EN 16931 report that the profile set aside on them is listed in its report with the reason
above.

### Measured (container, Python 3.12)

- Whole pipeline, warm: 6–7 ms per invoice for `srb` and `en16931`, ~12 ms for `peppol` (two
  rule sets). First use in a process: 350–440 ms (schemas and stylesheets).

### Consequences

Good:

- One call for the CLI, the API and the MCP server, with the same verdict everywhere.
- SEF's own examples come out the way SEF accepts them, and every exception is visible with its
  reason — the explainer can say "EN 16931 says X, but for SEF it does not apply because Y".
- Profiles are data: a new profile, or a changed set-aside, is a reviewable diff with tests.

Bad / accepted:

- The set-aside list is our reading and is maintained by hand; it must be revisited whenever
  EN 16931, the Ministry's list or SRB-CIUS changes. Three entries rest on the Ministry's
  examples rather than on the text (BR-O-05 to 07, BR-O-11 to 14, BR-AE-09) and are to be
  confirmed against the SEF demo environment (M5).
- Conditions on locations depend on the XPaths the Schematron layer reports; a rule-set upgrade
  that changes a rule's context could move a violation in or out of a condition. The tests that
  pin each set-aside catch it.

## Pros and cons of the options

### Run everything

- Bad: every correct Serbian invoice with an exemption code would be "invalid"; the reader would
  have to know which EN 16931 failures to ignore.

### Rule ids only

- Bad: BR-S-08 must still judge the invoice's breakdown and only not its RSD copy; BR-12 must
  still require BT-106 of the invoice and only not of the extension's reduced totals.

### A Serbian fork of the Schematron

- Bad: we would maintain a modified third-party rule set and could no longer claim to run
  CEN's rules as published.

### Dropping set-aside violations

- Bad: decisions disappear from the report; nobody could check them.
