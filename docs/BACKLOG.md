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
- [x] `ci/corpus-sources-check` — a scheduled CI job that downloads the corpus's sources each Monday and fails when a digest changed (a new edition to review)
- [x] `feat/rag-explain-citations` — `POST /invoices/explain`: each rule of a report explained once, in Serbian or English, from the passages that apply on the invoice's day, found by the rule's references, its terms, its place, its codes, then words and meaning fused by rank; a strict JSON schema whose citations can only be those passages' ids, checked again and sent back with the reason, three answers at most; Groq's `openai/gpt-oss-120b` behind `LLMClient`; limits per caller and organization, a time limit, nothing stored (ADR-0021)
- [x] An explanation's latency with a live Groq key measured against the budget (< 6 s) and noted in the API's README: 1.5 s for an invoice with one rule to explain (6 November 2026)
- [x] `feat/api-invoices-by-verdict` — stored invoices listed by the verdict of their latest report (`GET /invoices?valid=false`), to find the invoices a revalidation judged invalid; the invalid ones through a partial index built concurrently (migration 0009)
- [x] Learning notes: ~~hybrid retrieval~~ (16), ~~law that changes: dated passages~~ (15), ~~SSE vs. WebSockets~~ (13), ~~idempotent job design~~ (14), ~~Alembic migration safety~~ (06), ~~access and refresh tokens~~ (07), ~~authorization in a multi-tenant API~~ (08), ~~hostile uploads~~ (09), ~~scopes, pages and quotas~~ (10), ~~API keys~~ (11), ~~rate limits~~ (12)
- [x] Release: changelog move, version bump, `v0.2.0` tag prepared

## M3 — Repair loop + web UI (weeks 5–6) · tag `v0.3.0`

