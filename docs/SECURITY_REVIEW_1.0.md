# Security review for 1.0

The release of 1.0 waited on a security review (`docs/BRIEF.md`, M7). This review walked every
item of the OWASP ASVS 5.0 Level 1 checklist in `SECURITY.md` that was open or in progress. It
ran the audits CI runs, over the whole history, and decided each finding: fixed in the branch
of this review, or accepted with its reason below. It was done on 14 November 2026, on `main`
at `969a942`, in `chore/security-review-1.0`.

## What was run

| Check | Result |
| --- | --- |
| `pip-audit --strict` against the lock file | No known vulnerability. |
| `pnpm audit` | Nothing high or critical. One moderate advisory (`minimatch`, GHSA-g3hv-75wg-m249) and one low (`deepmerge`, GHSA-gcqx-w48m-w2h4), both only through the `shadcn` CLI, a development dependency not in the built application. Accepted below. |
| gitleaks over the history (480 commits) | No leak. |
| The end-to-end golden path against the production build, under the new headers | Passed, no page error. |
| The API's and the web's tests, ruff, mypy in strict mode, ESLint, TypeScript | Passed. |

## Items closed

Fixed in this branch:

- **V3:** the API's answers carry `Content-Security-Policy: default-src 'none';
  frame-ancestors 'none'`, `nosniff` and `Referrer-Policy: no-referrer`. The web's pages carry a
  policy whose `connect-src` is the site and the API alone, with `nosniff`, `no-referrer` and a
  `Permissions-Policy`. The policy that SECURITY.md promised would come with the hosting, the one
  bounding what an injected script could do with the refresh token, had never come.
- **V4:** the OpenAPI schema names each endpoint's permission (`x-required-permission`), read
  from the route's dependencies and held to the route audit by a test.
- **V6:** a new password among the 10,000 most common that meet the policy is refused, from a
  list that ships with the API.
- **V13:** production serves no interactive documentation.

Verified, then ticked, with the checklist's wording made to say what the code does:

- **V1:** user-originated rule ids and paths.
- **V3:** cookies; there are none.
- **V4:** the error schema.
- **V8:** the event stream's five minutes.
- **V9:** the signing key: replaced, not rotated, since nothing signed outlives 15 minutes.
- **V11:** cryptography and randomness.
- **V12:** TLS and outbound timeouts.
- **V13:** configuration and audits.
- **V15:** the validator as the authority, with the reading of M7; the gates in CI.

## Accepted, with the reason

- **Inline scripts are allowed (`script-src 'unsafe-inline'`).** Next.js renders each page with
  inline scripts of its own. A nonce on each would make every page dynamic, which costs the
  static and partially prerendered pages their caching. An injected script would still run, but
  React escapes what it renders, a lint rule forbids setting HTML from data, and the policy keeps
  the script from reaching any address but the site's and the API's. To revisit if the pages
  become dynamic anyway.
- **The refresh token lives in the page's storage (ADR-0027).** It is spent on use, and a
  replayed one ends its whole session. The policy above bounds where a script could send it.
- **The two advisories in the `shadcn` CLI.** It is a development tool that writes components
  into the source tree. It is not built into the application, and neither advisory has a path
  from a request. Dependabot proposes the fixed versions when they reach it.
- **Level 1 only.** The brief asks for ASVS Level 1. Level 2's items, multi-factor
  authentication first among them, are not claimed.
- **The public demo's model providers are free tiers.** The demo says so on the upload page, and
  asks for synthetic invoices only. Google's free tier, which may use what it is sent, reads only
  the evaluation's synthetic documents (ADR-0062).
