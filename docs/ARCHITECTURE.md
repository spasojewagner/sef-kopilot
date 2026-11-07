# Architecture

This document is the map of the system: what the pieces are, how data flows between them and
where each concern lives in the repository. It is kept current in the pull request that
changes the architecture; decisions and their trade-offs are recorded separately in
[`adr/`](adr/README.md). The product and engineering charter is [`BRIEF.md`](BRIEF.md).

Status: milestones M0 to M2 done (`v0.2.0`), M3 in progress. Sections marked *planned* describe the
target shape and are filled in as the milestones land.

## System context

```mermaid
flowchart LR
    ACC["Accountant / ERP vendor"] -->|browser| WEB["apps/web (Next.js)"]
    ERP["ERP system"] -->|HTTP API, API key| API["apps/api (FastAPI)"]
    AGENT["Claude / ChatGPT"] -->|MCP over HTTP, OAuth 2.1| API
    WEB -->|HTTP + SSE| API
    API --> CORE["packages/einvoice_core"]
    API --> DB[("PostgreSQL 16 + pgvector")]
    API -.->|SEF_JOBS=arq| REDIS[("Redis job queue")]
    REDIS -.-> WORKER["arq workers"]
    WORKER --> DB
    API -->|BYOK| LLM["LLM provider (Groq by default)"]
    API -.->|EMBEDDINGS_PROVIDER=jina| EMB["Jina embeddings API"]
    API -->|demo only| SEF["SEF demo environment"]
```

## The three layers (ADR-0002)

| Layer | Component | Trusts | Produces |
| --- | --- | --- | --- |
| 1 · Deterministic validator | `packages/einvoice_core` | XSD, EN 16931 + Peppol BIS Schematron, SRB-CIUS rules in code | `Violation {rule_id, severity, xpath, message}` |
| 2 · Explainer | `apps/api` (`rag`) | retrieved regulation chunks only | explanation (sr / en) with citations that must resolve |
| 3 · Repairer | `apps/api` (`repair`) + `einvoice_core` patch engine | patches as data, applied by code, re-validated by layer 1 | diff for human approval |

The language model sits between two deterministic walls and is never trusted; nothing leaves
the system without a green validator.

## Request flow (target, M2–M3)

1. Upload (`POST /invoices`) — limits on bytes, time and elements, hardened XML parsing (no DTD,
   no external entities). In no-store mode (`POST /invoices/validate`, ADR-0015) the bytes
   never touch the database.
2. Validate — in a child process of the API, one invoice at a time, stopped at a time limit
   (ADR-0015). Layer 1 runs XSD → Schematron → SRB-CIUS rules → arithmetic, in one call per
   profile (`srb`, `en16931`, `peppol`) that reports what a profile sets aside and why. Work
   that outlasts a request runs as a job (ADR-0019): its row in PostgreSQL is the truth, and it
   runs in the API's event loop or in arq workers on a Redis queue, behind the `JobRunner`
   interface, with its progress streamed over SSE (`GET /jobs/{id}/events`). The first job
   validates stored invoices again with the current rules (`POST /invoices/revalidations`);
   sending to SEF follows.
3. Explain (`POST /invoices/explain`, ADR-0021) — for each rule of the report, from its first
   violation: the passages the rule is authored from (ADR-0020), the specification's rows of
   the terms it names and of its place, the tax categories and codes it names, then `pg_trgm`
   words and pgvector meaning fused by rank, among the passages that apply on the invoice's
   day. The model answers a JSON schema whose citations can only be those passages' ids; the
   answer is checked again and sent back with the reason when it fails, three answers at most,
   and the response is built from the stored passages.
