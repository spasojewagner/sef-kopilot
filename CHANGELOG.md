# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Every pull request adds its
line under **Unreleased**; the maintainer moves the section to a version heading when a milestone
is tagged.

## [Unreleased]

### Added

- `evals`: the evaluations' runner, `sef-evals` (`make evals`, `make evals-check`), which
  measures the validator on every document of the corpus against golden labels, and against
  the published rule sets applied as published: the same verdicts and fatal rules, no false
  accept or reject, every mistake reported by the rules it must be. The measures are judged
  against `evals/thresholds.yaml` and written to a committed report, `evals/reports/latest.md`
  (ADR-0054).
- `evals`: the explanations' evaluations: every rule the mutations break, explained as the API
  explains a report, on a database of the evaluations' own; the rules explained, the citations
  that resolve to a stored passage, and those of a passage labelled relevant to the rule (90 %
  at least). The model's answers are recorded once with `make evals-record` and replayed
  offline, so CI never calls the model (ADR-0055).

## [0.5.0] - 2026-11-09

The SEF demo round trip (milestone M5): an organization's key to SEF, which its owner sets and
removes and which no one is shown, sealed for that organization alone; a stored invoice sent to SEF's
demo environment in the organization's name, only when the validator passes it, byte for byte
as validated and once, with where it stands in SEF asked until it is final; the same sending
from an assistant, through a scope asked for when it first sends, and from an ERP's API key,
by the owner's or the accountant's choice; and the pages where an owner sets the key and where
a member sends an invoice and sees what SEF answered. The client follows SEF's published API
and is tested against a stand-in that answers as its OpenAPI document describes; SEF's error
codes in the explanations, and what the published documents leave open, wait for a SEF demo
account, at the maintainer's decision.

### Added

