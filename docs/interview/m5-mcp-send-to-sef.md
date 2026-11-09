# M5 — `feat/mcp-send-to-sef`

## Three questions a senior engineer would ask

**1. "Why not grant sending with the other scopes when the assistant connects?"**

Because connecting is when people approve whatever a page shows them, and sending is the one
act that leaves the server: SEF keeps what it imports, and the buyer sees it. The challenge at
`/mcp` names the two scopes to ask for first, and a client that names none is given those two
to decide on. The first time the assistant calls `send_to_sef_demo`, the endpoint answers 403
`insufficient_scope` naming `invoices:send`, the client sends its person to the consent page,
and the person decides with the power named, at the moment it is about to be used. It is the
step-up that already existed for the other tools; nothing new was built for it.

**2. "An assistant repeats a tool call after a timeout. Do you get two invoices in SEF?"**

No. The tool calls the same function as the route: the submission is committed before SEF is
asked, and its id is SEF's `requestId`. A repeat after an answer that never came asks SEF again
with the same id; a repeat after an import is refused as `sent` before SEF is asked. That is why
the tool says `idempotentHint: true` while it is anything but read-only, and `openWorldHint:
true` because it reaches outside the server.

**3. "A client of the office approves an assistant that asks to send. What happens?"**

Their role does not grant `invoices:send`, so the approval keeps the other scopes only, as it
always did. What changed is the page: the request now says which scopes the role withholds, and
the page lists them apart, so the person does not believe they allowed something they did not;
if the role withholds everything asked, the page lets them only deny. An owner who later becomes
a client loses sending at the next refresh, because every token exchange reads the role again.

## The one concept to explain unaided

**Least privilege over time**: grant the narrow scopes at connection, and ask for the
dangerous one at the moment it is first used, through a challenge the client already
understands; the person decides with the power named, and the role still bounds what any
consent can give.

## Supporting facts worth remembering

- `scopes_supported` lists all three scopes; the 401 challenge's `scope` names the two to ask
  for first. MCP clients use the challenge's scope before the metadata's.
- Through an assistant, a person sends only the invoices they submitted, as they read only those:
  no scope reaches every invoice of the organization.
- The audit log records each sending with the MCP client it came through.
- Tool annotations are hints; the scope, the role and the server's instructions are what hold.
