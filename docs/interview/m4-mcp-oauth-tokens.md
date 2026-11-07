# M4 — `feat/mcp-oauth-tokens`

## Three questions a senior engineer would ask

**1. "A code is good once. What happens when it comes back, and why?"**

The second exchange is refused, and the consent is revoked: the refresh token the first
exchange issued is refused from then on, and its access token will be at the MCP endpoint,
which is to read the consent on every request. A code that comes back means someone else may
hold it (OAuth 2.1 §4.1.3), and the server cannot tell which of the two is the rightful client,
so it trusts neither. The consent's row is locked while the code is read, so two exchanges at
once take turns: the second sees the first, which a test on committing sessions holds.

**2. "Why sign the MCP endpoint's tokens with a key of their own, when the audience differs
anyway?"**

Because the audience protects only where it is checked. The web application's access tokens and
these are both HS256 JWTs from the same secret; a decoder that forgot to check `aud` would
accept one for the other. A key derived for these tokens alone (HMAC of the secret with a
label) makes that mistake harmless: the signature itself fails. It costs one line, and no new
secret to deploy.

**3. "How does refresh-token rotation catch a stolen token?"**

Each refresh token is spent once and replaced. If an attacker and the client both hold the same
token, whichever presents it second presents a spent one, and that revokes the consent: the
attacker's copy and the client's newest token both stop. The client signs in again; the
attacker is out. The tokens are kept as SHA-256 digests, so a copy of the table holds none.

## The one concept to explain unaided

**Rotation with reuse detection**: a refresh token is a one-time ticket that comes with the next
one, so the only way two parties can both use a token is for one of them to use a spent one,
which the server sees and answers by ending the whole chain.

## Supporting facts worth remembering

- Access tokens live fifteen minutes (`SEF_ACCESS_TOKEN_MINUTES`), refresh tokens thirty days
  (`SEF_REFRESH_TOKEN_DAYS`), as the web application's do.
- The role is read again at every exchange: a token carries the consent's scopes that the role
  still allows; none means no token. A member removed takes the consent and its tokens with
  them (the rows cascade).
- The redirect URI may be left out of a code's exchange (OAuth 2.1 §4.1.3): PKCE binds the code
  to whoever began. Given, it must be the one the code was sent to.
- Only a client that registered the `refresh_token` grant gets refresh tokens (RFC 7591 §2).
- The step had a review of its own, as ADR-0044 asked: it found the registered grant types
  ignored, no test of two requests at once, a resource that is no URI answered 500, and errors
  that repeated what the client sent; each is fixed and tested.