- `apps/api`: an organization's key to SEF, which an owner sets with `PUT
  /organization/sef-key` and removes with `DELETE`, sealed with Fernet under `SEF_FERNET_KEY`
  for that organization alone (ADR-0050, migration 0020); `GET /organization` shows since when
  one is set (`sef_key_set_at`), never the key, and `make rotate-sef-keys` seals every stored
  key again under a new secret.
- `apps/api`: a stored invoice sent to SEF's demo environment (`POST /invoices/{id}/sef`, the
  permission `invoices:send` of owners and accountants) with the organization's key, only when
  the validator passes it under SRB-CIUS, byte for byte as validated, and once: an answer lost
  is asked for again with the same `requestId` (ADR-0051, migration 0021). `GET
  /invoices/{id}/sef` shows what SEF answered and where the invoice stands in SEF, which the API
  asks once a minute where the jobs run, less often as an invoice ages, until it is final.
- `apps/api`: the OAuth scope `invoices:send`, with which a person lets an assistant send to
  SEF in their organization's name; a client that names no scope is not given it to decide on,
  and the MCP endpoint's challenge names the other two, so that it is asked for when an
  assistant first sends (ADR-0052). `GET /oauth/requests/{id}` names the scopes asked for that
  the person's role does not grant (`withheld`).
- `apps/web`: the consent page names apart what the person's role withholds, which approving
  does not give the client, and lets them only deny a client whose every scope it withholds;
  sending to SEF has its words in Serbian and English.
- `apps/api`: the MCP tools `send_to_sef_demo`, which sends a stored invoice of the person's to
  SEF's demo environment as `POST /invoices/{id}/sef` does, and `get_sef_status`, which reads
  where it stands in SEF as `GET /invoices/{id}/sef` does; the server's instructions tell an
  assistant to send only when its person asks.
- `apps/api`: an API key may hold `invoices:send`, for an ERP that sends its organization's
  invoices to SEF with an owner's or an accountant's key; the audit log names the key that sent
  (ADR-0053, migration 0022).
- `apps/web`: the API keys page offers sending to SEF to owners and accountants.
- `apps/web`: the organization's page shows every member since when the organization has a key
  to SEF, and lets its owner set one, in a field that forgets it once saved, replace it, or
  remove it after a second press.
- `apps/web`: the report says where the invoice stands in SEF, read again while the API asks
  SEF, and lets an owner or an accountant send a valid invoice, after a second press that names
  the organization; SEF's answers and the API's refusals are said in Serbian and English.

### Fixed

- `apps/api`: a page of the web application may send PUT, with which an owner sets the
  organization's key to SEF: the browser refused the request before it reached the API.

### Security

- `apps/api`: a request that the API's models refuse is answered 422 with where and why, and
  no longer with what it held: FastAPI's answer repeated each value refused, a password too
  short included, and for a field missing the whole object around it.

## [0.4.0] - 2026-11-08

The MCP server and OAuth 2.1 (milestone M4): the API's tools for an assistant at `/mcp`, in
the API's process, answering without sessions, to validate an invoice, explain its errors with
dated citations, read the rules, and work on the organization's stored invoices and their
repairs, each tool within what the person's role and the client's scopes allow; an
authorization server of the API's own for assistants that sign their person in, with PKCE,
resource indicators, self-registration or client metadata documents fetched safely, a consent
page that names who asks, and the step-up when a tool needs more; shown from Claude and ChatGPT
on the public demo. Around it: how long data is kept, explanations kept with a stored invoice's
report, rules embedded once, security events and structured logs, API keys on the
organization's page, and error reports and the model's traces that hold nothing a person sent.

### Added

- `apps/api`: finished jobs are deleted 30 days after they end (`SEF_JOB_RETENTION_DAYS`,
  ADR-0038), with their parameters, progress and result or error; a job under way never is.
  The API's process deletes them when it starts and every six hours with `SEF_JOBS=inline`, and
  each worker when it starts and every day at 03:17 with `SEF_JOBS=arq`.
- `apps/api`: an organization's stored invoices are deleted once they were stored longer ago
  than the retention period it set (ADR-0039), with their documents, reports and repairs; the
  audit log keeps what it named of them, by id. An organization without a period, as every one
  is until an owner sets it, keeps its invoices until a member deletes them. The same processes
  delete them, at the same times, as the old finished jobs.
- `apps/api`: `GET /organization` shows every member the organization's name and how long it
  keeps its stored invoices, and `PATCH /organization` lets an owner set that period, from 1 to
  3 650 days, or none with `null` (the permissions `organization:read` and
  `organization:manage`, which no API key holds). A change checks the owner's role again under
  the organization's lock, and the audit log records it with what the period was.
- `apps/web`: the organization's page, `/organization`, linked from the header: every member
  sees the organization's name, their role and how long it keeps its stored invoices, and an
  owner sets the period. A period that deletes invoices is saved only after a second press that
  names the day up to which stored invoices go.
- `apps/api`: the explanations of a stored invoice's report are kept with it, one set a language,
  once every rule asked about is explained (ADR-0040, migration 0013). Later requests read them
  without asking the language model or counting a request, until the invoice's report is
  another; `GET /invoices/{invoice_id}/explanations` reads them alone, or answers 204 when none
  are kept, and every answer with explanations says when they were written (`written_at`).
- `apps/web`: the report's page shows the explanations the API keeps for the report at once,
  reading them with `GET`, which asks the language model nothing, and offers to ask the model
  only when none are kept.
- `apps/api`: what each rule says is embedded once an embedding model and its vector kept
  (ADR-0041, migration 0014): an explanation asks the embedder only for texts it has not seen,
  once a text, and an embedder that fails or is late keeps nothing new.
- `apps/api`: an MCP server at `/mcp`, in the API's process (ADR-0042): Streamable HTTP
  without sessions, every message a POST answered with JSON, for clients of the protocol's
  current revision and earlier ones. A client connects with an API key; an access token of the
  web application, a page of another origin and a method other than POST are refused. Each tool
  requires its route's permission and counts against its limits; the first, `validate_invoice`,
  validates an invoice's XML as `POST /invoices/validate` does, storing nothing.
- `apps/web`: the brand's mark, a compass bezel whose needle is a check, beside the product's
  name, and the icons it gives a browser's tab and a phone's home screen.
- `apps/web`: a shared link to the site shows the brand's image (`opengraph-image.png`), at the
  site's address, which a build outside Vercel reads from `SITE_URL`.
- `apps/api`: the MCP tool `explain_errors` explains an invoice's errors as
  `POST /invoices/explain` does: the report and an explanation of each rule it names, in
  Serbian or English, with the passages it cites; counted as a validation and a request to the
  language model, storing nothing.
- `apps/api`: the first step of the MCP endpoint's OAuth 2.1 authorization server
  (ADR-0044), which answers once `SEF_PUBLIC_URL` names the API's address: MCP clients
  register themselves with `POST /oauth/register` (RFC 7591, migration 0015), always as public
  clients without a secret, with the redirect URIs OAuth 2.1 allows; counted by address.
- `apps/api`: the authorization endpoint, `GET /oauth/authorize`, requiring PKCE with S256, a
  registered redirect URI, the MCP endpoint as the resource and known scopes; a request waits
  ten minutes on the web application's page (`SEF_WEB_URL`) for a signed-in person, who
  approves it, for the scopes their role grants, or refuses it (`/oauth/requests/{id}`,
  migration 0016). An approval issues a code valid for two minutes and is recorded in the
  audit log; every answer to the client names the issuer (RFC 9207).
- `apps/api`: the token endpoint, `POST /oauth/token`: a code a consent issued is exchanged
  once, with its PKCE verifier, for an access token for the MCP endpoint alone (a JWT whose
  audience is the endpoint, signed with a key of its own) and, for a client that registered
  the grant, a refresh token, spent once for the next pair; a code or a refresh token
  presented again revokes the consent, and the role is read again at each exchange (migration
  0017).
- `apps/api`: the documents that send an MCP client to sign its person in, readable by pages
  of any origin: the MCP endpoint's protected resource metadata,
  `/.well-known/oauth-protected-resource/mcp` (RFC 9728), and the authorization server's,
  `/.well-known/oauth-authorization-server` (RFC 8414).
- `apps/api`: the MCP endpoint takes the authorization server's access tokens, for the scopes
  they carry and the role the member holds now, while the consent behind them stands; a
  refusal names the endpoint's protected resource metadata (RFC 9728 §5.1).
  `docs/DEPLOY.md` says how to turn it on and connect an assistant.
- `apps/web`: the page where a person decides on an MCP client's request, `/oauth/consent`
  (ADR-0044): what the client asks, the name it gave itself (unchecked), the address it takes
  them back to and the organization it will work in; allowing or denying takes them back to
  the client with its answer. A visitor who is not signed in signs in there, and stays.
- `apps/web`: a picture or a PDF chosen on the upload page is not sent; the page says that SEF
  Kopilot checks the e-invoice itself, the XML sent to SEF, and where to get it.
- `apps/api`: an MCP client may be known by its metadata document (ADR-0045), where
  `SEF_CLIENT_METADATA_DOCUMENTS=true`: an `https` client_id whose document the authorization
  server fetches at each authorization request, from the public internet only, and reads as a
  registration; its metadata says so (`client_id_metadata_document_supported`). Authorization
  requests are counted by address.
- `apps/web`: the consent page names the host that published the description of a client known
  by its metadata document, beside the name the client gives itself, which stays unchecked.
- `apps/api`: an MCP client running in a browser, such as the MCP Inspector, may sign its person
  in: the authorization server's metadata documents, registration and token endpoint answer a
  page of any origin, its preflight included; the rest of the API answers the web
  application's origins alone.
- `apps/api`: an MCP client's acts are told apart from the person's: a caller says which
  credential it came with, only a person in person decides on a repair or a client's request,
  a long request reads the consent again, the audit log names the client (migration 0018), and
  the client's requests are counted against its consent, apart from the person's own.
- `apps/api`: the MCP server's tools on stored invoices, `store_invoice`, `list_invoices` and
  `get_invoice`, as their routes do, and the scope an assistant needs for them,
  `invoices:submit`, which the consent page names; through an assistant, a person sees the
  invoices they submitted.
- `apps/api`: the MCP server's tools that explain a stored invoice, `explain_invoice` (the kept
  explanations first, ADR-0040), and validate stored invoices again, `revalidate_invoices`, in a
  job that `get_job` reads, as their routes do.
- `apps/api`: the MCP revision's step-up: a call through an MCP client of a tool its scopes
  do not reach is answered 403 `insufficient_scope`, with the scopes to ask the person for,
  before the tool runs; every tool stays listed (ADR-0046).
- `apps/api`: the MCP server's `propose_fix`, a repair of a stored invoice with the server's
  model writing the patches or the assistant giving its own, kept until a person decides on the
  web application's page it names, and `get_repair`, which reads whether they have.
- `einvoice_core`: the catalogue of the rules a profile applies, or sets aside, read from the
  rule sets the validator runs, with the calculation and SRB-CIUS rules, and a search over it
  by id, business term or words (ADR-0047).
- `apps/api`: `GET /rules`, the rules of a profile found by id, business term or words, with
  the passages that share the words, and `GET /rules/{rule_id}`, a rule with the passages an
  explanation of it would cite on a day.
- `apps/api`: the MCP server's `search_rules` and `get_rule`, as `/rules` answers, under the
  scope that checks invoices, `invoices:validate`.
- `apps/api`: every log line of a container as one JSON object, each request's lines named by
  its id, which `X-Request-ID` answers; the security events, logged with the fields that
  identify them and nothing a person wrote: sign-ins, refused keys, reused tokens, consents and
  repairs decided.
- `apps/api`: when each API key was last used, `last_used_at` in `GET /api-keys`, written at
  most once a minute with a security event, `api-key.used` (migration 0019).
- `apps/web`: the member's API keys on the organization's page: each with what it allows and
  when it was last used, a new one shown once, and a revocation asked twice.
- `apps/api`: unexpected errors of the API and its workers reported to Sentry where
  `SENTRY_DSN` is set, with where they happened and nothing a person sent (ADR-0048).
- `apps/api`: each request to the language model traced to Langfuse where its keys are set:
  the model, the time, the tokens and the outcome, never the conversation (ADR-0049).

### Changed

- `apps/web`: the pages wear the brand's colours and typefaces (ADR-0043): ink navy and one
  teal accent, in light and in dark; Onest for the text and JetBrains Mono for rule ids, paths
  and XML, served with the pages. A test measures the contrast of every pair of colours the
  pages set together against WCAG 2.2 AA.
- `apps/web`: the header is on the brand's navy, with a member's sections beside the logo, the
  one the page is in marked, and a first link that leads a keyboard past it to the page's
  content; the footer says where the source code is.
- `apps/web`: the home page is the product's page: what it does, beside an example of a report
  that tells its story once (the error, the explanation, the approved repair, the verdict); how
  an invoice goes through the validator, the model and a person; the rules it is checked
  against; the HTTP API and the MCP server; and the synthetic invoices to try it on.
- `apps/web`: a verdict, a rule's severity, a repair's state and a patch's outcome are each
  their state's colour on a tint of it, and a diff's lines too; the light theme's error, warning
  and success colours are a step deeper, so that their words stay at 4.5:1 on the tint.
- `apps/web`: a report and a repair open with a summary of what they are, under the way back,
  and the validator's layers are a checklist, beside the rules on a wide screen; shadows take
  the navy's hue.
- `apps/web`: signing in and registering stand beside the brand's navy on a wide screen; the
  upload's file field is drawn as the page's, the list of invoices is framed, an empty list
  shows where to begin, and a page that does not exist shows the mark off its course.
- `apps/web`: the language links keep the query of the page's address, so that a page that
  reads it is the same page in the other language.

### Fixed

- `apps/api`: `GET /oauth/authorize` sends a resource that is no URI back to the client as
  `invalid_target`, where it answered 500, and refuses an unknown scope without repeating
  what the client asked for: an OAuth error's description may hold only some characters.

### Security

- `apps/web`: no other site may show a page of the application in a frame
  (`frame-ancestors 'none'`, `X-Frame-Options: DENY`), where it could be laid under one of its
  own that has a person press a button unawares (clickjacking), as the page where a person lets
  an MCP client act for them requires (RFC 9700 §4.16).
- `apps/web`: signing in and registering are sent by the page's script only: until it has
  taken over, the button waits, and a form sent anyway is posted. The pages are built ahead of
  time, so a form could be sent before the script had loaded, and the browser sent it as a
  GET, with the password in the address, the history and the host's logs.

## [0.3.0] - 2026-11-07

The repair loop and the web application, live (milestone M3): patches `{xpath, op, value,
reason}` applied to a copy of a stored invoice in the validator's child process, with a guard
that leaves amounts, VAT, tax and company identifiers, dates and the document's number to a
person; repairs proposed by a member, an API key or the language model, which the validator
judges, and approved or rejected by a person only, in an audit log without invoice content; the
web application in Serbian (Latin) and English, to register, upload an invoice and read its
report, ask for the rules' explanations with their citations, ask the model for a repair and
decide it on a diff of the invoice; the golden path walked in a browser on every change; the API
as an image; and the public demo on free plans, whose pages wait for its sleeping API and ask
for synthetic invoices only.

### Added

- `einvoice_core`: the patch engine (ADR-0023). A patch `{xpath, op, value, reason}` names its
  place with the canonical path a violation reports, read by a grammar and walked step by step,
  and replaces a value, adds a basic component (with the aggregates on its way) where the UBL
  2.1 schema orders it, or removes an element or an attribute, leaving no element empty. A
  patch that touches an amount, VAT, a tax or company identifier, a date or the document's
  number is not applied: it needs a person's decision. `repair()` applies a list of patches,
  validates the invoice again under the same profile and shows a diff of what changed.
- `einvoice patch INVOICE PATCHES [--output PATH]`: the outcome of each patch, the diff and
  the verdict; exit 0 only when every patch applied and the invoice is valid, and never a write
  over the invoice itself. The file of patches may be UTF-8 or UTF-16, as Windows PowerShell 5.1
  writes it.
- `apps/api`: repairs of stored invoices (ADR-0024). `POST /invoices/{id}/repairs` applies a
  list of patches to a copy of the invoice in the validator's child process, within the limits
  of a validation, and keeps the repair: each patch's outcome, the difference and the report on
  the patched invoice; the invoice does not change until a person decides. `GET
  /invoices/{id}/repairs` lists them, the latest first, and `GET .../repairs/{repair_id}` shows
  one. Each proposal is committed with an event in a new audit log, which records who, with
  which key, the digests and each patch's place and outcome, and no invoice content
  (migration 0010).
- `apps/api`: a person approves or rejects a repair
  (`POST /invoices/{id}/repairs/{repair_id}/approval` and `.../rejection`); an API key is
  refused. Approval applies the patches again, only to the document they were proposed for and
  only if they leave the document they left then; the invoice becomes it within the storage
  quota, and the other repairs that waited for it are superseded. Both decisions go to the
  audit log.
- `apps/api`: the language model proposes repairs (ADR-0025).
  `POST /invoices/{id}/repairs/suggestion` sends it the stored invoice's fatal violations and
  the invoice's fields around them, by canonical path (`einvoice_core.fields`). Every answer is
  checked before anything is applied: a strict schema, the patch engine's own model and path
  grammar, and no value the model was not given. The validator's process applies the patches
  and tells the model what became of each, for two rounds within `SEF_REPAIR_SECONDS` (20).
  What is left is kept as a repair of the caller's, decided on like any other; the repair
  names its model (migration 0011), and the audit event adds the model and the rounds.
- `apps/api`: the pages of the web application's origins may call the API from a browser
  (CORS, `SEF_WEB_ORIGINS`: none by default, `https://` only in production). They may send a
  token, a JSON body and where an event stream stopped, and read `Location` and `Retry-After`,
  an error's included; no credentials are allowed.
