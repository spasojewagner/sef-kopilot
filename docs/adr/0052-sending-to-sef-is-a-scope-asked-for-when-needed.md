# 52. Sending to SEF is a scope of its own, which an assistant asks for when it first sends

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M5)
- Technical story: milestone M5, branch `feat/mcp-send-to-sef`; the brief's MCP tool
  `send_to_sef_demo`, over the sending of ADR-0051, with the scopes of ADR-0044 and the step-up
  of ADR-0046

## Context and problem statement

The MCP server gets the tool `send_to_sef_demo`, which does what `POST /invoices/{id}/sef` does:
it sends a stored invoice to SEF's demo environment in the organization's name. Unlike every
tool before it, it acts outside the server, where neither the server nor the person can take it
back: SEF keeps what it imports, and the buyer sees it. Only owners and accountants may send
(`invoices:send`). An assistant holds what its person allowed when they connected it, through
the scopes `invoices:validate` and `invoices:submit`, the second of which a client of the office
holds too. How should a person allow an assistant to send, and what should they be asked when
they connect it?

## Decision drivers

- Least privilege: an assistant that validates and stores invoices should not hold the power to
  send from its first connection.
- The person decides, on the consent page they know, at the moment the power is about to be
  used.
- What the consent page shows is what approving gives.
- Clients that follow the MCP revision's scope selection (the challenge's `scope` first, then
  `scopes_supported`) behave well without anything of their own.

## Considered options

1. **A scope of its own, `invoices:send`, which a client is not told to ask for first and asks
   for through the step-up when its assistant first sends.** Chosen.
2. A scope of its own, asked for by default with the others.
3. Sending folded into `invoices:submit`.
4. No tool: an assistant tells the person to send from the web application.

## Decision outcome

**A scope of its own.** `invoices:send` allows the permission of the same name, which a role
grants to owners and accountants. The authorization server supports it (`scopes_supported`
lists it), and a request may name it.

**Asked for when it is needed.** The MCP endpoint's 401 challenge names the scopes to ask for
first, `invoices:validate invoices:submit`, and a client that names no scope at
`/oauth/authorize` is given those two to decide on. The first call of `send_to_sef_demo` by an
assistant whose token lacks the scope, for a person whose role grants it, is answered 403
`insufficient_scope` with the scopes it holds and `invoices:send`, as ADR-0046 does for any
tool; a client that steps up sends its person to the consent page, where sending is named, and
repeats the call.

**The consent page tells what approving gives.** `GET /oauth/requests/{id}` names the scopes
asked for that the person's role does not grant (`withheld`), and the page lists them apart, so
that a client of the office asked to send does not read as if approving allowed it. When the
role withholds every scope, the page lets the person only deny. As before, the approval keeps
the scopes the role grants, and every refresh reads the role again: an owner who becomes a
client loses sending at the next refresh.

**The tool itself.** It sends what the route sends, through the same function, once through the
request id; through an assistant, a person sends the invoices they submitted, as they read only
those. Its annotations say it reaches outside the server (`openWorldHint`) and may be repeated
(`idempotentHint`), since a repeated call is asked about with the same request id or refused as
sent; the server's instructions tell the assistant to send only when its person asks.
`get_sef_status` reads where the invoice stands in SEF, with `invoices:submit`.

### Consequences

Good:

- Connecting an assistant gives it no power to act outside the server; the person grants it
  once, when it is first used, on a page that names it.
- No new mechanism: the scopes, the challenge and the step-up are those of M4.
- The consent page no longer shows a client of the office a power that approving would not
  give.

Bad / accepted:

- A client that does not step up cannot send until its person connects it again asking for
  `invoices:send`; the web application sends in any case.
- A client that asks for every scope in `scopes_supported` regardless of the challenge gets
  `invoices:send` asked for at once; the person still decides, with the scope named.
- Tool annotations are hints a client may ignore; what holds is the scope, the role and the
  instructions, in that order.

## Pros and cons of the options

### Asked for by default

- Good: one consent, no second visit to the page.
- Bad: every assistant connected to validate would be asked for the power to send, and most
  people approve what a page shows them at connection time.

### Folded into `invoices:submit`

- Good: no new scope.
- Bad: a client of the office holds `invoices:submit`, so the consent page would offer it a
  power its role withholds; and storing an invoice and sending it in the organization's name
  are not the same act.

### No tool

- Good: nothing outside the server is done through an assistant.
- Bad: the brief names the tool, and the accountant who works from an assistant would leave it
  for the last step, where the validator's verdict already decides.
