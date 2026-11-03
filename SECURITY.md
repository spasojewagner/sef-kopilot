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
   re-validated by layer 1. Patches that touch amounts, VAT, tax identifiers or dates of supply
   are rejected automatically.
5. Multi-tenancy is enforced in the service layer on every query (`organization_id`) and
   covered by tests.
6. Dependencies are audited in CI (`pip-audit`, `pnpm audit`); secrets are scanned with
   `gitleaks` in pre-commit and CI.
7. Everything that talks to the outside world is explicit and configurable; a self-hosted
   deployment makes no external calls except the LLM provider the operator chooses.

## OWASP ASVS 5.0 — Level 1 checklist

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done and tested. The checklist is
updated in the pull request that implements each item; chapters that do not apply to this
system are marked as such.

### V1 Encoding and sanitization

- [ ] Output encoding is applied by the templating / UI layer; API responses are JSON only.
- [ ] XPath and XSLT inputs that originate from users (rule ids, paths) are validated against an
      allow-list, never interpolated into expressions.
- [ ] XML parsers reject external entities and DTDs; entity expansion limits are enforced.

### V2 Validation and business logic

- [ ] All request bodies are validated with Pydantic models (strict types, bounded sizes).
- [ ] Business guardrails (forbidden patch fields, arithmetic rules in code, citation
      resolution) are enforced server-side and covered by tests.
- [ ] Rate limiting on upload, validation and explanation endpoints.

### V3 Web frontend security

- [ ] Content Security Policy, `X-Content-Type-Options`, `Referrer-Policy` and
      `Permissions-Policy` headers set by the web app and the API.
- [ ] Cookies (if used) are `Secure`, `HttpOnly`, `SameSite`.

### V4 API and web service

- [ ] CORS restricted to the configured web origin.
- [ ] Every endpoint declares its authentication and authorization requirements; OpenAPI
      documents them.
- [ ] Consistent error schema; no stack traces or internal paths in responses.

### V5 File handling

- [ ] Upload size limit, MIME/type checks, and content sniffing for XML (later PDF).
- [ ] Uploaded files are stored outside the web root (or not stored at all in no-store mode)
      and referenced by opaque ids.

### V6 Authentication

- [ ] Passwords hashed with argon2id; minimum length and breached-password checks.
- [ ] Generic authentication error messages; rate limiting on login.
- [ ] API keys for machine clients are random, hashed at rest, revocable.

### V7 Session management

- [ ] Short-lived JWT access tokens, rotating refresh tokens, server-side revocation list.
- [ ] Logout invalidates refresh tokens.

### V8 Authorization

- [ ] Role-based access (`owner`, `accountant`, `client`) enforced in the service layer.
- [ ] Tenant isolation by `organization_id` on every query, verified by tests that attempt
      cross-tenant access.

### V9 Self-contained tokens

- [ ] JWTs use an allow-listed algorithm, validated `iss`, `aud`, `exp`; keys rotate.

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
- [ ] Debug mode and interactive docs disabled or protected outside development.
- [ ] Dependency audits in CI; Dependabot enabled.

### V14 Data protection

- [ ] No invoice content in logs, traces, metrics or crash reports (tested with a log capture
      fixture).
- [ ] No-store mode; retention policy for stored invoices; deletion endpoint.

### V15 Secure coding and architecture

- [ ] Deterministic validator as the single source of truth; LLM output treated as untrusted.
- [ ] Static typing (`mypy --strict`), linting and tests gate every change.

### V16 Security logging and error handling

- [ ] Structured JSON logs with request ids; security-relevant events (login, key use,
      approval, send-to-SEF) are logged without payloads.
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
