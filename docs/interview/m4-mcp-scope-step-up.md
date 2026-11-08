# M4 — `feat/mcp-scope-step-up`

## Three questions a senior engineer would ask

**1. "The tool already refuses a call its scopes do not allow. Why refuse it again earlier?"**

Because of who reads the refusal. A tool's error is a JSON-RPC result inside an HTTP 200: the
client's model reads it, and the person is at best told to reconnect. A 403 with
`WWW-Authenticate: Bearer error="insufficient_scope"` and the scopes is read by the client
itself, which sends its person to the consent page again and repeats the call. Only the
endpoint, before the MCP SDK runs the tool, can answer with an HTTP status.

**2. "Parsing JSON-RPC in a middleware: what if you read it wrong?"**

Then a call is refused that should not be, or a client gets the tool's error instead of the
challenge: never more access. The tool still checks the role and the scopes itself, so the
endpoint can only refuse earlier. What it reads is narrow: a `tools/call`, alone or in a batch,
naming a tool in `tools.PERMISSIONS`, which a test holds to what each tool checks. Anything else
goes to the server unchanged, its body given again.

**3. "Why not hide the tools a token's scopes do not reach?"**

A client never calls a tool it was not shown, so it never steps up, and the person is never
asked; they would have to know to remove the connection and make it again. Listing grants
nothing. The backlog first said to filter the list; the decision against it is ADR-0046.

## The one concept to explain unaided

**A challenge versus an error**: an error tells, a challenge asks. A 403 `insufficient_scope`
with the scopes is a question the client knows how to put to its person; the same words in a
tool's result are only words.

## Supporting facts worth remembering

- The challenge names every scope still needed, the held ones too: a client need not remember
  what it was allowed, and asking for the new one alone could cost it the old.
- A scope the person's role would not allow is not asked for: the consent page could not grant
  it, and asking would loop. That case and an API key's missing permission stay the tool's
  error.
- Each step-up is a new consent; the earlier one stands until it is revoked or its tokens lapse.
