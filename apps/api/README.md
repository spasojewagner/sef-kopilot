# sef-kopilot-api

FastAPI application exposing the validator, the explanation and repair layers, multi-tenant
persistence, background jobs with SSE progress, the SEF demo integration and the MCP server.
The deterministic engine lives in `packages/einvoice_core`; this app only orchestrates it.

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

The web application's pages call the API from the browser. `SEF_WEB_ORIGINS` names the origins
whose pages may (CORS), separated by commas: `http://localhost:3000` in `.env.example`, and only
`https://` origins in production. With none, no page of another origin may call it. A page may
send `Authorization`, `Content-Type` and `Last-Event-ID`, and read `Location` and `Retry-After`;
it sends its token in a header, so no credentials are allowed.

## The image

`apps/api/Dockerfile` builds the API into an image (ADR-0034), from the repository's root:

```bash
docker build -f apps/api/Dockerfile -t sef-kopilot-api .
docker run -p 8000:8000 \
  -e DATABASE_URL=postgresql+asyncpg://user:password@host:5432/database \
  -e SEF_JWT_SECRET="$(openssl rand -hex 32)" \
  sef-kopilot-api
```

The build installs the locked dependencies of the API alone, without the tools of development,
checks the rule sets against their pins (fetching them when the build is given none), and
compiles every profile's stylesheets, so that a container does not compile them when it starts.
A container applies the migrations to its database and then serves on `PORT` (8000), as the
user `sef`, which owns no file; `SEF_ENVIRONMENT` is `production`, so the database and the
signing key must be given. It keeps nothing on its disk. `python -m sef_api.rag.ingest` loads
the corpus the image holds into the database.

Behind a platform's proxy, set `FORWARDED_ALLOW_IPS` to the proxy's addresses, or to `*` where
the proxy is the only way to the container: the rate limits count by the client's address,
which the server then takes from the proxy's `X-Forwarded-For` (ADR-0018).

In 512 MB and a tenth of a CPU, about what a small free instance has, the image is ready about
40 s after it starts on an empty database, validates a typical invoice in 0.1 to 0.4 s and one of
11 800 elements in about 5 s, and uses at most about 330 MB (measured on 7 November 2026).

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
| `organization:read`: see the organization and how long it keeps its invoices | yes | yes | yes |
| `organization:manage`: set how long the organization keeps its invoices | yes | no | no |

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

## How long data is kept

A finished job is deleted, with its parameters, progress and result or error, 30 days after it
ends (`SEF_JOB_RETENTION_DAYS`, ADR-0038); a job under way never is. A stored invoice is kept
until a member deletes it, unless its organization sets a retention period (ADR-0039): an owner
sets it with `PATCH /organization`, from 1 to 3 650 days, and `null` removes it.

```bash
curl -s -X PATCH localhost:8000/organization -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' -d '{"invoice_retention_days": 365}'
```

An invoice stored longer ago than the period is then deleted, with its document, its report and
its repairs, and that cannot be undone. The deletions run where the jobs run: in the API's
process when it starts and every six hours, or in each worker when it starts and every day at
03:17 UTC. `GET /organization` shows every member the period, and the audit log records each
change of it with what it was.

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
| `POST /invoices/{id}/explanations?language=` | the explanations of the invoice's report (below), kept with it once every rule asked about is explained |
| `GET /invoices/{id}/explanations?language=` | the explanations kept for the invoice's report in that language; 204 when none are |
| `DELETE /invoices/{id}` | 204; the document, its report and its kept explanations are gone |

Owners and accountants see every invoice of the organization; a client sees the ones they
submitted, and anything else is not found (404). An organization stores at most
`SEF_MAX_STORED_BYTES` (100 MiB) of documents and reports together; `POST /invoices` answers 507
beyond it, and deleting makes room. Every answer is marked `Cache-Control: no-store`. An
invoice's report is its latest, and `validated_at` says when the validator made it: when the
invoice was stored, or validated again. After a revalidation, `GET /invoices?valid=false`
lists the invoices it found invalid.

## Repairs

