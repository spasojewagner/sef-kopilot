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
- Liveness: `GET /health` · Readiness: `GET /ready` (503 while the database does not answer)

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
Without the variable those tests are skipped; CI always runs them.

## Layout

```text
src/sef_api/
  main.py        application factory (`create_app`): settings, database, routers
  settings.py    configuration from the environment (pydantic-settings)
  db.py          declarative base, engine, sessions, the `get_session` dependency
  models.py      organizations, users, memberships, roles, refresh tokens
  auth/          passwords, tokens, the sign-in service, `/auth` routes, `current_principal`
  migrations/    Alembic environment and revisions (`versions/`)
  routes/        one router module per resource
alembic.ini      command-line configuration of the migrations
tests/           httpx-based tests against the ASGI app; database tests on PostgreSQL
```
