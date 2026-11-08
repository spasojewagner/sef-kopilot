# Sending once over a network that loses answers: the request id

A request to SEF can end three ways from where the API stands: SEF answered yes, SEF answered
no, or no answer came. The third is the hard one. A timeout says nothing about whether SEF
imported the invoice; it only says that the answer did not arrive.

```
API ──POST /sales-invoice/ubl?requestId=R──► SEF   imports, answers 200 …
API ◄──────────── (lost) ─────────────────── SEF
API ──POST /sales-invoice/ubl?requestId=R──► SEF   "R again: here is the same invoice"
```

Trying again without care sends the invoice twice: two invoices in SEF, one buyer confused.
Never trying again leaves it unknown. The way out is an **idempotency key**: an id chosen by
the sender, the same on every attempt, that the receiver uses to recognise a request it has
already done. SEF's import takes one, `requestId`.

Three details make it work here:

1. **Commit the id before sending.** The submission row, `unconfirmed`, is committed first,
   and its id is the `requestId`. If the process dies after SEF imported the invoice, the row
   is still there, and the next attempt carries the same id.
2. **One id per version of the document.** A changed invoice is a different request; the
   unconfirmed one must be settled first, or SEF would answer for the old version.
3. **Retry only what is safe to repeat.** A timeout, 429 or 5xx is tried again with the same
   id. A 4xx is SEF's answer, and asking again would get the same answer.

This is "at least once" delivery made "exactly once" in effect: the sender may repeat itself,
and the receiver's memory of the id turns repetition into nothing.

Polling where an invoice stands is the same idea from the other side: a read can be repeated
freely, so each round claims its invoices in a short transaction (`FOR UPDATE SKIP LOCKED`,
marking them asked), talks to SEF outside any transaction, and writes what it heard. Two
workers never ask about one invoice at once, and a database lock is never held across a network
call.
