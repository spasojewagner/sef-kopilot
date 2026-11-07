# 42. The MCP server lives in the API's process and answers without sessions

- Status: accepted
- Date: 2026-11-07
- Deciders: the team (milestone M4's first item)
- Technical story: milestone M4, branch `feat/mcp-server`; the brief's MCP section; the access
  control of ADR-0013, the API keys of ADR-0017 and the rate limits of ADR-0018

## Context and problem statement

The brief offers everything SEF Kopilot does to the clients of the Model Context Protocol too:
an assistant an accountant talks to, or an ERP's own automation, calls tools such as
`validate_invoice` instead of the HTTP routes. The official Python SDK serves a server over
Streamable HTTP, which the brief fixes at `/mcp`. Where should the server run, how should it
keep its clients' sessions, and whom should it admit before the OAuth 2.1 authorization server
of the milestone's next step exists?

## Decision drivers

- A tool must do exactly what its route does: the same checks, the same limits, the same
  answers. Two ways in must not drift apart.
- The public demo runs on one free instance that sleeps and restarts many times a day.
- The validator stays the source of truth (ADR-0002): a client's model reports it, never judges.
- Nothing of an invoice in the logs.

## Considered options

1. **In the API's process, as a route of its application, without sessions; the tools call the
   services the routes call.** Chosen.
2. A server of its own that calls the HTTP API.
3. The SDK's defaults: sessions kept in memory, answers as event streams.

## Decision outcome

**The endpoint is a route of the API's application**, `/mcp`, behind its middleware: the limit
on bodies, the answers to unexpected failures, the charset. The SDK's session manager runs for
as long as the application does, in its lifespan. **Each tool does what its route does through
the same services** (`count_validation`, `refuse_when_busy`, `judged` for `validate_invoice`), so
a tool and its route count against one limit, and an HTTP error of the route becomes the tool's
error in the same words.

**No sessions** (`stateless_http`): each message is a POST answered with JSON
(`json_response`). Any instance answers any message, a restart loses nothing, and a client of
an earlier revision of the protocol (2025-06-18, say) is answered as one of the current one
(2026-07-28). Only POST is answered: a GET would open a stream of the server's own messages,
and it has none, so it is refused (405) rather than left open.

**Until OAuth 2.1, an API key admits a client.** `RequireKey`, in front of the server, checks
a request as `require` does a route's: the key and the role its member holds now, a 401 in the
routes' words otherwise. An access token of the web application is refused: it was issued for
the API's routes, and a token is accepted only by what it was issued for, which the OAuth step
will make explicit with resource indicators (RFC 8707). Each tool checks the permission its
route requires; `test_mcp.py` pins every tool's permission, as `GUARDED` pins every route's.

**A page of another origin is refused** (403): the protocol asks servers to check `Origin`
against DNS rebinding. The SDK's own check compares the `Host` header with a list of hosts,
which a server behind a platform's proxy does not know, so it is off, and the origins are the
web application's (`SEF_WEB_ORIGINS`). A page cannot send a key it was not given in any case:
there are no cookies.

**The SDK configures the root logger when a server is made** (`logging.basicConfig`); the
application puts it back, since the process's logging is uvicorn's. The server's tools log no
argument, which a test checks for an invoice's content.

### Consequences

Good:

- One set of checks and limits for the routes and the tools; a tool is a few lines over a
  service.
- Nothing to deploy, wake or keep in step: the server sleeps and wakes with the API.
- A message is an HTTP request like any other: the proxy, the limits and the logs see it so.

Bad / accepted:

- A message is a JSON body, within the 1 MiB limit on bodies (`SEF_MAX_BODY_BYTES`); a larger
  invoice is uploaded to the route. An assistant passing an invoice through its context seldom
  comes near it.
- Without sessions, the server cannot send messages of its own: no progress notifications, no
  request for the user's input in the middle of a call. The tools answer within a request;
  the protocol's sessionless revision asks for input by answering, which can come later.
- Until OAuth 2.1, a client must let its user set a header; assistants that sign in their users
  wait for the next step.

## Pros and cons of the options

### A server of its own that calls the HTTP API

- Good: the API stays one protocol; the server could be scaled or replaced alone.
- Bad: a second free instance that sleeps on its own, a second hop for every call, and the API
  key handed from one service to another.

### The SDK's defaults

- Good: progress notifications and requests to the client while a tool runs.
- Bad: sessions live in one process's memory and are lost at every restart, which the free plan
  does many times a day, and two instances would not share them; an event stream through the
  platform's proxy is one more thing to keep open.
