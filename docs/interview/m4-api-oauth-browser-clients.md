# M4 — `feat/api-oauth-browser-clients`

## Three questions a senior engineer would ask

**1. "You let every origin call your token endpoint. Isn't that CSRF waiting to happen?"**

CSRF borrows the authority a browser attaches by itself: a cookie, a client certificate. These
endpoints read none. A registration grants nothing, a code is worth nothing without the PKCE
verifier only its client knows, and the documents are public. A page of another origin can do
here only what it could do by calling the endpoints from a server of its own, so allowing it in
a browser lends it nothing.

**2. "Why not open the whole API that way?"**

The rest of it is a member's: invoices, repairs, a consent's request. Their tokens travel in a
header, not a cookie, so CORS is not what protects them, but there is no reason for a page of
another origin to read them, and the consent's request in particular must be decided on the
web application's own page. Opening only what an MCP client needs keeps that line visible.

**3. "How do two CORS policies live in one application?"**

One middleware chooses, by the request's path, between two of Starlette's: one for any origin
on the public endpoints, one for the web application's origins on everything else. It stays
outermost, so a preflight is answered before anything runs, and an error carries the headers a
page needs to read it.

## The one concept to explain unaided

**What CORS protects and what it does not**: it decides which pages may read an answer; it does
not authenticate anyone, and it matters only for credentials a browser sends by itself.

## Supporting facts worth remembering

- The MCP Inspector registers, reads the metadata and exchanges codes from the browser, and
  calls the MCP endpoint through its own proxy.
- Without an authorization server (`SEF_PUBLIC_URL`), nothing is open to every origin.