- `apps/web`: the application's shell (ADR-0026). Every page is in Serbian (Latin) and English,
  with the language first in its path (`/sr-Latn/…`, `/en/…`) and rendered once per language at
  build time; a path without a language goes to the one the browser asks for, or to Serbian,
  and no cookie is set. A header leads home and to the page in the other language; a footer
  says that the project is not a certified validator, and whether the API answers, with its
  version. The components are shadcn/ui's (style `new-york`, on Radix), in the repository, and
  dark mode follows the operating system. The pages ask the API through TanStack Query, with a
  client that gives up after 10 s and names the API's reason for an error.
- `apps/web`: registration, sign-in and sign-out (ADR-0027). A member of several organizations
  chooses one when signing in, and an error is said in the visitor's language, with the seconds
  to wait after too many attempts. The access token stays in the tab's memory, and the refresh
  token with whose it is in local storage, so that a reload or another tab stays signed in; the
  tabs take turns to refresh, so that the API's strict rotation never signs a person out. The
  header shows who is signed in, as `GET /auth/me` confirms it. Signing out, here or in another
  tab, forgets the visitor's cached answers.
- `docs/api/openapi.json`: the API's OpenAPI document in the repository, written by
  `make openapi` (`scripts/export_openapi.py`) from settings of its own, so that the environment
  does not change it; a test fails when it is not the API's. The web application's types are
  generated from it with `openapi-typescript`, and a test fails when they are not the
  document's (ADR-0028).