4. Repair — the model proposes patches `{xpath, op, value, reason}`, each at the canonical path
   of a violation (ADR-0023). The guard refuses any that touches an amount, VAT, a tax or company
   identifier, a date or the document's number, as needing a person's decision; code applies
   the rest where the UBL schema orders them; layer 1 validates the result under the same
   profile; the user sees a diff and approves; every step is written to the audit log. The
   patch engine is in the core (`einvoice patch`). A repair of a stored invoice is proposed by
   a member or an API key and applied to a copy in the validator's child process (ADR-0024);
   only a person approves it, onto the document it was proposed for, within the quota. The
   model proposes one on request (`POST /invoices/{id}/repairs/suggestion`, ADR-0025): it is
   sent the fatal violations and the invoice's fields around them, by canonical path; every
   answer is checked before it is applied; the validator's process applies each round and
   tells the model what became of each patch, two rounds at most within 20 s.
5. Send — the approved invoice goes to the SEF demo environment; status is polled; SEF error
   codes feed back into the same explanation pipeline.

## Repository map

| Path | Responsibility | Status |
| --- | --- | --- |
| `packages/einvoice_core` | parser, XSD, Schematron runner, SRB-CIUS rules, arithmetic, patch engine, CLI | M1 (`v0.1.0`): semantic model, hardened XML loading, UBL 2.1 parser, violation model, UBL 2.1 XSD validation, EN 16931 and Peppol BIS Schematron, SRB-CIUS rule set v1 (29 rules, ADR-0006), BR-CO arithmetic in Python (ADR-0007), validation pipeline with profiles (ADR-0008), `einvoice` CLI (ADR-0009), hostile documents: linear addressing, bounded numbers and reports, values read whole (ADR-0014). M3: the patch engine, with places named by canonical paths, the schema's order, the guard of the fields a person decides, and a repair that validates again and shows a diff, also as `einvoice patch` (ADR-0023); the fields around a place, which a repairer is shown (ADR-0025) |
| `apps/api` | HTTP API, auth and multi-tenancy, jobs, retrieval, explainer, repairer, SEF client, MCP server | M2 in progress: settings, PostgreSQL with Alembic migrations, the tenancy schema (ADR-0011), accounts, sign-in and tokens (ADR-0012), permissions, members and invitations (ADR-0013), invoice validation in a child process (ADR-0015), stored invoices with their reports, seen by organization and submitter, within a quota, listed by verdict (ADR-0016), API keys that act for a member within their role (ADR-0017), rate limits per address, account, caller and organization (ADR-0018), jobs with fenced attempts that continue from their progress, inline or on arq workers, followed over SSE, and the first of them, validating stored invoices again (ADR-0019); the corpus in PostgreSQL with pgvector and trigram indexes, its idempotent ingest with optional embeddings, and the passages each rule cites (ADR-0020); explanations of a report's rules in Serbian or English, from passages found by rule, term, place, code, words and meaning, through a language model behind `LLMClient` (Groq by default) whose citations are held to those passages (ADR-0021); `/health`, `/ready` (database and validator). M3: repairs of stored invoices proposed as patches, applied to a copy in the validator's child process and kept with what they did, approved or rejected by a person only, and an audit log without invoice content (ADR-0024); every request body other than an invoice bounded; repairs the language model proposes, from the fields around the violations, checked before they are applied, in two rounds (ADR-0025); explanations of a stored invoice's report, which is not validated again (ADR-0029); the API as an image, its rule sets compiled in and its migrations applied when it starts (ADR-0034) |
| `apps/web` | upload, report, explanations, diff and approval UI (sr-Latn / en) | M3: the shell. Every page in Serbian (Latin) and English, the language first in its path and each page rendered once per language; shadcn/ui components (`new-york`, Radix) in the repository; dark mode from the operating system; the API called from the browser through TanStack Query, and its status in the footer (ADR-0026); registration, sign-in and sign-out, with the access token in memory and the refresh token in local storage, refreshed by one tab at a time (ADR-0027); the invoices: upload, the list and the report, typed from the API's OpenAPI document that the repository keeps, and the report's page a static shell with the invoice's id streamed into it (ADR-0028); the rules' explanations with their citations, when the visitor asks (ADR-0029); the invoice's repairs, and each repair's page with what became of its patches, the API's diff and the report on the copy it leaves (ADR-0030); a repair asked of the language model from the report, refused for a reason the API names (ADR-0031); a person's approval or rejection on the repair's page, asked twice for an approval, and the repair read again when the outcome is unknown (ADR-0032); the golden path walked in Chromium by one Playwright test, against the production build and the API on a database of its own with a scripted model (ADR-0033) |
| `third_party/` | fetched UBL 2.1 schemas, EN 16931 and Peppol BIS artefacts, the ISO Schematron compiler, with their terms; compiled-stylesheet cache | M1 (UBL 2.1 and ISO Schematron added) |
| `corpus/` | the official documents explanations cite, as Markdown editions written by `scripts/build_corpus.py` from sources pinned by URL and SHA-256 in `manifest.toml` (the law and the rulebook on e-invoicing, the PIB rulebook, the SRB-CIUS specification, the tax categories); passages dated by edition, deferral and renumbering, and loaded with embeddings into `corpus_passages` (ADR-0020) | M2 |
| `fixtures/invoices/` | the Ministry's SEF examples (byte for byte, with provenance), synthetic invoices and generated mutations, the pipeline's recorded verdicts (ADR-0010); CEN's and OpenPeppol's examples are used from `third_party/`; never real company data | M1 |
| `evals/` | golden sets, runner, thresholds, latest report | planned (M6) |
| `infra/` | docker-compose for local PostgreSQL and Redis; Dockerfiles and deployment manifests | M0 (compose) |
| `scripts/` | rule-set fetcher, fixture generator, corpus converter, hook helpers, the API of the end-to-end test (ADR-0033) | M0 |
| `docs/` | brief, this document, ADRs, learning and interview notes, API docs | M0 |

