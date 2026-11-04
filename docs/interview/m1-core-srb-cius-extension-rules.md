# M1 — `feat/core-srb-cius-extension-rules`

## Three questions a senior engineer would ask

**1. "The extension lives outside the UBL schema. How do your rules cope with garbage
there?"**

UBL declares the content of `ext:ExtensionContent` as "any element, not validated", so a
schema-valid invoice can carry `8.400,00` or `NaN` where an amount belongs. The extension
helper therefore parses amounts defensively — `amount()` returns `None` for anything that is
not a finite decimal — and a rule reports "must be an amount; found '8.400,00'" instead of
raising. The arithmetic itself is exact `Decimal` subtraction, as every arithmetic check of the
validator is.

**2. "The specification and the Ministry's examples spell the advances element differently.
Which one do you check?"**

Both: SRB-CIUS writes `InvoicedPrepaymentAmmount`, the examples `InvoicedPrepaymentAmount`.
Without the extension's own XSD we cannot know which one SEF's schema accepts, and a rule must
not overlook an advance because one of the two documents has a typo. Reading both is safe
because the rules check what the element says, not its name; validating the name belongs to
the extension schema, which can be added when SEF provides it (M5).

**3. "Why check the reduced total with VAT (BT-E13) but not the reduced total without VAT
(BT-E10)?"**

Because the specification states a formula only for BT-E13: total with VAT minus paid amount.
For BT-E10 it gives none, and the Ministry's examples put the unreduced amount there (1 500
after an advance of 1 500). Writing a formula the text does not state would invent a
requirement — exactly what a rule may not do (ADR-0006).

## The one concept to explain unaided

**Why final invoices need the Serbian extension.** EN 16931 can say that something was paid
in advance (BT-113, paid amount) but not *which* advance invoices were settled, with which VAT
per category, and what remains taxable. Serbian VAT law needs exactly that, so SRB-CIUS adds it
in `SrbDtExt`: the advances used (BG-E1) with their VAT breakdown, and the totals reduced by
them, tied together by BT-E13 = BT-112 − BT-113. An invoice that uses these elements is no
longer just *compliant* with EN 16931 but *conformant* through an extension, which is what the
longer specification identifier says.

## Supporting facts worth remembering

- 29 SRB rules now; 0.8–1.2 ms per invoice (2–2.6 ms with the model).
- On the official examples: SRB-025 to SRB-028 hold on both final invoices and both
  foreign-currency invoices; SRB-029 warns on the two final invoices, which use the extension
  under the short identifier.
- In a foreign-currency invoice every VAT breakdown appears twice: in the invoice currency and
  in RSD — the main one (BG-23 and BG-E7) and, on a final invoice, the advances (BG-E2, BG-E5)
  and the reduced totals (BG-E3, BG-E6).
- `sbt` is now a canonical prefix, so violations inside the extension get the same XPath
  whatever prefix the document declares.
