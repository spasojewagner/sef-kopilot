# M1 — `feat/core-srb-cius-party-rules`

## Three questions a senior engineer would ask

**1. "The specification says 1..1, and two of your rules are only warnings. Aren't you
weakening it?"**

The text makes the seller's VAT status (BT-32) and the buyer's post code (BT-53) mandatory,
but the example documents published with it omit BT-32 in all 17 and BT-53 in nine. A fatal
rule would block invoices SEF may well accept — and since nothing leaves without a green
validator, a false fatal stops real work, while a warning still tells the user what the text
requires. The policy is written down in ADR-0006, each warning names its evidence, and the SEF
demo environment (M5) settles the severity. A *wrong* VAT status contradicts no example, so it
is fatal: one business term, two rules, because the evidence differs.

**2. "Several notes apply 'to residents'. How do you know who is resident?"**

The invoice does not say, so we read residency from the party's country code (`RS`), a proxy
recorded in ADR-0006 and in each rule. Its failure mode is a resident with a foreign address
escaping a check — a missed error, not a false one. Where even the proxy is impossible — the
payee has no address in EN 16931 — the rule says that it does not check the "for residents"
scheme note instead of guessing.

**3. "SRB-019 fires on text that 'names a model'. Isn't that fragile?"**

The specification prescribes a notation only when a payment model is given, and "97 1234" may
or may not mean model 97. So the rule fires only when the text starts with `mod` and a digit,
in any spelling — unmistakable intent — and then requires the exact form `(mod97) 1234`. A
plain reference is never reported: the heuristic can miss, it cannot accuse.

## The one concept to explain unaided

**Severity is a product decision backed by evidence.** The validator distinguishes "the
specification says" from "SEF enforces". A requirement the text states is fatal; one the
official examples contradict is a warning that still cites the text; evidence — the examples
now, the SEF demo environment in M5 — moves a rule between the two, recorded in the rule and the
changelog. Getting this wrong in either direction costs the user: a missed fatal gets an
invoice rejected by SEF, a false fatal blocks one SEF would accept.

## Supporting facts worth remembering

- Rules SRB-010 to SRB-019; 19 in total, 0.5–0.7 ms per invoice (2–2.5 ms with the model).
- On the 17 official examples: SRB-013 warns on all 16 schema-valid ones, SRB-017 on the 8
  schema-valid ones without a buyer post code; SRB-009 reports the placeholder PIBs; every other
  rule is satisfied.
- BT-32 in SEF: a second party tax scheme `RS-VAT-STATUS` with `VAT` or `NO-VAT`, beside the
  `VAT` scheme that carries `RS` + PIB (BT-31).
- BT-8 per SRB-CIUS: 35 = due on supply, 3 = on the issue date, 432 = on payment for an advance
  invoice, on collection (cash accounting) otherwise; 35 and non-advance 432 require BT-72.
- BT-10 for procurement awarded by another authority: `JN-JBKJS:` + five digits, optionally
  `-` and more.
