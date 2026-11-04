# 15. Validating invoices through the API: XML bodies within limits, a child process with a time limit, nothing stored

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-invoices-validate`, stacked on
  `fix/core-hostile-documents` (ADR-0014)

## Context and problem statement

The deterministic validator (`einvoice_core`, ADR-0002 and ADR-0008) runs from the command line;
M2 puts it behind the API, the way an ERP or the web app will call it. Validating is synchronous
CPU work, and an upload is hostile until proven otherwise. Measured on this validator:

- A typical invoice takes about 10 ms once the rule sets are compiled; compiling them takes
  1–3 s, so they must be compiled before the first request.
- Saxon holds Python's global interpreter lock while it applies a rule set: during a 2 s run,
  the main thread stalled for 1.7 s.
- After ADR-0014, the core's own work is linear, but the published rule sets still cost more
  than linearly in the elements that fail them, and they run as published (ADR-0005). An
  invoice of 1700 lines that each break a rule takes about 4 s, 8000 failing references 22 s.
- A process that has compiled every rule set holds about 210 MiB. A document near 20 000
  elements adds 80 MiB, or 210 MiB if every line breaks a rule. The free tier has 512 MB.

The first version of this branch validated in a worker thread. An independent review then
measured one authenticated client stalling every other request, sign-ins included: for 5 s
with one document, and for 42 s with seven at once. A second review of the child process that
replaced it showed that a request cancelled while the child worked left the child's answer in
the pipe, where the next request read it as its own: one organization's report handed to
another. Nothing in the shipped stack cancels a request today, but a timeout around the call,
or a server that cancels on disconnect, would. Still open: how the document travels and how
large it may be, what the answer is, where the work runs and how it is bounded, whether
anything is kept, and who may validate.

## Decision drivers

- An upload is hostile: its size, its type, its XML and the work it causes.
- No request may stall the others, and a runaway validation must be stoppable.
- No request may ever receive another's answer, whatever happens to either.
- One truth: the API's verdict is the validator's, word for word.
- The performance budget: under 500 ms for a typical invoice once warm.
- No invoice content in logs, ever (brief, guardrails).
- A 512 MB free-tier instance; boring, standard HTTP.

## Considered options

1. **The document as the raw request body, within limits on bytes, time and elements; the
   validator's own report as the answer; validation in a child process, one document at a
   time, stopped at a time limit; at most a few validations admitted at once; nothing
   stored; every role allowed.** Chosen.
2. A multipart upload, or JSON with the document in base64.
3. A response schema of the API's own, mapped from the report.
4. Validation on the event loop.
5. Validation in a worker thread (the first version).
6. A process pool (`concurrent.futures.ProcessPoolExecutor`).
7. A job queue (`arq`), answered later by polling or SSE.

## Decision outcome

Option 1. Concretely:

- **The request.** `POST /invoices/validate`. The body is the UBL 2.1 invoice or credit note
  itself, sent as `application/xml` or `text/xml`, parameters such as `charset` allowed; any
  other media type answers 415. `?profile=` chooses `srb` (the default, as SEF validates),
  `en16931` or `peppol`.
- **Bytes and time.** `SEF_MAX_INVOICE_BYTES`, 5 MiB by default, leaves room for an embedded
  PDF. A declared length above it answers 413 before anything is read. Otherwise the body is
  read in chunks and refused with 413 as soon as it passes the limit, so a chunked or lying
  upload is never held whole. A body that has not arrived within `SEF_UPLOAD_SECONDS` (30)
  answers 408.
- **Elements.** Memory and time grow with elements, not bytes: an embedded PDF is one text
  node. Before validating, the child counts the elements with a streaming parser as hardened
  as the validator's, keeping nothing it has counted, and refuses more than
  `SEF_MAX_INVOICE_ELEMENTS` (20 000, some 1500 invoice lines) with 413.
- **Where it runs.** In a child process (`ProcessValidator`), started with the application,
  warmed up with every rule set before it serves, and sent one document at a time over a
  pipe:
  - A validation longer than `SEF_VALIDATION_SECONDS` (15) is stopped by killing the child,
    which is replaced at once; the request answers 422.
  - A child that dies is replaced before the next document; one that cannot start is tried
    again 30 s later, so that a server heals once, say, its rule sets are fetched.
  - A turn, once it has begun, runs to its end in a task of its own, which the request awaits
    through a shield: a cancelled request does not cut it short, so it still waits for the
    answer, or stops a child that overruns, before the next document is sent. A turn still
    waiting for its place is cancelled with its request, since it holds nothing.
  - Every message carries a number, which the child echoes with its answer. An answer to
    another message replaces the child, and the request answers 500.
  - The child's standard streams go to the null device. What goes wrong comes back as a kind
    of outcome that carries no document content: unavailable (503), refused because the rule
    sets could not be applied (422), or failed, by the type of the error only (500).
  - `SEF_VALIDATOR=thread` runs the same work in a thread instead, without a time limit, for
    tests and tools.
- **Admission.** At most `SEF_MAX_VALIDATIONS_IN_FLIGHT` (8) validations wait or run; the next
  answers 503 with `Retry-After: 1`. That is checked before the body is read, and again once
  it is in.
- **The answer.** The validator's `ValidationReport`, the same report the command line prints
  for each file with `--format json`, and documented as such in OpenAPI. A document that
  cannot be read is a 200 with an invalid report, not an error. `Cache-Control: no-store`
  keeps the report out of caches.
- **The database.** The permission check is the request's only database work, and its
  transaction ends before the body is read: neither a slow upload nor a validation waiting
  for its turn holds a pooled connection.
- **Readiness.** `/ready` reports the validator as a dependency and answers 503 while it
  cannot run. The application still starts without it and logs why.
- **Nothing stored.** The document lives in memory for the length of the request. This
  endpoint is the no-store mode; storing invoices comes with `feat/api-invoices-store`.
- **Who.** `invoices:validate`, granted to every role. A client's job is to submit invoices and
  read the results. The endpoint's cross-tenant case checks that a validation leaves no trace
  in any organization.

### Consequences

Good:

- The event loop stays free: `/health` answered within 5 ms while a validation ran into its
  time limit, where the thread version stalled it for seconds.
- A runaway document costs one time limit, not the instance, and memory per validation is
  bounded by the element budget.
- `curl --data-binary @invoice.xml` is the whole client; an ERP needs nothing else.
- The API and the command line can never disagree: one report, one model.
- About 13 ms per typical invoice over HTTP, far inside the budget.

Bad / accepted:

- One child validates one document at a time. Saxon serialises its calls anyway, and more
  throughput means more instances, or the job queue of `feat/api-jobs-sse` for batches.
- The child holds about 210 MiB beside the API; the defaults keep the worst document within
  a 512 MB instance, and an operator with more memory can raise them.
- A stopped validation is followed by about 1.5 s of warm-up for the next child, during which
  the next documents wait their turn.
- The core's report is now part of the API contract: a change to it changes the API.
- A cancelled request's validation still runs to its end, up to the time limit; at most one
  such turn runs at a time, since the others are cancelled while they wait.
- Admission is global, not per client: one member can still fill it, and keep the child busy
  with documents within the element budget that each run into the time limit (8000 empty
  extension elements take 15 s in CEN's rules). Rate limits per client and organization come
  with `feat/api-rate-limits` (`SECURITY.md`).

## Pros and cons of the options

### A multipart upload, or base64 in JSON

- Good: what HTML forms send; one content type for the whole API.
- Bad: a parser for a format the document does not need, or a third more bytes encoded for
  nothing, and the size limit becomes the parser's business.

### A response schema of the API's own

- Good: the API could evolve apart from the core.
- Bad: two models of one verdict that can drift apart.

### Validation on the event loop

- Bad: every request waits while one document is checked.

### A worker thread

- Good: no process to manage; one compiled copy of the rule sets.
- Bad: measured, Saxon holds the GIL, so a large document stalls the event loop anyway, and
  a thread cannot be stopped at a time limit.

### A process pool

- Good: parallel validations.
- Bad: on Python 3.12 a task cannot be stopped without breaking the pool, and every worker
  holds its own 210 MiB of rule sets.

### A job queue

- Good: suits batches and slow work, with progress over SSE.
- Bad: for one invoice in milliseconds, a queue, a worker and a second request are cost
  without benefit; it comes with `feat/api-jobs-sse` for the work that needs it.
