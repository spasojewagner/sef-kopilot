# Evaluations

How well SEF Kopilot does its job, measured on golden sets and judged against the thresholds
in [`thresholds.yaml`](thresholds.yaml) (ADR-0054). The latest measures are in
[`reports/latest.md`](reports/latest.md).

```bash
make evals          # measure, print the table, write reports/latest.{json,md}
make evals-check    # measure, and fail if a threshold is not met or the report is stale
```

Both need the fetched rule sets (`make rulesets`); the runner is the workspace package
`sef-kopilot-evals` (`uv run sef-evals`). A pull request that changes what the validator
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

## The language model *(planned, M6)*

Explanations and repairs are measured on golden sets of their own, against recorded answers of
the model (cassettes) so that CI runs offline: citation resolution (100 %), citation relevance
(≥ 90 %, labelled by a person) and repair success on a held-out set (≥ 80 %).
