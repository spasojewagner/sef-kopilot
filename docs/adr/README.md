# Architecture decision records

Decisions that shape the system, in the [MADR](https://adr.github.io/madr/) format. A record
is immutable once merged; a changed decision gets a new record that supersedes the old one.
Start a new record from [`template.md`](template.md) and number it sequentially.

| ID | Title | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-monorepo-and-tooling.md) | Monorepo and tooling | accepted | 2026-11-03 |
| [0002](0002-deterministic-validator-is-the-source-of-truth.md) | Deterministic validator is the source of truth | accepted | 2026-11-03 |
| [0003](0003-semantic-invoice-model.md) | The invoice model follows the EN 16931 semantic model, not the XML syntax | accepted | 2026-11-03 |
| [0004](0004-ubl-schema-validation-layer.md) | UBL 2.1 schema validation: official schemas, confined loading, located violations | accepted | 2026-11-03 |
| [0005](0005-schematron-runner.md) | Schematron rule sets: executed as published with Saxon-HE, Peppol compiled with the ISO pipeline | accepted | 2026-11-03 |
| [0006](0006-srb-cius-rules-in-python.md) | SRB-CIUS rules: authored in Python, one rule per module, each cited and tested | accepted | 2026-11-04 |
| [0007](0007-calculation-rules-in-python.md) | EN 16931 calculation rules: recomputed in Python with CEN's semantics, proven equivalent | accepted | 2026-11-04 |
| [0008](0008-validation-pipeline-and-profiles.md) | The validation pipeline: fixed layer order, profiles that set aside published rules with reasons | accepted | 2026-11-04 |
| [0009](0009-command-line-interface.md) | Command-line interface: stdlib `argparse`, text and JSON output, exit codes 0/1/2 | accepted | 2026-11-04 |
| [0010](0010-fixture-corpus.md) | The fixture corpus: official SEF examples kept byte for byte, generated mutations, recorded verdicts | accepted | 2026-11-04 |
| [0011](0011-persistence-and-multi-tenant-schema.md) | Persistence: PostgreSQL through async SQLAlchemy, Alembic migrations, a schema keyed by organization | accepted | 2026-11-04 |
| [0012](0012-authentication-and-tokens.md) | Authentication: argon2id passwords, short-lived JWT access tokens, rotating refresh tokens | accepted, amended by 0013 | 2026-11-04 |
| [0013](0013-authorization-and-tenant-isolation.md) | Authorization: permissions per role, checked against the current membership, tenant isolation proven by tests | accepted | 2026-11-04 |

Planned (recorded when the work lands): hybrid retrieval and citation model (M2), job runner interface and SSE progress (M2), patch
model and forbidden-field guard (M3), OAuth 2.1 for MCP (M4), evaluation thresholds (M6).
