# M2 — `feat/api-auth-tokens`

## Three questions a senior engineer would ask

**1. "Why not a single long-lived JWT? It is simpler."**

Because nothing can revoke it: a stolen token works until it expires. The access token lives 15
minutes and is checked without the database; the refresh token is opaque, stored as a digest and
looked up, so sign-out and an ended membership can revoke it. The price is that a removed member
keeps access for up to 15 minutes, which is the usual trade-off and written down in ADR-0012.

**2. "How would you notice that a refresh token was stolen?"**

Rotation with reuse detection. Each refresh spends the token and issues the next one in the same
family. A spent token can only reappear if someone copied it, so when one is presented again the
whole family is revoked and both the thief and the person must sign in again. The row is locked
while a token is spent, so two simultaneous refreshes cannot both succeed.

**3. "Why argon2id with those parameters, and why hash in a thread?"**

argon2id is memory-hard, so guessing on GPUs is expensive. The parameters are OWASP's recommended
minimum, 19 MiB and two passes, which a 512 MB free-tier instance can afford for several sign-ins
at once; a hash records its parameters, so raising them later only needs a rehash at sign-in.
Hashing is CPU work that would block the event loop, so it runs in a worker thread. For an unknown
address a dummy hash is checked, so timing does not tell which addresses exist.

## The one concept to explain unaided

**A token is a bearer instrument: whoever holds it is you.** So its lifetime is short, it is
stored only as a digest, a refresh token is good for one use, and verification is strict: one
algorithm, a fixed type, and every claim the code relies on required and checked.

## Supporting facts worth remembering

- Access token: HS256, `typ: at+jwt`, claims `iss aud sub org role iat exp jti`, 15 minutes.
- Refresh token: `secrets.token_urlsafe(32)`, SHA-256 digest in `refresh_tokens`, 30 days,
  family per sign-in, `FOR UPDATE` while spent.
- Same 401 for a wrong password, an unknown address and a deactivated account.
- Not yet: rate limiting, breached-password check, key rotation, e-mail verification.
