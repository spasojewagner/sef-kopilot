# Evaluations

How well SEF Kopilot does its job, measured on golden sets and judged against the thresholds
in [`thresholds.yaml`](thresholds.yaml) (ADR-0054). The latest measures are in
[`reports/latest.md`](reports/latest.md).

```bash
make evals          # measure, print the table, write reports/latest.{json,md} and badge.json
make evals-check    # measure, and fail if a threshold is not met or the report is stale
make evals-record   # ask the model what cassettes/ lacks, then measure (needs a key)
```

They need the fetched rule sets (`make rulesets`) and PostgreSQL (`make up`, named by
`SEF_TEST_DATABASE_URL`, which `.env.example` leaves empty: write the server's URL there, as
its comment shows), on which the explanations get a database of their own; the runner is
the workspace package `sef-kopilot-evals` (`uv run sef-evals`). A pull request that changes what the validator
reports commits the report that `make evals` writes, as it commits `verdicts.json`: a changed
measure is a changed behaviour, and its diff is reviewed like code.

CI's `evaluations` job runs `sef-evals --check` on every push and pull request (ADR-0061): it
replays the cassettes offline, fails when a measure misses its threshold or when the committed
report is not what the run gives. The README's badge is `reports/badge.json`, which the same
run writes and shields.io reads from the default branch: it shows what the committed report
says, and the check keeps the two the same.

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

The model's answers are recorded once in [`cassettes/`](cassettes/), by the SHA-256 of each
request, and replayed offline: CI never calls the model. A change to what the
model is sent (the prompt, a passage, a document) has no recorded answer, and lowers
`explained` until it is recorded again. To record, with a key of your own on Groq's free tier:

```bash
make up                                   # PostgreSQL for the explanations' database
LLM_PROVIDER=groq GROQ_API_KEY=... make evals-record
```

It asks only what the cassette lacks, two seconds apart; at the provider's daily limit it stops
and keeps what it recorded, and the next run continues from there.

## The repairs

The golden set is [`golden/repairs.yaml`](golden/repairs.yaml) (ADR-0056): nine held-out
invoices, made at run time from the synthetic ones by the edits each case names, whose mistake
a repair may fix; and eleven whose mistake a person decides: eight mutations of a field the
guard keeps for a person, and three invoice types SEF does not accept, where the invoice does
not say which of the four it allows was meant. Each is repaired as the API repairs a stored
invoice, with the model's answers recorded in [`cassettes/repairs.json`](cassettes/).

| Measure | What it counts | Threshold |
| --- | --- | --- |
| `repair_success` | Held-out invoices that a repair leaves the validator accepting | 80 % |
| `overreach_rate` | Invoices with a mistake a person decides, that a repair made pass | 0 % |

## The reading of documents

The golden set is [`golden/extraction.yaml`](golden/extraction.yaml) (ADR-0063): ten synthetic
invoices by the fields they print, in two layouts, varied as invoices are: one line or twelve,
VAT at 20 % and at 10 %, an advance invoice and a debit note, a Cyrillic seller, amounts in the
millions, fields some invoices leave empty. Each is printed three ways in
[`golden/documents/`](golden/documents/): a PDF with its text, as a business program prints
one; a scan, a grey picture in a PDF without text; and a photograph of the paper on a desk.
Each document is opened as the API opens an upload and read by the provider's reading model as
the API reads it, with its answers recorded in [`cassettes/extraction.json`](cassettes/).

| Measure | What it counts | Threshold |
| --- | --- | --- |
| `extraction_pdf` | Fields read as the invoice has them, from a PDF with its text | 97 % |
| `extraction_scan` | Fields read as the invoice has them, from a scan | 95 % |
| `extraction_photo` | Fields read as the invoice has them, from a photograph | 90 % |
| `extraction_invented` | Fields the invoice leaves empty that the reading filled in | 5 % |
| `extraction_valid` | Documents read into an invoice the validator accepts as it was read | 60 % |

Amounts are compared as numbers and text with its spaces collapsed; a line the model missed
counts each of its fields, and a line it made up counts each as invented. Every golden
invoice's fields make an invoice the validator accepts, which the tests check, so a document
that does not is the reading's fault.

A page is shown to the model as a picture, and drawing a page may differ in its last bits from
one machine to another; a request is named by the documents its pictures were drawn from (the
document's SHA-256, the page, its size), so that answers recorded on one machine replay on
another. Recording uses the reading model (`qwen/qwen3.8-27b` on Groq, `SEF_EXTRACTION_MODEL`
for another), forty-five seconds apart, under the free tier's tokens a minute. The documents
are drawn by [`scripts/render_documents.py`](../scripts/render_documents.py), with Playwright for
Python installed apart; a document drawn again is a new request, to be recorded again.
