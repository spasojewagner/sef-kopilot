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
| [0008](0008-validation-pipeline-and-profiles.md) | The validation pipeline: fixed layer order, profiles that set aside published rules with reasons | accepted, amended by 0014 | 2026-11-04 |
| [0009](0009-command-line-interface.md) | Command-line interface: stdlib `argparse`, text and JSON output, exit codes 0/1/2 | accepted | 2026-11-04 |
| [0010](0010-fixture-corpus.md) | The fixture corpus: official SEF examples kept byte for byte, generated mutations, recorded verdicts | accepted | 2026-11-04 |
| [0011](0011-persistence-and-multi-tenant-schema.md) | Persistence: PostgreSQL through async SQLAlchemy, Alembic migrations, a schema keyed by organization | accepted | 2026-11-04 |
| [0012](0012-authentication-and-tokens.md) | Authentication: argon2id passwords, short-lived JWT access tokens, rotating refresh tokens | accepted, amended by 0013 and 0017 | 2026-11-04 |
| [0013](0013-authorization-and-tenant-isolation.md) | Authorization: permissions per role, checked against the current membership, tenant isolation proven by tests | accepted, amended by 0017 | 2026-11-04 |
| [0014](0014-hostile-documents-in-the-core.md) | Hostile documents in the core: linear addressing, bounded numbers and reports, whole values, a silent Saxon | accepted | 2026-11-04 |
| [0015](0015-validating-invoices-through-the-api.md) | Validating invoices through the API: XML bodies within limits, a child process with a time limit, nothing stored | accepted | 2026-11-04 |
| [0016](0016-stored-invoices.md) | Stored invoices: the document and its report in PostgreSQL, seen by organization and submitter, within a quota | accepted, amended by 0019 | 2026-11-04 |
| [0017](0017-api-keys.md) | API keys: a member's credentials for machine clients, narrowed to the work on invoices | accepted | 2026-11-04 |
| [0018](0018-rate-limits.md) | Rate limits: GCRA in the API's process, per address, per e-mail address, per caller and per organization | accepted | 2026-11-04 |
| [0019](0019-jobs-and-progress.md) | Jobs: a row that is the truth, fenced attempts that continue, inline or arq runners, progress over SSE | accepted | 2026-11-05 |
| [0020](0020-corpus-of-official-documents.md) | The corpus: official text as dated passages, made from pinned sources, kept in PostgreSQL | accepted | 2026-11-05 |
| [0021](0021-explanations-and-their-citations.md) | Explanations: the report's rules, passages found from the rule outward, an answer held to the passages it cites | accepted | 2026-11-05 |
| [0022](0022-explanations-name-no-value-of-their-own.md) | An explanation names no value its question does not contain | accepted | 2026-11-06 |
| [0023](0023-patches-and-the-fields-a-person-decides.md) | Patches: canonical places, the schema's order, and the fields a person decides | accepted | 2026-11-06 |
| [0024](0024-repairs-of-stored-invoices-and-the-audit-log.md) | Repairs of stored invoices: proposed by anyone, decided by a person, and audited | accepted | 2026-11-06 |

Planned (recorded when the work lands): the model's proposals of patches (M3), OAuth 2.1 for
MCP (M4), evaluation thresholds (M6).
