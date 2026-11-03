# M1 — `feat/core-srb-cius-rules`

## Three questions a senior engineer would ask

**1. "SRB-CIUS has no rule identifiers and no Schematron. How do you know your rules say what
the specification says?"**

Each rule implements one note of the specification's table and cites it (`1.3, Table 1,
BT-31`), with the document version pinned in a source registry; a test refuses a rule without a
citation. Each rule has its own test module with a document that satisfies it and edits that
break it, asserting the message and the XPath. The tightened cardinalities were read from the
PDF's drawing layer (the struck-through values), not from memory. And the rules were run on
all 17 example documents the Ministry publishes: rules 001 to 008 report nothing, and SRB-009
reports exactly the placeholder PIBs. Where the text and the examples disagree, the policy is
written down: the text decides what a rule checks, the disagreement makes it a warning.

**2. "You already run Saxon for EN 16931. Why write these rules in Python instead of
Schematron?"**

Because the notes are conditional and arithmetic: "for residents", "on advance invoices",
"when BT-8 is 35", a check digit, a code list. In Python each rule is a short, type-checked
file with its own tests, its own message and a precise location; in Schematron the same logic
becomes XPath 2.0 assertions and XSLT functions, and we would maintain a compiled stylesheet
for our own source. The price is that only a programmer can add a rule; the uniform shape —
metadata plus one `check` function — keeps that cheap.

**3. "Your validator rejects SEF's own example invoices. Isn't that a bug?"**

The SRB rules reject them for one reason only: their PIBs `123456789` and `987654321` have
the wrong check digit, so no real company can have them, and SEF would refuse them as
unregistered. That is why the check digit is a rule of its own (SRB-009): the verdict on the
examples fits in one sentence, and a real user's wrong last digit is explained as a typo. The
EN 16931 rules reject eight of the examples for a different reason — Serbia extends EN 16931's
code lists — and the SRB profile of the pipeline has to set those rules aside explicitly.

## The one concept to explain unaided

**What a CIUS is, and why a SEF validator is not "EN 16931 plus Serbian rules".** A CIUS may
only narrow EN 16931 — mandatory instead of optional, fewer codes, usage notes — so every
CIUS invoice is still an EN 16931 invoice (`#compliant#` in BT-24); new elements need an
extension (`#conformant#`). SRB-CIUS is both, and in places it also widens EN 16931: Serbian
VAT categories and `PDV-RS` exemption codes are not in EN 16931's code lists. So a correct
Serbian invoice fails `BR-CL-22`, and the SRB profile must run EN 16931 *minus* the rules the
Serbian rules replace, plus the SRB-CIUS rules.

## Supporting facts worth remembering

- Source: "Specifikacija prilagođene primene standarda EN 16931-1 …", version of 06.06.2025
  (efaktura.gov.rs). Our ids `SRB-001`…`SRB-009`; never renumbered once released.
- PIB (PIB rulebook, Article 2): an eight-digit serial from 10000001 to 99999999 plus an
  ISO 7064 MOD 11,10 check digit, which catches every single-digit substitution (a property
  test checks that). A JMBG may serve as PIB; its check digit is not defined by the rulebook,
  so only its form is checked.
- Severity policy: stated requirement → fatal; contradicted by the official examples or left
  open by the text → warning, with the evidence in the rule, until M5.
- 18 cardinalities are tightened (struck through) in the table, e.g. BT-31, BT-48, BT-34 and
  BT-49 become 1..1, BT-7 becomes 0..0.
- Nine rules take 0.3–0.4 ms per invoice; ~2 ms with building the typed model.
- One official example (`faktura-sa-prilogom.xml`) is not schema-valid: its embedded PDF is
  abbreviated with `...`.
