# Architecture decision records

Decisions that shape the system, in the [MADR](https://adr.github.io/madr/) format. A record
is immutable once merged; a changed decision gets a new record that supersedes the old one.
Start a new record from [`template.md`](template.md) and number it sequentially.

| ID | Title | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-monorepo-and-tooling.md) | Monorepo and tooling | accepted | 2026-11-03 |
| [0002](0002-deterministic-validator-is-the-source-of-truth.md) | Deterministic validator is the source of truth | accepted | 2026-11-03 |
| [0003](0003-semantic-invoice-model.md) | The invoice model follows the EN 16931 semantic model, not the XML syntax | accepted | 2026-11-03 |

Planned (recorded when the work lands): Schematron runner and compilation strategy (M1),
SRB-CIUS rule authoring format (M1), multi-tenant data model and row-level access (M2),
hybrid retrieval and citation model (M2), job runner interface and SSE progress (M2), patch
model and forbidden-field guard (M3), OAuth 2.1 for MCP (M4), evaluation thresholds (M6).
