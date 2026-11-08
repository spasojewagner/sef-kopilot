# M4 — `feat/mcp-invoice-tools`

## Three questions a senior engineer would ask

**1. "Why is there no scope for every invoice of the organization?"**

Least privilege. An assistant acts for one person, and what that person asks it about is their
own work. A scope for `invoices:manage` would let an assistant connected by an owner read every
member's invoices, a reach far larger than the job, held by a program the person does not
control. The caller's permission is the role's and the token's scopes together, and since no
scope maps to `invoices:manage`, the routes' own rule (`scope_of`) gives an assistant the
invoices its person submitted. An API key keeps what its role grants, as on the routes.

**2. "Why do the tools answer exactly what the routes answer?"**

One contract, two transports. The tools call the routes' services and the routes' presenters
(`present`, `present_stored`), so a stored invoice has one shape whichever way it is read, and
the tool's output schema is generated from the same Pydantic model. A test reads one invoice
three ways, stored by the tool, read by the route and by the tool, and asks that the answers
are equal; a field added to the route cannot go missing from the tool.

**3. "Storing is not idempotent. What happens when an assistant retries?"**

It stores the invoice twice, as two `POST /invoices` would; the tool says so in its annotations
(`idempotentHint: false`, `readOnlyHint: false`), which is what a client reads before it retries
a call on its own. The organization's quota bounds what a looping client can keep. Before it
writes, the tool reads the consent again (`check_again`): validation takes time, and a person
who revoked the consent meanwhile must not find an invoice stored afterwards.

## The one concept to explain unaided

**Effective permission is an intersection**: what an assistant may do is what the person's role
grants *and* what the person allowed the client, read again on every request; which invoices
it sees follows from that, by the same rule as for the person.

## Supporting facts worth remembering

- A client connected before this branch holds `invoices:validate` alone; a refresh never widens
  a consent (`invalid_scope`), so the person connects it again to give it `invoices:submit`.
- A tool the token's scopes do not reach answers a tool error naming the permission; the MCP
  revision's step-up (403 `insufficient_scope`) and `tools/list` filtered by the scopes follow.
- The organization's quota (`SEF_MAX_STORED_BYTES`) answers a tool error, not a crash.
