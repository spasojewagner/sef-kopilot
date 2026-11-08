# 39. OAuth 2.1 for an MCP server: from a 401 to a tool call

An assistant such as Claude or ChatGPT is given one address, `https://api.example/mcp`, and
nothing else. Everything it needs to connect on a person's behalf it discovers from there, in
documents the server publishes, and every step is a standard of its own:

```text
client                                   API (resource + authorization server)        person
  │ POST /mcp (no token)                       │
  │◀── 401  WWW-Authenticate: Bearer resource_metadata=".../.well-known/oauth-protected-resource/mcp"
  │ GET  /.well-known/oauth-protected-resource/mcp          RFC 9728: who issues tokens for me
  │ GET  /.well-known/oauth-authorization-server            RFC 8414: where to register, ask, exchange
  │ POST /oauth/register                                    RFC 7591: a public client, no secret
  │ browser ─▶ GET /oauth/authorize?…&code_challenge=S256(v)&resource=…/mcp      RFC 7636, 8707
  │                                         302 ─▶ web /oauth/consent ─────────────▶ Allow
  │ browser ◀── redirect_uri?code=…&state=…&iss=…                                   RFC 9207
  │ POST /oauth/token  code + verifier v                   ─▶ access token (aud …/mcp) + refresh
  │ POST /mcp  Authorization: Bearer <access token>        ─▶ the tools the scopes allow
  │ POST /oauth/token  refresh_token                        ─▶ the next pair; the old one spent
```

**Why each piece is there.**

- *Protected resource metadata* lets the MCP server say which authorization server it trusts
  without the client being configured for it.
- *Authorization server metadata* lists the endpoints and what they support (S256, public
  clients, the issuer in the answer), so nothing is guessed.
- *Dynamic registration* (or, in the newest revision, a client ID that is the URL of the
  client's own metadata document) lets a server meet a client it has never seen.
- *PKCE* binds the code to whoever began: the client sends the SHA-256 of a secret first and
  the secret itself last, so a stolen code is useless without it.
- *Resource indicators* name the server a token is for; the token's audience is that server,
  and the MCP server refuses any other, so a token cannot be replayed elsewhere ("no token
  passthrough").
- *The issuer in the authorization response* stops a client that talks to two servers from
  sending one's code to the other.

**What stays the server's own policy.** Who may consent (a signed-in person, never an API
key), which scopes a role allows, how long tokens live, and what makes a consent end: a code
or refresh token presented twice, or the member leaving the organization. The MCP endpoint
reads the consent behind a token on every request, so that ending it stops the token at once,
not when it expires.
