# Keeping a tenant's data: scopes, pages and quotas

Any API that keeps things for its users has to answer three questions, well or badly: who sees
which thing, how a long list is read, and what stops one user from filling the disk.

## Who sees what: a scope in the query

Isolating tenants means an `organization_id` condition on every query (note 08). Within a
tenant there can be ownership too. Here, a client of an accounting office sees only the invoices
they submitted, while the office's accountants see all of them.

- Express it as a **scope**: a condition added to the `WHERE` clause of every read and every
  delete. Do not load the row and check it afterwards; one forgotten check is a leak.
- Outside the scope the answer is **404, not 403**. A 403 would confirm that the invoice
  exists.
- Test it per role, beside the cross-tenant case: a client asks for the accountant's invoice
  and finds nothing.

## Pages: keyset, not offset

```text
offset:  page 1 = rows 1–50 · a new invoice arrives · page 2 = rows 51–100, which now
         begins with the old row 50: one invoice twice
keyset:  page 1 ends at (time₅₀, id₅₀) · page 2 = the rows before (time₅₀, id₅₀): nothing
         repeats, nothing is skipped
```

- Order by `created_at DESC, id DESC`, and continue with
  `WHERE (created_at, id) < (:time, :id)`. The id breaks ties, since two invoices can share a
  time; without it, a page that ends inside a tie loses the rest of it.
- An index on `(organization_id, created_at, id)` serves every page, however deep. An
  `OFFSET 10000` makes the database walk 10 000 rows to throw them away.
- Hand the client an **opaque cursor**: here base64url of the time and the id, so that it
  travels in a URL as it is. Validate it on the way in, and refuse a forged one (422).
- The trade-off: there is no "jump to page 7". Feeds and invoice lists rarely need one.

## Quotas: count what you store, and count it atomically

- Count **bytes, not items**. A 20 KiB invoice that breaks every rule can have a report many
  times its size, so the quota counts the documents and their reports together.
- **Check, then insert** is a race. Two uploads both add up 99 MiB, both find room, and both
  store. A transaction-level **advisory lock** per organization makes the two steps one: the
  second upload waits until the first commits, then sees it. The lock goes away with the
  transaction.
- PostgreSQL has two key spaces for advisory locks, one 64-bit key or two 32-bit keys, and they
  never meet. That is how this lock stays apart from the members' lock of note 08.
- Past the quota nothing is stored (507 here), and deleting makes room at once.

## In this repository

- `apps/api/src/sef_api/invoices/store.py`: the scope, the pages and the quota;
  `locks.py`: both advisory locks.
- `apps/api/tests/test_invoices_read.py`: pages, ties, forged cursors and the client's scope.
  `test_invoices_store.py`: the quota, and two uploads racing for the last room.
- The decisions are recorded in ADR-0016.
