# 12. Authentication: argon2id passwords, short-lived JWT access tokens, rotating refresh tokens

- Status: accepted; amended by [0013](0013-authorization-and-tenant-isolation.md), under which
  guarded endpoints check the membership on every request
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-auth-tokens`

## Context and problem statement

People sign in with an e-mail address and a password (the brief), work in one organization at a
time although they may belong to several (ADR-0011), and use the API from the web app and, from
M4, from MCP clients. The brief fixes argon2 for passwords and JWT access tokens with refresh
tokens. Still open: the hashing parameters on a free-tier instance with 512 MB of memory; what
an access token contains and how strictly it is checked; how refresh tokens are stored, rotated
and revoked; how a stolen one is noticed; and which organization a session belongs to. API keys
for machine clients follow in the next branch.

## Decision drivers

- A leaked database, a stolen token or a replayed request should give an attacker as little as
  possible, for as short a time as possible.
- Requests should not need the database just to know who calls; sessions must still be revocable.
- Hashing must be slow for an attacker and affordable for a small instance.
- Boring, widely used libraries.

## Considered options

1. **argon2id with OWASP's minimum parameters; JWT access tokens (HS256) valid for 15 minutes,
   checked without the database; opaque refresh tokens stored as digests, spent on use, grouped
   in families whose reuse revokes the session; sessions per organization** — chosen.
2. Server-side sessions with a cookie for everything.
3. Long-lived JWTs without refresh tokens.
4. Self-contained (JWT) refresh tokens.
5. Asymmetric signatures (RS256, EdDSA) now.
6. Authlib's JOSE implementation instead of PyJWT.

## Decision outcome

Option 1. Concretely:

- **Passwords.** argon2id (argon2-cffi) with 19 MiB of memory, two passes and one lane, OWASP's
  recommended minimum, hashed in a worker thread so that the event loop keeps serving. A hash
  made with other parameters is replaced at the next sign-in. Passwords have 12 to 128
  characters. For an unknown address a dummy hash is checked, and a wrong password, an unknown
  address and a deactivated account all get the same 401.
- **Access tokens.** JWT, HS256, header type `at+jwt` (RFC 9068), claims `iss`, `aud`, `sub`, `org`,
  `role`, `iat`, `exp` and `jti`, all required; only HS256 is accepted, so `none` and algorithm
  confusion are refused. Valid for 15 minutes (`SEF_ACCESS_TOKEN_MINUTES`) and signed with
  `SEF_JWT_SECRET`, at least 32 characters, required in production and random per process
  elsewhere. Checked without the database: a person removed from an organization or deactivated
  keeps access until the token expires. `GET /auth/me` does read the database.
- **Refresh tokens.** 256 random bits, given to the client once and stored as their SHA-256 digest
  (a slow hash protects guessable passwords; a random token needs none). The tokens of one
  sign-in form a family. `POST /auth/refresh` spends the token, issues the next for another 30
  days (`SEF_REFRESH_TOKEN_DAYS`) and re-reads the membership, so a change of role takes effect
  then and a deactivated person or a former member is signed out. A spent or revoked token
  presented again means that someone else has a copy: the whole family is revoked (reuse
  detection, OAuth 2.0 Security Best Current Practice). The token's row is locked while it is
  spent, so of two simultaneous refreshes the second counts as a replay. `POST /auth/logout`
  revokes the family.
- **Organizations.** A session belongs to one organization. A member of several names it at
  sign-in; without it the answer is 409 with the list to choose from. Switching organization
  means signing in again.
- **Registration** is open: it creates the account, an organization and the owner's membership.
  A taken address answers 409, which tells that the address has an account; there is no e-mail
  verification or password reset yet, because the free-tier stack has no mail service.
- **Not yet** (tracked in `SECURITY.md`): rate limiting on sign-in and refresh, a breached-password
  check against a local list (the self-hosted mode makes no external calls), and key rotation.

### Consequences

Good:

- No request needs the database to know its caller; sessions are still revocable, and a replayed
  refresh token ends the session for the thief as well as for the person.
- A leaked table holds no password and no usable token.
- One hash costs a few dozen milliseconds and 19 MiB, so a 512 MB instance survives a burst of
  sign-ins.

Bad / accepted:

- Up to 15 minutes of access after a person is removed or deactivated.
- A client that retries a refresh after a lost response is signed out (strict rotation).
- With HS256 only this service can verify its tokens; when MCP clients need tokens verified
  elsewhere (M4), asymmetric keys and a published key set are the change to make.

## Pros and cons of the options

### Server-side sessions with a cookie

- Good: instant revocation.
- Bad: a database read on every request; cookies bring CSRF into an API used by ERPs and MCP
  clients; not what the brief asks for.

### Long-lived JWTs only

- Bad: a stolen token works until it expires, and nothing can revoke it.

### JWT refresh tokens

- Bad: rotation and reuse detection still need state on the server, so a self-contained token
  adds size and a signature and saves nothing.

### Asymmetric signatures now

- Good: other services could verify tokens with a public key.
- Bad: key management for consumers that do not exist yet; to be revisited with MCP in M4.

### Authlib's JOSE implementation

- Good: Authlib serves the OAuth 2.1 work of M4.
- Bad: PyJWT is smaller and more widely known; token handling is confined to `auth/tokens.py`,
  so a later change of library stays local.
