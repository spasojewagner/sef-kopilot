# M1 — `feat/core-srb-cius-vat-rules`

## Three questions a senior engineer would ask

**1. "An exemption code from another category is fatal, an unknown one only a warning. Why
the difference?"**

Because the evidence differs. A code the Ministry lists under category O, used on a Z
breakdown, contradicts the list itself: the reason given does not fit the category. A code in
no list may be a typo, but it may also be newer than our copy: the list is dated
(1 September 2024), and SEF keeps its own, which it can extend without a new PDF. Blocking an
invoice on a code SEF might know would be a false fatal, so it is a warning until the SEF
demo environment (M5) shows how SEF treats unknown codes.

**2. "The specification writes AE20 and AE10. Why does your rule reject `AE20` as a
code?"**

The same note says a VAT category is the code (BT-118) *and* the rate (BT-119) together, and
spells that out for S: "S comprises S10 and S20, the rate is entered in BT-119". AE20 follows
the same pattern, and BT-118 is coded with UNCL 5305, where `AE20` does not exist. So the rule
expects `AE` with the rate 20 and, when it sees `AE20`, says exactly that. The reading is
recorded in the rule; if SEF disagrees, the demo environment will show it.

**3. "EN 16931 gives reverse charge the rate 0 (BR-AE-05); SRB-021 demands 20 or 10. Which
one is right?"**

For a SEF invoice, SRB-CIUS: Serbia uses AE to say "the recipient owes VAT at 20 %". Both
layers report on their own (`layer = "schematron"` vs. `"srb-cius"`), so the conflict is
visible rather than hidden, and the SRB profile of the pipeline sets BR-AE-05 to BR-AE-08
aside with this reason — together with BR-Z-10 and BR-S-10, which forbid the Serbian codes on
Z and S. We measured those conflicts on synthetic variants before writing the list.

## The one concept to explain unaided

**A national code list as data with provenance.** The Ministry's list is transcribed into
`einvoice_core.srb.vat` with its own keys (S20, S10, AE20, AE10, Z … N), its date and the
SHA-256 of the PDF it came from. Tests pin what can be checked locally — 124 codes, their
form, which keys share codes — while its authority is checked where it lives: against the
SEF demo environment in M5. When the Ministry issues a new list, the change is one data diff
that a reviewer can compare with the new document.

## Supporting facts worth remembering

- Categories: S (standard), Z (exempt with deduction), E (exempt without deduction), AE
  (reverse charge), R (excluded, Article 6 ZPDV), O and OE (not subject to VAT), SS (special
  procedures), N (annulment). Rates: 20 % and 10 %.
- The list's AE20 has one code more than AE10: `PDV-RS-36b-6` (investment gold). S has only
  `PDV-RS-OBJ` (first transfer of newly built buildings).
- The Ministry's PDF writes "АЕ" in Cyrillic; SRB-020 recognises a Cyrillic code and says so.
- Only the breakdown in the invoice currency counts as BG-23; the RSD copy of a
  foreign-currency invoice (SRB-CIUS 1.4) is checked for valid categories and rates only.
- 24 rules take 0.8–1.2 ms per invoice.
