# SEF Kopilot — working agreement for coding agents

This file is the distilled version of `docs/BRIEF.md`. The brief wins on any conflict; read it
in full before the first task of a session. `CLAUDE.md` and `AGENTS.md` are identical by
design (a pre-commit hook enforces it).

## Language and audience

- The maintainer (Marko Spasojević, GitHub `spasojewagner`) communicates in Serbian; reply in Serbian.
- Everything in the repository is English: code, comments, commits, PRs, docs. The product UI is
  Serbian (Latin) first, English second.
- Readers are hiring managers and senior engineers at ERP, fintech and e-invoicing companies.
  Every commit, branch, PR and document must read as the work of a careful professional team.

## Product in one sentence

Validate a UBL 2.1 e-invoice deterministically against SRB-CIUS (Serbian SEF profile),
EN 16931 and Peppol BIS Billing 3.0; explain each violation in sr/en with a dated citation
from the regulation; propose repairs as patches a human approves; re-validate; send to the
SEF demo environment; expose all of it as an HTTP API and an MCP server with OAuth 2.1.

## Architecture: three layers, one rule

1. **Deterministic validator** (XSD + Schematron + SRB-CIUS rules in code) — the source of truth.
2. **Explainer** (retrieval + LLM with structured output) — may cite only passages retrieval returned.
3. **Repairer** (LLM emits patches `{xpath, op, value, reason}`) — code applies them, layer 1 judges.

The LLM sits between two deterministic walls and is never trusted. Nothing leaves without a
green validator. Non-negotiable guardrails, encoded as tests:

- Patches touching amounts, VAT rates/categories, tax IDs (PIB), company identifiers or dates of
  supply are rejected and surfaced as "needs manual decision".
- Arithmetic rules (EN 16931 `BR-CO-*`) are checked in Python, never by the model.
- Every citation must resolve to a stored corpus chunk id; otherwise the response fails.
- No invoice content in logs or traces; a no-store mode keeps the invoice in memory only.
- Self-hosted Docker deployment makes no external calls except the configured LLM provider.

## Fixed stack (deviations only through an ADR)

- Backend: Python 3.12, `uv` workspace, FastAPI, Pydantic v2, SQLAlchemy 2.0 async + `asyncpg`,
  Alembic, `httpx`, PostgreSQL 16 + `pgvector` (multi-tenant by `organization_id`), Redis + `arq`
  behind a `JobRunner` interface, SSE for progress, `lxml`, Schematron via XSLT with `saxonche`.
- Quality: `ruff`, `mypy --strict` (core), `pytest` + `pytest-asyncio` + `pytest-cov`, `hypothesis`.
- LLM/embeddings behind adapters (`LLMClient`); Groq free tier by default, BYOK for others;
  structured outputs validated with Pydantic, max 3 retries with validation feedback.
- MCP: official Python SDK, Streamable HTTP at `/mcp`; OAuth 2.1 with PKCE, RFC 9728, RFC 8414,
  RFC 8707, RFC 7591 via Authlib.
- Frontend: Next.js (App Router), TypeScript strict, Tailwind v4, shadcn/ui, TanStack Query,
  Zustand (UI state only), Vercel AI SDK client, `next-intl` (`sr-Latn` default, `en`), Vitest +
  Testing Library, one Playwright smoke test, `pnpm`, Node 22 LTS.
- Rule sets are fetched by `scripts/fetch_rulesets.py` into `third_party/` (own licenses, never
  modified, never committed). SRB-CIUS rules are authored by us from the official specification.
- Deployment on free tiers only (Render, Neon, Upstash, Cloudflare Pages, GitHub Actions, GHCR).

## Repository layout

`apps/api` (FastAPI) · `apps/web` (Next.js) · `packages/einvoice_core` (validation engine, CLI) ·
`third_party` · `corpus` · `fixtures/invoices` · `evals` · `infra` · `docs` · `scripts` · `.github`

## Git rules (must be perfect)

- Identity for every commit: `Marko Spasojevic <markospasojevic758@gmail.com>` (repo-local config).
- No AI attribution anywhere: no `Co-Authored-By`, no "generated with", no tool names in commits,
  PRs or code comments. The process is documented in `CONTRIBUTING.md`, not in commits.
- Never run `git push`, `gh pr create`, `gh pr merge`, `gh release` or anything that writes to
  GitHub. The maintainer pushes, opens PRs, merges and tags; hand him exact commands.