A repair is a list of patches for a stored invoice (ADR-0023, ADR-0024), proposed by a member
or by a machine client with an API key. `POST /invoices/{id}/repairs` applies the patches to a
copy of the invoice in the validator's child process, within the same limits as a validation,
and keeps the repair: what became of each patch, the difference, and the validator's report on
the patched invoice. It answers 201, and `Location` names the repair. The invoice itself does
not change until a person approves the repair. A patch that touches an amount, VAT, a tax or
company identifier, a date or the document's number is not applied: it needs that person's
decision.

```bash
curl -si localhost:8000/invoices/$INVOICE/repairs -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"patches": [{"xpath": "/ubl:Invoice/cbc:InvoiceTypeCode", "op": "replace", "value": "380", "reason": "SEF takes 380, 381, 383 and 386 only"}]}'
```

| Endpoint | Answer |
| --- | --- |
| `POST /invoices/{id}/repairs` | 201 with the repair; 409 when ten of the invoice's repairs wait for a decision, or the invoice changed while the patches were applied; 422 for malformed patches, or an invoice that is not well-formed XML |
| `GET /invoices/{id}/repairs` | the invoice's repairs, the latest first (100 at most), without their reports and differences |
| `GET /invoices/{id}/repairs/{repair_id}` | one repair: each patch's outcome, the difference, the report |
| `POST /invoices/{id}/repairs/{repair_id}/approval` | 200 with the repair, `approved`: the invoice is now the patched document with its report; 403 with an API key; 409 when the repair waits for no decision, changes nothing, or the invoice or what its patches leave is not what it was when they were proposed; 507 beyond the storage quota |
| `POST /invoices/{id}/repairs/suggestion` | 201 with the repair the language model proposes (below); 409 when the invoice is valid, ten of its repairs wait, or it changed meanwhile; 422 when the model proposed no patch to keep; 502 when it gave no answer to use; 503 without a model; 504 when no round was done in time |
| `POST /invoices/{id}/repairs/{repair_id}/rejection` | 200 with the repair, `rejected`; the invoice stays as it is; 403 with an API key; 409 when the repair waits for no decision |

Every 409 of these endpoints names its `reason` beside the `detail`, so that a client tells them
apart without reading the English: `nothing-to-repair` (the invoice is valid),
`too-many-waiting`, `invoice-changed` (it is not the document the repair was proposed for, or it
changed while the patches were applied), `decided` (the repair waits for no decision),
`changes-nothing` and `outcome-changed` (the patches no longer leave the document they left).

```json
{"detail": "10 repairs of this invoice wait for a decision: decide on them first", "reason": "too-many-waiting"}
```

Only a person decides: a member signed in with an access token, never an API key, since a key
can leak from the ERP it serves. Approval applies the patches again, counted as a validation,
and only to the document they were proposed for, which they must turn into the document they
turned it into then; the invoice becomes that document within `SEF_MAX_STORED_BYTES`, and the
other repairs that waited for it become `superseded`, since they were proposed for a document
it no longer is. A repair is seen by whoever sees its invoice, and is deleted with it.
Proposing counts as a validation against the rate limits. Each proposal, approval and rejection is committed with an event in the audit log
(`audit_events`): who, with which key, to which invoice and repair, the digests of the document
before and after, the verdict, each patch's place, operation and outcome, and the repairs an
approval superseded; never a value or a reason, which may quote the invoice. An event outlives the invoice and the repair it names,
and goes with the organization.

### Repairs the language model proposes

`POST /invoices/{id}/repairs/suggestion` has the language model write the patches (ADR-0025),
and keeps what it proposes as a repair of the caller's, in person or with an API key, decided
on like any other. `?language=` sets the language of the patches' reasons, `sr` (the default)
or `en`. The repair's `model` names the model that wrote them.

