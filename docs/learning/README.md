# Learning notes

Short notes (one page or less, a diagram where it helps) on the concepts this project is
built on. They exist so that every decision in the code can be explained and defended, not
just used. New notes are added in the pull request that introduces the concept.

| # | Note | Introduced in |
| --- | --- | --- |
| 01 | [uv workspaces, src layout and pre-commit](01-monorepo-uv-workspaces-and-pre-commit.md) | M0 |
| 02 | [UBL 2.1, EN 16931 and how the two relate](02-ubl-2-1-document-model.md) | M1 |
| 03 | [Schematron and XPath assertions](03-schematron-and-xpath-assertions.md) | M1 |
| 04 | [EN 16931 business rules vs. a CIUS](04-en16931-business-rules-vs-a-cius.md) | M1 |
| 05 | [Golden files and mutation fixtures](05-golden-files-and-mutation-fixtures.md) | M1 |
| 06 | [Alembic migration safety](06-alembic-migration-safety.md) | M2 |
| 07 | [Access tokens, refresh tokens and rotation](07-access-and-refresh-tokens.md) | M2 |
| 08 | [Authorization in a multi-tenant API](08-authorization-in-a-multi-tenant-api.md) | M2 |
| 09 | [Hostile uploads: bytes, XML and the work they cause](09-hostile-uploads-and-xml.md) | M2 |
| 10 | [Keeping a tenant's data: scopes, pages and quotas](10-scopes-pages-and-quotas.md) | M2 |
| 11 | [Credentials for machines: API keys](11-api-keys.md) | M2 |
| 12 | [Rate limits: what to count, by which key, and how](12-rate-limits.md) | M2 |
| 13 | [Server-sent events vs. WebSockets](13-server-sent-events-vs-websockets.md) | M2 |
| 14 | [Idempotent jobs: delivered at least once, done once](14-idempotent-jobs.md) | M2 |
| 15 | [Law that changes: editions, valid time and ids that stay](15-dated-passages-of-changing-law.md) | M2 |
| 16 | [Hybrid retrieval: from the rule outward, then words and meaning fused by rank](16-hybrid-retrieval.md) | M2 |
| 17 | [Partial indexes: an index of the few rows a query looks for](17-partial-indexes.md) | M2 |
| 18 | [Patches at canonical paths: where a change goes, and why order matters](18-patches-at-canonical-paths.md) | M3 |
| 19 | [Audit logs: who did what, without what it said](19-audit-logs-without-content.md) | M3 |

Planned: OAuth 2.1 flows for MCP.
