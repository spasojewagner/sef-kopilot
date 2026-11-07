# Security policy

SEF Kopilot handles documents that are commercially sensitive (invoices) and talks to a
government platform (the SEF **demo** environment). Security is therefore a design input, not a
release checklist. This document describes how to report a problem, what the project promises,
and the OWASP ASVS checklist the code is held to.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem.

- Preferred: use GitHub's private vulnerability reporting on this repository
  ("Security" tab → "Report a vulnerability").
- Alternative: email the maintainer at `markospasojevic758@gmail.com` with "SEF Kopilot security"
  in the subject.

You will get an acknowledgement within 72 hours and a status update at least every 14 days
until the issue is resolved. Credit is given in the changelog unless you prefer otherwise.

## Supported versions

The project is pre-alpha. Only the `main` branch and the latest tagged release receive fixes.

## Scope and threat model (summary)

- **Assets:** invoice content (XML, later PDF), tenant API keys for SEF, user credentials,
  LLM provider keys supplied by the operator or the tenant (bring your own key).
- **Trust boundaries:** the deterministic validator is the only authority on validity; the
  language model is untrusted input, not a decision maker (see `docs/BRIEF.md`, §2).
- **Out of scope for this project:** the SEF platform itself, third-party LLM providers, and
  the production SEF environment, which the project does not talk to by default.

## Security principles

1. Invoice content never reaches logs, traces or error reports. A **no-store mode** processes an
   invoice entirely in memory.
2. Per-tenant secrets (SEF API keys) are encrypted at rest (Fernet, key from the environment),
   never logged, never returned by the API.
3. XML parsing is hardened: no external entities, no DTD processing, size and type limits on
   uploads, no network access during parsing.
4. Model output is data, not instructions: structured, schema-validated, applied by code, and
   re-validated by layer 1. An explanation may cite only the passages retrieval found, and is
   checked before it is used. A patch is applied by code at a path read by a grammar, never
   evaluated; one that touches an amount, VAT, a tax or company identifier, a date or the
   document's number is refused as needing a person's decision. A patch the model writes is
   checked before it is applied, names no value the model was not given, and waits for a
   person's approval like any other.
5. Multi-tenancy is enforced in the service layer on every query (`organization_id`) and
   covered by tests.
6. Dependencies are audited in CI (`pip-audit`, `pnpm audit`); secrets are scanned with
   `gitleaks` in pre-commit and CI.
7. Everything that talks to the outside world is explicit and configurable; a self-hosted
   deployment makes no external calls except the LLM provider the operator chooses. Embedding
   the corpus is off by default (`EMBEDDINGS_PROVIDER=none`), and what an embedder is sent is
   public text: the official documents and what the rules of a report say, never an
   organization's data. Explaining and the model's repairs are off by default too
   (`LLM_PROVIDER=none`). To explain, the model is sent the first violation of each rule a
   report names, whose message may quote a value of the invoice, and public passages. To
   propose a repair, it is sent the first ten fatal violations and the invoice's fields
   around them, by canonical path and value: the aggregates the violations are in, never the
   whole invoice, never the extensions (ADR-0025).

## OWASP ASVS 5.0 — Level 1 checklist

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done and tested. The checklist is
updated in the pull request that implements each item; chapters that do not apply to this
system are marked as such.

### V1 Encoding and sanitization

- [x] Output encoding is applied by the UI layer: the web application renders an invoice's
      values, and the rules' messages that quote them, as text, which React escapes; a lint
      rule forbids setting HTML from data (`react/no-danger`), and a test renders a document
      whose values are markup (ADR-0028). API responses are JSON, but for a stored document,
      served back as an attachment with `nosniff` (V5).
- [~] XPath and XSLT inputs that originate from users (rule ids, paths) are validated against an
      allow-list, never interpolated into expressions: a patch's path is read by a grammar of
      child steps and walked one step at a time, never evaluated as XPath (ADR-0023; tested
      with functions, axes, wildcards, predicates and unions).
- [x] XML parsers reject external entities and DTDs: a document that declares a DOCTYPE is
      refused, and while it is parsed no entity is expanded, no DTD read and no socket opened
      (tested on the parser itself).