```bash
curl -si -X POST "localhost:8000/invoices/$INVOICE/repairs/suggestion?language=sr" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

The model is sent the invoice's first ten fatal violations and the invoice's fields around them,
sixty at most: every basic component that holds text, and every attribute, of the aggregate a
violation is in, by canonical path and with its value, saying which fields a person decides.
Nothing else of the invoice is sent, and nothing in the extensions. Before anything is applied,
every answer is checked. It must hold at most twenty patches, each one the patch engine takes,
at a canonical path, writing no amount, rate, date or identifier the model was not given
(ADR-0022). An answer that fails goes back to the model with what is wrong, up to three a round.
The validator's child process applies the patches, after those kept from an earlier round, and
validates what they leave. While fatal violations remain, the model is told what became of each
patch and asked once more: two rounds at most, within `SEF_REPAIR_SECONDS` (20).

A patch that failed is not kept, since it changed nothing, nor is one that wrote at its place
the value already there; the model is told so in the next round, and without another patch to
keep the answer is 422. One that a person decides is kept, for the person to see, and changes
nothing either. A round that leaves more fatal violations
than there were is not kept. A suggestion counts as a validation and as a request to the
language model, and the audit event of the proposal adds the model and the rounds.

Without the model's answers, a suggestion for a synthetic invoice takes about 40 ms through the
child process, with one round or two (the median of eight, measured on 6 November 2026); the
rest of the budget of 20 s is the model's.

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
| `POST /invoices/validate`, `/invoices/explain`, `POST /invoices`, and a repair's proposal, suggestion and approval | caller: a member, or one API key | `SEF_VALIDATIONS_PER_MINUTE` (60) |
| the same | organization | `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300) |
| requests to the language model, `/invoices/explain` and `/repairs/suggestion`, beside the validations | caller | `SEF_EXPLANATIONS_PER_MINUTE` (10) |
| the same | organization | `SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE` (30) |

A limit allows its count at once, then one request every period divided by the count. Wrong
passwords are counted before the next password is checked, also for addresses no account has,
and the right password starts the count afresh. The counts live in the API's process, so with
several workers each counts its own.

The address is the one the server saw. Behind a reverse proxy, tell uvicorn which proxy to
trust, so that the address is the client's and not the proxy's:
`uvicorn sef_api.main:create_app --factory --proxy-headers --forwarded-allow-ips=<proxy address>`.

Every request body other than an invoice, the JSON of a request, is read at most to
`SEF_MAX_BODY_BYTES` (1 MiB) before the application sees it: a longer one, declared or counted
while it is read, answers 413. An invoice has its limit of its own (`SEF_MAX_INVOICE_BYTES`).

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
checked before it is used. An answer may name only the dates, amounts, rates and identifiers
its question contains: the model invents none and computes none (ADR-0022).

| `LLM_PROVIDER` | What explains, and proposes repairs |
| --- | --- |
| `none` (default) | nothing: `/invoices/explain` and `/repairs/suggestion` answer 503, and nothing leaves the server |
| `groq` | with `GROQ_API_KEY`: Groq's `openai/gpt-oss-120b`, or the model `SEF_LLM_MODEL` names |

