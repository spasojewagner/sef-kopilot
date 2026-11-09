# SEF Kopilot

**Deterministic validation, plain-language explanations and reviewable repairs for Serbian (SEF) and EU electronic invoices.**

[![CI](https://github.com/spasojewagner/sef-kopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/spasojewagner/sef-kopilot/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-orange)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node 22 LTS](https://img.shields.io/badge/node-22_LTS-339933?logo=node.js&logoColor=white)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> **Status: pre-alpha, under active development.** Nothing here is production-ready yet.
>
> SEF Kopilot is an independent open-source project. It is **not affiliated with** the Serbian
> Ministry of Finance or the SEF platform (Sistem elektronskih faktura), and it is **not a certified
> validator**: an invoice that passes here can still be rejected by SEF, and the sender remains
> responsible for what they submit. By default the project only ever talks to the public SEF
> **demo** environment.

**Try it:** <https://sef-kopilot.vercel.app>, a public demo on free plans (`docs/DEPLOY.md`).
Upload only synthetic invoices, such as those in `fixtures/invoices/synthetic/`: the demo is
public, and an explanation or a repair sends an invoice's violations and fields to the language
model's provider. Its API sleeps after 15 minutes without a visitor and wakes in about a minute.
From Claude or ChatGPT, connect `https://sef-kopilot-api.onrender.com/mcp`: [`docs/DEMO.md`](docs/DEMO.md)
shows both on a synthetic invoice.

## The problem

Every invoice between Serbian businesses has to pass through SEF as UBL 2.1 XML that satisfies
the Serbian profile (SRB-CIUS) of the European standard EN 16931. When an invoice is rejected,
the feedback is a rule identifier such as `BR-CO-15` or a terse SEF error code. Accountants and
ERP vendors then spend their time translating codes into "what is actually wrong, which
regulation says so, and what do I change".

The rules keep moving. In ten months the Serbian framework changed three times (the law in
December 2025, the rulebook on 1 August 2026, the technical instruction on 1 October 2026), and
from 1 January 2027 SEF derives the preliminary VAT return from these invoices, so a wrong VAT
category is no longer a formatting problem but a tax problem. In the same window Germany, France,
Croatia, Poland and Spain switch on e-invoicing mandates built on the same EN 16931 / Peppol
foundation, so the problem repeats in every market.

## What it will do

| Capability | Description |
| --- | --- |
| **Validate** | UBL 2.1 XML against XSD, the EN 16931 Schematron, Peppol BIS Billing 3.0 and an SRB-CIUS rule set authored from the official specification. Deterministic: no model involved. |
| **Explain** | Every violation explained in Serbian and English, with a citation of the actual regulation passage (law, rulebook, technical instruction, SRB-CIUS specification), each tagged with the date it took effect. |
| **Repair** | Repairs proposed as a list of patches that a human reviews and approves; the patched invoice is re-validated and shown as a diff. Amounts, VAT, tax identifiers and dates of supply are never changed automatically. |
| **Send** | The approved invoice can be sent to the SEF demo environment and its status followed. |
| **Integrate** | Everything is an HTTP API and an MCP server secured with OAuth 2.1, usable from Claude, ChatGPT or an ERP. |

## How it works

```mermaid
flowchart TD
    XML["UBL 2.1 invoice (XML)"] --> V

    subgraph L1["1 · Deterministic validator (source of truth)"]
        V["XSD + Schematron (EN 16931, Peppol BIS) + SRB-CIUS rules"]
        V --> VIOL["violations {rule_id, severity, xpath, message}"]
    end

    VIOL --> E

    subgraph L2["2 · Explainer (retrieval + LLM, structured output)"]
        E["rule_id + violated fragment + retrieved regulation passages"]
        E --> EXPL["explanation (sr / en) + citations that must resolve to retrieved chunks"]
    end

    EXPL --> R

    subgraph L3["3 · Repairer"]
        R["LLM proposes patches {xpath, op, value, reason}"]
        R --> APPLY["code applies patches"]
        APPLY --> REVAL["layer 1 re-validates"]
        REVAL --> DIFF["diff → human approves"]
    end

    DIFF --> SEF["SEF demo environment"]
```

**The one rule: the language model sits between two deterministic walls and is never trusted.**
Layer 1 decides what is valid. Layer 2 may only cite passages that retrieval actually returned.
Layer 3 may only emit patches; code applies them and layer 1 judges the result. Nothing leaves
the system without a green validator.

Guardrails that are encoded as tests, not as comments:

- Patches that touch monetary amounts, VAT rates or categories, tax identifiers (PIB), company
  identifiers or dates of supply are rejected automatically and surfaced as "needs manual decision".
- Arithmetic rules (EN 16931 `BR-CO-*`) are checked in Python, never delegated to the model.
- Every citation must resolve to a stored corpus chunk; a citation that does not resolve fails
  the response.
- No invoice content is ever written to logs or traces, and a **no-store mode** processes an
  invoice entirely in memory.
- A self-hosted Docker deployment works with zero external calls except the LLM provider the
  operator configures (bring your own key).

## Roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| M0 | Monorepo, tooling, CI, documentation skeleton | done |
| M1 | Validator core: UBL parser, XSD, Schematron runner, SRB-CIUS rule set v1, fixtures, CLI | done — v0.1.0 |
| M2 | API, persistence, auth, jobs with SSE progress, regulation corpus, explanations with citations | done — v0.2.0 |
| M3 | Repair loop with approval and audit log, web UI (sr-Latn / en), public demo | done — v0.3.0 |
| M4 | MCP server with OAuth 2.1, shown from Claude and ChatGPT | done — v0.4.0 |
| M5 | SEF demo round trip; SEF error mapping waits for a SEF demo account | done — v0.5.0 |
| M6 | Evaluation harness with CI quality gate, sandbox billing | in progress |
| M7 | PDF extraction (beta), case study, 1.0 | planned |

The detailed backlog lives in [`docs/BACKLOG.md`](docs/BACKLOG.md); the full product and
engineering charter is [`docs/BRIEF.md`](docs/BRIEF.md).

## Technology

| Area | Choice |
| --- | --- |
| Validation engine | Python 3.12, `lxml`, Schematron via XSLT with Saxon-HE (`saxonche`), Pydantic v2 models |
| API | FastAPI, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL 16 with `pgvector`, Redis + `arq` jobs, SSE |
| Explanations | Provider-agnostic LLM and embedding adapters (Groq by default, bring your own key for OpenAI / Anthropic), hybrid retrieval (curated map, vectors, trigram) |
| Integration | MCP (official Python SDK, Streamable HTTP) with OAuth 2.1 via Authlib |
| Web | Next.js (App Router), TypeScript strict, Tailwind CSS v4, shadcn/ui, TanStack Query, `next-intl` |
| Quality | `ruff`, `mypy --strict`, `pytest` + `hypothesis`, Vitest + Testing Library, Playwright, `gitleaks`, GitHub Actions |
| Hosting | Vercel (web), Render (API, Docker), Neon (PostgreSQL), Groq (language model), all on free plans |

## Repository layout

```text
sef-kopilot/
  apps/api/                FastAPI application
  apps/web/                Next.js application
  packages/einvoice_core/  pure-Python validation engine (parser, XSD, Schematron, SRB-CIUS rules, patches, CLI)
  third_party/             fetched rule sets and their licenses (never modified, never committed)
  corpus/                  official regulation texts as dated passages, made from pinned sources
  fixtures/invoices/       official example invoices and synthetic ones (never real company data)
  evals/                   golden sets, evaluation runner, thresholds, latest report
  infra/                   Dockerfiles, docker-compose, deployment manifests
  docs/                    BRIEF, ARCHITECTURE, ADRs, learning notes, interview notes, API docs
  scripts/                 maintenance scripts (rule-set fetcher, fixture generator, corpus converter)
```

## Getting started

Prerequisites: Git, Python 3.12 with [`uv`](https://docs.astral.sh/uv/), Node.js 22 LTS with
`pnpm` (run `corepack enable` once), Docker (Docker Desktop on Windows/macOS). GNU `make` is
optional — every target in the `Makefile` is a single plain command you can run by hand.

```bash
git clone https://github.com/spasojewagner/sef-kopilot.git
cd sef-kopilot
make setup        # uv sync --all-packages · pnpm install --frozen-lockfile · pre-commit hooks
make rulesets     # fetch the pinned EN 16931 and Peppol BIS rule sets into third_party/
make up           # PostgreSQL 16 + pgvector and Redis in Docker (needs a running Docker daemon)
make migrate      # apply the database migrations (Alembic) to the database of `make up`
make ingest       # load the regulation corpus (corpus/) into that database
make test         # core, api and web test suites with their coverage gates
make e2e          # the golden path in Chromium (Playwright), against the API and a build
make lint         # ruff, Prettier, ESLint — no changes
make typecheck    # mypy --strict and tsc --noEmit
make api          # FastAPI with auto-reload → http://127.0.0.1:8000/docs
make worker       # an arq worker for the jobs on the Redis queue (with SEF_JOBS=arq)
make web          # Next.js dev server → http://localhost:3000
```

Validate an invoice from the command line (exit status 0 valid, 1 invalid, 2 error):

```bash
uv run einvoice validate fixtures/invoices/synthetic/srb-minimal-invoice.xml   # valid (srb)
uv run einvoice validate invoice.xml --profile en16931 --format json
uv run einvoice validate invoices/                     # every .xml file under a directory
uv run einvoice rules --profile srb   # what the SEF profile checks and sets aside
```

Repair one with patches from a JSON file, validated again and shown as a diff (exit status 0
only when every patch applied and the invoice is valid; `packages/einvoice_core/README.md`
shows the patches):

```bash
uv run einvoice patch invoice.xml fixes.json --output fixed.xml
```

Copy `.env.example` to `.env` to override the local defaults. Nothing up to M1 needs a secret;
explanations (`POST /invoices/explain`) need a language model: `LLM_PROVIDER=groq` with a
`GROQ_API_KEY` of your own (Groq's free tier is enough), and without one the endpoint answers
503.
The API's database tests run when `SEF_TEST_DATABASE_URL` names a PostgreSQL server (with
`make up`: `postgresql+asyncpg://sef:sef@localhost:5432/postgres`), and its worker tests when
`SEF_TEST_REDIS_URL` names a Redis database they may empty (`redis://localhost:6379/15`);
otherwise they are skipped. The end-to-end test makes its database on the same server, and needs
Chromium for Playwright, installed once with
`pnpm --filter @sef-kopilot/web exec playwright install chromium` (`apps/web/README.md`).

## Documentation

- [`docs/BRIEF.md`](docs/BRIEF.md) — product and engineering charter (the source of truth for scope and decisions)
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system map: layers, request flow, repository map, cross-cutting concerns
- [`docs/adr/`](docs/adr/README.md) — architecture decision records (MADR)
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — the public demo: what runs where, and the steps to deploy it
- [`docs/DEMO.md`](docs/DEMO.md) — the MCP server from Claude and ChatGPT, with screenshots
- [`docs/learning/`](docs/learning/README.md) — one-page notes on the concepts the project is built on
- [`docs/interview/`](docs/interview/README.md) — the questions each pull request should survive
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — how the repository is worked on: branches, commits, pull requests, releases
- [`SECURITY.md`](SECURITY.md) — security policy, reporting, and the OWASP ASVS checklist
- [`CHANGELOG.md`](CHANGELOG.md) — notable changes per release
- [`docs/SESSIONS.md`](docs/SESSIONS.md) — engineering log, one entry per working session

## License

Copyright 2026 Marko Spasojević. Licensed under the [Apache License, Version 2.0](LICENSE).

Third-party rule sets fetched into `third_party/` keep their own licenses (for example the
EN 16931 validation artefacts are published under the EUPL 1.2) and are deliberately kept out
of this repository.