- `apps/web`: upload an invoice, read its report, and list the organization's invoices
  (ADR-0028). The invoices' page sends an invoice or a credit note in UBL 2.1 XML under the
  chosen profile (SEF, EN 16931 or Peppol) and opens its report; an error is said in the
  visitor's language, with the seconds to wait when the API names them. The report shows what
  the validator read (the seller, the buyer, the day of issue, the amount payable), the
  verdict, every rule the invoice fails, the fatal ones first, with each place it fails it, and
  what each layer of the validator did. The list shows the newest invoices first, twenty at a
  time. An amount keeps every digit the invoice states, and an invoice's day is the same day in
  every time zone.
- `POST /invoices/{invoice_id}/explanations`: the explanations of a stored invoice's latest
  report, as `POST /invoices/explain` writes them for a document in the body, in Serbian or
  English. The invoice is not validated again; the request counts as one to the language model,
  per caller and per organization, and as no validation (ADR-0029).
- `apps/web`: the rules' explanations on an invoice's report, when the visitor asks for them,
  in the page's language (ADR-0029). Each rule's card says what the rule requires, why the
  invoice fails it and what to change, with the passages it cites, dated and linked to their
  official sources. The page says first what the language model is sent, names the rules left
  for a later request, and says why there are none: too many requests, no model on the server,
  no answer in time.
- `apps/web`: the repairs of a stored invoice (ADR-0030). The report's page lists them, the
  latest first: who proposed each, where it stands, whether the copy it leaves is valid, and
  how many of its patches applied, wait for a person or could not apply. Each repair has its own
  page, with who decided on it, what became of each patch and why, the difference it makes to
  the invoice, as the API keeps it, and the validator's report on the copy. A removed or added
  line is marked for screen readers, not only by colour, and the diff shows no line numbers:
  they count the lines of the invoice indented anew, not of the file sent.
- `apps/web`: a repair asked of the language model from an invalid invoice's report
  (ADR-0031). The page says first what the model is sent, asks nothing until the visitor asks,
  and opens the repair it writes, its reasons in the page's language. A refusal says why: the
  conflict's reason, no patch a repair keeps, an unusable answer, the seconds to wait, or no
  model on the server; asking again is offered only where it could help.
- `apps/web`: a person approves or rejects a repair on its page (ADR-0032). The page says what
  an approval does, the invoice becomes the copy and the other waiting repairs are superseded,
  and asks a second time; a rejection takes one press, and a repair that changes nothing offers
  only its rejection. Afterwards the invoice, its report, its repairs and the list's verdicts are
  read again when shown. When the outcome is unknown (no answer in time, no API, a server's
  failure), the page reads the repair again and shows where it stands.
- The golden path, tested end to end (ADR-0033): one Playwright test, in Chromium, registers,
  uploads an invalid invoice, reads its report, also after a reload, finds it in the list, has
  the language model suggest a repair, reads its diff, approves it, and finds the invoice valid
  on its report and in the list, with no error in the console. It runs against the web application's production
  build and the API, which `scripts/serve_e2e_api.py` starts on a database made anew for each
  run, with a scripted model, so that no key is needed. `make e2e` runs it, and a CI job on
  every pull request, which keeps the report and the trace of a failure.
- `apps/api/Dockerfile`: the API as an image (ADR-0034). It holds the lock file's dependencies of
  the API alone, the rule sets checked against their pins with every profile's stylesheets
  compiled, and the corpus; a container applies the migrations, then serves on `PORT` as a user
  that owns no file, trusting a proxy's `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS`. A CI
  job builds it, starts it on an empty database and validates an invoice through it.