The model is sent the rule's first violation (its rule, place and message, which may quote a
value of the invoice) and the passages; nothing else of the invoice. With
`EMBEDDINGS_PROVIDER=jina`, what each rule says (its title, its statement or its rule set's
message, never the violation's message) is embedded too, to find passages by meaning in a
corpus embedded by the same model; the embedder is still sent public text only. Each text is
embedded once a model, and its vector kept in `rule_embeddings` for every later explanation
(ADR-0041). All of a request's explanations have `SEF_EXPLANATION_SECONDS` (30), the
embeddings a fifth of them.
The answers are those of a validation, and:

| Answer | When | Setting (default) |
| --- | --- | --- |
| 503 | no model is configured; answered before the body is read | `LLM_PROVIDER` |
| 429 + `Retry-After` | the caller, or their organization, has made as many requests to the language model this minute as allowed, for explanations or a repair | `SEF_EXPLANATIONS_PER_MINUTE` (10), `SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE` (30) |

Without the model's answers, a request for a synthetic invoice takes 100 to 170 ms. With Groq's
free tier and `openai/gpt-oss-120b`, the whole request for an invoice with one rule to explain
took 1.5 s (measured on 6 November 2026), within the budget of 6 s an explanation.

`POST /invoices/{id}/explanations` explains a stored invoice's latest report in the same way,
without validating it again (ADR-0029), and keeps the explanations with the invoice, one set a
language, when every rule asked about is explained (ADR-0040). Later requests in that language,
by any member who may see the invoice, read the kept set: the model is not asked, nothing is
counted, and a server without a model answers too. `written_at` says when they were written. A
set explains the report whose digest it keeps, on the day whose law it cites: once the
invoice's report is another, after a repair is approved or the invoice validated again, the
next request writes a new set in its place. `GET /invoices/{id}/explanations` reads the kept
set alone, and never asks the model; it answers 204 when none is kept, which a browser does not
log as an error, as it would a 404.

## The MCP server

The API is also an MCP server, for the clients of the Model Context Protocol: an assistant
that an accountant talks to, or an ERP's own automation (ADR-0042). It answers at `/mcp`, in
the API's process, over Streamable HTTP without sessions: each message is a POST, answered with
JSON. Clients of the protocol's current revision (2026-07-28) and of earlier ones are answered.

- **Who may connect:** a client sends, as a bearer token, an API key, as a machine client of
  the routes does, or, once `SEF_PUBLIC_URL` makes the API an authorization server, an access
  token its token endpoint issued for the MCP endpoint (below). An access token of the web
  application is refused (401): it was issued for the API's routes. A revoked or expired key, a
  consent that was revoked or is gone, and a member who has left are refused as the routes
  refuse them. A refusal's `WWW-Authenticate` names the endpoint's protected resource metadata
  and the scopes (RFC 9728 §5.1), which is how a client that has never met the server finds
  where to sign its person in.
- **What it may do:** each tool requires a permission, as the route it stands for does, and
  counts against the same limits; with an access token, its scopes must allow it too. A tool's
  error is the route's error, in the same words.
- **Its tools:**

  | Tool | Requires | Does what this route does |
  | --- | --- | --- |
  | `validate_invoice` | `invoices:validate` | `POST /invoices/validate`: the XML as text, a profile (`srb` by default); nothing is stored |
  | `explain_errors` | `invoices:validate` | `POST /invoices/explain`: the same, and a language (`sr` by default); the report and the explanations of its rules, with their citations; nothing is stored |

- **Its limits:** a message is a JSON body, at most `SEF_MAX_BODY_BYTES` (1 MiB): a larger
  invoice is uploaded to the tool's route instead. Only POST is answered (405 otherwise),
  since the server sends no messages of its own. A page of an origin other than the web
  application's is refused (403).

A client that lets its user set a header connects with the URL and the key. By hand:

```bash
curl -s localhost:8000/mcp -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}'
```

## The authorization server (OAuth 2.1)

For the assistants that sign their users in, the MCP endpoint gets an OAuth 2.1 authorization
server of its own, step by step (ADR-0044). Its routes, under `/oauth`, answer once
`SEF_PUBLIC_URL` names the API's address, such as `https://sef-kopilot-api.onrender.com`;
without it, they answer 404, and the MCP endpoint takes API keys alone.

- **Clients register themselves** with `POST /oauth/register` (RFC 7591). Every client is
  public: it is registered with `token_endpoint_auth_method: none`, whatever it asks for, gets
  no secret, and will prove with PKCE that it began the authorization it ends. A redirect URI
  is `https`, `http` on the loopback interface, or a scheme of the application's own, with no
  fragment; ten at most. Registering grants nothing, and is counted by address: ten an hour.
- **A client asks** by sending the person's browser to `GET /oauth/authorize` (OAuth 2.1
  §4.1), with `response_type=code`, PKCE (`code_challenge_method=S256`), a redirect URI it
  registered, the MCP endpoint as the `resource` (RFC 8707) and the scopes it wants
  (`invoices:validate`, the scope of the tools that validate). An unknown client or redirect
  URI is answered there (400); any other fault sends the browser back to the client with the
  error. A request that will do waits ten minutes for a person, on the web application's page
  at `SEF_WEB_URL` (`/oauth/consent?request=...`), which must be one of `SEF_WEB_ORIGINS`.
- **A person decides**, signed in, never with an API key: `GET /oauth/requests/{id}` says
  what the client asks; `POST .../approval` lets it act for them, for the scopes their role
  grants, records the consent in the audit log and answers where to send the browser, the
  client's redirect URI with a code valid for two minutes; `POST .../refusal` sends it back
  with `access_denied`. Every answer the client gets names this server (`iss`, RFC 9207).