- [x] `feat/repair-patch-engine` — patch model, forbidden-field guard, apply → revalidate → diff
- [x] `feat/repair-proposals` — repairs of stored invoices proposed as patches by a member or an API key, applied to a copy in the validator's child process and kept with what they did; the audit log; every request body other than an invoice bounded (split from `feat/repair-loop-audit`)
- [x] `feat/repair-approval` — a person approves or rejects a repair, never an API key; approval applies the patches again to the document they were proposed for and replaces the invoice within the quota; the other proposals are superseded; both decisions in the audit log
- [x] `feat/repair-model-loop` — the model proposes patches for a report's violations, checked as explanations are (no value of its own), within the 20 s budget, through the same proposals and approval
- [x] `feat/web-bootstrap` — Next.js app shell, shadcn/ui, TanStack Query, `next-intl` (sr-Latn default, en); the API's CORS for the web application's origins
- [x] `feat/web-sign-in` — register, sign in (choosing the organization) and sign out; the tokens in the browser (ADR-0027). Split from `feat/web-upload-report`, because every endpoint of invoices needs a token
- [x] `feat/web-upload-report` — upload an invoice, read its report, list the organization's invoices; the API's OpenAPI document in the repository and the web application's types generated from it (ADR-0028). A violation's explanation and citations split to `feat/web-explanations`, to keep the pull request reviewable
- [x] `feat/web-explanations` — on the report's page, each rule's explanation in the page's language, with its dated citations, when the visitor asks; `POST /invoices/{invoice_id}/explanations` explains the stored report without validating the invoice again and counts as a request to the language model alone (ADR-0029); an API without a language model says so
- [x] `fix/api-unexpected-errors-readable` — an unexpected failure (500) the web application can read: Starlette answered it outside every middleware, so it had no CORS headers and a page saw only a network error; a middleware inside the others now answers it, and raises it again for the server's log (found in `feat/web-bootstrap`)
- [x] `fix/rag-explanations-invent-no-values` — a fix names no value the invoice does not have: the first live answer to SRB-009 gave a corrected PIB "for example", which the prompt forbids. A deterministic check of the numbers an answer names, sent back as feedback, and the model's non-breaking hyphens (`BT‑31`) written as plain ones, so that a search for `BT-31` finds them
- [x] `fix/api-json-charset` — JSON answers declare `charset=utf-8`: Windows PowerShell 5.1 reads a JSON body without one as ISO-8859-1 and garbles č, ć, š, ž and the model's quotation marks
- [x] `fix/web-header-phone` — the signed-in header fits a phone: the name on one line, the account's address giving way first, and below 640 px the languages in the footer; their place kept until their links stream in, so that nothing beside them moves (found in `feat/web-repairs`)
- [x] `feat/web-repairs` — the repairs of a stored invoice, listed on its report, and each repair's page: who proposed it and who decided, what became of each patch, the API's diff without its numbers, and the report on the copy it leaves (ADR-0030). Split from `feat/web-diff-approve`, to keep the pull request reviewable
- [x] `feat/web-repair-suggestion` — ask the language model for a repair from an invalid invoice's report, and open the repair it writes; say why there is none, by the reason every 409 of the repairs now names (ADR-0031)
- [x] `fix/repair-patches-that-change-nothing` — the repairer keeps no patch that writes the value already there (applied, changing nothing), so that a suggestion of nothing else answers 422 instead of waiting for a decision that cannot approve it, and the model is told (found in `feat/web-repair-suggestion`)
- [x] `feat/web-diff-approve` — approve or reject a repair on its page, in person, an approval asked twice; the invoice, its report, its repairs and the list's verdicts read again; why the API refuses, by the conflict's reason; the repair read again when the outcome is unknown (ADR-0032)
- [x] `build/api-container` — the API as an image: the lock file's dependencies, the rule sets checked by their pins and compiled while it is built, the migrations applied when a container starts, a user that owns no file; a CI job builds it, starts it on a database and validates an invoice through it (ADR-0034)
- [x] `chore/infra-deploy` — the public demo: the API on Render from `render.yaml`, its database on Neon, the web application on Vercel instead of Cloudflare Pages, since the report's page needs a server for its id; no Upstash until there are workers (ADR-0035, `docs/DEPLOY.md`). First deployed on 2026-11-07: the web application at <https://sef-kopilot.vercel.app>, the API at <https://sef-kopilot-api.onrender.com>
- [x] `fix/api-image-fetches-rule-sets` — the first build on Render failed: a clone holds no rule sets, and the image's build fetched three of them with git, which its stage lacked; CI had given its build the rule sets from its cache, and now gives it what a clone holds (found in the first deploy)
- [x] `docs/infra-first-deploy` — what the first deploy needed, folded into the runbook: the GitHub apps of Vercel and Render given access to the repository, Neon's pooled host told apart, the database's URL read for the corpus without being shown; the README links the live demo
- [x] `feat/web-api-waking-up` — the pages say that the API is waking up, and wait, rather than that it does not answer, while a free instance starts (about a minute): a request asks `/health` first when the API has not answered for ten minutes, for up to two minutes, and is then sent once; the footer and a notice above the page say so after three seconds (ADR-0036)
- [x] `feat/web-demo-upload-notice` — a notice on the public demo's upload: synthetic invoices only, since an explanation or a repair sends violations and fields to the model's provider; `SEF_PUBLIC_DEMO` in `render.yaml`, reported by `GET /health`, with a link to the repository's synthetic invoices (ADR-0037)
- [x] `test/web-golden-path` — Playwright smoke test for the golden path (upload → report → fix → approve): one test in Chromium against the production build and the API, which starts on a database made anew with a scripted model; a CI job on every pull request (ADR-0033)
- [x] `test/api-settings-without-the-environment` — the API's test applications read the developer's environment and `.env`, though `settings_for` said they did not (`Settings.model_validate` reads both); they are built from the values given alone, with `Settings.from_values()`, as the OpenAPI exporter and the end-to-end test's launcher are (found in `test/web-golden-path`)
- [x] Release: `v0.3.0` (2026-11-07). Retention and the explanations kept with a stored invoice's report moved to M4, the maintainer's decision: the milestone's goal, the repair loop with approval, the web application and the public demo, is met and live, and neither of the two shows on the demo

