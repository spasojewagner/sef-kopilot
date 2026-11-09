# M6 — `chore/release-0.6.0`

## Three questions a senior engineer would ask

**1. "What does 0.6.0 deliver, in one breath?"**

Numbers a reader can check and a gate a change can fail: the validator agrees with the
published rule sets on every document of the corpus; the model's explanations cite only stored
passages, nearly all of them relevant by a person's labels; its repairs fix held-out invoices
and never make a person's decision pass; all of it replayed offline in CI as a job of its own,
with the README's badge reading the committed report. Around it: OpenAI and Anthropic beside
Groq, an organization's own model key, and credits per stored invoice, bought through Stripe's
sandbox, off by default.

**2. "Paid providers and Stripe, in a free project, never tried against real accounts?"**

On purpose, and the release says so. Each follows its documented API and is tested on answers
shaped as the documentation shows; Stripe's requests are also checked by `stripe-mock`, which
validates them against Stripe's own API description. Live Stripe keys are refused by the
settings. What none of it proves is a real account's behaviour today; the first operator with a
key is the first to see it, and the ADRs name that risk rather than hide it.

**3. "A threshold was missed on the first recording. What happened?"**

`repair_success` came in at 5 of 9. Every miss was an invoice type SEF does not accept, for which
the model rightly proposed nothing: the invoice does not say which of the four allowed codes was
meant. The labels were wrong by the set's own criterion; at the maintainer's decision those
cases became ones a person decides, new held-out invoices took their places before the model saw
them, and ADR-0056 records it with the suspicion it invites.

## The one concept to explain unaided

**Evaluations are tests of the whole system against labels from outside it**: unit tests check
that the code does what it was written to do; evaluations check that what it does is right, on
data it was not built on, and a missed number is as likely to be a wrong label as a wrong
model, which is why each number names the cases behind it.

## Supporting facts worth remembering

- Migrations in the milestone: 0023 (model keys), 0024 (credits), 0025 (purchases).
- ADR-0054 to ADR-0061; learning notes 44 to 47.
- The tag goes on the merge commit of this pull request, whose checks passed; the release notes
  are in `.handoff/RELEASE-v0.6.0.md`.
