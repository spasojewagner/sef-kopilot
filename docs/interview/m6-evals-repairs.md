# M6 — `feat/evals-repairs`

## Three questions a senior engineer would ask

**1. "80 % of what? Your repairer was built on these fixtures."**

Not on these. The held-out invoices are made at run time from the synthetic ones by edits the
golden set names: a specification identifier, a payment model without its space, a country
written SRB or rs, on a plain invoice and on a final one, and two at once. None is a fixture the
repairer was developed or tested on. `repair_success` is the share of them a repair leaves the
validator accepting, through the same repairer, rounds, checks and patch engine the API uses.

**2. "Success is easy if the model may change anything. What stops it?"**

The guard, measured here. Eleven invoices carry a mistake a person decides: a PIB, a VAT rate,
the amount due, a date, a price, and the invoice's type. `overreach_rate` counts those that a
repair made pass by any route round the guard, and the threshold is zero. In the first recording
the model did propose a PIB check digit and an amount due; the guard kept them as suggestions
for a person, and none passed.

**3. "You moved cases after the first run. Isn't that tuning to the result?"**

That is exactly the question to ask. Three held-out cases were invoice types SEF does not
accept: 325 or 389. SRB-001 allows four codes, and a proforma invoice may have been meant as an
invoice or an advance invoice, so neither the invoice nor the violation gives the right one: the
cases failed the set's own criterion, and the model, following the repairer's rule never to
write a value of its own, rightly proposed nothing. They became cases a person decides; four new
held-out invoices of the kinds that do meet the criterion took their places, written before the
model saw them. ADR-0056 records it, with the suspicion it invites.

## The one concept to explain unaided

**Measure the refusal as well as the success**: a repairer that fixes everything is dangerous,
so the set holds cases it must not fix, and the threshold for those is zero, not a percentage.

## Supporting facts worth remembering

- 9 held-out cases, 11 a person decides; one more or less moves `repair_success` by eleven
  points: a floor that catches a broken repairer, not a fine measure.
- Recorded against Groq's free tier (`openai/gpt-oss-120b`), replayed offline in CI.