## M4 — MCP + OAuth 2.1 (week 7) · tag `v0.4.0`

- [x] `feat/api-job-retention` — finished jobs deleted 30 days after they end (`SEF_JOB_RETENTION_DAYS`, 30), never one under way; where the jobs run, at the start and then every six hours (the API's process) or every day (a worker) (ADR-0038; retention moved from M2, then from M3 on 2026-11-07; decided 2026-11-06)
- [x] `feat/api-invoice-retention` — stored invoices kept until their organization sets a retention period of its own, none by default (decided 2026-11-06): `organizations.invoice_retention_days`, 1 to 3 650 days; `GET /organization` for every member and `PATCH /organization` for owners (`organization:read`, `organization:manage`, no key), checked again under the organization's lock and recorded in the audit log with what the period was; the deletion is one statement, where and when old jobs are deleted, and the audit log keeps its events (ADR-0039; `SECURITY.md`, V14)
- [x] `feat/web-organization-settings` — the organization's page, `/organization`, linked from the header (an icon on a phone): every member sees the organization, their role as the API reports it and how long invoices are kept; an owner sets the period, asked twice when it deletes and told the day up to which stored invoices go; an unknown outcome read again, a refusal followed by the role read again
- [x] `feat/api-explanations-kept` — the explanations of a stored invoice's report kept with it, one set a language, by the digest of the report and the day whose law they cite; read again by `POST` and by `GET /invoices/{invoice_id}/explanations` without asking the model or counting, until the report is another; only whole sets; written in the request, not by a job (ADR-0040, amending ADR-0029; moved from M3 on 2026-11-07)
- [x] `feat/web-explanations-kept` — the report's page reads the kept explanations as it opens (`GET`, which asks the model nothing) and shows them at once; the offer to ask the model only when none are kept; one cache key for the kept and the written; nothing shown while reading
- [x] `perf/rag-rule-embeddings-kept` — what each rule says embedded once an embedding model and kept in `rule_embeddings`, keyed by the model and the text's digest, public and of no organization; two rules that say the same ask once; a failing or late embedder keeps nothing new (ADR-0041)
- [ ] Langfuse and Sentry wiring; structured JSON logs with security events (sign-in, API key use, and when each key was last used) — moved here from M2, after the public demo of M3
- [ ] A local multilingual embedding model (BGE-M3, 1024 numbers) behind the `Embedder` adapter, for a self-hosted deployment that makes no call to embed
- [x] `feat/mcp-server` — the MCP server at `/mcp`, in the API's process (ADR-0042): Streamable HTTP without sessions, every message a POST answered with JSON, for clients of the protocol's 2026-07-28 revision and earlier ones; an API key admits a client until OAuth 2.1, an access token of the web application is refused, a page of another origin too, and only POST is answered; each tool requires its route's permission, pinned by a test, and counts against the route's limits; the first tool, `validate_invoice`, does what `POST /invoices/validate` does (split on 2026-11-07: the other tools follow, one reviewable change each)
- [x] `feat/web-brand` — the brand, at the maintainer's request (2026-11-07): ink navy and one teal accent as tokens under shadcn/ui's names, in light and dark, their contrast tested against WCAG 2.2 AA; Onest and JetBrains Mono from the packages' files; the mark, a compass bezel whose needle is a check, as the favicon and the home-screen icon; the header on the navy, with a member's sections and the current one marked, and a link past it to the one `main` (ADR-0043)
- [x] `feat/web-landing` — the home page as the product's page: what it does, beside an example of a report that tells its story once, the end shown without motion; the course an invoice takes; the rule sets; the HTTP API and the MCP server at the build's API; the synthetic invoices to try it on; the image a shared link shows, at `SITE_URL` off Vercel
- [x] `feat/web-app-restyle` — the application's pages in the brand's look: states as tints that keep 4.5:1 (tested as a browser mixes them), a report and a repair opening with their summary under the way back, the validator's layers as a checklist beside the rules, the upload's field, the framed list and its empty state, signing in beside the navy, the 404
- [x] `feat/mcp-explain-errors` — `explain_errors` does what `POST /invoices/explain` does: the report and an explanation of each rule it names, in Serbian or English, with its citations; counted as a validation and a request to the language model, storing nothing; refused before counting on a server without a model
- [x] `feat/mcp-oauth-clients` — the first step of OAuth 2.1 for the MCP endpoint (ADR-0044, the API's own authorization server, for public clients only): `SEF_PUBLIC_URL`, and clients registering themselves (RFC 7591, migration 0015), with the redirect URIs OAuth 2.1 allows, counted by address (OAuth 2.1 moved up on 2026-11-07: assistants that sign in their users connect only with it; split into steps)
- [x] `feat/mcp-oauth-authorization` — the authorization endpoint (PKCE S256, RFC 8707 `resource`, scopes per tool), the request a person decides on for ten minutes at `SEF_WEB_URL`, approved for the scopes their role grants or refused, and the code a consent issues, for two minutes, recorded in the audit log (migration 0016); the issuer in every answer (RFC 9207)
- [x] `feat/web-oauth-consent` — the web application's page where a signed-in person lets a client act for them, or not: what it asks, its unchecked name, the host it takes them back to and the organization it will work in; signing in on the page; no page framed by another site (RFC 9700 §4.16); language links that keep the query; the golden path ends with a client's request allowed
- [x] `fix/web-credentials-post` — a sign-in or a registration sent before the page's script has loaded is the browser's own GET of the form, with the password in the address, the history and the host's logs; the button waits for the script, and the forms are posted (found in `feat/web-oauth-consent`)
- [x] `feat/mcp-oauth-tokens` — the token endpoint: a consent's code exchanged once, with its PKCE verifier, for an access token whose audience is the MCP endpoint (a JWT signed with a key of its own) and, for a client that registered the grant, a refresh token spent once for the next pair; a code or refresh token presented again revokes the consent; the role read again at each exchange (migration 0017); reviewed on its own (split on 2026-11-07: the MCP endpoint's side follows)
- [x] `feat/mcp-oauth-resource` — the MCP endpoint accepting these tokens with the scopes they carry, the consent and the role read again on every request; the metadata documents (RFC 9728, RFC 8414) and `WWW-Authenticate` that send clients to the authorization server; the learning note on OAuth 2.1 for an MCP server; how to turn it on in the demo (`docs/DEPLOY.md`, step 6)
- [x] `feat/web-upload-picture-or-pdf` — a picture or a PDF chosen on the upload page is told for what it is and not sent, with where to get the XML (asked for on 2026-11-08, after the maintainer tried a picture of an invoice)
- [x] `feat/mcp-oauth-client-metadata` — client ID metadata documents, the revision's preferred registration, fetched safely: only where `SEF_CLIENT_METADATA_DOCUMENTS` allows it, at each authorization request, from the public internet only, pinned to the address checked, with no redirect, in five seconds and 5 KiB; authorization requests counted by address (ADR-0045); the learning note on SSRF and DNS rebinding
- [x] `feat/web-consent-client-host` — the consent page names the host that published a client's metadata document, beside the name it gives itself (draft-ietf-oauth-client-id-metadata-document §6.4; ADR-0045)
- [x] `feat/api-oauth-browser-clients` — MCP clients in a browser: the authorization server's public endpoints (the metadata documents, registration, the token endpoint) answer a page of any origin, the browser's preflight included (found in the review of `feat/mcp-oauth-resource`)
- [x] `feat/mcp-client-credential` — before the first MCP tool that writes (found in the review of `feat/mcp-oauth-resource`): a principal that says which credential it came with (in person, an API key, or a consent by its id), its consent read again by `check_again`, so that an MCP client never passes for a person where only a person may act (approving a repair, deciding on a consent); the audit log names the client (migration 0018); requests counted per consent
- [x] `feat/mcp-invoice-tools` — tools on stored invoices, through the routes' services and answering as the routes do: `store_invoice`, `list_invoices` and `get_invoice`; the scope they need, `invoices:submit`, which the consent page names; through an assistant, a person sees the invoices they submitted, never the organization's (split on 2026-11-08: the explanations and revalidation follow, then the step-up)
- [x] `feat/mcp-invoice-explanations` — tools on stored invoices, as their routes do: `explain_invoice`, the kept explanations first (ADR-0040), and `revalidate_invoices`, a job `get_job` reads; the tools say which only read
- [ ] `feat/mcp-scope-step-up` — the MCP revision's step-up: a tool the token's scopes do not reach answers 403 `insufficient_scope`, naming the scopes it needs in `WWW-Authenticate`, and `tools/list` offers only the tools the scopes reach
- [ ] `feat/mcp-propose-fix` — `propose_fix`: a repair the model proposes for a stored invoice, which a person decides on the repair's page (ADR-0024), whose address the tool answers
- [ ] `feat/mcp-search-rules` — `search_rules`: the rules of a profile and the passages of the corpus, by a rule's id or by words
- [ ] Demo from Claude and ChatGPT documented with screenshots
- [ ] Release: `v0.4.0`

## M5 — SEF demo round trip (week 8) · tag `v0.5.0`

- [ ] `feat/sef-demo-client` — SEF demo client, encrypted per-tenant key, send + status polling, and the MCP tool `send_to_sef_demo` over it (moved from `feat/mcp-server`, which had no client to call)
- [ ] `feat/sef-error-mapping` — SEF error codes mapped into the explanation pipeline; Peppol profile polish
- [ ] The SEF internal technical instruction (Interno tehničko uputstvo) in the corpus, once its official text can be pinned like the others (moved from M2)
- [ ] Confirm against the SEF demo what the published documents leave open: the warning-level SRB rules (SRB-013, SRB-017, SRB-023, SRB-029), the set-asides that rest on the Ministry's examples (ADR-0008), and whether SEF requires a due date or payment terms when an amount is due (EN 16931 BR-CO-25, absent from CEN's UBL Schematron; ADR-0010)
- [ ] Release: `v0.5.0`

## M6 — Evals, CI gate, billing (week 9) · tag `v0.6.0`

- [ ] `feat/evals-harness` — golden sets, eval runner, `evals/thresholds.yaml`, offline cassettes
- [ ] `ci/evals-gate` — CI fails below thresholds; README badge from the latest report
- [ ] `feat/billing-stripe-sandbox` — Stripe sandbox credits per invoice, verified webhooks
- [ ] OpenAI and Anthropic adapters behind `LLMClient` (the operator's key, `LLM_PROVIDER=openai|anthropic`), and an organization's own key kept encrypted like its SEF key (BYOK), compared on the evaluation set
- [ ] Release: `v0.6.0`

## M7 — PDF beta, case study, 1.0 (week 10) · tag `v1.0.0`

- [ ] `feat/pdf-extraction-beta` — PDF or picture → UBL extraction with a review step, clearly marked beta (pictures added on 2026-11-08 at the maintainer's request; kept after the evaluations, which can measure it)
- [ ] `docs/readme-case-study` — final README (problem, demo GIF, architecture diagram, numbers, how to run, how to self-host), 90-second demo video script, `docs/CASE_STUDY.md`
- [ ] `chore/release-1.0` — security review pass, `v1.0.0`
