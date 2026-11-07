# M4 — `feat/mcp-server`

## Three questions a senior engineer would ask

**1. "Why is the MCP server inside the API's process rather than a service of its own?"**

Because a tool must do exactly what its route does. In the process, `validate_invoice` calls
the functions `POST /invoices/validate` calls, so both count against one rate limit and answer
the same errors in the same words. A separate service would call the API over HTTP: a second
free instance that sleeps on its own, a second hop on every call, and the caller's key passed
along. The cost of the choice is that the API's process carries the SDK; it is a library, not a
second server.

**2. "Why no sessions? The SDK keeps them by default."**

It keeps them in one process's memory. The demo's instance sleeps and restarts many times a
day, and every restart would end every client's session; two instances would not share them.
Without sessions each message is a POST answered with JSON, which any instance can answer, and
the protocol's 2026-07-28 revision needs none anyway. What is given up is the server's own
messages, such as progress notifications, which these tools do not need.

**3. "Why refuse the web application's access tokens? They are valid tokens of the same API."**

A token is accepted only by the resource it was issued for. The access tokens were issued for
the API's routes, to the web application; accepting them at `/mcp` would let anything that
holds one act through another door than the one it was given. API keys are the credential
machine clients already have, scoped by permission. The OAuth 2.1 step issues tokens whose
audience is the MCP endpoint itself.

## The one concept to explain unaided

**One service, two doors**: a protocol adapter should be a thin layer over the same functions
the existing interface calls, so that its checks, limits and errors cannot drift from them.

## Supporting facts worth remembering

- Messages are JSON-RPC 2.0; a tool's failure is a result with `isError`, which the client's
  model reads; a refused request (401, 403, 405, 413) never reaches the protocol.
- The SDK sets up the root logger when a server is made; the application puts it back.
- `Origin` is checked against the web application's origins; the SDK's `Host` check is off,
  since behind a platform's proxy the server does not know its hosts.
