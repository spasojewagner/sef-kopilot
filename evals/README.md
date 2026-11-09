# Evaluations

How well SEF Kopilot does its job, measured on golden sets and judged against the thresholds
in [`thresholds.yaml`](thresholds.yaml) (ADR-0054). The latest measures are in
[`reports/latest.md`](reports/latest.md).

```bash
make evals          # measure, print the table, write reports/latest.{json,md}
make evals-check    # measure, and fail if a threshold is not met or the report is stale
make evals-record   # ask the model what cassettes/ lacks, then measure (needs a key)
```

They need the fetched rule sets (`make rulesets`) and PostgreSQL (`make up`, named by
`SEF_TEST_DATABASE_URL`), on which the explanations get a database of their own; the runner is
the workspace package `sef-kopilot-evals` (`uv run sef-evals`). A pull request that changes what the validator
reports commits the report that `make evals` writes, as it commits `verdicts.json`: a changed
measure is a changed behaviour, and its diff is reviewed like code.

## The validator

The golden set is [`golden/documents.yaml`](golden/documents.yaml): every document of the
corpus (`fixtures/invoices/`, and the examples CEN/TC 434 and OpenPeppol publish), in groups,
with the profile each is judged by, whether it must be accepted or rejected, and the rules
that must be among those reported. The labels come from the documents' publishers and from the
mistakes the mutations were made to have, never from what the validator answered.

| Measure | What it counts | Threshold |
| --- | --- | --- |
| `agreement` | Documents on which the validator's verdict is the reference's | 100 % |
| `rule_agreement` | Documents on which it reports the reference's fatal rules | 100 % |
| `false_accept_rate` | Documents that must be rejected, accepted | 0 % |
| `false_reject_rate` | Documents that must be accepted, rejected | 0 % |
| `detection` | Documents whose mistake is reported by the rules it must be reported by | 100 % |

The reference is the published artefacts applied as published, as the EU's reference
validators compose them: the UBL 2.1 schema, then EN 16931's Schematron (with Peppol's for the
Peppol profile), with nothing set aside and no rule of SEF Kopilot's own. Every document is
compared under EN 16931, or under Peppol for Peppol's examples: SRB-CIUS has no published
reference. `rule_agreement` leaves out what the reference reports inside `ext:UBLExtensions`,
where CEN's stylesheet applies the calculation rules to the Serbian extension's copies of the
totals (ADR-0007).

The published unit tests of the rule sets are fragments of invoices, which the schema refuses;
they are applied to the Schematron layer alone, by the conformance tests
(`test_schematron_conformance.py`), not here.

## The explanations

The golden set is [`golden/explanations.yaml`](golden/explanations.yaml): the 41 readable
mutations, each rule they break explained in Serbian on a fixed day, as the API explains a
report, from the passages retrieval finds in the repository's corpus without embeddings. For
each rule, the passages retrieval finds are labelled relevant or not (ADR-0055); `uv run
sef-evals --unlabelled` lists those no label names.

| Measure | What it counts | Threshold |
| --- | --- | --- |
| `explained` | Rules of the golden documents that the model explained | 90 % |
| `citation_resolution` | Citations of a passage stored in the corpus and applying on the day | 100 % |
| `citation_relevance` | Citations of a passage labelled relevant to the rule | 90 % |

The model's answers are recorded once in [`cassettes/explanations.json`](cassettes/), by the
SHA-256 of each request, and replayed offline: CI never calls the model. A change to what the
model is sent (the prompt, a passage, a document) has no recorded answer, and lowers
`explained` until it is recorded again. To record, with a key of your own on Groq's free tier:

```bash
make up                                   # PostgreSQL for the explanations' database
LLM_PROVIDER=groq GROQ_API_KEY=... make evals-record
```

It asks only what the cassette lacks, two seconds apart; at the provider's daily limit it stops
and keeps what it recorded, and the next run continues from there.

## Repairs *(planned, M6)*

Repair success on a held-out set of invoices (≥ 80 %), on recorded answers too, and no patch
ever applied to a field a person decides.
