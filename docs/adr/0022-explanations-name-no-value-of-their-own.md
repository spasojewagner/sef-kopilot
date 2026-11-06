# 22. An explanation names no value its question does not contain

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `fix/rag-explanations-invent-no-values`; amends
  [0021](0021-explanations-and-their-citations.md)

## Context and problem statement

The first live explanation, of `SRB-009` for a PIB whose check digit is wrong, was right about
the rule and the passages, and computed the right check digit. Its fix, though, read "check and
correct the seller's PIB so that its last digit is the right check digit (for example
100000024)". The system prompt forbids exactly that: a fix must never invent an amount, a rate,
a date or an identifier, but say which one to check. A PIB with its last digit changed is the
PIB of another taxpayer, or of none, and an accountant may copy it into the invoice.

ADR-0021 holds the answer's citations to the passages by a schema and a check, not by the
prompt. The values it names were held by the prompt alone, and the prompt did not hold.

## Decision drivers

- The model is never trusted (the brief): what it must not do is checked in code.
- No false refusals of what the model may say: the invoice's own values, as the violation
  quotes them, and the passages' numbers, in whatever notation the model writes them.
- Deterministic and explainable: the reason is sent back to the model in a sentence.

## Considered options

1. **Every value the answer names must occur in its question, compared in one notation.**
   Chosen.
2. A stronger prompt alone.
3. Removing the numbers from the fix before it is returned.
4. No digits at all in the fix.

## Decision outcome

A value is a date (ISO 8601, or as Serbian writes it, `5. 10. 2026.`), a number with decimals
or groups (an amount: `1.200,00`), a number with a percent sign (a rate), or a run of five
digits or more (a PIB, a registration number, an account). The explanation and the fix may
name a value only if the question the model was sent contains it: the violation's message, its
place, the invoice's day, the passages as shown. Both sides are written one way before they are
compared: a date as ISO 8601, a number as its digits, so that `1.200,00` matches the message's
`1200.00` and `5. 10. 2026` the day `2026-10-05`. Shorter plain numbers are not values: a check
digit, the 7064 of ISO 7064, the 31 of BT-31.

An answer that names another value is not used: it goes back to the model with the values and
"say which value to check instead of writing one", within the three answers ADR-0021 allows.
The prompt now says "not even as an example, and do not compute one" as well. The model's
non-breaking hyphens and spaces (`BT‑31`) become plain ones, so that an identifier reads as the
specification writes it.

### Consequences

Good:

- A PIB, an amount, a rate or a date the model made up, or computed, does not reach the user;
  computing amounts is the validator's work, and its messages quote the amounts it computed.
- The check costs nothing and needs no model; the refusal tells the model what to change.

Bad / accepted:

- A value written in words, or one of four digits or fewer without decimals, passes: the check
  holds what matters most, identifiers and amounts, and the prompt the rest.
- A value the model derives correctly but the question does not contain (a VAT amount it
  computed) is refused too; the explanation can say which value to compute and where.
- One more way for an answer to be unusable: a model that keeps naming values ends without an
  explanation for that rule, which says why.

## Pros and cons of the options

### A stronger prompt alone

- Good: nothing to build.
- Bad: the first prompt already said it, and the model wrote "for example" anyway.

### Removing the numbers from the fix

- Good: the user never sees one.
- Bad: rewrites what the model said into text that may no longer make sense, and hides that the
  model broke the rule.

### No digits at all in the fix

- Good: simplest.
- Bad: refuses `BT-31`, `ISO 7064`, `Article 4` and the invoice's own values, which a fix needs.
