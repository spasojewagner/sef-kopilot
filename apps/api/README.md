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
| `GET /invoices?limit=&after=` | the newest invoices first, up to 100 a page (50 by default), without their reports; `next` is the `after` of the next page |
| `GET /invoices/{id}` | one invoice with its report |
| `GET /invoices/{id}/content` | the document byte for byte, as an attachment |
| `DELETE /invoices/{id}` | 204; the document and its report are gone |

Owners and accountants see every invoice of the organization; a client sees the ones they
submitted, and anything else is not found (404). An organization stores at most
`SEF_MAX_STORED_BYTES` (100 MiB) of documents and reports together; `POST /invoices` answers 507
beyond it, and deleting makes room. Every answer is marked `Cache-Control: no-store`.

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
| `POST /invoices/validate` and `POST /invoices` | caller: a member, or one API key | `SEF_VALIDATIONS_PER_MINUTE` (60) |
| `POST /invoices/validate` and `POST /invoices` | organization | `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300) |

A limit allows its count at once, then one request every period divided by the count. Wrong
passwords are counted before the next password is checked, also for addresses no account has,
and the right password starts the count afresh. The counts live in the API's process, so with
several workers each counts its own.

The address is the one the server saw. Behind a reverse proxy, tell uvicorn which proxy to
trust, so that the address is the client's and not the proxy's:
`uvicorn sef_api.main:create_app --factory --proxy-headers --forwarded-allow-ips=<proxy address>`.

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
Without the variable those tests are skipped; CI always runs them. The validator's tests need
the fetched rule sets (`make rulesets`), as the core's do.

## Layout

```text
src/sef_api/
  main.py        application factory (`create_app`): settings, database, routers
  settings.py    configuration from the environment (pydantic-settings)
  db.py          declarative base, engine, sessions, the `get_session` dependency
  models.py      organizations, users, memberships, roles, invitations, refresh tokens,
                 stored invoices, API keys
  locks.py       the advisory locks on an organization's members, invoices and API keys
  rate_limits.py the rate limiter (GCRA), what it counts and the limits
  api_keys/      issuing, authenticating, listing and revoking API keys, `/api-keys` routes
  auth/          passwords, tokens, the sign-in service, `/auth` routes, `current_principal`
  invoices/      upload limits, the validator and its child process, stored invoices,
                 `/invoices` routes
  members/       members and invitations, `/members` and `/invitations` routes
  migrations/    Alembic environment and revisions (`versions/`)
  routes/        one router module per resource
alembic.ini      command-line configuration of the migrations
tests/           httpx-based tests against the ASGI app; database tests on PostgreSQL
```