- **The client exchanges the code** at `POST /oauth/token`, a form (OAuth 2.1 §3.2), once,
  with the PKCE verifier that began it and its client id; the redirect URI, if it names one,
  must be the one the code was sent to. It gets an access token for the MCP endpoint alone, for
  fifteen minutes (`SEF_ACCESS_TOKEN_MINUTES`): a JWT (RFC 9068) whose audience is
  `SEF_PUBLIC_URL/mcp`, naming the person, their organization, the client, the scopes and the
  consent, signed with a key derived from `SEF_JWT_SECRET` for these tokens alone, so that it
  and the web application's never pass for each other. A client that registered the
  `refresh_token` grant also gets a refresh token, kept as its SHA-256, which
  `grant_type=refresh_token` spends once for the next pair, with the consent's scopes or fewer.
  A code or a refresh token presented a second time revokes the consent: its refresh tokens and
  its access tokens are refused from then on. The role is read again at every exchange, and a
  member who is no longer one takes the consent with them (migration 0017). Token requests are
  counted by address: sixty a minute.
- **The documents that send a client here** are public, and a page of any origin may read them:
  `/.well-known/oauth-protected-resource/mcp` (RFC 9728), the MCP endpoint's, names this server
  as the issuer of its access tokens, and is at `/.well-known/oauth-protected-resource` too;
  `/.well-known/oauth-authorization-server` (RFC 8414) names this server's endpoints and what
  they support.
- **The MCP endpoint takes these access tokens**, checking on every request that the consent
  behind one stands and reading the member's role again, so that a revoked consent stops its
  access tokens at once. Refused, a client is told where the endpoint's metadata is (RFC 9728
  §5.1) and finds the rest from there: it needs no address but `/mcp`.
- **A client may be known by its metadata document** (ADR-0045), the revision's preferred way
  for a client to introduce itself, where `SEF_CLIENT_METADATA_DOCUMENTS=true`: its
  `client_id` is an `https` URL, and the document there, fetched at each authorization
  request, gives its name and redirect URIs, as a registration would. The fetch reaches only the
  public internet: every address the host resolves to must be public, the request goes to the
  address checked, with no redirect followed, within five seconds and 5 KiB. A document that
  will not do stops the request with 400. Authorization requests are counted by address:
  thirty a minute. Off by default: a self-hosted deployment calls out to nothing it did not
  choose.
- **Next:** the consent page naming the host that published a client's document.

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
  main.py        application factory (`create_app`): settings, database, routers, the MCP
                 endpoint
  settings.py    configuration from the environment (pydantic-settings)
  db.py          declarative base, engine, sessions, the `get_session` dependency, pgvector's
                 column type
  models.py      organizations, users, memberships, roles, invitations, refresh tokens,
                 stored invoices, API keys, jobs, the corpus's documents and passages,
                 repairs and audit events
  locks.py       the advisory locks on an organization's members, invoices and API keys,
                 and the one that makes two ingests of the corpus take turns
  rate_limits.py the rate limiter (GCRA), what it counts and the limits
  api_keys/      issuing, authenticating, listing and revoking API keys, `/api-keys` routes
  auth/          passwords, tokens, the sign-in service, `/auth` routes, `current_principal`
  invoices/      upload limits, the validator and its child process (validating and patching),
                 stored invoices and validating them again, `/invoices` routes
  repairs/       repairs of stored invoices: proposals and their outcomes, the repairer
                 that has the language model propose patches, `/invoices/{id}/repairs` routes
  audit.py       the audit log's events: who did what, without the invoice's content
  bodies.py      the limit on every request body other than an invoice
  llm.py         the language model behind an adapter (Groq), and the languages it writes in
  values.py      the dates and numbers a model's answer names, and those it made up
  jobs/          running a job, the inline runner, the Redis queue and its worker, `/jobs`
                 routes with the event stream
  members/       members and invitations, `/members` and `/invitations` routes
  organization/  the caller's organization and its retention period, `/organization` routes
  retention.py   deleting finished jobs and stored invoices once they are past their retention
  rag/           the corpus: text in two scripts, editions and dated passages, embeddings,
                 ingesting (`python -m sef_api.rag.ingest`), the passages each rule cites
  mcp/           the MCP server at `/mcp`: who may connect, its tools, the endpoint
  oauth/         the authorization server of the MCP endpoint: clients registering
                 themselves, their requests and a person's decision, `/oauth` routes
  migrations/    Alembic environment and revisions (`versions/`)
  routes/        one router module per resource
alembic.ini      command-line configuration of the migrations
Dockerfile       the API's image; `docker/start.sh` applies the migrations, then serves
tests/           httpx-based tests against the ASGI app; database tests on PostgreSQL
```
