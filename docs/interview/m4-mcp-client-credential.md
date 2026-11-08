# M4 — `feat/mcp-client-credential`

## Three questions a senior engineer would ask

**1. "The MCP tools only read today. Why do this now?"**

Because the next tools write, and the checks that keep a person in charge were written as "came
without an API key", which an MCP client's caller also is. Approving a repair or deciding on a
client's request must stay a person's, so the principal now says which credential it came with,
and `in_person` means the web application's own session, nothing else. It is cheaper to fix the
predicate before anything relies on the wrong one.

**2. "Why count an assistant's requests apart from the person's?"**

An assistant can loop. Counted against the person, it would lock them out of their own work; on
a count of its own, against its consent, it holds back only itself, and the organization's
count still bounds them together.

**3. "What does the audit log gain?"**

Accountability: an act through an assistant is the person's, under their consent, but whoever
reads the log must see that an assistant did it, and which, as it sees which key a machine
client used.

## The one concept to explain unaided

**Who acts versus through what**: the person is the actor; the credential is the channel; the
system's rules about who may decide depend on the channel too.

## Supporting facts worth remembering

- Work that outlasts its first check, an upload and its validation, checks the consent again
  before it changes anything, as it checks a key.
- Migration 0018 adds one nullable column to `audit_events`; no event so far changes.
