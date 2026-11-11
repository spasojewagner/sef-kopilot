# Evaluation report

Written by `make evals` (ADR-0054); do not edit. Measured with the rule sets ubl-2.1 sha256:60b80d76394a, en16931 validation-1.3.17, peppol-bis-billing-3 3.0.21, iso-schematron 2020-10-01, and the answers of gemini/gemini-3.1-flash-lite and groq/openai/gpt-oss-120b recorded in evals/cassettes/.

| Measure | What it counts | Value | Threshold | Met |
| --- | --- | --- | --- | --- |
| `agreement` | Documents on which the validator's verdict is the reference's | 100.0% (93 of 93) | ≥ 100% | yes |
| `rule_agreement` | Documents on which the validator reports the reference's fatal rules | 100.0% (93 of 93) | ≥ 100% | yes |
| `false_accept_rate` | Documents that must be rejected, accepted | 0.0% (0 of 56) | ≤ 0% | yes |
| `false_reject_rate` | Documents that must be accepted, rejected | 0.0% (0 of 38) | ≤ 0% | yes |
| `detection` | Documents whose mistake is reported by the rules it must be reported by | 100.0% (60 of 60) | ≥ 100% | yes |
| `explained` | Rules of the golden documents that the model explained | 100.0% (47 of 47) | ≥ 90% | yes |
| `citation_resolution` | Citations of a passage stored in the corpus and applying on the day | 100.0% (93 of 93) | ≥ 100% | yes |
| `citation_relevance` | Citations of a passage labelled relevant to the rule | 96.8% (90 of 93) | ≥ 90% | yes |
| `repair_success` | Held-out invoices that a repair leaves the validator accepting | 100.0% (9 of 9) | ≥ 80% | yes |
| `overreach_rate` | Invoices with a mistake a person decides, that a repair made pass | 0.0% (0 of 11) | ≤ 0% | yes |
| `extraction_pdf` | Fields read as the invoice has them, from a PDF with its text | 100.0% (569 of 569) | ≥ 97% | yes |
| `extraction_scan` | Fields read as the invoice has them, from a scan | 99.5% (566 of 569) | ≥ 95% | yes |
| `extraction_photo` | Fields read as the invoice has them, from a photograph | 99.8% (568 of 569) | ≥ 90% | yes |
| `extraction_invented` | Fields the invoice leaves empty that the reading filled in | 1.9% (2 of 108) | ≤ 5% | yes |
| `extraction_valid` | Documents read into an invoice the validator accepts as it was read | 100.0% (30 of 30) | ≥ 60% | yes |

## `citation_relevance`

- fixtures/invoices/synthetic/mutations/br-cl-23-unit-code.xml [sr] BR-CL-23: cites srb-cius/1-3-table-1-bt-129/2025-06-06, labelled not relevant
- fixtures/invoices/synthetic/mutations/srb-012-legal-registration-number.xml [sr] SRB-012: cites srb-cius/1-3-table-1-bg-7/2025-06-06, labelled not relevant
- fixtures/invoices/synthetic/mutations/srb-013-seller-vat-status-missing.xml [sr] SRB-013: cites srb-cius/1-3-table-1-bg-4/2025-06-06, labelled not relevant

## `extraction_scan`

- software-maintenance.scan.pdf: lines[1].unit read as 'H87', the invoice has 'C62'
- software-maintenance.scan.pdf: lines[2].unit read as 'H87', the invoice has 'C62'
- freight-transport.scan.pdf: lines[1].name read as 'Prevoz robe, relacija Beograd - Niš', the invoice has 'Prevoz robe, relacija Beograd – Niš'

## `extraction_photo`

- freight-transport.jpg: lines[1].name read as 'Prevoz robe, relacija Beograd - Niš', the invoice has 'Prevoz robe, relacija Beograd – Niš'

## `extraction_invented`

- cyrillic-engineering.pdf: totals.prepaid filled in as '0.0'
- cyrillic-engineering.scan.pdf: totals.prepaid filled in as '0.0'
