# 16. Stored invoices: the document and its report in PostgreSQL, seen by organization and submitter, within a quota

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-invoices-store`

## Context and problem statement

`POST /invoices/validate` keeps nothing (ADR-0015). The layers to come work on invoices that
stay: an explanation is asked for later, a repair is approved later, an invoice is sent to SEF
later. An organization therefore has to keep the invoices its members submit. Several things
were open:

- where the documents live and what is kept with each;
- who in an organization sees which invoice;
- how a list of thousands is read;
- what stops one tenant from filling a database of 512 MB;
- and what deleting means.

## Decision drivers

- Tenant isolation is tested on every endpoint (ADR-0013).
- An invoice is a legal document, and SEF must receive the bytes that were checked: it is kept
  byte for byte.
- One verdict: what is stored is the validator's own report (ADR-0008).
- The validation endpoint's limits, child process and logging rules apply unchanged.
- Free tiers: Neon's PostgreSQL has 512 MB, and there is no object store in the stack.
- Boring, explainable choices.

## Considered options

Where the documents live:

1. **In PostgreSQL, as `bytea` beside the report (JSONB) and a few columns for listing.**
   Chosen.
2. An object store (S3, Cloudflare R2) for the documents, and their metadata in PostgreSQL.
3. The report only, without the document.

Who sees which invoice:

1. **Owners and accountants every invoice of the organization (`invoices:manage`); a client
   the ones they submitted (`invoices:submit`).** Chosen.
2. Every member every invoice of the organization.

How a list is read:

1. **Newest first, a page at a time, continued from an opaque cursor that names the time and
   the id of the last invoice of the page before (keyset pagination).** Chosen.
2. `limit` and `offset`.

What bounds what a tenant stores:

1. **A quota per organization in bytes, documents and reports together, checked under an
   advisory lock.** Chosen.
2. A number of invoices per organization.
3. The bytes of the documents only.
4. Nothing until rate limits arrive.

## Decision outcome

**The table.** `invoices` (migration 0004) holds, per row:

- the organization and the member who submitted it (forgotten if their account is deleted);
- the time it was stored;
- the profile and the validator's report (JSONB) with its size in bytes;
- the document (`bytea`, loaded only when asked for), its size and its SHA-256 digest;
- what the validator read, for listing: the document type, number, issue date, currency,
  seller, buyer and amount due. All are empty when the validator could not read an invoice,
  and a constraint keeps the number, date and amount together.

An index on the organization, the time and the id serves every list without sorting.

**Storing.** `POST /invoices` validates the body as `POST /invoices/validate` does, with the
same limits, and stores the document with the report: 201 with the stored invoice, and
`Location` names it. A document the validator cannot read is stored too, with the report that
says why: the report is the answer, not an error. With its report, the validator's child sends
a summary of what it read from a schema-valid invoice, each text cut at 200 characters, so
that no document makes a list large. The upload and the validation outlast the transaction in
which the permission was checked, so the permission is checked again in the one that stores
the invoice.

**Who sees what.** Every endpoint requires `invoices:submit`, which every role holds. What a
caller then sees is a scope: the whole organization with `invoices:manage` (owners and
accountants), otherwise the invoices they submitted, so that the clients of an accounting
office do not see each other's. An invoice outside the scope answers 404, as one of another
organization does: its existence is not confirmed.

**Reading.** `GET /invoices` lists up to 100 invoices a page (50 by default), newest first,
without their reports; the page's `next` continues it with `?after=`. The cursor is the time
and the id of the last invoice, base64url-encoded so that it travels in a URL as it is, and
the next page is everything before it in that order. `GET /invoices/{id}` adds the report.
`GET /invoices/{id}/content` returns the document byte for byte as an attachment, with
`X-Content-Type-Options: nosniff`, so that a browser saves a hostile document instead of
rendering it in the API's origin. Every answer carries `Cache-Control: no-store`.

**The quota.** `SEF_MAX_STORED_BYTES` (100 MiB by default) bounds what one organization
stores, documents and their reports together: a small invoice that breaks many rules has a
report many times its size. Beyond it, `POST /invoices` answers 507 Insufficient Storage,
which RFC 4918 defines for a server unable to store what a request needs, and which OneDrive's
API answers when a storage quota is reached. Adding up and storing
happen under a transaction-level advisory lock on the organization's invoices, in
PostgreSQL's two-key space, which never meets the single key of the members' lock (ADR-0013),
so concurrent uploads cannot overshoot. Validating without storing is not counted.

**Deleting.** `DELETE /invoices/{id}` removes the row, the document and the report with it,
within the same scope as reading, and the quota makes room at once.

### Consequences

Good:

- One transaction stores the document, its report and its listing; one backup holds them all,
  and there is no second service to keep consistent with the database.
- A list reads neither documents nor reports, and its pages neither shift nor repeat when
  invoices are stored meanwhile.
- Isolation within the tenant is a scope in the queries, tested for every role, beside the
  cross-tenant case of every endpoint.
- No tenant can fill the database, whatever it uploads.

Bad / accepted:

- Documents of up to 5 MiB in rows make the database and its backups grow with them. An object
  store can take the `content` column later without changing the API.
- A stored report is what the validator said when the invoice was stored. Rules change;
  re-validating comes with the repair loop (M3).
- The same document can be stored twice; the digest shows it.
- The quota counts the report as JSON, not PostgreSQL's own size on disk (compression, row
  headers, the index): an approximation, close enough for a budget.
- 507 is a 5xx code: a monitor that counts server errors must leave it out.
- PostgreSQL keeps a deleted row until it is vacuumed, and Neon's point-in-time history keeps
  it until that history expires. There is no retention policy yet (`SECURITY.md`, V14).

## Pros and cons of the options

### An object store for the documents

- Good: the database stays small, and large files are cheap.
- Bad: a second service and a second credential for the self-hosted deployment, and two
  writes to keep consistent without a transaction around them; nothing in the free stack
  provides one.

### The report only

- Bad: the document is the record. Explaining, repairing and sending to SEF all need it.

### Every member every invoice

- Bad: an accounting office's clients would read each other's invoices.

### `limit` and `offset`

- Good: what everyone knows; a page number is easy to show.
- Bad: an invoice stored between two requests shifts every later page by one, so the client
  sees one invoice twice or misses one, and a deep offset makes the database count every row
  it skips.

### A number of invoices

- Bad: one invoice can be 5 MiB, or a 20 KiB invoice with a report of hundreds of KiB; a count
  does not bound bytes.

### The documents' bytes only

- Bad: reports would be stored without bound, as the case above shows.

### Nothing until rate limits

- Bad: a rate limit slows a tenant down but does not stop it; the database would fill anyway,
  only more slowly.
