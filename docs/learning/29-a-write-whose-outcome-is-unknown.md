# 29. A write whose outcome is unknown: read before you write again

A person approves a repair. The page sends `POST .../approval`, and one of three things comes
back: an answer (the repair, approved), a refusal (409, 507, ...), or nothing that says what
happened. Nothing is the hard case, and it happens in ordinary ways:

```text
the page waits 60 s and gives up      the API may still be validating, then approve
the connection drops                  the request may have arrived, or not
a proxy answers 502 or 504            the API may have answered it with 200
the API fails with 500                after its commit, or before
```

In each of them the decision may have been recorded. The page cannot tell from what it has.

**Two wrong answers.** Saying "it failed, try again" is wrong when the approval went through:
the person presses again, the API refuses with 409 (`decided`), and they see two failures for
one success. Trying again by itself is worse: the same, unseen. Both treat the request as if
it had not happened, which is the one thing the page does not know.

**Read, then decide what to do.** The page asks the API how the repair stands now, which is
safe to ask as often as needed, and shows it. Approved: there is nothing to do, and the page
says so. Still waiting: the person may approve again, and knows what they are doing. A 409
`decided` is read the same way, since someone else may have decided meanwhile.

```ts
onError: (error) => {
  if (uncertain(error) || conflictOf(error) === "decided") {
    void client.invalidateQueries({ queryKey: repairQuery(invoice, id).queryKey, exact: true });
  }
},
```

Invalidating the repair's query marks it stale, and the page that shows it reads it again at
once. The message beside it says to check the state before trying again.

**Why this is enough here.** The decision is safe to send twice, in the sense that matters: the
API approves a repair once, and refuses it after that, so a second send cannot approve twice
or approve the wrong document. An operation that could do harm when repeated, a payment, an
append, needs more: a key the client chooses for the request (an idempotency key), so that the
server can answer a repeat with the first answer. The upload of an invoice is that kind of
write: sent twice, it stores the invoice twice.

The question to ask of any write a page sends: if the answer never comes, how does the page
learn what happened, and what would a second send do?
