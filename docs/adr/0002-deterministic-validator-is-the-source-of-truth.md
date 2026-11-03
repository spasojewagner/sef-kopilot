# 2. Deterministic validator is the source of truth

- Status: accepted
- Date: 2026-11-03
- Deciders: Marko Spasojević
- Technical story: `docs/BRIEF.md` §2, "Architecture: three layers, one rule"

## Context and problem statement

SEF Kopilot uses a language model to explain validation errors and to propose repairs.
Electronic invoices are legal and tax documents: SEF rejects an invoice on a rule violation,
and from 2027 the preliminary VAT return is derived from invoice content. A language model is
probabilistic, cannot be audited line by line and may invent rules that do not exist. The
question is which component is allowed to decide that an invoice is valid, and how far the
model's output is trusted.

## Decision drivers

- Correctness must be verifiable: a reviewer, an auditor or a test must be able to show *why*
  an invoice passed or failed, with a reference to the rule.
- The same invoice must produce the same verdict every time (reproducible evaluations, stable
  CI, defensible behaviour towards customers).
- Regulatory rule sets already exist as executable artefacts (XSD, Schematron for EN 16931 and
  Peppol BIS); the Serbian profile (SRB-CIUS) can be expressed the same way.
- The product must be safe to use with a cheap or self-hosted model.

## Considered options

1. **Deterministic validator decides; the model only explains and proposes** — chosen.
2. The model validates (prompted with the rules and the invoice).
3. The model edits the XML directly and the result is validated afterwards.

## Decision outcome

Option 1, structured as three layers with one rule: **the language model sits between two
deterministic walls and is never trusted.**

1. **Deterministic validator** (`packages/einvoice_core`): XSD validation, EN 16931 and Peppol
   BIS Schematron executed as published, SRB-CIUS rules implemented in code, each with the
   specification paragraph it comes from, and EN 16931 arithmetic (`BR-CO-*`) re-implemented
   in Python. Its output is a list of violations `{rule_id, severity, xpath, message}`. This is
   the only component that may say "valid".
2. **Explainer**: receives violations plus regulation passages returned by retrieval, and
   produces a structured explanation. Every citation must resolve to a stored corpus chunk id;
   a citation that does not resolve fails the whole response.
3. **Repairer**: produces patches `{xpath, op, value, reason}` as data. Code applies them,
   layer 1 re-validates the result, and a human approves the diff. Patches that touch monetary
   amounts, VAT rates or categories, tax identifiers (PIB), company identifiers or dates of
   supply are rejected automatically and surfaced as "needs manual decision".

Supporting rules:

- Nothing leaves the system (API response, SEF submission) without a green result from layer 1.
- Guardrails are tests, not comments: the forbidden-field guard, the citation resolution
  check and the arithmetic rules each have a test suite that fails the build.
- No invoice content is written to logs, traces or error reports; a no-store mode processes an
  invoice in memory only.
- Evaluation thresholds (from M6) make the decision measurable: agreement with the reference
  EU validator 100 %, false-accept rate 0 %.

### Consequences

Good:

- Every verdict is explainable by pointing at a rule and an XPath; evaluations are reproducible.
- The model can be swapped, downgraded or self-hosted without changing what is accepted.
- The repair loop is bounded: a patch list is reviewable, loggable and reversible; free-form
  XML edits are not.

Bad / accepted:

- The SRB-CIUS rules have to be authored and maintained by hand from the specification; this
  is the single largest piece of domain work in M1.
- Two passes of validation per repair (before and after) cost time; the performance budget in
  the brief (validate < 500 ms warm, whole loop < 20 s) accounts for it.
- Some violations have no safe automatic repair by design (anything touching amounts or
  identifiers); the product must present "needs manual decision" well rather than pretend.

## Pros and cons of the options

### The model validates

- Good: fastest to prototype; handles edge cases the rules do not express.
- Bad: non-deterministic, unauditable, hallucinated rules, no stable evaluation baseline; a
  wrong "valid" verdict reaches the tax authority.

### The model edits XML directly, validated afterwards

- Good: fewer moving parts than a patch model.
- Bad: unbounded changes (an edit can silently alter an amount), no diff a human can approve
  per change, no way to forbid specific fields reliably, hard to log safely.
