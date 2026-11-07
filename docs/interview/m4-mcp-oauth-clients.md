# M4 — `feat/mcp-oauth-clients`

## Three questions a senior engineer would ask

**1. "The brief says Authlib. Why routes of your own?"**

Authlib's authorization server is synchronous and built around Flask and Django requests; the
API is asynchronous end to end, so using it means threads and a second way of holding a
database session. The MCP SDK has an asynchronous one, but its registration mints a client
secret and later compares the stored secret itself, so the server would keep secrets in clear,
and neither has the protocol's newest pieces (client ID metadata documents, the issuer in the
authorization response). The surface needed for public clients is small: the ADR records the
choice and its price, which is getting the RFCs right ourselves, with tests per requirement.

**2. "A client asks for `client_secret_post` and you register it as public. Is that allowed?"**

RFC 7591 lets the server replace any metadata value it does not support, and the answer tells
the client what it was registered with, so a client that reads it sends no secret. Being public
costs it nothing: OAuth 2.1 asks every client for PKCE, which is what proves that the client
ending an authorization began it. The server, in exchange, holds no secret that could leak.

**3. "Anyone can register. What stops a flood?"**

Registering grants nothing: a client can do nothing until a person signs in and lets it. The
endpoint is counted by address, ten an hour, its body is bounded like every other, and a row is
a few hundred bytes. Registrations never completed can be deleted, as old jobs are.

## The one concept to explain unaided

**A public client proves itself with PKCE, not a secret**: it makes a random verifier, sends its
SHA-256 when the authorization begins, and the verifier itself when it collects the token; only
the one that began can finish.

## Supporting facts worth remembering

- Redirect URIs: `https`; `http` only on the loopback interface (an application on the person's
  own computer); or a scheme of the application's own; never a fragment, `javascript:` or
  `data:`; compared exactly when used.
- Without `SEF_PUBLIC_URL`, every `/oauth` route answers 404 and the MCP endpoint takes API keys.
