# M4 — `feat/api-key-last-used`

## Three questions a senior engineer would ask

**1. "A write on every request with a key? On a GET?"**

At most one a minute per key. The update carries its own condition, `last_used_at` empty or
older than a minute, so a machine that sends a request a second costs one write a minute, and
two requests at the same moment write once: PostgreSQL makes the second wait on the row and
read it again, and the condition no longer holds. The minute is the precision promised, and
enough for the question it answers, "which of my keys still serve a machine?".

**2. "Why commit inside authentication?"**

Because a request that only reads ends without a commit, and its session's work would be rolled
back with the time it noted. Noting the use is the request's first work, so committing it on
its own commits nothing else, and whatever the request does next, the use stands.

**3. "Why log the use only when the time is written?"**

The event and the column say the same thing at the same precision: one line a minute per key
in use, not one per request, which would drown the other security events. Whoever needs every
request has the access log, which names the request.

## The one concept to explain unaided

**Conditional update as a rate limit**: let the `WHERE` of a single statement decide whether to
write, so that concurrency and throttling are handled by the database's row lock, not by code
that reads then writes.

## Supporting facts worth remembering

- A refused key, revoked or expired, notes nothing; the routes and the MCP endpoint note alike.
- Migration 0019 adds one nullable column; undoing it forgets when the keys were used.
