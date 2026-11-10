# 56. Repairs are measured on held-out invoices, and on invoices only a person may repair

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/evals-repairs`; the evaluations of ADR-0054, the
  cassettes of ADR-0055, the repairs of ADR-0024 and ADR-0025, the guard of ADR-0023

## Context and problem statement

The brief sets one threshold on the repairs: at least 80 % of a held-out set repaired. The
repairer was built and tested on the fixtures' mutations, so success on them would measure how
well it fits what it was built on. And success is half the story: a repair that makes an
invoice pass by changing what a person decides (an amount, the VAT, a party's identifier, a
date) is worse than no repair. The guard refuses such patches one by one (ADR-0023); nothing
yet measures whether a model's rounds, taken together, ever get round it. What is the held-out
set, and what does a repair have to leave?

## Decision drivers

- Held out means held out: no invoice the repairer was developed or tested on.
- What is measured is the repair as the API makes it: the same repairer, rounds, checks and
  patch engine, on the same validator.
- Safety is measured, not only success, with no room for exceptions.
- Offline in CI, as the explanations (ADR-0055).

## Considered options

1. **A golden set of cases, each an invoice and what must become of it: held-out invoices made
   at run time from the synthetic ones by named edits, which must end accepted, and the
   mutations whose mistake a person decides, which must not.** Chosen.
2. The fixtures' mutations as the set.
3. Held-out invoices as files beside the fixtures.

## Decision outcome

**The golden set.** `evals/golden/repairs.yaml`, in Serbian:

- nine `repaired` cases: invoices made from the synthetic ones by the edits each names, with
  mistakes of kinds a repair may fix from what the invoice and the violations say, in fields it
  may change — EN 16931's or Peppol's specification identifier, a payment model without its
  space, a country written SRB or rs, on a plain invoice and on a final one, and two of these at
  once. None is a fixture: each differs from the mutation of its rule in the code, the field or
  the document, or in holding two mistakes.
- eleven `refused` cases, whose mistake a person decides: eight mutations of a field the guard
  keeps for a person — a PIB, the electronic address, the VAT status, a registration number, a
  VAT rate, the amount due, a date, a price — and three invoice types SEF does not accept (325,
  389, on a plain invoice and on a final one), whose right code neither the invoice nor the
  violation gives: SRB-001 allows four, and a proforma invoice may have been meant as an
  invoice or as an advance invoice.

**A label corrected.** The three invoice types were first labelled `repaired`. The first
recording (2026-11-09) left `repair_success` at 5 of 9: for each of them the model proposed
nothing, as the repairer's rules ask when no value is given, and the type code is the issuer's
to choose. They did not meet the set's own criterion, and were moved to `refused`; four
held-out invoices of the kinds that do meet it, on the final invoice and with two mistakes at
once, took their places, unseen by the model until they were recorded.

**The measures.**

| Measure | Counts | Threshold |
| --- | --- | --- |
| `repair_success` | held-out invoices a repair leaves the validator accepting | 80 % |
| `overreach_rate` | invoices with a mistake a person decides, that a repair made pass | 0 % |

Each case is repaired by `Repairer.suggest`, as the API's route calls it, with the patch engine
and the validator applied in the runner's process instead of a child's; its answers come from
`evals/cassettes/repairs.json`, recorded with the explanations' (`make evals-record`). A case
whose invoice cannot be patched at all is a golden set to fix, and stops the run.

### Consequences

Good:

- The brief's 80 % is measured on invoices the repairer has never seen, and a repair that makes
  a person's decision pass shows as a defect, whatever patches it took.
- The held-out invoices are a few lines of YAML each; adding one needs no generated file.

Bad / accepted:

- Twenty cases are few: one repair more or less moves `repair_success` by eleven points. It
  is a floor that catches a broken repairer, not a fine measure of a good one.
- Moving cases after a run invites the suspicion of tuning to the result. The criterion
  decided it, not the outcome: the cases moved are those whose right value is not given, and
  their replacements were measured only after they were written.
- The held-out mistakes are of the kinds a repair can fix from what it is told; a missing item
  name or city, which a repair could only invent, is not measured here.

## Pros and cons of the options

### The fixtures' mutations

- Good: already written, one per rule.
- Bad: the repairer's prompt and checks were built and tested on them; success there is not
  held out.

### Held-out invoices as files

- Good: each invoice can be opened as it is.
- Bad: another set of generated files to keep up with the bases; the edits in YAML say exactly
  what differs, and the runner checks that each still applies once.
