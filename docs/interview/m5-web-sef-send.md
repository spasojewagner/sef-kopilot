# M5 — `feat/web-sef-send`

## Three questions a senior engineer would ask

**1. "The browser times out while the API is still talking to SEF. What does the person see?"**

That no answer came, and the list of sendings read again. The request may take up to two
minutes, since the API tries SEF three times, and the page waits that long; if the answer is
lost anyway, the submission the API committed before asking SEF is there, `unconfirmed` or
already answered, and the page shows it. Sending again is safe: the same submission's id is the
request id SEF sees, so SEF imports the invoice once.

**2. "How does the page learn the buyer rejected the invoice?"**

The API asks SEF where each imported invoice stands, every minute at first, less often as it
ages, until SEF calls it final (ADR-0051). The page reads the API's list again every half a
minute while the latest submission is imported, not final and less than thirty days old, the
same window the API watches, and stops otherwise. The page never asks SEF itself.

**3. "Why a second press for sending, and not for uploading?"**

Uploading keeps the invoice in the organization's own store, where a member can delete it.
Sending gives it to SEF in the organization's name, where the buyer sees it and only SEF's own
cancellation takes it back. The second press names the invoice and the organization, so the
person knows exactly what leaves and in whose name.

## The one concept to explain unaided

**Polling with a stop condition that mirrors the server's**: the page reads again only while
the server is still learning something new, using the same rule the server uses to stop.

## Supporting facts worth remembering

- A refusal names its reason (`invalid`, `no-key`, `sent`, `unconfirmed`, `changed`), and the
  page reads again what that reason concerns.
- The organization's key is read only for a valid invoice, and only for a member who may send.
- The hook that reads the visitor's role moved to `hooks/use-identity.ts`, unchanged, in a
  commit of its own.
