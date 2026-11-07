# M3 — `feat/web-diff-approve`

## Three questions a senior engineer would ask

**1. "The approval timed out on the client. What does the page tell the person?"**

That it does not know, and it finds out. A timeout, a dropped connection or a 500, 502 or 504
may come after the API recorded the approval: it validates the copy, commits, and only then
answers. So the page does not say "failed, try again", which would have the person send it
again and see a 409 for a decision that went through. It invalidates the repair's query, which
reads the repair again at once, shows it as it stands, approved or still waiting, and says to
check it before trying again. It never sends the decision again by itself. A `decided` refusal
is read the same way, since someone else may have decided meanwhile.

**2. "After an approval, what in the cache is wrong, and how do you fix it?"**

The approval's answer is the decided repair, so that goes under its key, fresh. What it
changed on the server is the invoice: its document, its report, so its explanations, and its
other repairs, now superseded; and the list of invoices, whose verdicts may change. All of
that is under two keys, the invoice's and the list's, which the page marks stale with
`refetchType: "none"`: nothing is read again while the repair's page shows the answer, and
each is read when a page shows it. The order matters: invalidate first, then write the
answer, or the answer would be marked stale too. A rejection changes the invoice's list of
repairs alone.

**3. "Why a second press for approval, and not a dialog?"**

An approval replaces the invoice's document and cannot be undone from the page; a second press
under a sentence that says so stops a stray click. A modal dialog would do the same at the cost
of a focus trap to get right and of hiding the diff and the report the person is deciding on,
at the moment they decide. In place, the keyboard's focus moves to the question and back when
it is cancelled. A rejection changes nothing and takes one press. An approval that can never
pass, because the repair changes nothing or the invoice changed since, is not offered again.

## The one concept to explain unaided

**When a write's answer does not come, read before you write again.** The decision may have been
recorded; the page asks how things stand, shows it, and leaves the next press to the person.

## Supporting facts worth remembering

- `POST /invoices/{invoice_id}/repairs/{repair_id}/approval` and `.../rejection`, in person only
  (403 with an API key); an approval answers 409 with `decided`, `changes-nothing`,
  `invoice-changed` or `outcome-changed`, 507 past the storage quota, 503 when the validator is
  busy (with `Retry-After`) or absent. The page waits 60 s.
- The approval's audit event keeps the old and the new document's digests, not the old document.
- A repair that changes nothing (its patches all wait for a person) offers only its rejection;
  the person corrects those fields in the invoice itself.
- Checked in a browser against the API: the approval after the second press, the report valid
  afterwards, the other repair superseded, the list's verdict changed, a rejection leaving the
  invoice as it was, and a repair that changes nothing offering only its rejection.
