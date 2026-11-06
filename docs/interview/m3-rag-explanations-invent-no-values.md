# M3 — `fix/rag-explanations-invent-no-values`

## Three questions a senior engineer would ask

**1. "The prompt already said 'never invent an identifier'. Why wasn't that enough?"**

Because a prompt is a request, not a guarantee. The first live answer to `SRB-009` was right
about the rule, cited the right passages and even computed the right check digit, then
suggested "for example 100000024" as the corrected PIB. That is helpful-sounding and wrong: a
PIB with its last digit changed belongs to another taxpayer, or to none, and an accountant may
copy it. Everything else the model must not do in this project is checked in code; the values
it names were the one thing held only by words.

**2. "How do you tell an invented value from one the model may repeat?"**

By what the model was shown. A value (a date, a number with decimals or groups, a rate, a run
of five digits or more) may appear in the answer only if it appears in the question: the
violation's message, its place, the invoice's day, the passages. Both sides are first written
one way, a date as ISO 8601 and a number as its digits, so `1.200,00` matches the message's
`1200.00` and `5. 10. 2026` the invoice's `2026-10-05`. Short plain numbers are not values (the
check digit 4, the 7064 of ISO 7064, the 31 of BT-31), which keeps the check from refusing
ordinary sentences.

**3. "What does it miss, and what does it cost?"**

A value written in words, and small integers, which the prompt still forbids. A value the model
derived correctly, such as a VAT amount it computed, is refused too, deliberately: arithmetic
is the validator's, whose messages quote what it computed. The cost is one more reason for an
answer to go back, within the same three answers; a model that keeps naming values leaves that
rule unexplained, with the reason, and the other rules stand.

## The one concept to explain unaided

**Hold the model with checks, not instructions.** Each rule the model must keep gets a
deterministic test of its answer whose failure goes back to it as feedback: citations are
checked against the ids it was given, values against the question it was asked.

## Supporting facts worth remembering

- `_values` in `sef_api.rag.explainer` writes dates and numbers one way; `_invented` is the
  difference between the answer's values and the question's.
- The feedback: "it names 100000024, which neither the violation nor the passages contain: say
  which value to check instead of writing one".
- The prompt now adds "not even as an example, and do not compute one"; non-breaking hyphens
  and spaces in the answer become plain ones.
- ADR-0022 amends ADR-0021; seven faults seeded into the check, seven caught once the prompt's
  new sentence had a test of its own.