- The public demo's hosting (ADR-0035), with its runbook in `docs/DEPLOY.md`: the API on Render's
  free plan from `render.yaml`, deployed from `main` once CI has passed and only when its image
  changes; its database on Neon; the web application on Vercel's Hobby plan, with Node.js 22 and a
  build only when it changes (`apps/web/vercel.json`). No secret is in the repository: Render
  generates the signing key and asks for the others when the Blueprint is applied.
- `apps/web`: the pages wait for a sleeping API (ADR-0036). When the API has not answered for
  ten minutes, a request first waits until it answers `/health`, for up to two minutes, as the
  demo's free instance wakes, and is then sent once. After three seconds of waiting, the footer
  says that the API is waking up, and a notice above the page says why, and that what the
  visitor sends will go as soon as the API answers.
- The public demo asks for synthetic invoices only (ADR-0037). `SEF_PUBLIC_DEMO`, set in
  `render.yaml`, makes `GET /health` report `public_demo`; the upload then says that what is
  uploaded is stored there, and that explanations and repairs send the rules' messages and the
  invoice's fields to the language model's provider, and links to the repository's synthetic
  invoices.

### Changed

- `apps/api`: the limit on explanations counts every request to the language model, for
  explanations or a repair, and a 429 says "too many requests to the language model"; its
  settings keep their names.
- `pnpm-workspace.yaml` rules on every install script of a dependency in `allowBuilds`, which
  pnpm 11 and later read instead of `ignoredBuiltDependencies`; none runs.
- `NEXT_PUBLIC_API_URL` moves from the root `.env.example` to `apps/web/.env.example`, because
  Next.js reads a web application's variables from its own directory.
- `apps/api`: every 409 of the repairs names its `reason` beside the `detail`
  (`RepairConflict`): `nothing-to-repair`, `too-many-waiting`, `invoice-changed`, `decided`,
  `changes-nothing`, `outcome-changed`, so that a client tells them apart without reading the
  English.
- `docs/DEPLOY.md`: what the first deploy needed, in the steps where it was met: Vercel's and
  Render's GitHub apps given access to the repository, Neon's pooled host told apart, and the
  database's URL read for the corpus without being shown or kept in the shell's history. The
  README links the live demo, <https://sef-kopilot.vercel.app>.

### Security

- `apps/api`: every request body other than an invoice is read at most to `SEF_MAX_BODY_BYTES`
  (1 MiB) before the application parses it, and answered 413 beyond, whether or not its length
  was declared. FastAPI read a JSON body whole, however long, before validating it.

### Fixed

- `apps/api`: an unexpected failure answers a 500 that a page can read. Starlette answered it
  outside every middleware, so it had no CORS headers, and a page of the web application saw
  only a network error and said that the API does not answer; it is now answered inside them,
  with a JSON body in UTF-8, and the exception still reaches the server's log.
- `apps/api`: the API's image builds from a clone of the repository, which holds no rule sets.
  The build then fetches them, three of them with git, which its stage lacked, so the first
  build on Render failed; CI had given its build the rule sets from its cache, and now gives it
  what a clone holds.
- `apps/api` tests: a test application's settings are the values its test gives, and no longer
  what the developer's environment and `.env` hold besides, which could give it a language
  model's provider and key. `Settings.from_values()` builds settings from given values alone,
  for the tests, the OpenAPI exporter and the end-to-end test's launcher.
- `apps/api`: the repairer keeps no patch that writes at its place the value already there. It
  applied and changed nothing, so a suggestion of such patches alone was kept as a repair that
  could only be rejected; it is now no repair (422), and in a second round the model is told
  that the patch changed nothing.
- `apps/api`: a repair is kept only if its proposer still holds the permission once the
  patches are applied, as an invoice is stored; a member removed meanwhile, or a key revoked,
  left a repair behind.
- `apps/api`: an explanation names no date, amount, rate or identifier that neither the
  violation nor the passages contain (ADR-0022). The first live answer to `SRB-009` gave a
  corrected PIB "for example", which the prompt forbade; such an answer now goes back to the
  model with the values it named, and the model's non-breaking hyphens (`BT‑31`) become plain
  ones.
- `apps/api`: every JSON answer says `charset=utf-8`. Windows PowerShell 5.1 read a JSON body
  without one as ISO-8859-1, so `č` came out as `Ä` and the quotation marks of an explanation
  as control codes that hid the letters between them.
- `apps/api` tests: the worker test of an attempt cut short no longer fails when its first
  worker runs into a new minute, a few CI runs in a hundred. That worker waited for the sweep
  at second 0 and the job the test leaves unfinished ran too early; the tests' workers now
  sweep at startup only, and a test pins the production schedule.
- `apps/web`: the signed-in header fits a phone. The product's name no longer breaks over
  two lines, nor does the account's button stand past the screen's edge (by up to 51 px at
  360 px), which made every page scroll sideways; below 640 px the languages are in the
  footer. Their place is kept until their links come, so that nothing beside them moves.

## [0.2.0] - 2026-11-06

The HTTP API around the validator, and the explanations (milestone M2): FastAPI on PostgreSQL
with accounts, organizations and roles, short-lived access tokens and rotating refresh tokens,
invitations, API keys for machine clients and rate limits; invoices validated in a child process
within limits on bytes, time and elements, or stored with their reports within a quota and
listed by verdict; jobs that validate stored invoices again, in the API's process or on arq
workers, followed over server-sent events; the corpus of the official documents the rules come
from, as dated passages pinned to their sources and checked against them every week; and
explanations of the rules a report names, in Serbian or English, whose citations can only be
passages of that corpus.

### Added

- `.github/workflows/corpus-sources.yml`: every Monday, and by hand, the corpus's official
  sources are downloaded afresh and compared with their pinned digests and with the corpus; a
  failed run reports a source a publisher changed.
- `apps/api`: `GET /invoices?valid=false` lists only the stored invoices whose latest report is
  invalid, and `valid=true` only the valid ones, a page at a time as before: after a
  revalidation, the invoices it found invalid. The invalid ones are read through an index of
  their own (migration 0009, built without holding writes back).