- [x] A value is read whole by every layer: comments and processing instructions, which could
      split it and hide a wrong amount from the arithmetic, are dropped while parsing (tested
      on every document of the fixture corpus).

### V2 Validation and business logic

- [x] All request bodies are validated with Pydantic models (strict types, bounded sizes): an
      invoice is read in chunks within `SEF_MAX_INVOICE_BYTES`, and every other body is read
      by a middleware up to `SEF_MAX_BODY_BYTES` (1 MiB) before FastAPI parses it (413
      beyond, whether or not its length was declared).
- [x] Business guardrails (forbidden patch fields, arithmetic rules in code, citation
      resolution) are enforced server-side and covered by tests: the arithmetic rules are
      computed in Python, and an explanation cites only passages retrieval read from the
      database, enforced by its answer's schema and checked again (tests send answers that
      cite other ids). The patch guard checks what a patch touches (its place, what it is
      inside of, what it would remove) before anything changes, in the core every caller goes
      through (tested on the mutations whose fixes would change a PIB, an amount or a date).
- [x] Rate limiting on upload, validation and explanation endpoints: validations are admitted
      a few at a time (503 with `Retry-After` beyond), and counted per caller and per
      organization (429 with `Retry-After`) before the body is read; a request for
      explanations is counted as a validation and against limits of its own, per caller and
      per organization, in the same step. The explanations of a stored invoice, which is not
      validated again, count against the latter alone (ADR-0029).
- [x] The work one request for explanations causes is bounded: five rules at most, passages
      cut to 6 000 characters, three answers a rule, and 30 seconds in all.
- [x] The work one upload causes is bounded: a budget of elements counted before any
      validation (413), a time limit enforced by killing the validator's child process
      (422), and a deadline for the body (408).
- [x] Work in the background is bounded: a member has one job of each kind under way (a
      unique index; 409 beyond), a revalidation validates one invoice at a time within the
      same limits and the storage quota, and a worker cuts an attempt short after an hour.
- [x] The work one repair causes is bounded: 100 patches, a path of 1 000 characters whose
      positions have six digits at most, a value of 1 000 characters; a path costs as many
      steps as it has, and `einvoice patch` reads 1 MiB of patches at most.

### V3 Web frontend security

- [ ] Content Security Policy, `X-Content-Type-Options`, `Referrer-Policy` and
      `Permissions-Policy` headers set by the web app and the API.
- [ ] Cookies (if used) are `Secure`, `HttpOnly`, `SameSite`. The web application sets none:
      the language is in the path (`localeCookie: false`), and the tokens are kept as ADR-0027
      says. A Content-Security-Policy, which bounds what a script injected into the page could
      do with the refresh token in local storage, comes with the hosting (`chore/infra-deploy`).

### V4 API and web service

- [x] CORS restricted to the configured web origins (`SEF_WEB_ORIGINS`, none by default and
      `https://` only in production): their pages may send the token, the body's type and where
      an event stream stopped, and read `Location` and `Retry-After`, an error's included; no
      credentials, since a token travels in a header, never in a cookie. Tested with the
      application's own origin, another one, and none configured.
- [x] Every endpoint is public by name or requires a permission; a test over the application's
      routes enforces it, and OpenAPI documents the bearer scheme (an access token or an API
      key).
- [ ] OpenAPI names the permission each endpoint requires.
- [ ] Consistent error schema; no stack traces or internal paths in responses.

### V5 File handling

- [x] XML uploads: a size limit counted while the body is read (413), the media type checked
      (415), and the content judged by the hardened parser, never by the declared type.
- [ ] The same for PDF uploads (M7).
- [x] Uploaded files are stored outside the web root (or not stored at all in no-store mode)
      and referenced by opaque ids: a stored invoice is a database row named by a random UUID,
      and its document is served back only as an attachment with `nosniff`.
- [x] What an organization stores is bounded: documents and their reports together, under a
      lock, so concurrent uploads cannot overshoot (507 beyond the quota; tested with two).

### V6 Authentication