- Never rewrite history that has been handed off. Before handoff, tidy with `git reset --soft`
  + recommit or `git commit --fixup` + `git rebase --autosquash` (`GIT_SEQUENCE_EDITOR=true`).
- Never commit secrets, real invoices, databases, `node_modules`, `.venv`, build output. `gitleaks`
  runs in pre-commit and CI. Never bypass hooks with `--no-verify`.
- `main` is always releasable; nobody commits to it directly. One branch per unit of work:
  `type/scope-short-description` (lowercase, hyphens), started from the latest `main`. Stacked
  branches are named as such in the handoff. Merges on GitHub are merge commits (no squash).
- Commits: Conventional Commits, atomic, English, imperative subject ≤ 72 chars, no trailing
  period, body wrapped at 72 explaining why. Types: `feat fix docs test refactor perf chore ci
  build style`. Scopes: `core api web mcp rag repair sef evals infra ci docs adr deps repo`.
  Forbidden subjects: `wip`, `fix`, `update`, `changes`, `stuff`, `misc`, `final`, `asdf`.
  A feature commit includes its tests and docs. Never mix refactors with behaviour changes.
  Aim for 3–10 buildable commits per branch; one PR ≈ one reviewable change (≈400 lines).
- Every branch gets a PR text in `.handoff/PR.md` (gitignored) following
  `.github/PULL_REQUEST_TEMPLATE.md`: summary, changes, how to test, screenshots, interview
  notes (three senior-engineer questions with answers + one concept to explain unaided), checklist.
  PR title = the branch's main commit subject.
- Versions: SemVer; `CHANGELOG.md` (Keep a Changelog) gets a line under `[Unreleased]` in every
  PR; milestones end with a version bump, changelog move and an annotated tag prepared for the
  maintainer.

## Session protocol

- Start: read `CLAUDE.md`, `docs/BRIEF.md`, `docs/BACKLOG.md`; run `git status`,
  `git log --oneline --graph -20`, `git branch -a`; confirm branch and clean tree; pick the next
  backlog item; state the plan in 3–5 lines (Serbian).
- Work: tests first where sensible → implement → full relevant test suite → lint/type → docs and
  CHANGELOG → commit. Small steps, frequent commits.
- End: Handoff block in chat (Serbian): branch and commit count, test results and coverage,
  PR title, `.handoff/PR.md`, the maintainer's exact commands (push, open PR, post-merge cleanup),
  the one thing he must be able to explain, and the next branch. Append a one-entry summary to
  `docs/SESSIONS.md` (English, committed).

## Definition of done (every PR)

- All tests pass; new behaviour has tests; coverage: `einvoice_core` ≥ 90 %, API ≥ 80 %.
- `ruff`, `mypy --strict` (core), `eslint`, `tsc --noEmit` and `pre-commit run --all-files` clean.
- No secrets, no real data, no invoice content in logs. Public API documented (OpenAPI).
  Migrations reversible (`alembic downgrade -1` in CI).
- `CHANGELOG.md` updated; an ADR (`docs/adr/NNNN-title.md`, MADR) for every architectural decision.
- Performance budget noted: validate < 500 ms warm, explanation < 6 s, repair loop < 20 s.
- From M6: evals thresholds in `evals/thresholds.yaml` gate CI (offline mode with cassettes).

## Data and compliance

- Fixtures: official examples and synthetic invoices only (fake companies, fake PIBs with valid
  checksums). Never a real company's invoice, even anonymised.
- Corpus: official sources only, stored as text with `source_url`, `fetched_at`, `valid_from`.
- The product is not a certified validator; README and UI say so.
- Security: OWASP ASVS checklist in `SECURITY.md`, rate limiting, size/type limits, hardened XML
  parsing (no external entities, no DTD), dependency audits in CI.

## Ask vs. decide

- Ask before: destructive Git operations, deleting the maintainer's files, changing milestone
  order, adding a paid service, anything touching his accounts or keys (only variable names are
  ever visible to agents).
- Decide and record in an ADR: libraries within the fixed stack, module boundaries, schema design,
  test strategy, naming.

## Teaching the maintainer

- New concepts get a ≤ 1 page note in `docs/learning/` (English, diagram if it helps).
- Interview notes are mandatory in every PR; each handoff names the one thing to explain unaided.
- Answer "why" with the trade-off, not just the choice. Prefer boring, well-understood solutions.