## Cross-cutting concerns

- **Multi-tenancy:** every table that holds a tenant's data carries `organization_id`; people are
  global and belong to organizations through memberships with a role. Row-level access is
  enforced in the service layer and covered by tests that attempt cross-tenant requests
  (ADR-0011; every guarded endpoint has a cross-tenant test, ADR-0013).
- **Background work:** a job's row is the truth and a queue carries only its id; taking a job
  on counts an attempt, every later write requires the attempt to be the latest, and progress
  is written with the work it counts, so that a job delivered twice does its work once
  (ADR-0019).
- **No-store mode:** an invoice can be processed entirely in memory; nothing about its content
  reaches logs, traces, metrics or error reports in either mode.
- **The corpus:** official text in the repository, generated and checked against pinned sources,
  which a weekly job downloads afresh to find a text a publisher changed; passages carry the
  days they apply, and an id that names the first, so a citation never changes meaning. It is
  public data shared by every organization, so its tables carry no `organization_id`; only the
  ingest command writes them, and nothing leaves the server to embed it unless
  `EMBEDDINGS_PROVIDER` says so (ADR-0020).
- **The language model:** untrusted, and asked only about violations layer 1 reported in the
  same request. It is sent the first violation of each rule and public passages, never the
  document; an embedder is sent what the rules say, never what the invoice holds. Nothing
  leaves the server unless `LLM_PROVIDER` says so (ADR-0021).
- **Configuration:** environment variables only (`.env.example` lists the names); secrets are
  never committed; tenant SEF keys are encrypted at rest with Fernet.
- **Observability:** structured JSON logs with request ids, OpenTelemetry traces to Langfuse
  (LLM cost per invoice), Sentry for errors. *(planned, M4)*
- **Quality gates:** `pre-commit` locally and in CI (ADR-0001); coverage gates (core ≥ 90 %,
  API ≥ 80 %); one end-to-end test of the golden path in a browser, against the API with a
  scripted model, on every pull request (ADR-0033); evaluation thresholds gate CI from M6.
- **Deployment:** free tiers only — Render (API), Neon (PostgreSQL), Upstash (Redis),
  Cloudflare Pages (web), GitHub Actions and GHCR. Cold starts are expected and shown in the UI.
  *(planned, M3)*
