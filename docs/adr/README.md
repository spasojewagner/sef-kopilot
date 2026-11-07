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
| [0025](0025-repairs-the-model-proposes.md) | Repairs the model proposes: the fields around the violations, checked patches, two rounds | accepted | 2026-11-06 |
| [0026](0026-the-web-application-shell.md) | The web application: the language in the path, shadcn/ui in the repository, the browser calling the API | accepted | 2026-11-06 |
| [0027](0027-a-visitors-tokens-in-the-browser.md) | A visitor's tokens in the browser: the access token in memory, the refresh token in local storage, one refresh at a time | accepted | 2026-11-06 |
| [0028](0028-the-apis-contract-and-the-pages-of-invoices.md) | The API's contract in the repository, the web application's types generated from it, and an invoice's page as a static shell | accepted | 2026-11-06 |
| [0029](0029-explanations-of-a-stored-invoice.md) | Explanations of a stored invoice: its report explained, when the visitor asks | accepted, amended by 0040 | 2026-11-06 |
| [0030](0030-a-repairs-page.md) | A repair's page: the API's diff and report, read as it keeps them | accepted | 2026-11-07 |
| [0031](0031-a-repair-asked-of-the-model-from-the-page.md) | A repair asked of the model from the page, and a reason in every conflict | accepted | 2026-11-07 |
| [0032](0032-a-persons-decision-on-the-repairs-page.md) | A person's decision on a repair's page: asked twice, and read again when unknown | accepted | 2026-11-07 |
| [0033](0033-one-end-to-end-test-of-the-golden-path.md) | One end-to-end test of the golden path, against the API with a scripted model | accepted | 2026-11-07 |
| [0034](0034-the-apis-image.md) | The API's image: the lock file's dependencies, rule sets compiled in, migrations at start | accepted | 2026-11-07 |
| [0035](0035-the-public-demos-hosting.md) | The public demo: the web application on Vercel, the API on Render, its database on Neon | accepted | 2026-11-07 |
| [0036](0036-the-pages-wait-for-a-sleeping-api.md) | The pages wait for a sleeping API, and say that it is waking up | accepted | 2026-11-07 |
| [0037](0037-the-public-demo-asks-for-synthetic-invoices.md) | The public demo asks for synthetic invoices, by a setting of the API | accepted | 2026-11-07 |
| [0038](0038-finished-jobs-are-deleted-after-thirty-days.md) | Finished jobs are deleted after thirty days, where they run | accepted | 2026-11-07 |
| [0039](0039-an-organization-sets-how-long-it-keeps-its-invoices.md) | An organization sets how long it keeps its stored invoices | accepted | 2026-11-07 |
| [0040](0040-explanations-are-kept-by-the-digest-of-their-report.md) | Explanations of a stored invoice are kept with it, by the digest of the report they explain | accepted | 2026-11-07 |
| [0041](0041-what-the-rules-say-is-embedded-once.md) | What the rules say is embedded once an embedding model, and kept | accepted | 2026-11-07 |
| [0042](0042-the-mcp-server-lives-in-the-apis-process.md) | The MCP server lives in the API's process and answers without sessions | accepted | 2026-11-07 |

Planned (recorded when the work lands): OAuth 2.1 for MCP (M4), evaluation thresholds (M6).
