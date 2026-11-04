# M2 — `feat/api-invoices-store`

## Three questions a senior engineer would ask

**1. "Why keep a 5 MiB document in PostgreSQL rather than in an object store?"**

One transaction stores the document, its report and its listing, and one backup holds them all.
An object store is a second service with its own credential and a second write that no
transaction covers: a crash between the two leaves a row without its file, or a file nobody
references. The free stack has no object store, and a self-hosted deployment would need one.
PostgreSQL stores large values out of line (TOAST), the column is loaded only when the document
is asked for, and the quota bounds the total. The cost is a database that grows with the
documents; the `content` column can move to an object store later without changing the API.

**2. "Two uploads arrive together for an organization at 99 MiB of its 100. What happens?"**

One is stored and the other answers 507. Adding up what the organization stores and inserting
one more is a check-then-act race: without a lock both would find room. Both steps run in one
transaction that first takes an advisory lock for the organization's invoices, so the second
upload waits until the first commits, then sees it. The lock is released with the transaction.
It lives in PostgreSQL's two-key space, which never meets the members' lock, and no path takes
both. A test runs two uploads that add up at the same moment and stores exactly one. And the
quota counts reports with documents, because a small invoice that breaks many rules has a
report many times its size.

**3. "How does a list of thousands of invoices stay correct while people keep uploading?"**

Keyset pagination. A page ends with a cursor naming the time and the id of its last invoice,
and the next page is everything before that pair, newest first. With `offset`, an invoice
stored between two requests would shift every later page by one, showing one invoice twice or
skipping one, and a deep offset makes the database walk the rows it skips. The id breaks ties
of time; a test stores three invoices at the same moment and reads them one per page. The
cursor is opaque base64url, so it travels in a URL unchanged, and a forged one answers 422.

## The one concept to explain unaided

**Authorization within a tenant is a scope in the query.** The organization is the first
condition, and a client's own submissions the second, added to the `WHERE` clause of every
read and delete rather than checked after loading. An invoice outside the scope answers 404, as
another organization's does, so its existence is never confirmed.

## Supporting facts worth remembering

- `POST /invoices` validates as `POST /invoices/validate` does, then stores the document byte
  for byte with the report: 201 and `Location`. An unreadable document is stored with the
  report that says why.
- `GET /invoices` (50 a page, up to 100, no reports), `GET /invoices/{id}` (with the report),
  `GET /invoices/{id}/content` (an attachment with `nosniff`, so a browser never renders a
  hostile document), `DELETE /invoices/{id}`. Every answer is `no-store`.
- `invoices:submit` for every role; `invoices:manage` for owners and accountants widens the
  scope to the whole organization.
- The permission is checked again where the invoice is stored: the upload and the validation
  outlast the first check, and a member removed meanwhile stores nothing.
- `SEF_MAX_STORED_BYTES`, 100 MiB by default; 507 beyond it.
