# 54. The system is measured on golden sets labelled apart from it, against thresholds in CI

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/evals-harness`; the brief's evaluation thresholds
  (§ Definition of done), the validator of ADR-0002 and ADR-0008, the corpus of ADR-0010

## Context and problem statement

The tests say that each piece does what it was written to do. They do not say how well the
system does its job, in numbers that a reader can check and that a change can lower: whether
the validator's verdicts are the ones the published rule sets give, whether it lets through an
invoice that SEF would refuse, whether the model's explanations cite what they should and its
repairs repair. The brief sets thresholds for each — agreement with the reference EU validator
100 %, false accepts 0 %, repair success at least 80 % on a held-out set, citations resolved
100 % and relevant at least 90 % — and asks that CI fail below them, offline. Where do the
measures live, what are they measured on, against what reference, and how do they gate a
change?

## Decision drivers

- A measure is only as good as its labels: what a document must get cannot come from what
  the system answered, or the measure only says that the system agrees with itself.
- Reproducible: the same code and rule sets give the same numbers, on any machine, without
  network or keys.
- Every number names the cases behind it, so that a failure says which document to look at.
- A change that lowers a measure is seen in review, as `verdicts.json` makes a changed verdict
  seen.
- Nothing of the evaluations ships in the API's image.

## Considered options

1. **A package of the workspace, `evals/`, with golden sets in YAML, thresholds in
   `evals/thresholds.yaml`, a runner that writes a committed report, and a check in CI.**
   Chosen.
2. Assertions on numbers inside the existing test suites.
3. A hosted evaluation service (Langfuse datasets, an EU validator's API).

## Decision outcome

**Where.** `evals/` is a member of the uv workspace, `sef-kopilot-evals` (`sef_evals`), with
its golden sets, `thresholds.yaml` and the latest report beside it, as the brief lays the
repository out. It depends on the packages it measures; the API depends on nothing of it, and
its image does not hold it. `make evals` (`uv run sef-evals`) measures, prints a table and
writes `evals/reports/latest.json` and `latest.md`; `make evals-check` writes nothing and fails
when a threshold is not met or the committed report is not what the run gives.

**Golden labels.** `evals/golden/documents.yaml` names every document of the corpus in groups:
the profile it is judged by, whether it must be accepted or rejected, and the rules that must be
among those reported. The labels come from the documents' publishers (CEN's and OpenPeppol's
examples are valid; the Ministry's carry placeholder PIBs, and two of them a genuine flaw that
ADR-0008 found), and from the mistake each mutation was made to have, which its header states
(ADR-0010). A test holds the golden set to the corpus: every document whose verdict
`verdicts.json` records is in it, and nothing else.

**The reference.** No validator is published for SRB-CIUS, and a reference validator for EN
16931 is a composition of published artefacts rather than a file to run: the UBL 2.1 schema,
then EN 16931's Schematron (with Peppol's for Peppol), as published. The runner applies exactly
that, with nothing set aside and no rule of SEF Kopilot's, to every document under EN 16931
(Peppol for Peppol's examples), and compares it with the validator under the same profile. The validator
differs from it on purpose in two places, set-asides and CEN's calculation rules computed again
in Python (ADR-0007, ADR-0008), so agreement measures that these choices change no verdict.

**The measures of the validator**, each a count over cases that names those that fail:

| Measure | Counts | Threshold |
| --- | --- | --- |
| `agreement` | documents with the reference's verdict | 100 % |
| `rule_agreement` | documents with the reference's fatal rules, outside `ext:UBLExtensions` | 100 % |
| `false_accept_rate` | documents that must be rejected, accepted | 0 % |
| `false_reject_rate` | documents that must be accepted, rejected | 0 % |
| `detection` | documents whose mistake is reported by the rules it must be | 100 % |

`rule_agreement` leaves out what either side reports inside the extension, where CEN's
stylesheet applies EN 16931's rules to the Serbian copies of the totals, which are none of its
business groups (ADR-0007). The validator is deterministic, so its thresholds allow no
exception: a miss is a defect, not noise.

**The report.** JSON for machines and Markdown for people, holding the measures, the cases that
failed and the rule sets' pins, and never a time, a machine or a version of the code: the same
inputs write the same bytes, so the committed report is checked like a generated file.

**The language model.** Explanations and repairs are measured the same way, on golden sets of
their own, with the model's answers recorded once against the free tier (cassettes) and
replayed offline in CI; their thresholds join `thresholds.yaml` with those sets. A threshold
whose measure the run does not take is not met, so a threshold cannot be satisfied by its
measure being left out.

### Consequences

Good:

- The numbers the README will show are the ones CI checks, from labels a reviewer can read and
  dispute line by line.
- Every miss names its document and what differed, as the first run did: it found that two of
  the Ministry's examples are rejected for their own flaws besides the placeholder PIBs, and
  that under EN 16931 the validator, too, reports rules inside the Serbian extension, so the
  comparison leaves the extension out on both sides.
- The runner is quick (a few seconds on the corpus), offline and needs only the fetched rule
  sets.

Bad / accepted:

- The reference shares the validator's XML loading and its XSLT engine (Saxon, as the EU's
  validators use); it is independent in its rules and their composition, not in its machinery.
- The corpus is what the measures see: 93 documents. A defect that no document exercises
  passes the evaluations; the unit tests and the conformance tests remain the first net.
- A change in behaviour also changes the committed report, which the pull request regenerates
  with `make evals`.

## Pros and cons of the options

### Assertions inside the test suites

- Good: nothing new to run.
- Bad: no report and no numbers to show; a test passes or fails, and the thresholds would be
  scattered through assertions instead of one file a reader can find.

### A hosted evaluation service

- Good: dashboards, datasets and history out of the box.
- Bad: a network call, an account and a key in CI, against the brief's offline gate; the EU's
  validator as a service would also see every document sent to it.
