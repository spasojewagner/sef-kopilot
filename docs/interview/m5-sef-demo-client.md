# M5 — `feat/sef-demo-client`

## Three questions a senior engineer would ask

**1. "SEF times out after you sent the invoice. Did it import it? What do you do?"**

We do not know, and we do not guess. The submission was committed, `unconfirmed`, before SEF
was asked, and its id went to SEF as the `requestId`. Sending the invoice again asks SEF with
the same id, which is what the parameter is for: SEF answers for the invoice it already has
instead of importing a second one. A refusal (4xx) is never tried again; a timeout, 429 or 5xx
is, with the same id. Whether SEF's demo honours the id exactly so is on the list of things to
confirm against it.

**2. "How do you guarantee that what reaches SEF is what the validator passed?"**

The document is validated again under SRB-CIUS just before sending, whatever profile it was
stored under, and only a valid report lets it through. Then, under the invoice's row lock, its
stored digest must still be the one validated: a repair approved in between would change it,
and the request is refused as `changed` rather than sending bytes nobody validated. The bytes
sent are the bytes validated, and the audit log records their digest.

**3. "Why poll for the status instead of letting SEF call you?"**

SEF's subscription needs an address SEF can reach, which a self-hosted deployment may not
have, and notifies a day later. Polling one invoice at a time, less often as it ages and never
once SEF calls it final, costs a few requests and needs nothing new: the inline runner or the
workers already run once a minute. Each round claims its invoices with `FOR UPDATE SKIP LOCKED`
in a short transaction and talks to SEF outside it, so two workers never ask about one invoice
and no lock waits on the network.

## The one concept to explain unaided

**An idempotency key turns "at least once" into "exactly once" in effect**: choose the id
before sending, keep it with the attempt, repeat it on every retry, and let the receiver
recognise what it already did.

## Supporting facts worth remembering

- The client follows SEF's own OpenAPI document (`/swagger/public_v1/swagger.json`): the header
  `ApiKey`, `POST /api/publicApi/sales-invoice/ubl`, `GET /api/publicApi/sales-invoice`.
- `sendToCir=No`: the central register of invoices paid from public funds is not for the demo.
- What SEF writes, a refusal or a buyer's comment, may quote the invoice: it is kept for the
  members who may see the invoice, answered with `no-store`, and logged by its kind only.
