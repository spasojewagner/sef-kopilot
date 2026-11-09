# Evaluation report

Written by `make evals` (ADR-0054); do not edit. Measured with the rule sets ubl-2.1 sha256:60b80d76394a, en16931 validation-1.3.17, peppol-bis-billing-3 3.0.21, iso-schematron 2020-10-01.

| Measure | What it counts | Value | Threshold | Met |
| --- | --- | --- | --- | --- |
| `agreement` | Documents on which the validator's verdict is the reference's | 100.0% (93 of 93) | ≥ 100% | yes |
| `rule_agreement` | Documents on which the validator reports the reference's fatal rules | 100.0% (93 of 93) | ≥ 100% | yes |
| `false_accept_rate` | Documents that must be rejected, accepted | 0.0% (0 of 56) | ≤ 0% | yes |
| `false_reject_rate` | Documents that must be accepted, rejected | 0.0% (0 of 38) | ≤ 0% | yes |
| `detection` | Documents whose mistake is reported by the rules it must be reported by | 100.0% (60 of 60) | ≥ 100% | yes |
