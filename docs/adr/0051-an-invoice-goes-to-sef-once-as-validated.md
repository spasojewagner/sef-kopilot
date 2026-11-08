# 51. An invoice goes to SEF once, as the validator passed it, and is watched until it is final

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M5)
- Technical story: milestone M5, branch `feat/sef-demo-client`; the brief's "nothing leaves
  without a green validator", and the SEF demo round trip: send, then status polling

## Context and problem statement

An organization's invoices can now be sent to SEF's demo environment with its own key
(ADR-0050). SEF's public API, as its OpenAPI document describes it
(`/swagger/public_v1/swagger.json`), imports a UBL invoice with `POST
/api/publicApi/sales-invoice/ubl` and tells where a sales invoice stands with `GET
/api/publicApi/sales-invoice`, each with the key in the header `ApiKey`. Three things must hold
around those two calls: nothing invalid is sent; an invoice is not imported twice when an answer
is lost on the way; and the member learns what became of it, the buyer's decision included,
without asking SEF themselves.

## Decision drivers

- Nothing leaves without a green validator, and what leaves is exactly what was validated.
- An invoice imported once, even when a request is tried again after an answer that never came.
- What SEF answers, which may quote the invoice, reaches the members who may see the invoice,
  and no log.
- A self-hosted deployment calls SEF only for what a member sent.
- No public address needed to hear back from SEF; free tiers; the job runners already there.

## Considered options

1. **Import within the request, the submission committed first with its id as SEF's
   `requestId`, and each imported invoice asked about where the jobs run, less often as it
   ages.** Chosen.
2. The import as a background job, on the `JobRunner`.
3. SEF's subscription to status changes (`/api/publicApi/subscribe`), for SEF to call back.
4. One request a day for each organization's changes (`/api/publicApi/sales-invoice/changes`).

## Decision outcome

**Validated again, sent as validated.** `POST /invoices/{id}/sef` validates the stored document
under SRB-CIUS, whatever profile it was stored under, and refuses (409, `invalid`) unless the
report finds it valid. Under the invoice's lock, the stored digest must still be the one
validated (`changed` otherwise), so a repair approved meanwhile is not sent unvalidated. The
document goes byte for byte, `sendToCir=No` (the demo, not the register of invoices paid from
public funds), `executeValidation=true` (SEF validates it too).

**Once, through a request id.** The submission is committed, `unconfirmed`, before SEF is asked,
and its id is the `requestId`. SEF's answer makes it `imported`, with SEF's ids, or `refused`,
with SEF's words, or with `key` when SEF refused the organization's key. No answer, after the
client's three attempts, leaves it unconfirmed; sending the invoice again asks SEF again with
the same id, so SEF imports it once. An invoice has at most one submission that is unconfirmed
or imported (a partial unique index); an imported invoice is not sent again (`sent`); a refused
one may be, as a new submission, once it is repaired.

**Watched until final.** Where the jobs run, once a minute, the imported invoices that are due are
claimed in a transaction of their own that marks them asked (`FOR UPDATE SKIP LOCKED`, so that
two processes never ask about one), SEF is asked outside any transaction, and its status is
kept, with the buyer's comment. An invoice is due a minute after it was last asked while it was
sent within the hour, every quarter of an hour on its first day, then every six hours, for
thirty days, and no more once SEF calls it final: approved, rejected, cancelled, reversed
(`Storno`) or deleted. A round that fails logs the kind of failure and waits for the next time.

**Who sends.** `invoices:send`, held by owners and accountants; a client submits invoices but
does not send them in the organization's name. No API key or MCP client may yet: each needs its
own step (the key's permissions, the MCP scope and the `send_to_sef_demo` tool).

**What is kept and what is said.** SEF's words, a refusal or a buyer's comment, are kept on the
submission for the members who may see the invoice, answered with `Cache-Control: no-store`, and
deleted with the invoice; a log line names a failure by its kind and status. The audit log
records each sending, with the document's digest, the attempt and the outcome; a security event
says who sent which invoice and how it ended.

### Consequences

Good:

- The member sees SEF's answer in the same request; a lost answer costs a second request,
  never a second invoice in SEF.
- What SEF holds is exactly what the validator passed.
- No callback address, no new service: the inline runner or the workers watch.

Bad / accepted:

- That SEF imports once for a repeated `requestId` is what the published API's parameter is
  for, and is to be confirmed against the demo, with the other open points (`docs/BACKLOG.md`).
- An unconfirmed submission waits for a member to send the invoice again; nothing sends in the
  background in anyone's name.
- Polling costs a request an invoice; a busy organization would rather read the day's changes.

## Pros and cons of the options

### The import as a background job

- Good: a slow SEF never holds a request.
- Bad: SEF answers an import at once; the member would wait for a job and read its result
  instead of the answer, and the job's own attempts would repeat what the request id guards.

### SEF's subscription

- Good: SEF says when something changes; no polling.
- Bad: SEF must reach the API at a public address, which a self-hosted deployment may not have,
  and a notification is for the next day.

### The day's changes for each organization

- Good: one request an organization, however many invoices.
- Bad: a day's grain, every invoice of the organization, not only those sent from here, and a
  state to keep of which days were read.
