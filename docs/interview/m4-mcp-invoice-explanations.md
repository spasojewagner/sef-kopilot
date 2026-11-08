# M4 — `feat/mcp-invoice-explanations`

## Three questions a senior engineer would ask

**1. "`explain_invoice` writes the explanations it keeps. Why is it marked read-only?"**

Because the hint is about the person's world, and nothing of it changes. What the tool keeps is
what it answered, for the same report: the next call, the route's `GET`, and the web page read
it back, and a new report makes it stale (ADR-0040). A client that reads `readOnlyHint: true`
may call it without asking its person first, which is right for "what is wrong with this
invoice?". It is not idempotent: what could not be explained in time is asked again.
`revalidate_invoices` replaces reports, so it says it writes, although nothing is lost that the
rules of today would not write again.

**2. "Why answer a job, rather than wait for the revalidation to end?"**

An organization may store thousands of invoices (ADR-0019), and a tool call that holds the
connection for minutes is cut by a client's or a proxy's timeout, leaving the assistant unsure
whether anything happened. The job is the route's: the tool starts it, answers its id at once,
and `get_job` reads its progress, as `GET /jobs/{id}` does. A revalidation under way is an
error that names its job, since a tool's caller has no `Location` header to follow.

**3. "How do you keep the tools from drifting from the routes?"**

The logic moved out of the route bodies into `explain_stored` and `start_revalidation`, which
both call, in a commit of its own that changes no behaviour. The tests then read one invoice's
explanations by the tool and by the route and ask that the answers be equal, the model asked
once; and they read one job both ways.

## The one concept to explain unaided

**Long work behind a short call**: start the work, answer an id at once, and let the caller read
where it is; the work survives the call, and the caller is never left guessing.

## Supporting facts worth remembering

- A kept explanation is read without the language model, so a server without one still answers
  what it kept, and says so for the rest.
- A job's scope is fixed when it starts: a member's revalidation takes on what they submitted,
  whoever reads its progress later.
