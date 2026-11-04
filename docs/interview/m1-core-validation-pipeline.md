# M1 — `feat/core-validation-pipeline`

## Three questions a senior engineer would ask

**1. "Your SRB profile switches off EN 16931 rules. Isn't that cheating the standard?"**

It is the opposite of hiding them. SEF's own documents break those rules because SRB-CIUS
widens EN 16931: Serbian VAT categories and `PDV-RS` exemption codes, reverse charge at a rate,
category O beside taxed supplies, and an extension whose totals CEN's relative rule contexts
also judge. Each set-aside is data with a reason and the rule that checks the matter instead
(`BR-CL-22` → SRB-022/023), and every set-aside violation stays in the report, apart. The
evidence: with valid check digits for their placeholder PIBs, 15 of the Ministry's 17 examples
pass the SRB profile with warnings only, and the remaining two have real problems.

**2. "Why not set aside BR-S-08 outright instead of this location logic?"**

Because BR-S-08 is right about the invoice's own breakdown and wrong only about the RSD copy of
a foreign-currency invoice, which EN 16931 does not know. Setting the rule aside by id would stop
checking every Serbian invoice's per-category taxable amounts. The condition — "located in a VAT
total in another currency than the invoice's" — sets aside exactly the misfire. The same goes for
BR-12 inside the extension's reduced totals.

**3. "Why does the pipeline stop after a schema error instead of reporting everything?"**

Because the business rules assume a schema-valid document: CEN's XSLT casts `xs:decimal('12,50')`
and raises instead of failing an assertion, and our typed model cannot be built from a broken
structure. Running them anyway would turn one root cause into dozens of misleading violations.
The report says which layers did not run and why, so the user fixes the schema errors first.

## The one concept to explain unaided

**A profile is a reading of the standards, written down as data.** `srb` says: run CEN's EN 16931
rules, the SRB-CIUS rules and the calculation rules; do not apply these EN 16931 rules, for these
reasons, checked instead by those rules. Because the reading is data — not scattered `if`s — it
can be reviewed as a table (ADR-0008), tested entry by entry, shown to the user next to the
verdict, and revisited when the evidence changes (SEF demo, M5).

## Supporting facts worth remembering

- Order: `xml` → `xsd` → `schematron` → `srb-cius` → `arithmetic`; `validate()` never raises for
  a bad document, only `ValueError` for an unknown profile.
- Every profile hands BR-CO-10 to BR-CO-17 to the arithmetic layer (ADR-0007).
- Three SRB set-asides rest on the Ministry's examples rather than the text (BR-O-05 to 07,
  BR-O-11 to 14, BR-AE-09) and are to be confirmed in M5.
- Warm: 6–7 ms per invoice for `srb` and `en16931`, ~12 ms for `peppol`; first use 350–440 ms.
