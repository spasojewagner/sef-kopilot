# M6 — `ci/evals-gate`

## Three questions a senior engineer would ask

**1. "How can CI gate on a language model without calling one?"**

It replays. The model's answers were recorded once into cassettes, each named by the hash of
the request; CI replays them offline, so the gate measures the code around the model (retrieval,
prompts, checks, the patch engine, the validator) on real answers, deterministically, for free.
A change that alters a request finds no recorded answer and drops the measure, which fails the
gate until the answers are recorded again on purpose.

**2. "What exactly fails the job?"**

Two things: a measure below its threshold in `evals/thresholds.yaml`, or a committed report
that is not what the run gives. The second matters as much: a change that moves a measure must
commit the new report, so the change in quality shows up as a diff a reviewer reads.

**3. "Where does the badge come from? Who updates it?"**

Nobody separately. The run writes `badge.json` beside the report, in shields.io's endpoint
format, and `--check` holds it to the run like the rest of the report; the README asks shields.io
to read that file from the default branch. No token, no bot pushing commits, and the badge can
never claim more than the committed report.

## The one concept to explain unaided

**A quality number belongs in version control**: when the measures are committed and checked
against the run, every change to quality is a reviewed diff, and the badge is just a view of a
file the repository already holds.

## Supporting facts worth remembering

- The job: `evaluations (thresholds and report)`, PostgreSQL plus the rule sets, `uv run
  sef-evals --check`.
- The runner's own tests stay in the API's job with their coverage gate (≥ 90 %).
- The badge shows the default branch; it is blank while the repository is private.
