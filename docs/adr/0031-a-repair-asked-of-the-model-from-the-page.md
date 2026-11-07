# 31. A repair asked of the model from the page, and a reason in every conflict

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-repair-suggestion`; the model's repairs of
  ADR-0025 on the pages of ADR-0030

## Context and problem statement

`POST /invoices/{invoice_id}/repairs/suggestion` asks the language model for patches that repair
a stored invoice's fatal violations, checks them, applies them to a copy and keeps the repair
(ADR-0025). The repairs' pages show what is kept (ADR-0030), and nothing asked for one. Each
request spends the model's requests, behind limits per member and per organization, and takes
up to the server's 20 s of rounds, each validated. It can be refused in many ways, and three of
them share a status: 409 when the invoice is valid, when as many of its repairs as allowed wait
for a decision, or when it changed while the patches were applied. The page must answer each
differently, and so must every other client: the first two will not change by asking again, the
third may. The 409's body said why in English prose only. How does a page ask for a repair, and
how does any client tell the refusals apart?

## Decision drivers

- The model's requests are spent on what the visitor asks for, never by the page by itself.
- The visitor is told what the model is sent before anything is sent.
- A refusal says what to do next: wait, decide on the waiting repairs, try again, or nothing.
- Clients other than the page (an ERP, an MCP tool) need the same answer without parsing English.
- The contract stays one the OpenAPI document describes and the web application's types follow.

## Considered options

How a client tells the 409s apart:

1. **A `reason` beside the `detail` in every 409 of the repairs (`RepairConflict`).** Chosen.
2. The page compares the detail's text.
3. A status of its own for each refusal (412, 423, ...).
4. RFC 9457 problem details, with a `type` URI for each.

How the page asks:

1. **A mutation, on the visitor's request, which opens the repair it writes.** Chosen.
2. A query, as the explanations are asked for (ADR-0029).

## Decision outcome

**Every 409 of the repairs** carries `reason`: `nothing-to-repair`, `too-many-waiting`,
`invoice-changed`, `decided`, `changes-nothing` or `outcome-changed`, with the `detail` as before.
The routes raise a `ConflictError` with its reason, and one exception handler answers it, as the
login already answers its 409 with a body of its own (the organizations to choose from). The
OpenAPI document names `RepairConflict` for the four routes, and a test pins them. Other errors
keep their `{"detail"}`: their status already says which they are.

**The page** offers a repair in the repairs' section of a report whose invoice is invalid and is
XML, since patches apply only to XML. It says what the model is sent, the violations, whose
messages may quote the invoice, and the invoice's fields around them, and asks nothing until the
visitor presses "Predloži popravku". The request is a mutation: it creates a repair, and its
answer is that repair. The answer is put in the cache under the repair's key, so that its page
opens at once without asking again, the invoice's list is invalidated, and the page navigates
to the repair, but only if the visitor is still on the report. A failure is never retried by
itself. The page says why and offers to ask again where that could help: not for a valid invoice,
too many waiting repairs, a missing invoice, or a server without a model or a validator (503
without `Retry-After`); with the seconds to wait for 429 and for a busy validator. It waits a
minute before it gives up.

### Consequences

Good:

- Any client acts on a refusal by its reason, and the English stays for people.
- The visitor spends the model's requests only on purpose, and knows what was sent.
- The repair the model writes is on screen as soon as the answer arrives.

Bad / accepted:

- A body that differs by status: a 409 of the repairs has two fields, other errors one. The
  OpenAPI document says which.
- A server without a model and one without a validator read alike to the page: both answer 503
  without `Retry-After`, so the page names both.
- A suggestion whose patches change nothing is kept and waits like any other; the backlog drops
  such patches in the repairer.

## Pros and cons of the options

### The page compares the detail's text

- Good: no change to the API.
- Bad: the detail is prose for people, which may be reworded at any time; every client would
  copy the same comparisons, and break together.

### A status of its own for each refusal

- Good: no body to read.
- Bad: 409 is what each of them is, a conflict with the state of the invoice or the repair;
  other statuses would mean something else to HTTP clients and caches, and there are not six
  fitting ones.

### RFC 9457 problem details

- Good: a standard shape, `type`, `title`, `status`, `detail`, read by generic clients.
- Bad: every error of the API answers `{"detail"}` today, and moving all of them is a change of
  its own; a `reason` now does not prevent it later, where `type` would carry the same code.

### A query, as the explanations

- Good: the same pattern as the explanations, kept by its key.
- Bad: a suggestion creates a repair on the server; a query may run again when its key is asked
  for or the window regains focus, and each run would create another. A mutation runs only when
  called, and its answer is the repair to show.
