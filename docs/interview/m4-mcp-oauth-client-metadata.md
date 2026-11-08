# M4 — `feat/mcp-oauth-client-metadata`

## Three questions a senior engineer would ask

**1. "Your server now fetches URLs that strangers send it. How do you stop it reaching your own
network?"**

Every address the host resolves to must be on the public internet, and the request goes to the
address that was checked, with the host's name for TLS, so a name that resolves elsewhere a
moment later (DNS rebinding) changes nothing. No redirect is followed, the answer is bounded in
time and size and asked for uncompressed, and the requests that cause a fetch are counted by
address. Before all that, fetching is off unless the operator turns it on: a self-hosted
deployment calls out to nothing it did not choose.

**2. "The draft lets you cache documents. Why fetch at every authorization?"**

An authorization is rare and paced by a person, so a cache saves almost nothing, and it would
have to be bounded, shared or not between instances, and invalidated. Fetching each time keeps
the client as its document says now; the row in `oauth_clients` is only what the consent and
the token exchange read afterwards.

**3. "What stops a document client from pretending to be Claude?"**

Nothing in the document itself: the name is the client's to choose. What a person can trust is
the host that published the document, since the server fetched it from there over TLS. So the
consent page shows the name as unchecked, the host it will send them back to, and, next, the
host of the `client_id`.

## The one concept to explain unaided

**Server-side request forgery and DNS rebinding**: why checking a URL's host is not enough, and
why the connection must go to the address that was checked.

## Supporting facts worth remembering

- A client known by a document needs no registration; its `client_id` is the document's URL,
  which the document must repeat exactly.
- The server's metadata says whether documents are fetched
  (`client_id_metadata_document_supported`), so a client knows whether to register instead.
- Clients of today register themselves either way (RFC 7591); documents are the revision's
  preferred way, not the only one.
