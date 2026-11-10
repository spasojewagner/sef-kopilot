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
| 20 | [A loop around an untrusted model: copy, check, apply, tell](20-a-loop-around-an-untrusted-model.md) | M3 |
| 21 | [CORS: which pages may read the API's answers](21-cors.md) | M3 |
| 22 | [Server and client components: what runs where](22-server-and-client-components.md) | M3 |
| 23 | [Tokens in a browser: where to keep them, and what can reach them there](23-tokens-in-a-browser.md) | M3 |
| 24 | [One contract, two languages: the API's OpenAPI document and the web application's types](24-one-contract-two-languages.md) | M3 |
| 25 | [A static shell with a hole: a page whose address the build cannot know](25-a-static-shell-with-a-hole.md) | M3 |
| 26 | [A read that costs: POST, asked for on purpose, kept once paid for](26-a-read-that-costs.md) | M3 |
| 27 | [Reading a unified diff, and what its numbers count](27-reading-a-unified-diff.md) | M3 |
| 28 | [A request that creates: a mutation, and what the cache learns from its answer](28-a-request-that-creates.md) | M3 |
| 29 | [A write whose outcome is unknown: read before you write again](29-a-write-whose-outcome-is-unknown.md) | M3 |
| 30 | [An end-to-end test for the seams: what only it can catch, and how it stays steady](30-an-end-to-end-test-for-the-seams.md) | M3 |
| 31 | [An image built once, started many times](31-an-image-built-once-started-many-times.md) | M3 |
| 32 | [A warm cache hides a cold path: test the path the platform takes](32-a-warm-cache-hides-a-cold-path.md) | M3 |
| 33 | [Waking or down: a cold start, seen from the browser](33-waking-or-down.md) | M3 |
| 34 | [Where an error is answered decides what it carries: middleware as an onion](34-where-an-error-is-answered.md) | M3 |
| 35 | [The Model Context Protocol: tools a model may call, over plain HTTP](35-the-model-context-protocol.md) | M4 |
| 36 | [Colour you can read: OKLCH and the contrast ratio](36-colour-you-can-read.md) | M4 |
| 37 | [Motion with its end first: an animation that hides nothing](37-motion-with-its-end-first.md) | M4 |
| 38 | [A consent a person can trust: what the page shows, and what it refuses](38-a-consent-a-person-can-trust.md) | M4 |
| 39 | [OAuth 2.1 for an MCP server: from a 401 to a tool call](39-oauth-for-an-mcp-server.md) | M4 |
| 40 | [Fetching an address a stranger gave you: SSRF and DNS rebinding](40-fetching-an-address-a-stranger-gave-you.md) | M4 |
| 41 | [Asking for more scope: the step-up](41-asking-for-more-scope.md) | M4 |
| 42 | [A secret at rest: sealing a tenant's key so that a copy of the database opens nothing](42-a-secret-at-rest.md) | M5 |
| 43 | [Sending once over a network that loses answers: the request id](43-sending-once-over-a-network-that-loses-answers.md) | M5 |
| 44 | [A measure is only as good as its labels: golden sets and the reference](44-a-measure-is-only-as-good-as-its-labels.md) | M6 |
| 45 | [Measuring a model offline: cassettes](45-measuring-a-model-offline-with-cassettes.md) | M6 |
| 46 | [A balance is a sum of entries](46-a-balance-is-a-sum-of-entries.md) | M6 |
| 47 | [A webhook is a request anyone can send](47-a-webhook-is-a-request-anyone-can-send.md) | M6 |