- `apps/api`: explanations (ADR-0021). `POST /invoices/explain?language=sr|en` validates an
  invoice as `/invoices/validate` does, keeping nothing, and explains each rule its report
  names, fatal ones first and five at most (`SEF_MAX_EXPLANATIONS`): what the rule asks, why the
  invoice fails it and what to change, citing the passages of the corpus that apply on the
  invoice's issue date. Retrieval finds them by the rule's references, the terms its message
  names, its place, the tax codes it names, then by words and, with embeddings, meaning, fused
  by rank; an embedder is sent what the rules say, never what the invoice holds. The model
  answers a JSON schema whose citations can only be the ids of those passages; an answer is
  checked again and sent back with what was wrong, three answers at most, and a rule without an
  explanation says why. `LLM_PROVIDER=groq` with `GROQ_API_KEY` uses Groq's
  `openai/gpt-oss-120b` (`SEF_LLM_MODEL` names another), behind the `LLMClient` adapter; the
  default, `none`, sends nothing and answers 503. Requests for explanations count as validations
  and against `SEF_EXPLANATIONS_PER_MINUTE` (10) and `SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE`
  (30), and have `SEF_EXPLANATION_SECONDS` (30).
- `corpus/`: the official documents that explanations cite (ADR-0020): the Law and the
  Rulebook on Electronic Invoicing, the Rulebook on the Tax Identification Number, the SRB-CIUS
  specification and the Ministry's list of tax categories, seven editions in all, as Markdown
  written by `scripts/build_corpus.py` from sources that `corpus/manifest.toml` pins by URL and
  SHA-256 (`make corpus` downloads and rebuilds, `make corpus-check` compares). Each passage (an
  article, a section, a table row, a tax category) applies from its edition's day, or the later
  day the amending act defers it to, until a later edition changes it; its id names that first
  day, `e-invoicing-law/article-4b/2027-07-01`.
- `apps/api`: the corpus in PostgreSQL (migration 0008: the `vector` and `pg_trgm` extensions,
  `corpus_documents` and `corpus_passages`, with an HNSW index on the embeddings and a trigram
  index on the text folded to Latin letters, so that a search in either script finds the
  other). `python -m sef_api.rag.ingest` (`make ingest`) makes the tables hold exactly the
  corpus, any number of times, and embeds what is not embedded yet when
  `EMBEDDINGS_PROVIDER=jina` (with `JINA_API_KEY`; the default, `none`, embeds nothing).
  `sef_api.rag.citations` gives the passages each SRB-CIUS rule is authored from on a day; a
  test resolves every reference of every rule.
- `apps/api`: jobs (ADR-0019). A job's row in PostgreSQL is the truth: taking a job on counts
  an attempt, and every later write requires the attempt to be the latest, so that a job
  delivered twice does its work once and one cut short continues from its progress. The first
  job validates stored invoices again: `POST /invoices/revalidations` (202 with `Location`;
  409 while the caller has one under way) takes the invoices the caller may see, one at a
  time, makes each new report the invoice's latest and counts what became of it (`valid`,
  `invalid`, `kept` when the new report would not fit the quota, `failed`, `deleted`).
  `GET /jobs/{id}` reads a job, and `GET /jobs/{id}/events` follows it as server-sent events,
  resumable with `Last-Event-ID`. Jobs run in the API's process (`SEF_JOBS=inline`, the
  default), or in arq workers on a Redis queue (`SEF_JOBS=arq` with `REDIS_URL`;
  `make worker`) that sweep unfinished jobs back onto it once a minute.
