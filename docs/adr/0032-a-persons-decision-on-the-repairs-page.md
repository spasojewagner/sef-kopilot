# 32. A person's decision on a repair's page: asked twice, and read again when unknown

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-diff-approve`; the approval and rejection of
  ADR-0024 on the repair's page of ADR-0030

## Context and problem statement

A person approves or rejects a repair, in person and never with an API key (ADR-0024). An
approval applies the patches again, only to the document they were proposed for, and makes the
invoice the document they leave, with its report; the other repairs that waited are superseded.
There is no undoing it from the page: the invoice's old document is gone from it. A rejection
changes nothing but the repair. The repair's page shows what the person decides on (ADR-0030),
and has no way to decide. How does the page take the decision, keep what it shows true
afterwards, and act when it cannot know whether the decision was recorded: the answer did not
come in time, the API could not be reached, or a proxy answered with a failure?

## Decision drivers

- An approval replaces the invoice: it is not made by one stray press.
- The page shows the repair, the invoice and the list as they are after the decision.
- A decision sent twice is refused the second time (409 `decided`), but the person must not be
  told that it failed when it was recorded.
- Rejection, which changes nothing, costs one press.
- Keyboard and screen reader users follow every step.

## Considered options

How an approval is confirmed:

1. **A second press, in place, under a sentence that says what it does.** Chosen.
2. A modal dialog.
3. No confirmation, with an undo.

What the page does when the outcome is unknown:

1. **It reads the repair again, and says to check it before trying again.** Chosen.
2. It offers to try again.
3. It sends the decision again by itself.

## Decision outcome

**The decision** closes a repair's page while the repair waits for one. It says what an approval
does, that the invoice becomes the copy and the other waiting repairs are superseded, and that
the copy is not valid yet when it is not. "Odobri" asks "Odobravate popravku?" in place, with "Da,
odobri" and "Odustani", and the keyboard's focus moves to the question and back. "Odbij" is taken
at once. A repair that changes nothing has nothing to approve: it offers only its rejection,
and says to correct what awaits a person in the invoice itself.

**The cache** learns from the answer, the decided repair, which is put under its key after the
rest is marked stale. An approval marks stale the invoice's key, under which its report,
explanations and repairs are kept, and the list of invoices, whose verdicts may change; a
rejection marks the invoice's list of repairs alone. Nothing is asked again at once: the repair
on screen is the answer, and the rest is read again when a page shows it.

**A refusal** says why, by the conflict's reason (ADR-0031) or the status: decided already,
nothing to approve, the invoice changed since, the patches leave another document, a person
decides in person, not found, too many requests, a busy or absent validator, a full storage
quota. An approval that cannot pass, because the repair changes nothing, the invoice changed or
the patches leave another document, is not offered again; its rejection still is.

**An unknown outcome**, no answer within the minute the page waits, no API, or a 500, 502 or
504, has the repair read again at once, and so does a `decided` refusal. The page then shows the
repair as it stands, decided or still waiting, and says to check it before trying again. It never
sends a decision again by itself.

### Consequences

Good:

- No approval by one press, and no dialog to trap the focus or block the page.
- After a decision every page shows the invoice as it is, with one request saved on the repair's.
- A decision that went through while the page heard nothing is shown as made, not as failed.

Bad / accepted:

- Two presses for an approval every time, the price of a step that cannot be undone here.
- A 500 that came before the decision was recorded reads as unknown too: one more read of the
  repair, which costs a request.
- An approval cannot be undone from the page. The audit log keeps both documents' digests, not the
  old document.

## Pros and cons of the options

### A modal dialog

- Good: the familiar shape of a confirmation.
- Bad: a component and a focus trap to get right, and it hides the diff and the report the
  person is deciding on, at the moment they are deciding.

### No confirmation, with an undo

- Good: one press.
- Bad: an undo needs the old document kept and a way back in the API, which supersedes the other
  repairs as it approves; neither exists, and adding them is a change of the API's model.

### Offer to try again

- Good: simple.
- Bad: a decision that went through would be sent again and refused with 409, and the person
  would see two failures for one success.

### Send the decision again by itself

- Good: no press for the person.
- Bad: the same, without the person knowing; a page should not repeat a write it cannot see.