- [x] Passwords hashed with argon2id (OWASP's minimum parameters), 12 to 128 characters, rehashed
      when the parameters change.
- [ ] Breached-password check against a local list (the self-hosted mode makes no external calls).
- [x] Generic authentication error messages; an unknown address takes as long as a wrong password.
- [x] Rate limiting on sign-in, registration, token refresh and accepting invitations, per
      address; wrong passwords counted per e-mail address before the next is checked, whether
      an account has the address or not (429 with `Retry-After`).
- [x] API keys for machine clients: 256 random bits, shown once and stored as a SHA-256
      digest, revoked at once. A removed member's keys are deleted with the membership, and a
      deactivated account's are refused. A rule in `.gitleaks.toml` recognizes a leaked key.

### V7 Session management

- [x] Short-lived JWT access tokens (15 minutes); refresh tokens stored as digests, spent on use,
      and a replayed one revokes its whole session.
- [x] Logout invalidates refresh tokens.
- [x] The tokens of one session are locked in one order, so a sign-out or a replay during a
      refresh also revokes the token it issued.
- [x] In the browser (ADR-0027) the access token stays in the tab's memory and is never stored;
      the refresh token is in local storage, and the tabs refresh one at a time (Web Locks), so
      that rotation never ends a session by mistake. Signing out forgets the session at once,
      then revokes it, and the visitor's cached answers are forgotten with it.

### V8 Authorization

- [x] Permissions per role (`owner`, `accountant`, `client`) in one table, checked against the
      current membership on every guarded request, so that removal and role changes act at once.
- [x] Tenant isolation by `organization_id` on every query; another organization's objects
      answer 404. Every guarded endpoint has a cross-tenant test, and a test fails when one is
      missing.
- [x] An organization keeps an active owner. Changes to its members and its sessions are
      ordered by one advisory lock, granted in arrival order, and the permission for such a
      change is checked again under it.
- [x] An invitation stops working when the owner who issued it may no longer invite.
- [x] Within an organization, a client reads and deletes only the invoices they submitted;
      another member's answers 404, as another organization's does (tested per role).
- [x] An API key allows what it holds and its member's role grants at that moment, both. A key
      holds only permissions for work on invoices, so it administers no one and issues no keys;
      every guarded endpoint has a cross-tenant case with another organization's key.
- [x] An upload that outlasts its permission check is checked again before it is stored: a
      member removed, or an API key revoked, during the validation stores nothing.
- [x] A validation's answer reaches only its own request: the validator's turns end whole
      even when a request is cancelled, and every answer names its message (tested by
      cancelling a validation in flight).
- [x] Jobs are seen within the same scope as invoices: a client reads and follows only the
      jobs they started, and another's answers 404 before any event stream begins. A job
      works within the scope of the member who started it, fixed when it starts.
- [~] An event stream outlives the permission check it began with by at most five minutes,
      then ends; the client reconnects and is checked again.

### V9 Self-contained tokens

- [x] JWTs use an allow-listed algorithm (HS256) and type (`at+jwt`); `iss`, `aud`, `exp`, `iat`,
      `sub`, `org`, `role` and `jti` are required and checked.
- [ ] Signing keys rotate (key ids, the previous key accepted for a grace period).

### V10 OAuth and OIDC

- [ ] MCP authorization implements OAuth 2.1 with PKCE, resource indicators (RFC 8707),
      protected resource metadata (RFC 9728), authorization server metadata (RFC 8414) and
      dynamic client registration (RFC 7591) with scope checks per tool.

### V11 Cryptography

- [ ] Tenant SEF keys encrypted with Fernet (AES-128-CBC + HMAC); key from environment only.
- [ ] No home-grown cryptography; randomness from `secrets`.

### V12 Secure communication

- [ ] TLS everywhere in deployment; outbound calls use `httpx` with certificate verification
      and timeouts.

### V13 Configuration

- [ ] Configuration from environment variables only; `.env.example` lists names, never values.
- [x] `REDIS_URL`, which may carry the queue's password, is a secret setting that never
      appears in a log or a `repr`, and must name `redis://` or `rediss://` (TLS, for a
      server elsewhere).
- [x] `JINA_API_KEY` is a secret setting too; `EMBEDDINGS_PROVIDER=jina` without it refuses to
      start, and an embedder's error names the status it got, never the texts it was sent.
- [x] `GROQ_API_KEY` is a secret setting as well; `LLM_PROVIDER=groq` without it refuses to
      start, and the model client's error names the status and Groq's error code, never what
      it was asked or answered.
- [x] The corpus's sources are pinned by SHA-256 in `corpus/manifest.toml`: the converter
      refuses a download whose digest differs, and loading the corpus refuses an edition file
      that is not exactly what the converter writes (ADR-0020).
- [ ] Debug mode and interactive docs disabled or protected outside development.
- [ ] Dependency audits in CI; Dependabot enabled.

### V14 Data protection

- [x] No invoice content in logs: a failure logs only the type of its error, and a test sends
      a marked invoice through every outcome of the validation endpoint, checking both the log
      records and the file descriptors. A job that fails logs only the type of its error too,
      and records a message written for its member.
- [ ] No invoice content in traces, metrics or crash reports (with Langfuse and Sentry).
- [x] The validator writes nothing to the process's standard streams: Saxon's warnings, which
      can quote a document, go to the null device (tested on the file descriptors); where that
      device cannot be opened, a log warning says that they reach the standard error instead.
- [x] No-store mode: `POST /invoices/validate` and `POST /invoices/explain` keep the invoice
      in memory for the length of the request, and tests check that they leave no row behind.
      Explaining logs the rules, the model and the number of answers, never a message (tested
      with a message that quotes the invoice); so does a repair the model proposes, which logs
      the number of patches, rounds and answers, never a field, a value or a reason (tested).
- [x] Responses that carry invoice data send `Cache-Control: no-store`: the validation report,
      the explanations, every answer about a stored invoice, and every job and its event
      stream, each checked by a test.
- [x] Responses that carry a credential send `Cache-Control: no-store` as well (RFC 6749): the
      tokens of registration, sign-in, accepting an invitation and refreshing, an invitation's
      code and a new API key, each checked by a test.
- [~] Deletion: `DELETE /invoices/{id}` removes the invoice, its document and its report. A
      finished job, with its parameters, progress and result, is deleted 30 days after it ends
      (`SEF_JOB_RETENTION_DAYS`, ADR-0038), and never while it is under way (tested). A retention
      period for stored invoices, set by each organization, is still to come.
- [x] The corpus holds public text only and belongs to no organization: its tables have no
      `organization_id` by design, and only the ingest command writes them (ADR-0020).

### V15 Secure coding and architecture

- [~] Deterministic validator as the single source of truth; LLM output treated as untrusted:
      the explainer is asked about violations layer 1 reported in the same request, never
      about violations a client sends; its answer is parsed against a schema, its citations
      checked, its values held to those of its question (ADR-0022), and the response built
      from stored passages, not from what the model wrote about them. The violation and the passages are sent as data the model is told not to
      follow. The repairer's patches are parsed against a schema and the patch engine's own
      model and path grammar, their values held to what the model was sent, and applied by the
      validator's process to a copy that layer 1 judges; a person approves them (ADR-0025).
- [ ] Static typing (`mypy --strict`), linting and tests gate every change.

### V16 Security logging and error handling

- [ ] Structured JSON logs with request ids; security-relevant events (login, key use,
      approval, send-to-SEF) are logged without payloads.
- [x] An audit log in the database records what an organization must account for, committed
      with the change itself: who proposed, approved or rejected a repair, with which key, to
      which invoice, the digests before and after and each patch's place and outcome, never a
      value or a reason (ADR-0024), and the model that wrote the patches, when one did
      (ADR-0025). Only a person signed in decides on a repair; an API key is refused (403).
- [ ] Errors are handled centrally; unexpected exceptions are reported to Sentry without
      invoice content.

### V17 WebRTC

- Not applicable: the system does not use WebRTC.

## Secrets handling for contributors

- Never commit `.env`, keys, tokens or certificates. `.gitignore` excludes them and `gitleaks`
  blocks commits that contain secret-looking strings.
- The maintainer creates all accounts and API keys and puts values in a local `.env`; tooling
  and assistants only ever see variable names.
- If a secret is ever committed, treat it as compromised: rotate it first, then rewrite history.
