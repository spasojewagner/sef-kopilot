# M6 — `feat/web-billing`

## Three questions a senior engineer would ask

**1. "The owner pays on Stripe's page and comes back. When does the page show the credits?"**

When Stripe has told the API, which happens a moment after it sends the owner back: the event
and the redirect are separate. The page cannot know the payment from the redirect alone (anyone
can type `?checkout=paid`), so it only says the payment is on its way and reads the balance
again every five seconds for a minute; the balance comes from the API, which counted the
payment only after verifying Stripe's signed event.

**2. "Why is there no card form?"**

Checkout is hosted by Stripe: the browser goes to Stripe's page with the URL the API got back
from Stripe. No card number ever passes through the web application or the API, which keeps
both out of PCI scope and leaves 3-D Secure and the like to Stripe.

**3. "Who sees what?"**

Whoever may store invoices sees the balance, since storing spends it; only the owner sees the
ledger and the packs, as only the owner may buy (the API enforces both). Where the server does
not count credits, the card is not shown at all: the public demo stays as it was.

## The one concept to explain unaided

**A redirect is not a confirmation**: the return URL is a hint for the user interface; the
truth is the server-to-server event, verified by its signature, and the page reads the state the
server derived from it.

## Supporting facts worth remembering

- Prices come from the API in cents and are formatted with `Intl.NumberFormat` in the visitor's
  language (`€10.00`, `10,00 €`).
- The page reads `?checkout=` from the address with `useSyncExternalStore`, so nothing is read
  on the server and no state is set in an effect.
- 402 on upload: "no credit left", with who can add more.
