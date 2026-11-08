# 46. An MCP client steps up for a tool's scope, and every tool is listed

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M4)
- Technical story: milestone M4, branch `feat/mcp-scope-step-up`; the scopes per tool of
  ADR-0044, of which there are two since `feat/mcp-invoice-tools`

## Context and problem statement

A person allows an MCP client some scopes: `invoices:validate` to check invoices,
`invoices:submit` to keep and read them. A client allowed the first only, or connected before
the second existed, calls a tool that needs the second. Until now the tool answered an error in
words ("requires the permission invoices:submit"), which a client's model reads and the person
never sees as a question: the only way on was to remove the connection and make it again. The
MCP revision describes a step-up instead: the resource server answers HTTP 403 with
`WWW-Authenticate: Bearer error="insufficient_scope"` and the scopes needed (RFC 6750 §3.1), and
the client asks its person again and repeats the call. How should the endpoint ask for more, and
should `tools/list` show a client the tools its scopes do not reach?

## Decision drivers

- The person decides, in the flow they already know: the consent page, with the scopes named.
- A tool beyond the scopes never runs, whatever the client does with the answer.
- No second source of truth for what a tool needs.
- A client that does not step up still gets an answer it can show.

## Considered options

1. **A 403 `insufficient_scope` from the endpoint, before the tool runs, and every tool
   listed.** Chosen.
2. The same 403, and `tools/list` filtered by the scopes.
3. The tool's error in words, as before.

## Decision outcome

**Answered at the endpoint, before the server.** A tool's answer is a JSON-RPC result inside
an HTTP 200, which no client takes for a challenge, so `RequireCredential` reads a token
holder's posted messages (a batch too) and, for a `tools/call` of a tool whose permission the
person's role grants, a scope could allow, and the token's scopes do not, answers 403 with the
protected resource metadata and the scopes: those the token holds and those the call needs,
since a client need not remember what it was allowed before. What each tool needs is
`tools.PERMISSIONS`, which a test holds to what each tool checks. Anything else, an unknown
tool or a message that is no JSON, is the server's to answer, as before.

**Only where asking could help.** A permission the person's role would not grant, which the
consent page could not allow either, and an API key's missing permission, are the tool's error,
in words, as before. The tool still checks the role and the scopes itself: the challenge can
only refuse earlier, never allow.

**Every tool listed.** A client hidden a tool would never call it, so never step up for it,
and the person would never be asked. Listing does not grant anything.

### Consequences

Good:

- A client that steps up asks the person again on the consent page and repeats the call; the
  person is not told to remove a connection.
- The tool's own checks are unchanged; the step-up adds a refusal, nothing more.

Bad / accepted:

- A token holder's message is parsed twice, by the endpoint and by the server; messages are at
  most 1 MiB, the API's limit on bodies.
- A client that does not step up shows its person an HTTP error rather than the tool's words;
  the error says which scope the person has not allowed.
- Each step-up is a new consent: the earlier one stands until it is revoked or its tokens lapse.

## Pros and cons of the options

### `tools/list` filtered by the scopes

- Good: a client's model is not offered what would be refused.
- Bad: what is not listed is never called, so never asked for; the person would have to know
  to reconnect. It also hides the server's reach from the person choosing what to allow.

### The tool's error, as before

- Good: nothing to parse ahead of the server.
- Bad: no client takes a 200 for a challenge; the person is never asked, only told, through the
  client's model, if at all.
