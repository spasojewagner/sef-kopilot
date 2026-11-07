# M4 — `feat/api-invoice-retention`

## Three questions a senior engineer would ask

**1. "Serbian law keeps invoices for ten years. How can you delete them?"**

Because SEF Kopilot is not where the law keeps them. Article 15 of the Law on Electronic
Invoicing keeps a private-sector e-invoice for ten years from the end of the year of issue, in
SEF or with an information intermediary engaged to keep it, and a public-sector one permanently
in SEF. SEF Kopilot checks and repairs an invoice before it is sent; what it stores are working
copies. That is why each organization chooses how long to keep them, and why the default is to
keep them: nothing goes unless an owner decided it. Archiving as an intermediary would be another
product, with the integrity duties that article sets.

**2. "Two owners: one demotes the other while the other shortens the period. What happens?"**

The change of the period takes the organization's lock, the one every change of its members
takes, and checks the caller's role again once it holds it. Either the demotion commits first,
and the check under the lock refuses the change (403), or the change commits first, made by
someone who was an owner when it was made. A test holds the request at the lock while the
demotion happens, and the period stays as it was.

**3. "How does the deletion avoid reading every invoice?"**

It compares the time of storing alone with now less the organization's period, so the index the
list of invoices already has, organization then time of storing, finds the old invoices of each
organization with a period and reads none of the others. Written as `created_at + period < now`,
the same condition hides the column inside an expression, and PostgreSQL reads every invoice of
the organization to filter them; the plan shows the difference.

## The one concept to explain unaided

**Check, lock, check again**: a permission checked before a lock can be stale by the time the
change is made, so a change that matters takes the lock that the competing change takes, and
checks once more while it holds it. The first check spares the lock to callers who would fail
anyway.

## Supporting facts worth remembering

- `invoice_retention_days`: 1 to 3 650 days, empty by default; it counts from when the invoice was
  stored.
- `PATCH /organization` follows merge-patch: a value sets, `null` removes, an absent field keeps.
- The audit event `organization.retention_set` holds what the period was and what it became.
- An invoice goes with its repairs; the audit log keeps its events, which name it by id.
