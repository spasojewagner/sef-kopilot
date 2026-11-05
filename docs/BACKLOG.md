# Backlog

Milestones, branches and deliverables from [`BRIEF.md`](BRIEF.md) §6, tracked as checkboxes.
Items are ticked in the pull request that delivers them. Issue numbers are added when the
maintainer mirrors an item to GitHub Issues.

Legend: `[ ]` not started · `[~]` in progress · `[x]` done

## M0 — Bootstrap (days 1–2) · branch `chore/bootstrap`

- [x] `chore(repo): initial commit` on `main`: `.gitignore`, `.gitattributes`, `.editorconfig`,
      `LICENSE` (Apache-2.0), `README.md`, `CHANGELOG.md`, `docs/BRIEF.md`, `CLAUDE.md` =
      `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/BACKLOG.md`, `docs/SESSIONS.md`
- [x] uv workspace with `packages/einvoice_core` (one passing test)
- [x] `apps/api` FastAPI hello world with `GET /health` and `GET /ready` (passing tests)
- [x] `apps/web` Next.js scaffold with one passing Vitest test
- [x] `pre-commit` configuration with all hooks (ruff, ruff-format, mypy, eslint, prettier,
      gitleaks, conventional commit message check)
- [x] GitHub Actions `ci.yml`: lint, type, test and gitleaks jobs for api, core and web
- [x] `infra/docker-compose.yml` with PostgreSQL 16 + pgvector and Redis
- [x] `scripts/fetch_rulesets.py` pulling EN 16931 and Peppol BIS rule sets into `third_party/`
      with their licenses, plus a `make rulesets` target
- [x] ADR-0001 "Monorepo and tooling", ADR-0002 "Deterministic validator is the source of truth"
- [x] `.github/PULL_REQUEST_TEMPLATE.md` and issue templates
- [x] README status badges

## M1 — Validator core (weeks 1–2) · tag `v0.1.0`

- [x] `feat/core-ubl-parser` — UBL 2.1 parser into typed Pydantic models (ADR-0003)
- [x] `feat/core-xsd-validation` — XSD validation with hardened `lxml` parsing (ADR-0004)
- [x] `feat/core-schematron-runner` — EN 16931 and Peppol BIS Schematron via `saxonche`, compiled once and cached (ADR-0005)
- [x] `feat/core-srb-cius-rules` — SRB-CIUS rule framework (one rule per module, cited, tested) and the first nine rules: document codes, identifiers, PIB check digits (ADR-0006)
- [x] `feat/core-srb-cius-party-rules` — legal registration numbers (BT-30, BT-47, BT-61), the seller's VAT status (BT-32, `RS-VAT-STATUS`), cities and post codes (BT-37, BT-38, BT-52, BT-53, BT-66, BT-67), preceding invoice date (BT-26), delivery date when BT-8 requires it (BT-72), public-procurement reference (BT-10), payment model notation (BT-83)
- [x] `feat/core-srb-cius-vat-rules` — VAT categories, rates and exemption codes from the Ministry's code list (BT-95, BT-102, BT-118, BT-119, BT-121, BT-151)
- [x] `feat/core-srb-cius-extension-rules` — the Serbian extension (Table 2): advance payments used on final invoices, reduced totals, RSD amounts of foreign-currency invoices, the extended specification identifier
- [x] `feat/core-arithmetic-rules` — BR-CO-10 to BR-CO-17 in Python with CEN's semantics, differential property-based test against CEN's XSLT (ADR-0007)
- [x] Violation model `{rule_id, severity, xpath, message}`
- [x] `feat/core-validation-pipeline` — one call for all layers: XSD, then Schematron only for schema-valid documents, SRB-CIUS and arithmetic; profiles `srb`, `en16931`, `peppol`; the SRB profile sets aside, with reasons, the EN 16931 rules SRB-CIUS widens; one violation limit (ADR-0008)
- [x] `feat/core-cli` — `einvoice validate file.xml --profile srb` on the pipeline: text and JSON output, exit codes, `einvoice rules` to list the rules of a profile (ADR-0009)
- [x] `feat/core-fixtures-corpus` — the Ministry's 17 SEF examples committed with their provenance, 43 generated mutation fixtures (`scripts/make_fixtures.py`), the pipeline's recorded verdicts on 93 documents; with CEN's and OpenPeppol's 1 471 unit-test documents, over 1 500 in all (ADR-0010)
- [x] Learning notes: ~~Schematron and XPath assertions~~ (03), ~~UBL 2.1 document model~~ (02), ~~EN 16931 business rules vs. CIUS~~ (04), ~~golden files and mutation fixtures~~ (05)
- [x] Release: changelog move, version bump, `v0.1.0` tag prepared