- `apps/api`: rate limits (ADR-0018). Per address: signing in 30 a minute, registering 10 an
  hour, refreshing and signing out 60 a minute, accepting an invitation 10 a minute. Per
  e-mail address: 10 wrong passwords in 15 minutes, at sign-in and when an invitation is
  accepted, counted before the next password is checked and for addresses without an account
  alike. Per caller (a member, or one API key) and per organization: the validations a minute
  that `SEF_VALIDATIONS_PER_MINUTE` (60) and `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300)
  allow, storing included, counted before the body is read. Beyond a limit, 429 with
  `Retry-After`. The counts live in the API's process.
- `apps/api`: API keys for machine clients such as ERPs. `POST /api-keys` issues a key that
  acts for the caller with some of their permissions (`invoices:validate`, `invoices:submit`,
  `invoices:manage`, each one the caller's role grants) and shows it once; a client sends it as
  `Authorization: Bearer sefk_…`. On every request a key allows only what it holds and its
  member's role grants at that moment; it administers no members and issues no keys.
  `GET /api-keys` lists the keys that work and `DELETE /api-keys/{id}` revokes one: a member
  manages their own (`api_keys:issue`), an owner every key of the organization
  (`api_keys:manage`). A key is stored as a SHA-256 digest, is deleted with its member's
  membership, and works until it is revoked or reaches its optional expiry; a member has at
  most 20 that work (ADR-0017).
- `.gitleaks.toml`: the secret scan recognizes the API's keys, in the pre-commit hook and in
  the history.
- `apps/api`: stored invoices. `POST /invoices` validates an invoice as `/invoices/validate`
  does and keeps it for the organization, byte for byte, with the validator's report and what
  it read (number, issue date, parties, amount due); `GET /invoices` lists them newest first,
  a page at a time with an opaque cursor; `GET /invoices/{id}` reads one with its report;
  `GET /invoices/{id}/content` downloads the document as an attachment; `DELETE /invoices/{id}`
  deletes it. Owners and accountants see every invoice of the organization (`invoices:manage`),
  a client the ones they submitted (`invoices:submit`). An organization stores at most
  `SEF_MAX_STORED_BYTES` (100 MiB) of documents and reports together; beyond it, 507
  (ADR-0016).
- `apps/api`: invoice validation. `POST /invoices/validate` takes a UBL 2.1 invoice or credit
  note as the request body (`application/xml`), checks it against the chosen profile (`srb` by
  default, `en16931` or `peppol`) and answers with the validator's own report, marked
  `Cache-Control: no-store`; nothing is stored and no invoice content is logged. The body is
  refused with 413 beyond `SEF_MAX_INVOICE_BYTES` (5 MiB), counted while it is read, or beyond
  `SEF_MAX_INVOICE_ELEMENTS` (20 000); with 408 when it has not arrived within
  `SEF_UPLOAD_SECONDS`; with 415 when it is not XML. Every role holds the new permission
  `invoices:validate` (ADR-0015).
- `apps/api`: the validator runs in a child process that the application starts with it,
  warmed up with every rule set, one invoice at a time. A validation longer than
  `SEF_VALIDATION_SECONDS` (15) is stopped (422) and the child replaced; one that dies, or
  answers another message than the one sent, is replaced too. A validation whose request is
  cancelled still ends before the next one begins. At most `SEF_MAX_VALIDATIONS_IN_FLIGHT` (8)
  validations wait or run; the next answers 503 with `Retry-After` (ADR-0015).
- `apps/api`: permissions, members and invitations. Endpoints ask for a permission that the
  member's role grants (the owner holds every permission; an accountant may see the members;
  only an owner manages them), checked against the current membership on every request, so
  that removal, deactivation and role changes act at once; `GET /auth/me` reports the role held
  now. `GET /members`, `PATCH /members/{user_id}` and `DELETE /members/{user_id}`, with at least
  one active owner kept. Invitations with one-time codes: `POST`, `GET` and
  `DELETE /invitations`, redeemed with `POST /auth/accept-invitation`; an invitation stops
  working when its issuer may no longer invite. Changes to an organization's members and its
  sessions are ordered by an advisory lock per organization, and the tokens of one session are
  locked in a fixed order. A route audit, a refused-role test and a cross-tenant test for every
  guarded endpoint run in CI (ADR-0013).
- `apps/api`: accounts and tokens. `POST /auth/register` creates an account, its organization
  and makes the person the owner; `POST /auth/login` signs in to one organization (a member of
  several chooses one). Passwords are hashed with argon2id; access tokens are 15-minute JWTs
  (HS256, `at+jwt`); refresh tokens live 30 days, are stored as digests, are spent on use, and a
  replayed one ends the session. `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`
  (ADR-0012).
- `apps/api`: PostgreSQL persistence. Settings from the environment (`pydantic-settings`;
  `DATABASE_URL` required in production and never echoed), one async SQLAlchemy engine per
  application with a session per request, and Alembic migrations (`make migrate`) starting with
  organizations, users and memberships with the roles owner, accountant and client. Database
  tests run on the PostgreSQL server named by `SEF_TEST_DATABASE_URL`, in a database of their
  own; CI provides one and checks that every migration can be undone (ADR-0011).

### Changed

- `.env.example` sets `EMBEDDINGS_PROVIDER=none`: a copy of it starts the API without a key.
- A stored invoice's report is its latest, and `validated_at` tells when the validator made it
  (migration 0007 fills it from when the invoice was stored); ADR-0016 is amended.
- The OpenAPI security scheme is named `access token or API key`: the same bearer header takes
  either.
- `GET /ready` checks the database and the validator, and answers 503 while either cannot
  serve.
- The API starts from its factory: `uvicorn sef_api.main:create_app --factory` (`make api`); the
  module-level `app` is gone, so importing the module has no side effects.

### Fixed

- `corpus/`: `make corpus` downloads the Legal Information System's texts. The manifest pinned
  them as the system's web application receives them, and the system starts a text downloaded
  from anywhere else with a line that names it ("Преузето са …"), so every download failed its
  digest. The five digests are now of the text a download receives; the converter leaves the
  line out, and the corpus files are unchanged.
- `apps/api`: every answer that carries a credential sends `Cache-Control: no-store`, as
  RFC 6749 requires: the tokens of registration, sign-in, accepting an invitation and
  refreshing, and an invitation's code. Only the invoice endpoints sent it before.
- `einvoice_core`: addressing elements takes time linear in the size of the document. Canonical
  XPaths and SVRL locations read each element's children once (`sibling_index()`) instead of
  all of an element's siblings for every element: an invoice of 8000 lines validates in 5 s
  instead of 39 s (ADR-0014).
- `einvoice_core`: a number of more than 28 digits is a `MODEL` violation instead of an
  exception, and the SRB-CIUS and arithmetic checks compute exactly instead of rounding beyond
  28 digits. Amounts in the Serbian extension must have the form of `xs:decimal`, with the
  digits 0 to 9 only (ADR-0014).
- `einvoice_core`: a comment or a processing instruction inside a value no longer splits it.
  The parser drops both, so every layer reads `14400<!-- -->1` as 144001, as the schema does;
  the arithmetic layer read 14400 and passed an invoice whose amount due did not add up
  (ADR-0014).
- `einvoice_core`: the set-aside list of a report is cut at `max_violations` like the
  violations, and the rest counted in `set_aside_omitted`; a document of 144 KB made a report
  of 7.6 MB (ADR-0014).
- `einvoice_core`: Saxon's warnings, some of which quote the document, no longer reach the
  process's standard error; where the null device cannot be opened, a log warning says that
  they will (ADR-0014).

## [0.1.0] - 2026-11-04

The validator core (milestone M1) on the bootstrapped monorepo (M0): UBL 2.1 invoices and
credit notes parsed into a typed model and checked against the UBL 2.1 schemas, CEN's
EN 16931 and OpenPeppol's BIS Billing 3.0 Schematron, the SRB-CIUS rule set v1 (29 rules) and
the EN 16931 calculation rules in Python, combined in one validation pipeline with the
profiles `srb`, `en16931` and `peppol`; the `einvoice` command line; and a fixture corpus
whose verdicts the tests pin.

### Added

- Fixture corpus: the Ministry of Finance's 17 SEF example documents committed byte for byte
  with their source URL and SHA-256; 43 mutation fixtures generated by
  `scripts/make_fixtures.py` (`make fixtures`), each a synthetic invoice with one deliberate
  mistake and the rules the SRB profile reports for it; two synthetic final invoices with the
  Serbian extension; and the pipeline's recorded verdicts on all 93 corpus documents, which the
  tests compare (ADR-0010).
- `einvoice` command line: `einvoice validate PATH ... [--profile] [--format text|json]` with
  exit status 0 (valid), 1 (invalid) and 2 (error), and `einvoice rules` to list what a profile
  checks and sets aside (ADR-0009). A path may be a directory or a pattern such as `*.xml`,
  expanded by the command where the shell does not (cmd, PowerShell).
- `einvoice_core`: validation pipeline. `validate(source, profile)` reads the document, checks
  it against the UBL 2.1 schemas and, when it is schema-valid, runs the profile's Schematron
  rule sets, the SRB-CIUS rules and the calculation rules, and returns one report with the
  verdict, the violations in layer order, the layers that ran, and the published rules the
  profile sets aside, each with its reason. Profiles `srb`, `en16931` and `peppol`; the
  violation model gains the layer `xml` for unreadable documents (ADR-0008).
- `einvoice_core`: arithmetic layer. The EN 16931 calculation rules BR-CO-10 to BR-CO-17 are
  computed in Python from the typed model, with CEN's rounding and tolerance, and report the
  expected and the found amount; a differential test checks them against CEN's XSLT on
  generated invoices (ADR-0007).
- `einvoice_core`: SRB-CIUS extension rules SRB-025 to SRB-029: the reduced total with VAT of
  a final invoice (BT-E13 = BT-112 - BT-113), advances used that are also preceding invoices,
  the RSD VAT breakdowns of foreign-currency invoices (BG-E5, BG-E6, BG-E7), and the extended
  specification identifier when the extension is used (a warning). The Serbian extension
  namespace has the canonical prefix `sbt` in every layer.
- `einvoice_core`: SRB-CIUS VAT rules SRB-020 to SRB-024: VAT category codes (S, Z, E, AE, R,
  O, OE, SS, N) on breakdowns, allowances, charges and lines; S and AE at 20 or 10 percent;
  VAT exemption reason codes checked against the Ministry's list of 1 September 2024 (a code of
  another category is fatal, an unlisted code a warning) and required for exempt and non-taxed
  categories. The list is transcribed into `einvoice_core.srb.vat` (124 codes).
- `einvoice_core`: SRB-CIUS rules SRB-010 to SRB-019: the public-procurement buyer reference,
  the preceding invoice's issue date, legal registration numbers, the seller's VAT
  registration status (BT-32, `RS-VAT-STATUS`), cities and post codes, the delivery date when
  VAT is due on supply or on collection, and the notation of payment models in BT-83. A
  missing VAT status and a missing buyer post code are warnings, because the official
  examples omit them (ADR-0006).
- `einvoice_core`: SRB-CIUS rule layer, authored from the specification (version of
  06.06.2025): one rule per module with an `SRB-NNN` identifier, the business terms it concerns
  and the passages it cites; violations in the `srb-cius` layer. The first nine rules cover the
  invoice type code, the RSD VAT currency, the unused VAT point date, the advance-invoice due
  date, the specification identifier, JBKJS identifiers, VAT identifiers, electronic addresses
  and PIB serial and check digits (ADR-0006).
- `einvoice_core`: Schematron layer. The EN 16931 rules (official CEN XSLT) and the Peppol BIS
  Billing 3.0 rules run with Saxon-HE (`saxonche`); Schematron sources are compiled with the
  pinned ISO Schematron pipeline and cached; SVRL results become violations with canonical
  XPaths and source lines. Verified against every unit test CEN and OpenPeppol publish
  (ADR-0005).
- Rule-set fetcher: the ISO Schematron reference implementation (`iso-schematron`).
- `einvoice_core`: violation model shared by all validation layers, and UBL 2.1 XML Schema
  validation against the official OASIS schemas, with confined schema loading, canonical
  XPath locations and readable messages (ADR-0004).
- Rule-set fetcher: pinned ZIP archive sources (HTTPS URL + SHA-256) next to git tags; the
  OASIS UBL 2.1 package is now fetched into `third_party/ubl-2.1`.
- `einvoice_core`: typed invoice document model following the EN 16931 semantic model
  (`Decimal` amounts, BT/BG-named fields, canonical XPath per business group), hardened XML
  loading (no DTD, entities or network; size limit) and a UBL 2.1 Invoice / CreditNote parser
  verified against all official CEN and OpenPeppol example documents (ADR-0003).
- Project charter (`docs/BRIEF.md`), README with vision and architecture, contributor guide,
  security policy, backlog and session log.
- uv workspace with `packages/einvoice_core` (src layout, strict typing, 90 % coverage gate)
  and `apps/api` (FastAPI application factory with `GET /health` and `GET /ready`).
- `apps/web`: Next.js (App Router, TypeScript strict, Tailwind CSS v4) scaffold with Vitest
  and Testing Library; pnpm workspace with a one-day minimum release age and shared Prettier.
- `pre-commit` hooks: hygiene, ruff, uv.lock, mypy --strict, ESLint, Prettier, gitleaks and a
  Conventional Commits check with the project's fixed types and scopes.
- GitHub Actions CI: pre-commit on all files, test suites with coverage gates, web build,
  rule-set fetch, full-history gitleaks scan, dependency audits; Dependabot for uv, npm and
  actions.
- `infra/docker-compose.yml` with PostgreSQL 16 + pgvector and Redis; `.env.example`; Makefile.
- `scripts/fetch_rulesets.py` with `third_party/manifest.json` pinning EN 16931
  `validation-1.3.17` and Peppol BIS Billing 3.0 `3.0.21` by tag and commit.
- ADR-0001 "Monorepo and tooling", ADR-0002 "Deterministic validator is the source of truth",
  `docs/ARCHITECTURE.md`, first learning and interview notes, pull request and issue templates.

### Changed

- Dependabot proposes only minor and patch updates for Python and Node packages; major
  versions are planned migrations (CONTRIBUTING.md, "Dependency updates").

### Fixed

- The parser reads BT-11 (project reference) on credit notes, where UBL 2.1 carries it as an
  `AdditionalDocumentReference` with type code 50.
- The synthetic credit note satisfies EN 16931: one payment means code (UBL-SR-47) and no UBL
  extensions (UBL-CR-001).
- The core test suite passes on Windows: opening XML text as a file name fails there with
  `EINVAL` rather than `ENOENT`, and examples with an upper-case `.XML` extension are listed
  once instead of twice.
- Rule-set fetcher: archive member names are judged by POSIX and Windows rules on every host;
  backslashes, drive letters, NTFS streams and NUL bytes are refused, also in directory entries.

[Unreleased]: https://github.com/spasojewagner/sef-kopilot/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/spasojewagner/sef-kopilot/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/spasojewagner/sef-kopilot/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/spasojewagner/sef-kopilot/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/spasojewagner/sef-kopilot/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/spasojewagner/sef-kopilot/releases/tag/v0.1.0
