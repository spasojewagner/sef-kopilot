# 35. The Model Context Protocol: tools a model may call, over plain HTTP

An assistant such as a chat application has a language model and a list of **tools**: things
it may ask a server to do, each with a name, a description for the model and a JSON Schema for
its arguments and its answer. The Model Context Protocol (MCP) is the standard way to offer such
tools. Its messages are JSON-RPC 2.0: a `method`, `params`, an `id`, and a `result` or an
`error` in reply.

```text
user ──► assistant (the client) ── tools/list ───────────────► SEF Kopilot (the server)
                │                 ◄── validate_invoice: schema ──
          its model decides
          to call a tool ─────────── tools/call validate_invoice {xml} ──►
                                  ◄── {valid, violations: [...]} ───────
          its model writes the answer from what the tool said
```

**The transport.** Over **Streamable HTTP**, the client posts each message to one URL, here
`/mcp`, and the server answers with JSON, or with an event stream when it has several things to
say. Earlier revisions of the protocol opened a **session** with `initialize`, whose id the
client sent with every later message; the server kept it in memory. The 2026-07-28 revision
needs none: each request carries what the server must know. SEF Kopilot keeps no session for
any revision, so a restart, which the free plan does often, loses nothing.

**What a tool call goes through here.**

```text
POST /mcp ─► LimitBodies (1 MiB) ─► RequireKey: Origin? POST? API key? ─► SDK: parse, find the
tool, check the arguments against its schema ─► validate_invoice: permission, rate limit,
validator ─► the report, as the route's
```

**Three ideas worth keeping.**

- **The model is a client, not a judge.** The tool's description and the server's instructions
  tell it that the rule sets decide; it reports the validator's verdict. The server never trusts
  what a model sends: arguments are checked against the schema, and the document by the
  validator, as an upload is.
- **One service, two doors.** A tool is a thin layer over the same functions a route calls, so
  the two cannot disagree, and a client's model is told why it was refused in the route's words.
- **A token belongs to the resource it was issued for.** The web application's access tokens
  are for the API's routes; the MCP endpoint takes API keys now, and will take tokens issued for
  it once it has an OAuth 2.1 authorization server (M4's next step).

**An error, two kinds.** A failure the client can act on (no permission, too many requests, an
invoice too large) is a tool result marked `isError`, whose text the model reads. A malformed
message is a JSON-RPC error, and a refused request (401, 403, 405, 413) never reaches the
protocol at all.