## M2 — API + explanations (weeks 3–4) · tag `v0.2.0`

- [x] `feat/api-settings-database` — settings from the environment, async PostgreSQL (SQLAlchemy 2 + asyncpg), Alembic with organizations, users and memberships (`owner`, `accountant`, `client`), `/ready` on the database, test databases, a PostgreSQL service in CI (ADR-0011)
- [x] `feat/api-auth-tokens` — email + password (argon2id), JWT access tokens and rotating refresh tokens with reuse detection; registration creates an organization and its owner (ADR-0012)
- [x] `feat/api-rbac-members` — permissions per role checked against the current membership, the members of an organization (roles, removal, the last-owner rule), invitations with one-time codes, a route audit and a cross-tenant case for every guarded endpoint (ADR-0013)
- [x] `fix/core-hostile-documents` — addressing in linear time, numbers of at most 28 digits computed exactly, values read whole when a comment splits them, reports bounded by the violation limit, Saxon's warnings off the error stream (ADR-0014; found by the reviews of the invoice endpoint)
- [x] `feat/api-invoices-validate` — `POST /invoices/validate`: an XML body within limits on bytes, time and elements, the validator's own report, nothing stored (the no-store mode); the validator in a child process with a time limit, admission, `/ready` on the validator (ADR-0015)
- [x] `feat/api-invoices-store` — invoices and their reports kept per organization: store, list a page at a time, read, download and delete; a client sees what they submitted; a storage quota per organization (ADR-0016)
- [x] `feat/api-keys` — API keys for machine clients (ERPs): 256 random bits shown once and kept as a digest, acting for the member who issued them with chosen invoice permissions within the member's role, revoked by the member or an owner, deleted with the membership; a cross-tenant case with another organization's key for every endpoint; credentials kept out of caches (ADR-0017)
- [x] `feat/api-rate-limits` — rate limits in the API's process (GCRA): sign-in, registration, refresh and accepting invitations per address, wrong passwords per e-mail address, validations per caller and per organization (429 with `Retry-After`; ADR-0018)
- [x] `feat/api-jobs-sse` — jobs whose row is the truth, with fenced attempts that continue from their progress; inline or on `arq` workers with a sweep, behind `JobRunner`; the first job validates stored invoices again within the quota; progress over SSE, resumable with `Last-Event-ID` (ADR-0019)
- [x] `feat/rag-corpus-ingest` — the corpus: the law and the rulebook on e-invoicing, the PIB rulebook, the SRB-CIUS specification and the tax categories as Markdown editions made from sources pinned by URL and SHA-256 (`scripts/build_corpus.py`); passages dated by edition, deferral and renumbering, with ids that name their first day; `corpus_passages` with pgvector and trigram indexes, an idempotent ingest that embeds with Jina when configured, and the passages each SRB-CIUS rule cites (ADR-0020)
- [ ] The SEF internal technical instruction (Interno tehničko uputstvo) in the corpus, once its official text can be pinned like the others
- [ ] A scheduled CI job that downloads the corpus's sources and reports a digest that changed (a new edition to review)
- [x] `feat/rag-explain-citations` — `POST /invoices/explain`: each rule of a report explained once, in Serbian or English, from the passages that apply on the invoice's day, found by the rule's references, its terms, its place, its codes, then words and meaning fused by rank; a strict JSON schema whose citations can only be those passages' ids, checked again and sent back with the reason, three answers at most; Groq's `openai/gpt-oss-120b` behind `LLMClient`; limits per caller and organization, a time limit, nothing stored (ADR-0021)
- [ ] An explanation's latency with a live Groq key measured against the budget (< 6 s) and noted in the API's README
- [x] `feat/api-invoices-by-verdict` — stored invoices listed by the verdict of their latest report (`GET /invoices?valid=false`), to find the invoices a revalidation judged invalid; the invalid ones through a partial index built concurrently (migration 0009)
- [ ] Finished jobs deleted after a period, with the retention of stored invoices (`SECURITY.md`, V14): how long accounting documents are kept is the maintainer's decision, not the code's
- [x] Learning notes: ~~hybrid retrieval~~ (16), ~~law that changes: dated passages~~ (15), ~~SSE vs. WebSockets~~ (13), ~~idempotent job design~~ (14), ~~Alembic migration safety~~ (06), ~~access and refresh tokens~~ (07), ~~authorization in a multi-tenant API~~ (08), ~~hostile uploads~~ (09), ~~scopes, pages and quotas~~ (10), ~~API keys~~ (11), ~~rate limits~~ (12)
- [ ] Release: `v0.2.0`

