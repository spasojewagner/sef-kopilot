# M2 — `feat/api-invoices-validate`

## Three questions a senior engineer would ask

**1. "How do you stop someone from sending a 2 GB invoice, or an XML bomb?"**

In layers.

- **Size.** The bytes are counted while the body is read. A declared `Content-Length` over the
  limit answers 413 at once. Otherwise the chunks are added up, and the request stops with 413
  as soon as it passes 5 MiB, so a chunked or lying client is never held in memory whole.
- **Speed.** A body that does not arrive within 30 s answers 408.
- **Content.** The content goes to a parser that refuses what invoices never need: DTDs,
  entities and network access. XXE and the "billion laughs" therefore fail before any
  expansion or file read. Tests pin those settings on the parser itself, and through the API
  they check that the document was refused for its DOCTYPE.

**2. "Your validation once took 73 s for a 600 KiB document. How do you keep one request from
taking the server down?"**

By bounding what one document can cost, at four points:

- **The core.** It was quadratic in our own code; a profile found it, and that is fixed
  (ADR-0014).
- **Elements.** The published rule sets still cost more than linearly per failing element,
  and we cannot change them. So the child first counts elements with a streaming parser and
  refuses more than 20 000.
- **A child process with a time limit.** Saxon holds the GIL, which I measured: a 2 s
  transform stalled the main thread for 1.7 s. So a thread does not protect the event loop,
  and a thread cannot be stopped. Validation runs in a child process, which is killed at 15 s
  and replaced at once. With it, `/health` answered within 5 ms while a validation ran into
  its limit.
- **Admission.** At most eight validations wait or run; the ninth gets 503 with
  `Retry-After`.

The review that found this also found the request holding a database connection through a
slow upload. The transaction now ends right after the permission check.

**3. "What happens to a validation whose request is cancelled?"**

It runs to its end. The API and the child talk over a pipe, one message and one answer at a
time. Had the request's coroutine simply been cancelled while the child worked, the lock would
have passed to the next request with the answer still on its way, and the next request,
perhaps another organization's, would have read it as its own. So a turn runs as a task of
its own, which the request awaits through `asyncio.shield`: a cancelled request leaves it to
wait for the answer, or to kill a child that overruns, before the next document is sent. A
turn still waiting for the lock is cancelled with its request, since it holds nothing. As a
second wall, every message carries a number that the child echoes, and an answer to another
message replaces the child. A test cancels a validation in flight and checks that the next
request gets its own report.

## The one concept to explain unaided

**A request is hostile until proven otherwise, and its cost is part of the attack surface.**

- Limit the body while you read it, not by trusting a header, and give it a deadline.
- Check its type.
- Hand it to a parser that refuses what an attacker needs.
- Bound the work it causes with budgets you can enforce: elements, a time limit in a process
  you can kill, and admission.
- Never write it to a log, nor let native code print it.

## Supporting facts worth remembering

- `POST /invoices/validate?profile=srb|en16931|peppol`, with `Content-Type: application/xml`.
  The answer is the validator's `ValidationReport` with `Cache-Control: no-store`, and nothing
  is stored.
- 413: bytes or elements; 408: too slow; 415: not XML; 422: stopped at the time limit, or rule
  sets that could not be applied; 503: busy (with `Retry-After`) or unavailable; 500: a
  failure, logged by its type.
- About 13 ms per typical invoice over HTTP. The child warms up in 1–3 s, holds about
  210 MiB, and is replaced in about 1.5 s after a kill.
- Every role holds `invoices:validate`.
- The answer is the core's report as it is: the API and the command line can never disagree,
  and OpenAPI documents the report directly. The cost is that a change to the report is a
  change to the API.
