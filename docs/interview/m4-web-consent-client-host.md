# M4 — `feat/web-consent-client-host`

## Three questions a senior engineer would ask

**1. "The page already shows the client's name. Why the host as well?"**

The name is what the client says of itself: anyone can publish a document that calls itself
Claude. The host is what the server checked, since it fetched the description from there, over
TLS, with that host's certificate. Whoever runs the host stands behind the client, so a person
who reads "Claude", published at a domain they have never heard of, can tell something is off.
The metadata document draft asks for exactly this (§6.4).

**2. "Why work the host out in the browser, rather than have the API send it?"**

A document client's `client_id` is the document's URL, so the host is in it, and the API sends
the `client_id` already. The page derives it as it derives the host of the redirect URI: one
source of truth, no field to keep in step, no change to the API.

**3. "And a client that registered itself?"**

Its `client_id` is random, made by the server, so no one published anything to show. Its name
stays marked as unchecked, and the host it sends the person back to is the clue the page gives.

## The one concept to explain unaided

**A claim and a proof**: a name a client asserts versus a host the server read it from; a
consent screen shows both, and says which is which.

## Supporting facts worth remembering

- The host shown is the URL's host and port, as the browser parses it: what a person can check
  in an address bar.
- Nothing changes for registered clients: they have no publisher, and the page says nothing of
  one.
