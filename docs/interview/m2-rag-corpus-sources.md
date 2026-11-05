# M2 — `fix/rag-corpus-sources`

## Three questions a senior engineer would ask

**1. "Your corpus pins its sources by SHA-256. What do you do when a pin breaks?"**

Find out what changed before touching the pin. Here the text had not changed: the Legal
Information System adds a line ("Преузето са https://pravno-informacioni-sistem.rs") to a text
that is not requested by its own web application, which it tells by the `Referer`. The pins
had been taken in a browser inside that application, so every download from the converter
failed them. The pins now name what a plain client receives, the reader leaves the line out
with the system's other additions, and the Markdown, the part that matters, stayed byte for
byte the same.

**2. "Why not send the `Referer` the server wants?"**

It would have made the converter pass itself off as the system's web application, to be rid
of the system's own credit line. The line costs nothing to drop, and the corpus credits the
source in its manifest and its README anyway.

**3. "How did this get past the tests?"**

The tests read downloaded copies; the digest of a live download is checked only when someone
runs `--fetch`, which the build environment could not reach. That is why the handoff asked
for the live run, and why the backlog has a scheduled job that downloads the sources and
reports a digest that changed.

## The one concept to explain unaided

**A content pin checks bytes, so it is only as good as the request that produced them.** A
server that varies its answer by the request's headers needs the pin taken with the request
the tool itself makes.
