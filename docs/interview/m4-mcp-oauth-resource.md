# M4 — `feat/mcp-oauth-resource`

## Three questions a senior engineer would ask

**1. "How does an assistant that knows only `https://…/mcp` find out where to sign in?"**

It is refused, and the refusal says where to look: `WWW-Authenticate: Bearer
resource_metadata="…/.well-known/oauth-protected-resource/mcp", scope="invoices:validate"`
(RFC 9728 §5.1). That document names the authorization server; the server's own document
(RFC 8414) names its endpoints and what they support. From there the client registers, sends
its person to be asked, and exchanges the code. Nothing about this server is configured in the
client beforehand.

**2. "The access token is a signed JWT. Why read the database on every request anyway?"**

Because a signature says who issued the token, not whether the consent behind it still stands.
The token names its consent (`sid`); the endpoint reads it, refusing one that was revoked (a
code or a refresh token came back), that went with a member who left, or that is not the
token's person and client, and reads the member's role again. A revocation therefore takes
effect at once, not when the token expires, at the cost of a read by primary key in the session
that reads the role, as the endpoint does for an API key.

**3. "What may a client do with a token for `invoices:validate`?"**

What the scopes and the role both allow, never more than either: a tool requires its permission
in the member's role and among the permissions the token's scopes map to. A token for managing
members could not validate, and an owner's consent does not lend the owner's role to a scope
that does not name it.

## The one concept to explain unaided

**Resource and authorization server, apart even in one process**: the MCP endpoint only checks
tokens (audience, issuer, signature, the consent), and the authorization server only issues
them; the metadata documents are the contract between the two that a client can read.

## Supporting facts worth remembering

- An API key still works at `/mcp`: machine clients keep what they have.
- Every refusal at `/mcp` carries the challenge, a key's too; an assistant is told only that its
  token will not do, never what became of its person.
- The web application's access token is refused at `/mcp` as before: issued for the API's
  routes, by another key, for another audience.
- To turn it on in the demo: `SEF_PUBLIC_URL` and `SEF_WEB_URL` on Render (`docs/DEPLOY.md`,
  step 6); then a connector to `https://sef-kopilot-api.onrender.com/mcp`.
