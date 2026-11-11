# SEF Kopilot

**Deterministic validation, plain-language explanations and reviewable repairs for Serbian (SEF) and EU electronic invoices.**

[![CI](https://github.com/spasojewagner/sef-kopilot/actions/workflows/ci.yml/badge.svg)](https://github.com/spasojewagner/sef-kopilot/actions/workflows/ci.yml)
[![Evaluations](https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fspasojewagner%2Fsef-kopilot%2Fmain%2Fevals%2Freports%2Fbadge.json)](evals/reports/latest.md)
[![Latest version](https://img.shields.io/github/v/tag/spasojewagner/sef-kopilot?sort=semver&label=version)](CHANGELOG.md)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
![Python 3.12](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![Node 22 LTS](https://img.shields.io/badge/node-22_LTS-339933?logo=node.js&logoColor=white)
[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit)](https://github.com/pre-commit/pre-commit)

> SEF Kopilot is an independent open-source project. It is **not affiliated with** the Serbian
> Ministry of Finance or the SEF platform (Sistem elektronskih faktura), and it is **not a certified
> validator**: an invoice that passes here can still be rejected by SEF, and the sender remains
> responsible for what they submit. By default the project only ever talks to the public SEF
> **demo** environment.

![An invoice SEF would reject is uploaded, the language model suggests a repair, the validator checks it on a copy, and a person approves it: the invoice is valid](docs/demo/golden-path.gif)

*The golden path on a synthetic invoice whose type code SEF does not accept (`SRB-001`): its
report, a repair the model suggests, the diff checked by the validator, a person's approval.
Recorded with `make demo-gif` against the end-to-end test's API, whose model is scripted.*

**Try it:** <https://sef-kopilot.vercel.app>, a public demo on free plans (`docs/DEPLOY.md`).
Upload only synthetic invoices, such as those in `fixtures/invoices/synthetic/`: the demo is
public, and an explanation or a repair sends an invoice's violations and fields to the language
model's provider. Its API sleeps after 15 minutes without a visitor and wakes in about a minute.
From Claude or ChatGPT, connect `https://sef-kopilot-api.onrender.com/mcp`: [`docs/DEMO.md`](docs/DEMO.md)
shows both on a synthetic invoice. How it was built, its decisions and its numbers are told in
the [case study](docs/CASE_STUDY.md).

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

## What it does

| Capability | Description |
| --- | --- |
| **Validate** | UBL 2.1 XML against XSD, the EN 16931 Schematron, Peppol BIS Billing 3.0 and 29 SRB-CIUS rules authored from the official specification, with the `BR-CO` arithmetic in Python. Deterministic: no model involved. Also a command-line tool, `einvoice`. |
| **Explain** | Every violation explained in Serbian and English, with citations of the actual regulation (the law, the rulebooks, the SRB-CIUS specification, the tax categories), each passage dated by when it applies to the invoice. |
| **Repair** | Repairs proposed as patches that code applies to a copy and the validator checks again; a person reviews the diff and approves it, and every step is in an audit log. Amounts, VAT, tax identifiers and dates are never changed by the model. |
| **Read** *(beta)* | A PDF, a scan or a photograph of an invoice read into its fields, shown beside the document for a person to check; code writes the UBL of what they confirm. |
| **Send** | A valid invoice sent to the SEF demo environment with the organization's own SEF key, and its status followed. Built and tested against SEF's published API: signing up for the demo takes an eID the project does not have yet. |
| **Integrate** | An HTTP API ([OpenAPI](docs/api/openapi.json)) with API keys, and an MCP server of 16 tools secured with OAuth 2.1, usable from Claude, ChatGPT or an ERP. |

## How it works

```mermaid
flowchart TD
    XML["UBL 2.1 invoice (XML)"] --> V

    subgraph L1["1 · Deterministic validator (source of truth)"]
        V["XSD + Schematron (EN 16931, Peppol BIS) + SRB-CIUS rules + BR-CO arithmetic"]
        V --> VIOL["violations {rule_id, severity, xpath, message}"]
    end

    VIOL --> E

    subgraph L2["2 · Explainer (retrieval + LLM, structured output)"]
        E["rule_id + violated fragment + retrieved regulation passages"]
        E --> EXPL["explanation (sr / en) + citations that must resolve to retrieved passages"]
    end

    EXPL --> R

    subgraph L3["3 · Repairer"]
        R["LLM proposes patches {xpath, op, value, reason}"]
        R --> APPLY["code applies the allowed patches to a copy"]
        APPLY --> REVAL["layer 1 re-validates"]
        REVAL --> DIFF["diff → a person approves"]
    end

    DIFF --> SEF["SEF demo environment"]
```

**The one rule: the language model sits between two deterministic walls and is never trusted.**
Layer 1 decides what is valid. Layer 2 may only cite passages that retrieval actually returned.
Layer 3 may only emit patches; code applies them and layer 1 judges the result. Nothing leaves
the system without a green validator.

Guardrails that are encoded as tests, not as comments:

- Patches that touch monetary amounts, VAT rates or categories, tax identifiers (PIB), company
  identifiers, dates or the document's number are rejected automatically and surfaced as
  "needs manual decision".
- Arithmetic rules (EN 16931 `BR-CO-*`) are checked in Python, never delegated to the model.
- Every citation must resolve to a stored passage in force on the invoice's day; an answer
  whose citation does not resolve, or that names a value its question did not contain, is
  refused.
- No invoice content is ever written to logs or traces, and a **no-store mode** processes an
  invoice entirely in memory.
- A self-hosted deployment works with zero external calls except the language model provider
  the operator configures (bring your own key).

The system around the three layers:

```mermaid
flowchart LR
    PERSON["Accountant"] -->|browser| WEB["apps/web<br/>Next.js"]
    ERP["ERP system"] -->|HTTP, API key| API
    AGENT["Claude / ChatGPT"] -->|MCP, OAuth 2.1| API
    WEB -->|HTTP + SSE| API["apps/api<br/>FastAPI: REST, /mcp, /oauth"]
    API -->|one invoice at a time,<br/>with a time limit| CHILD["validator process<br/>einvoice_core + Saxon-HE"]
    CHILD --> RULES[("rule sets, pinned<br/>third_party/")]
    API --> DB[("PostgreSQL 16<br/>pgvector · pg_trgm")]
    API -.->|SEF_JOBS=arq| REDIS[("Redis + arq workers")]
    API -->|bring your own key| LLM["Groq · OpenAI · Anthropic · Gemini"]
    API -->|organization's key| SEF["SEF demo environment"]
```

A validation runs in a child process of the API, so that Saxon, which holds Python's GIL,
never stalls other requests; work that outlasts a request runs as a job whose progress streams
over SSE. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) follows a request through every step,
and [`docs/adr/`](docs/adr/README.md) records the 64 decisions behind it.

## In numbers

The evaluations run in CI on every change, offline, with the model's answers recorded once and
replayed; a threshold missed fails the build ([`evals/reports/latest.md`](evals/reports/latest.md),
[`evals/thresholds.yaml`](evals/thresholds.yaml)).

| Measure | Result |
| --- | --- |
| Verdicts that agree with the published rule sets, applied as published | **100 %** (93 of 93 documents) |
| Documents that must be rejected, accepted | **0 %** (0 of 56) |
| Mistakes reported by the rules they must be reported by | **100 %** (60 of 60) |
| Citations that resolve to a stored passage in force on the day | **100 %** (93 of 93) |
| Citations labelled relevant to their rule | **96.8 %** (90 of 93) |
| Held-out invoices a repair leaves valid | **100 %** (9 of 9) |
| Invoices whose mistake a person decides, made to pass by a repair | **0 %** (0 of 11) |
| Fields read as printed from a PDF, a scan, a photograph *(beta)* | **100 %, 99.5 %, 99.8 %** |

| Engineering | |
| --- | --- |
| Tests | 1,770 for the validator core (100 % coverage), 1,603 for the API (99 %), 581 for the web application, one end-to-end test in Chromium |
| Conformance | in the core's tests: the rule sets run on their publishers' own unit tests, 1,131 of CEN's and 340 of OpenPeppol's, with the results the publishers expect |
| Rules | EN 16931 and Peppol BIS as CEN and OpenPeppol publish them, 29 SRB-CIUS rules, 8 `BR-CO` calculations |
| Regulation corpus | 5 documents, 7 dated editions, 385 passages |
| Performance | a typical invoice validated in 13 ms warm through the API, 6.5 ms in the core (budget 500 ms); an explanation in 1.5 s on Groq's free tier (budget 6 s) |
| History | 109 pull requests, 64 decision records, an engineering log of every working session ([`docs/SESSIONS.md`](docs/SESSIONS.md)) |

## Run it locally

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
make api          # FastAPI with auto-reload → http://127.0.0.1:8000/docs
make web          # Next.js dev server → http://localhost:3000
```

Copy `.env.example` to `.env` to override the local defaults; it documents every variable.
Validation needs no secret. Explanations, repairs and reading need a language model:
`LLM_PROVIDER=groq` with a `GROQ_API_KEY` of your own (Groq's free tier is enough), or `openai`,
`anthropic` or `gemini` with a key of yours; without one those endpoints answer 503.

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

The checks CI runs, and the demo:

```bash
make test         # core, api and web test suites with their coverage gates
make e2e          # the golden path in Chromium (Playwright), against the API and a build
make evals        # measure on the golden sets and write evals/reports/ (the report, the badge)
make lint         # ruff, Prettier, ESLint — no changes
make typecheck    # mypy --strict and tsc --noEmit
make demo-gif     # record the golden path again as docs/demo/golden-path.gif (ffmpeg, gifsicle)
```

The API's database tests run when `SEF_TEST_DATABASE_URL` names a PostgreSQL server (with
`make up`: `postgresql+asyncpg://sef:sef@localhost:5432/postgres`), and its worker tests when
`SEF_TEST_REDIS_URL` names a Redis database they may empty (`redis://localhost:6379/15`);
otherwise they are skipped. The end-to-end test makes its database on the same server, and needs
Chromium for Playwright, installed once with
`pnpm --filter @sef-kopilot/web exec playwright install chromium` (`apps/web/README.md`).

## Self-host

The API is one Docker image; the web application is a Node.js server. The public demo's
deployment on free plans is written out step by step in [`docs/DEPLOY.md`](docs/DEPLOY.md);
on a server of your own:

1. **PostgreSQL 16 with pgvector**, such as the `pgvector/pgvector:pg16` image, and a database
   whose role may create the `vector` and `pg_trgm` extensions (the migrations create them).
2. **The API.** The image fetches the rule sets by their pins and compiles them while it is
   built, and migrates the database each time it starts:

   ```bash
   docker build -f apps/api/Dockerfile -t sef-kopilot-api .
   docker run -d --name sef-kopilot-api -p 8000:8000 --env-file api.env sef-kopilot-api
   ```

   `api.env` holds at least `DATABASE_URL` (`postgresql+asyncpg://…`), `SEF_JWT_SECRET` (32
   characters or more), `SEF_WEB_ORIGINS` (the web application's origin) and, for explanations,
   repairs and reading, `LLM_PROVIDER` with its key. `/ready` answers 200 once the database and
   the rule sets are ready; `/docs` shows the API.
3. **The corpus**, once, and again whenever `corpus/` changes; the image holds it:

   ```bash
   docker exec sef-kopilot-api python -m sef_api.rag.ingest
   ```

4. **The web application**, built with the API's address, which is written into the pages:

   ```bash
   NEXT_PUBLIC_API_URL=https://api.example.com SITE_URL=https://kopilot.example.com \
     pnpm --filter @sef-kopilot/web build
   pnpm --filter @sef-kopilot/web start --port 3000
   ```

What leaves the server is what its operator turns on. By default nothing does but the requests
to `LLM_PROVIDER`'s model, and an organization's invoices to SEF's demo once its owner sets its
SEF key; embeddings (`EMBEDDINGS_PROVIDER`), tracing (`LANGFUSE_*`), error reports
(`SENTRY_DSN`), MCP client metadata documents and Stripe are all off. Jobs run in the API's own
process (`SEF_JOBS=inline`) unless `SEF_JOBS=arq` sends them to workers on Redis. The MCP
endpoint takes API keys; `SEF_PUBLIC_URL` and `SEF_WEB_URL` turn on its OAuth 2.1 authorization
server for Claude and ChatGPT. [`SECURITY.md`](SECURITY.md) lists the controls, and
`.env.example` every limit.

## Roadmap

| Milestone | Scope | Status |
| --- | --- | --- |
| M0 | Monorepo, tooling, CI, documentation skeleton | done |
| M1 | Validator core: UBL parser, XSD, Schematron runner, SRB-CIUS rule set v1, fixtures, CLI | done — v0.1.0 |
| M2 | API, persistence, auth, jobs with SSE progress, regulation corpus, explanations with citations | done — v0.2.0 |
| M3 | Repair loop with approval and audit log, web UI (sr-Latn / en), public demo | done — v0.3.0 |
| M4 | MCP server with OAuth 2.1, shown from Claude and ChatGPT | done — v0.4.0 |
| M5 | SEF demo round trip | done — v0.5.0 |
| M6 | Evaluation harness with CI quality gate, sandbox billing | done — v0.6.0 |
| M7 | PDF and picture reading (beta), case study, 1.0 | the reading and the case study are done; 1.0 follows a security review |

After 1.0, once the project has a SEF demo account: SEF's error codes mapped into the
explanations, SEF's internal technical instruction in the corpus, and the rules the published
documents leave open confirmed against SEF itself. The detailed backlog lives in
[`docs/BACKLOG.md`](docs/BACKLOG.md); the full product and engineering charter is
[`docs/BRIEF.md`](docs/BRIEF.md).

## Technology

| Area | Choice |
| --- | --- |
| Validation engine | Python 3.12, `lxml`, Schematron via XSLT with Saxon-HE (`saxonche`), Pydantic v2 models |
| API | FastAPI, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL 16 with `pgvector`, Redis + `arq` jobs, SSE |
| Explanations and reading | Provider-agnostic LLM and embedding adapters (Groq by default; OpenAI, Anthropic and Gemini with your own key), hybrid retrieval (curated map, trigram, optional vectors), PDFium and Pillow for documents |
| Integration | MCP (official Python SDK, Streamable HTTP) with OAuth 2.1 via Authlib |
| Web | Next.js (App Router), TypeScript strict, Tailwind CSS v4, shadcn/ui, TanStack Query, `next-intl` |
| Quality | `ruff`, `mypy --strict`, `pytest` + `hypothesis`, Vitest + Testing Library, Playwright, `gitleaks`, GitHub Actions |
| Hosting | Vercel (web), Render (API, Docker), Neon (PostgreSQL), Groq (language model), all on free plans |

## Repository layout

```text
sef-kopilot/
  apps/api/                FastAPI application, MCP server and OAuth 2.1 authorization server
  apps/web/                Next.js application
  packages/einvoice_core/  pure-Python validation engine (parser, XSD, Schematron, SRB-CIUS rules, patches, CLI)
  third_party/             fetched rule sets and their licenses (never modified, never committed)
  corpus/                  official regulation texts as dated passages, made from pinned sources
  fixtures/invoices/       official example invoices and synthetic ones (never real company data)
  evals/                   golden sets, evaluation runner, recorded answers, thresholds, latest report
  infra/                   docker-compose for local PostgreSQL and Redis
  docs/                    case study, architecture, ADRs, learning notes, interview notes, API docs
  scripts/                 maintenance scripts (rule-set fetcher, fixture generator, corpus converter)
```

## Documentation

- [`docs/CASE_STUDY.md`](docs/CASE_STUDY.md) — the problem, the decisions and their trade-offs, what went wrong, the numbers
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — system map: layers, request flow, repository map, cross-cutting concerns
- [`docs/adr/`](docs/adr/README.md) — architecture decision records (MADR)
- [`docs/BRIEF.md`](docs/BRIEF.md) — product and engineering charter (the source of truth for scope and decisions)
- [`docs/DEPLOY.md`](docs/DEPLOY.md) — the public demo: what runs where, and the steps to deploy it
- [`docs/DEMO.md`](docs/DEMO.md) — the MCP server from Claude and ChatGPT, with screenshots
- [`docs/DEMO_VIDEO.md`](docs/DEMO_VIDEO.md) — the script of the 90-second demo video
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
