# 45. A client's metadata document is fetched only where the operator allows it, at each authorization

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M4)
- Technical story: milestone M4, branch `feat/mcp-oauth-client-metadata`; the authorization
  server of ADR-0044, whose last step this is; the guardrail that a self-hosted deployment calls
  out to nothing but its language model's provider

## Context and problem statement

The MCP revision prefers a way for a client to introduce itself that needs no registration: its
`client_id` is an `https` URL, and the document at that URL describes it, with its name and its
redirect URIs (OAuth Client ID Metadata Document, draft-ietf-oauth-client-id-metadata-document).
The authorization server fetches the document when a client asks for an authorization. That is
a request to an address a stranger chose, from inside the server's network: the server-side
request forgery the draft warns about. And a self-hosted deployment of SEF Kopilot promises to
call out to nothing but its language model's provider. When, how and how safely should the
server fetch a client's document?

## Decision drivers

- The self-hosted guardrail holds by default: no outbound request the operator did not choose.
- No request to the server's own network, whatever the URL's host resolves to, now or a moment
  later.
- A person sees who vouches for a client: the host that published its document.
- Little to keep consistent: an authorization is rare and paced by a person.

## Considered options

1. **Fetched at each authorization request, where `SEF_CLIENT_METADATA_DOCUMENTS` allows it,
   pinned to an address checked as public.** Chosen.
2. Fetched and cached as the document's HTTP cache headers say.
3. Dynamic registration alone (RFC 7591), which every client of today also speaks.
4. Fetched only from hosts the operator lists.

## Decision outcome

**Off unless the operator turns it on.** `SEF_CLIENT_METADATA_DOCUMENTS=true` makes the
authorization server fetch documents and say so in its metadata
(`client_id_metadata_document_supported`). Without it, a URL is an unknown `client_id`, and
clients register themselves as before. The demo turns it on.

**Fetched at every authorization request, never cached.** The document read is the client's
row in `oauth_clients`, whose id is the URL: its name and redirect URIs, which the consent and
the token exchange read as they read a registered client's. Fetching again at each request
keeps the row as the document is now, with no cache to bound or invalidate; the draft allows a
server not to cache. Authorization requests are counted by address, so a stranger cannot make
the server fetch at will.

**Fetched as an untrusted address must be.** The `client_id` is `https`, with a path, and with
no user, fragment, query, or `.` or `..` segment. Its host is resolved once, and every address
it resolves to must be public: none on the loopback interface, a private or a link-local
network, or reserved. The request goes to the address that was checked, with the host's name
for TLS and its certificate, so a name that resolves elsewhere a moment later changes nothing.
No redirect is followed. The answer must come within five seconds, be 200, be JSON, and be at
most 5 KiB. Errors are not kept.

**Read as a registration is, and more strictly.** The document's `client_id` must be the URL
exactly; its `client_name` and `redirect_uris` must be there (as MCP asks); the redirect URIs
follow the rules of registration; a secret, or an authentication other than none, is refused,
as every client is public (ADR-0044). A document that will not do stops the authorization
request with 400, since no redirect URI can be trusted.

**The person sees who vouches for the client.** The consent page shows the host of the
`client_id`, which published the document, beside the name the client gives itself, which is
unchecked; a client that can only send the person to their own computer is marked as such, as
before.

### Consequences

Good:

- A self-hosted deployment calls out to nothing it did not choose; the demo speaks the
  revision's preferred registration.
- The fetch cannot reach the server's own network through the URL, a redirect or a second
  resolution of the name.
- No cache: the client is always as its document says now.

Bad / accepted:

- Every authorization request of a document client waits for one fetch, five seconds at most;
  a person waits for the consent page anyway.
- A document's host that is down stops the client's authorizations until it is back, as the
  draft asks.
- Behind a proxy that the operator requires for outbound requests, the fetch, which goes to the
  address it checked, does not use the proxy; such an operator leaves documents off.

## Pros and cons of the options

### Cached by the document's cache headers

- Good: one fetch for many authorizations, as the draft suggests.
- Bad: a cache to bound, keep per instance or share, and invalidate; for requests a person makes
  a few times a month, nothing is saved.

### Dynamic registration alone

- Good: no outbound request at all.
- Bad: the revision deprecates it for clients and servers that meet for the first time; clients
  that prefer documents would get a registration they did not ask for, or none.

### Hosts the operator lists

- Good: a trust policy the draft allows.
- Bad: the hosts of tomorrow's assistants are not known today; the person deciding sees the host
  in any case, and decides.
