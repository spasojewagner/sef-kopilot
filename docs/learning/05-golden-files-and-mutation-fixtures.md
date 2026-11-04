# Golden files and mutation fixtures

There are two ways to test a validator on whole documents, and a good corpus uses both.

**Intent.** A person states, before the code runs, what a document must produce. A *mutation
fixture* is a valid document with one deliberate mistake and the rules that must report it:
"a typo in the seller's PIB → SRB-009, twice". Intent catches wrong behaviour on the cases
someone thought of.

**Observation** (a *golden file*, also called approval or snapshot testing). The machine
records what the code says today about every document; a person approves the record once, by
reviewing it; from then on a test fails whenever the observation changes. Observation catches
any change anywhere, including on documents nobody wrote an expectation for — here, the
Ministry's and CEN's examples.

```text
catalogue (intent) ── make fixtures ──▶ mutation files ──┐
official and synthetic documents ────────────────────────┼──▶ pipeline ──▶ verdicts.json
                                                         │                 (observation)
tests:  mutation report == its intent · each verdict == verdicts.json · files == generator
```

## Record the right thing

A golden file is useful only if it changes when behaviour changes, and only then. Record a
stable projection of the output, not the output:

| Record | Leave out |
| --- | --- |
| validity, rule ids, how often each was reported, what was set aside | messages (they get reworded), line numbers (CRLF vs. LF, reformatting), timings |

Keep the order deterministic (sorted keys, one entry per document) and the format readable as a
diff, because the diff is what gets reviewed.

## Pitfalls

- **Regenerating without reading.** The approval *is* the review. A test that says "run
  `make fixtures`" is answered by explaining, in the pull request, why each verdict changed.
- **Brittle snapshots.** Record whole messages and every rewording fails a hundred tests;
  people then regenerate blindly, and the golden file stops protecting anything.
- **Fixtures that drift.** A hand-written invalid file loses its meaning: months later nobody
  knows which mistake it was meant to show. Generate it from a catalogue that states the
  mistake, and check the files against the generator.
- **Edits that silently miss.** A text edit that matches zero or two places produces some other
  document. Here every edit must match its base exactly once, or generation stops and names it.

## In this repository

`scripts/make_fixtures.py` (the catalogue and the generator), `fixtures/invoices/verdicts.json`
(the observation), `scripts/tests/test_make_fixtures.py` and
`packages/einvoice_core/tests/test_corpus.py` (the checks); the decision is ADR-0010.