## M3 — Repair loop + web UI (weeks 5–6) · tag `v0.3.0`

- [ ] `feat/repair-patch-engine` — patch model, forbidden-field guard, apply → revalidate → diff
- [ ] `feat/repair-loop-audit` — approval flow and audit log
- [ ] `feat/web-bootstrap` — Next.js app shell, shadcn/ui, TanStack Query, `next-intl` (sr-Latn default, en)
- [ ] `feat/web-upload-report` — upload, report, violation detail with citations
- [ ] Explanations of a stored invoice kept with its report, written once by a job and read with the invoice; the embeddings of what the rules say kept for reuse
- [ ] `feat/web-diff-approve` — diff view, approval, history
- [ ] `chore/infra-deploy` — public demo on Render + Neon + Upstash + Cloudflare Pages, "waking up" state for cold starts
- [ ] Playwright smoke test for the golden path (upload → report → fix → approve)
- [ ] Release: `v0.3.0`

## M4 — MCP + OAuth 2.1 (week 7) · tag `v0.4.0`

- [ ] Langfuse and Sentry wiring; structured JSON logs with security events (sign-in, API key use, and when each key was last used) — moved here from M2, after the public demo of M3
- [ ] A local multilingual embedding model (BGE-M3, 1024 numbers) behind the `Embedder` adapter, for a self-hosted deployment that makes no call to embed
- [ ] `feat/mcp-server` — MCP server (Streamable HTTP at `/mcp`) with `validate_invoice`, `explain_errors`, `propose_fix`, `revalidate`, `search_rules`, `send_to_sef_demo`
- [ ] `feat/mcp-oauth21` — OAuth 2.1 with PKCE, RFC 9728, RFC 8414, RFC 8707, RFC 7591; scopes per tool
- [ ] Demo from Claude and ChatGPT documented with screenshots
- [ ] Learning note: OAuth 2.1 flows for MCP
- [ ] Release: `v0.4.0`

## M5 — SEF demo round trip (week 8) · tag `v0.5.0`

- [ ] `feat/sef-demo-client` — SEF demo client, encrypted per-tenant key, send + status polling
- [ ] `feat/sef-error-mapping` — SEF error codes mapped into the explanation pipeline; Peppol profile polish
- [ ] Confirm against the SEF demo what the published documents leave open: the warning-level SRB rules (SRB-013, SRB-017, SRB-023, SRB-029), the set-asides that rest on the Ministry's examples (ADR-0008), and whether SEF requires a due date or payment terms when an amount is due (EN 16931 BR-CO-25, absent from CEN's UBL Schematron; ADR-0010)
- [ ] Release: `v0.5.0`

## M6 — Evals, CI gate, billing (week 9) · tag `v0.6.0`

- [ ] `feat/evals-harness` — golden sets, eval runner, `evals/thresholds.yaml`, offline cassettes
- [ ] `ci/evals-gate` — CI fails below thresholds; README badge from the latest report
- [ ] `feat/billing-stripe-sandbox` — Stripe sandbox credits per invoice, verified webhooks
- [ ] OpenAI and Anthropic adapters behind `LLMClient` (the operator's key, `LLM_PROVIDER=openai|anthropic`), and an organization's own key kept encrypted like its SEF key (BYOK), compared on the evaluation set
- [ ] Release: `v0.6.0`

## M7 — PDF beta, case study, 1.0 (week 10) · tag `v1.0.0`

- [ ] `feat/pdf-extraction-beta` — PDF → UBL extraction with a review step, clearly marked beta
- [ ] `docs/readme-case-study` — final README (problem, demo GIF, architecture diagram, numbers, how to run, how to self-host), 90-second demo video script, `docs/CASE_STUDY.md`
- [ ] `chore/release-1.0` — security review pass, `v1.0.0`
