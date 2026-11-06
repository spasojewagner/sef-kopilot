# sef-kopilot-api

FastAPI application exposing the validator, the explanation and repair layers, multi-tenant
persistence, background jobs with SSE progress, the SEF demo integration and (from M4) the MCP
server. The deterministic engine lives in `packages/einvoice_core`; this app only orchestrates it.

## Run locally

From the repository root, with PostgreSQL running (`make up` starts it in Docker):

```bash
uv sync --all-packages
make migrate          # uv run alembic -c apps/api/alembic.ini upgrade head
make api              # uv run uvicorn sef_api.main:create_app --factory --reload
```

- Interactive documentation: <http://127.0.0.1:8000/docs>
- Liveness: `GET /health` · Readiness: `GET /ready` (503 while the database does not answer or
  the validator cannot run, for example without its rule sets)

Invoices are validated in a child process that the application starts with it, and which
compiles the validator's schemas and rule sets first (a few seconds), so that no request pays
for it; fetch them first with `make rulesets`. See [Validating an invoice](#validating-an-invoice).

Configuration comes from the environment or a `.env` file in the working directory; the
variables are in [`.env.example`](../../.env.example). Without `DATABASE_URL` the API uses the
database of `make up`; in production the variable is required.

Every JSON answer is `application/json; charset=utf-8`. JSON needs no charset, but Windows
PowerShell 5.1 reads a body without one as ISO-8859-1, which garbles the Serbian letters of a
message or an explanation.

## Accounts and tokens

`/auth` signs people up and in (ADR-0012). Registration creates an account, its organization and
makes the person the owner; sign-in returns two tokens for one organization:

| Token | Lifetime | Use |
| --- | --- | --- |
| access token (JWT, HS256, `typ: at+jwt`) | 15 minutes | `Authorization: Bearer …` on every request; checked without the database |
| refresh token (256 random bits, stored as a SHA-256 digest) | 30 days | `POST /auth/refresh` once for a new pair; a second use ends the session |

Machine clients authenticate with an [API key](#api-keys) instead, in the same header.

```bash
curl -s localhost:8000/auth/register -H 'Content-Type: application/json' \
  -d '{"email": "ana@primer.example", "password": "a long passphrase", "organization_name": "Primer"}'
curl -s localhost:8000/auth/me -H "Authorization: Bearer $ACCESS_TOKEN"
```

Passwords are hashed with argon2id (OWASP's minimum: 19 MiB, two passes) in a worker thread.

## Members and permissions

Endpoints ask for a permission; a member's role grants permissions (ADR-0013):

| Permission | owner | accountant | client |
| --- | :-: | :-: | :-: |
| `members:read`: see the members and their roles | yes | yes | no |
| `members:manage`: invite people, change roles, remove members | yes | no | no |
| `invoices:validate`: have an invoice checked by the validator | yes | yes | yes |
| `invoices:submit`: store invoices, and read and delete the ones submitted oneself | yes | yes | yes |
| `invoices:manage`: read and delete every invoice the organization stores | yes | yes | no |
| `api_keys:issue`: issue API keys that act for oneself, see and revoke one's own | yes | yes | yes |
| `api_keys:manage`: see and revoke every API key of the organization | yes | no | no |

`GET /members`, `PATCH /members/{user_id}` and `DELETE /members/{user_id}` work in the
organization of the caller's access token. The role is read from the membership on every
request, so a removed member, a deactivated account or a changed role takes effect at once, not
when the access token expires. An organization keeps at least one active owner, and changes to
its members take turns (one advisory lock per organization). A member of another organization
is not found (404), never forbidden.

People join with an invitation. `POST /invitations` returns a one-time code, valid for seven
days, that the owner passes on (there is no mail service); the person redeems it with
`POST /auth/accept-invitation`, which creates their account if the address has none and
otherwise asks for its password, then signs them in to the organization. Only the code's digest
is stored; `GET /invitations` lists the open ones and `DELETE /invitations/{id}` revokes one. An
invitation stops working when the owner who issued it is removed, demoted or deactivated, so a
departing owner cannot return through it.

## Validating an invoice

`POST /invoices/validate` takes the invoice or credit note itself as the request body
(`Content-Type: application/xml`) and returns the validator's report (ADR-0015). `?profile=`
chooses `srb` (the default, as SEF validates), `en16931` or `peppol`. Nothing is stored: the
document lives in memory for the length of the request (no-store mode), and its content never
reaches a log.

```bash
curl -s localhost:8000/invoices/validate -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/xml' --data-binary @fixtures/invoices/synthetic/srb-final-invoice.xml
```

A document the validator cannot read, because the XML is malformed or declares a DOCTYPE or an
entity, is a violation in the report, not an error. A warm validation of a typical invoice takes
about 10 ms. The limits, all in [`.env.example`](../../.env.example):

| Answer | When | Setting (default) |
| --- | --- | --- |
| 413 | the body is larger than the limit, declared or counted while it is read | `SEF_MAX_INVOICE_BYTES` (5 MiB) |
| 413 | the document has more elements than the budget (an embedded PDF is one) | `SEF_MAX_INVOICE_ELEMENTS` (20 000) |
| 408 | the body has not arrived in time | `SEF_UPLOAD_SECONDS` (30) |
| 415 | the media type is not `application/xml` or `text/xml` | |
| 422 | the validation took longer than allowed and was stopped | `SEF_VALIDATION_SECONDS` (15) |
| 503 + `Retry-After` | as many validations as allowed are waiting or running | `SEF_MAX_VALIDATIONS_IN_FLIGHT` (8) |
| 429 + `Retry-After` | the caller, or their organization, has had as many validations this minute as allowed; see [Rate limits](#rate-limits) | `SEF_VALIDATIONS_PER_MINUTE` (60), `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300) |
| 503 | the validator cannot run on this server | |

The validator runs in a child process, one invoice at a time (`SEF_VALIDATOR=process`). Saxon
holds Python's global interpreter lock while it applies a rule set, so in the API's own process
a large document would stall every other request; in a child, a validation that runs too long
can be stopped, and the child is replaced at once. `SEF_VALIDATOR=thread` validates in a thread
of the API's process instead, without a time limit, for tests and tools.

## Stored invoices

`POST /invoices` validates the invoice in the body exactly as `POST /invoices/validate` does,
with the same limits, then keeps it for the caller's organization: the document byte for byte,
its SHA-256 digest, the profile, the validator's report and what the validator read from it
(type, number, issue date, currency, seller, buyer, amount due). It answers 201, and `Location`
names the stored invoice (ADR-0016). A document the validator cannot read is stored too, with
the report that says why.

```bash
curl -si localhost:8000/invoices -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/xml' --data-binary @fixtures/invoices/synthetic/srb-final-invoice.xml
curl -s "localhost:8000/invoices?limit=20" -H "Authorization: Bearer $ACCESS_TOKEN"
```

| Endpoint | Answer |
| --- | --- |
| `GET /invoices?limit=&after=&valid=` | the newest invoices first, up to 100 a page (50 by default), without their reports; `next` is the `after` of the next page; `valid=false` lists only those whose latest report is invalid, `valid=true` only the valid ones |
| `GET /invoices/{id}` | one invoice with its report |
| `GET /invoices/{id}/content` | the document byte for byte, as an attachment |
| `DELETE /invoices/{id}` | 204; the document and its report are gone |

Owners and accountants see every invoice of the organization; a client sees the ones they
submitted, and anything else is not found (404). An organization stores at most
`SEF_MAX_STORED_BYTES` (100 MiB) of documents and reports together; `POST /invoices` answers 507
beyond it, and deleting makes room. Every answer is marked `Cache-Control: no-store`. An
invoice's report is its latest, and `validated_at` says when the validator made it: when the
invoice was stored, or validated again. After a revalidation, `GET /invoices?valid=false`
lists the invoices it found invalid.

## Jobs

Work that outlasts a request runs as a job (ADR-0019). The first one validates stored invoices
again with the rules the server has now:

```bash
curl -si -X POST localhost:8000/invoices/revalidations -H "Authorization: Bearer $ACCESS_TOKEN"
curl -sN localhost:8000/jobs/$JOB_ID/events -H "Authorization: Bearer $ACCESS_TOKEN"
```

`POST /invoices/revalidations` answers 202 with the job, and `Location` names it. The job takes
on the invoices the caller may see, as `GET /invoices` lists them, that were stored by the time
it was started, and makes each new report the invoice's latest. An invoice whose new report
would take the organization past its quota keeps the one it has. Its progress and its result
count `total`, `done`, `valid`, `invalid`, `kept`, `failed` and `deleted`. A member has one
revalidation under way at a time: another request answers 409, with the one under way in
`Location`.

| Endpoint | Answer |
| --- | --- |
| `GET /jobs/{id}` | the job: its status, progress, result or error, and `version` |
| `GET /jobs/{id}/events` | server-sent events: a `job` event at once and whenever the job changes, with its `version` as the `id`; resume with `Last-Event-ID`; the stream ends with the finished job or after five minutes |

A client sees the jobs it would see the invoices of. In a browser, read the stream with `fetch`,
since `EventSource` cannot send an `Authorization` header.

Jobs run in the API's own process by default (`SEF_JOBS=inline`): unfinished ones are taken on
again when it starts. With more than one process, set `SEF_JOBS=arq` and `REDIS_URL`, and run
workers beside the API:

```bash
SEF_JOBS=arq make worker   # uv run python -m sef_api.jobs.worker
```

A worker puts every unfinished job back on the queue when it starts and once a minute, so
nothing is lost with Redis, and cuts an attempt short after an hour; the next attempt continues
where it stopped.

## API keys

A machine client, such as an ERP, authenticates with an API key instead of a person's password
(ADR-0017). A member issues keys for the machines that act for them, each with some of their
permissions, and sees a key only once, when it is issued:

```bash
curl -s localhost:8000/api-keys -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name": "Pantheon", "permissions": ["invoices:validate", "invoices:submit"]}'
curl -s localhost:8000/invoices -H "Authorization: Bearer $API_KEY"
```

- A key is `sefk_` and 43 characters. The database keeps its SHA-256 digest, and lists show
  its first 12 characters. A rule in `.gitleaks.toml` recognizes a key pasted into a file.
- A key may hold `invoices:validate`, `invoices:submit` and `invoices:manage`, each only if the
  member's role grants it. On every request it allows only what it holds and the member's role
  grants at that moment. A key administers no members and issues no keys.
- `GET /api-keys` lists the keys that work, the newest first, without the keys themselves;
  `DELETE /api-keys/{id}` revokes one at once. A member sees and revokes their own keys, an
  owner every key of the organization.
- A key works until it is revoked or reaches its optional `expires_at`. It is deleted with its
  member's membership, and a deactivated account's keys are refused. A member has at most 20
  keys that work.

Every answer that carries a credential, whether tokens, an invitation code or a new key, is
marked `Cache-Control: no-store`.

## Rate limits

Beyond a limit the API answers 429 with `Retry-After` in whole seconds, and a detail that names
what was counted (ADR-0018):

| What | Counted per | Limit |
| --- | --- | --- |
| `POST /auth/login` | address | 30 a minute |
| `POST /auth/register` | address | 10 an hour |
| `POST /auth/refresh` and `/auth/logout` | address | 60 a minute, together |
| `POST /auth/accept-invitation` | address | 10 a minute |
| wrong passwords, at sign-in and when accepting an invitation | e-mail address | 10 in 15 minutes |
| `POST /invoices/validate`, `/invoices/explain` and `POST /invoices` | caller: a member, or one API key | `SEF_VALIDATIONS_PER_MINUTE` (60) |
| `POST /invoices/validate`, `/invoices/explain` and `POST /invoices` | organization | `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300) |
| `POST /invoices/explain`, beside the validations | caller | `SEF_EXPLANATIONS_PER_MINUTE` (10) |
| `POST /invoices/explain`, beside the validations | organization | `SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE` (30) |

A limit allows its count at once, then one request every period divided by the count. Wrong
passwords are counted before the next password is checked, also for addresses no account has,
and the right password starts the count afresh. The counts live in the API's process, so with
several workers each counts its own.

The address is the one the server saw. Behind a reverse proxy, tell uvicorn which proxy to
trust, so that the address is the client's and not the proxy's:
`uvicorn sef_api.main:create_app --factory --proxy-headers --forwarded-allow-ips=<proxy address>`.

## The corpus

Explanations cite the official documents the validator's rules come from: the law and the
rulebook on e-invoicing, the PIB rulebook, the SRB-CIUS specification and the list of tax
categories, kept as text in [`corpus/`](../../corpus/README.md) (ADR-0020). Load them into the
database, after `make migrate`:

```bash
make ingest           # uv run python -m sef_api.rag.ingest [--corpus <directory>]
```

An ingest can run any number of times: it adds, updates and deletes passages until the
database holds exactly the corpus, and prints what it did. Each passage has the days it applies
(`valid_from`, up to but not including `valid_to`) and an id that names the first,
`e-invoicing-law/article-4b/2027-07-01`; `sef_api.rag.citations` gives the passages each
SRB-CIUS rule is authored from on a day.

Passages are found by keyword in either script (`search_text`, folded to Latin letters without
diacritics, with a trigram index) and, once embedded, by meaning (`embedding`, an HNSW index):

| `EMBEDDINGS_PROVIDER` | What an ingest embeds |
| --- | --- |
| `none` (default) | nothing; nothing leaves the server |
| `jina` | with `JINA_API_KEY`: every passage without an embedding of `jina-embeddings-v5-text-small` (1024 numbers), 32 to a request, again when its words change |

The migration that creates the tables needs a role that may create the `vector` and `pg_trgm`
extensions: the superuser of `make up` locally, Neon's default role in production.

## Explanations

`POST /invoices/explain` takes an invoice as `POST /invoices/validate` does, validates it in the
same way, and explains each rule its report names: what the rule asks, why the invoice fails it
and what to change, citing the corpus's passages that apply on the invoice's issue date
(ADR-0021). `?language=` is `sr` (the default, in Latin script) or `en`. Nothing is stored, and
the answer is `no-store`.

```bash
curl -s 'localhost:8000/invoices/explain?language=sr' -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/xml' \
  --data-binary @fixtures/invoices/synthetic/mutations/srb-009-pib-check-digit.xml
```

The answer, with the report as `POST /invoices/validate` gives it, shortened:

```json
{
  "report": { "profile": "srb", "valid": false, "violations": ["…"] },
  "day": "2026-10-05",
  "language": "sr",
  "model": "groq/openai/gpt-oss-120b",
  "explanations": [
    {
      "rule_id": "SRB-009",
      "violations": 2,
      "text": "…",
      "fix": "…",
      "citations": [
        {
          "id": "pib-rulebook/article-2/2018-10-01",
          "document": "pib-rulebook",
          "title": "Pravilnik o poreskom identifikacionom broju",
          "label": "Члан 2.",
          "heading": "Поступак, начин и рокови одређивања и додељивања ПИБ-а",
          "version": "Službeni glasnik RS, br. 57/2003, 68/2003, 32/2009, 48/2010 i 44/2018",
          "valid_from": "2018-10-01",
          "valid_to": null,
          "source_url": "https://…"
        }
      ],
      "problem": null
    }
  ],
  "unexplained": []
}
```

Each rule is explained once, from its first violation; rules with a fatal violation come first,
and those beyond `SEF_MAX_EXPLANATIONS` (5) are named in `unexplained`. A rule that cannot be
explained (no passage concerns it, the model gave no usable answer in three, or the time ran
out) has `text` and `fix` null and a `problem` that says why; the others stand. Every citation
is a stored passage: the model may cite only the ids retrieval gave it, and its answer is
checked before it is used.

| `LLM_PROVIDER` | What explains |
| --- | --- |
| `none` (default) | nothing: `/invoices/explain` answers 503, and nothing leaves the server |
| `groq` | with `GROQ_API_KEY`: Groq's `openai/gpt-oss-120b`, or the model `SEF_LLM_MODEL` names |

The model is sent the rule's first violation (its rule, place and message, which may quote a
value of the invoice) and the passages; nothing else of the invoice. With
`EMBEDDINGS_PROVIDER=jina`, what each rule says (its title, its statement or its rule set's
message, never the violation's message) is embedded too, to find passages by meaning in a
corpus embedded by the same model; the embedder is still sent public text only. All of a
request's explanations have `SEF_EXPLANATION_SECONDS` (30), the embeddings a fifth of them.
The answers are those of a validation, and:

| Answer | When | Setting (default) |
| --- | --- | --- |
| 503 | no model is configured; answered before the body is read | `LLM_PROVIDER` |
| 429 + `Retry-After` | the caller, or their organization, has asked for as many explanations this minute as allowed | `SEF_EXPLANATIONS_PER_MINUTE` (10), `SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE` (30) |

Without the model's answers, a request for a synthetic invoice takes 100 to 170 ms. With Groq's
free tier and `openai/gpt-oss-120b`, the whole request for an invoice with one rule to explain
took 1.5 s (measured on 6 November 2026), within the budget of 6 s an explanation.

## Database and migrations

PostgreSQL through SQLAlchemy 2 (async, asyncpg); the schema is versioned with Alembic
(ADR-0011). Every table that holds a tenant's data has an `organization_id`.

```bash
uv run alembic -c apps/api/alembic.ini upgrade head                    # apply
uv run alembic -c apps/api/alembic.ini downgrade -1                    # undo the last one
uv run alembic -c apps/api/alembic.ini revision --autogenerate --rev-id NNNN -m "add ..."
uv run alembic -c apps/api/alembic.ini upgrade head --sql              # print the SQL instead
```

Revision ids are four-digit sequence numbers (`NNNN` is the next one). A generated revision is a
draft: read it, make the downgrade exact, and run the tests, which check that the migrations
build exactly the models' schema and that every step can be undone.

## Test

```bash
uv run pytest apps/api --cov=apps/api/src/sef_api      # or: make test-api
```

Database tests run on the server named by `SEF_TEST_DATABASE_URL` (environment or `.env`), for
example `postgresql+asyncpg://sef:sef@localhost:5432/postgres` with `make up`. The suite creates
a database of its own, migrates it, rolls every test back and drops the database at the end.
Without the variable those tests are skipped; CI always runs them. The worker tests need Redis
as well, the database named by `SEF_TEST_REDIS_URL` (`redis://localhost:6379/15` with
`make up`), which they empty. The validator's tests need the fetched rule sets
(`make rulesets`), as the core's do.

## Layout

```text
src/sef_api/
  main.py        application factory (`create_app`): settings, database, routers
  settings.py    configuration from the environment (pydantic-settings)
  db.py          declarative base, engine, sessions, the `get_session` dependency, pgvector's
                 column type
  models.py      organizations, users, memberships, roles, invitations, refresh tokens,
                 stored invoices, API keys, jobs, the corpus's documents and passages
  locks.py       the advisory locks on an organization's members, invoices and API keys,
                 and the one that makes two ingests of the corpus take turns
  rate_limits.py the rate limiter (GCRA), what it counts and the limits
  api_keys/      issuing, authenticating, listing and revoking API keys, `/api-keys` routes
  auth/          passwords, tokens, the sign-in service, `/auth` routes, `current_principal`
  invoices/      upload limits, the validator and its child process, stored invoices and
                 validating them again, `/invoices` routes
  jobs/          running a job, the inline runner, the Redis queue and its worker, `/jobs`
                 routes with the event stream
  members/       members and invitations, `/members` and `/invitations` routes
  rag/           the corpus: text in two scripts, editions and dated passages, embeddings,
                 ingesting (`python -m sef_api.rag.ingest`), the passages each rule cites
  migrations/    Alembic environment and revisions (`versions/`)
  routes/        one router module per resource
alembic.ini      command-line configuration of the migrations
tests/           httpx-based tests against the ASGI app; database tests on PostgreSQL
```
