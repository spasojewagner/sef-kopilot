# M4 — `feat/mcp-propose-fix`

## Three questions a senior engineer would ask

**1. "An assistant proposes a repair. What stops it from approving it?"**

Nothing it can reach approves. No tool decides; the approval route takes a person in person
only (`in_person`: the web application's own session, not an API key nor an MCP client), and an
assistant's access token is issued for the MCP endpoint alone, so it is refused on the routes
anyway. The tool answers `decide_at`, the web application's page of the repair, for the
assistant to hand to its person. The invoice changes only there, and the repair says who
proposed it; the audit log names the client it came through.

**2. "Why may the assistant give its own patches? Isn't the server's model enough?"**

The assistant is often the stronger model, already talking with the person about the invoice.
Its patches meet the same walls as anyone's (ADR-0025): each at a canonical path, applied to a
copy, the copy validated by the deterministic validator, and a patch that touches an amount,
VAT, a tax or company identifier, a date or the number left to the person. Where the patches
came from changes nothing about what is trusted. Without patches, the server's model writes
them, as `POST .../repairs/suggestion` does.

**3. "Why one tool for two routes?"**

For the client's model it is one intention, "propose a fix", and the only difference is who
writes the patches; two tools would make it choose without knowing why. The tool takes the
route of each case, the logic moved out of both routes' bodies first, so each case answers
what its route answers.

## The one concept to explain unaided

**Propose, never dispose**: an assistant may prepare a change, as anyone may, but the decision
is a person's, on a page of their own, and the system's channels make that true rather than a
promise in a prompt.

## Supporting facts worth remembering

- `decide_at` is in the language asked for (`sr-Latn` or `en`); on a server without
  `SEF_WEB_URL` it is none.
- A repair proposed through an assistant counts as a validation, and as a request to the
  language model when the server's model writes the patches, against the client's consent.
