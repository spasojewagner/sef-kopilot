# 61. The evaluations gate CI as a job of their own, and the badge reads the committed report

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `ci/evals-gate`; the evaluations of ADR-0054, the
  cassettes of ADR-0055, the brief's "evals thresholds in `evals/thresholds.yaml` gate CI
  (offline mode with cassettes)" and "README badge from report"

## Context and problem statement

The evaluations already ran in CI, inside the API's job, as one test among its eight hundred
that runs `sef-evals --check`. A pull request that drops a measure below its threshold failed,
but as "api tests", and a reader of the repository saw nothing of the measures until they
opened the report. The brief asks for the thresholds to gate CI and for a README badge from the
report. Where does the gate run, and where does the badge come from?

## Decision drivers

- A failed gate names itself: a reviewer and a branch rule see "evaluations", not a test inside
  the API's suite.
- The badge says what the committed report says, and cannot drift from it.
- No service that writes to the repository or holds a token; offline, as the cassettes are.

## Considered options

1. **A CI job of its own running `sef-evals --check`; the run writes `badge.json` beside the
   report, in shields.io's endpoint format, and the README reads it from the default branch.**
   Chosen.
2. A badge made by CI after the run and pushed to a branch or a gist.
3. The CI workflow's own badge only.

## Decision outcome

**The gate.** The job `evaluations (thresholds and report)` has PostgreSQL and the rule sets,
replays the cassettes and runs `uv run sef-evals --check`: it fails when a measure misses its
threshold, or when a file of the committed report is not what the run gives. The runner's own
tests stay in the API's job, with their coverage gate.

**The badge.** `sef-evals` writes `evals/reports/badge.json` with the report: how many
thresholds the run met, out of how many, green when all, red otherwise. It is part of the
report, so `--check` holds it to the run like `latest.json` and `latest.md`. The README shows it
through shields.io's endpoint badge, reading the file on the default branch.

### Consequences

Good:

- A branch rule can require "evaluations"; a failure says which measure, in the job's log and in
  the report's diff.
- The badge is a committed file: no token, no bot, no write to the repository from CI, and it
  can never claim more than the report it sits beside.

Bad / accepted:

- The badge shows the default branch's report, not a pull request's.
- shields.io reads a public file: the badge is blank while the repository is private, and it
  depends on shields.io being up.

## Pros and cons of the options

### A badge pushed by CI

- Good: could show a run that was never committed.
- Bad: CI needs a token that writes to the repository, or a gist and its token; a bot's commits
  on the default branch; a badge that can disagree with the committed report.

### The workflow's badge only

- Good: nothing to build.
- Bad: says only that every job passed, nothing of the measures.
