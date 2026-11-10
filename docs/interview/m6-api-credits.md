# M6 — `feat/api-credits`

## Three questions a senior engineer would ask

**1. "Two requests store an invoice at the same moment with one credit left. What happens?"**

One stores, the other gets 402. The spend is a single statement, `UPDATE credit_accounts SET
balance = balance - 1 WHERE organization_id = … AND balance > 0 RETURNING balance`. The first
takes the row lock and decrements; the second waits for that lock, re-reads the row after the
first commits, finds `balance = 0`, updates nothing and is refused. A CHECK on the column backs
it up. There is no read-then-write gap to race through, and a test proves it with two sessions
that pause between spending and committing.

**2. "Why keep a ledger as well as a balance? Isn't that duplication?"**

The balance answers "how many?" fast, under a lock, on the hot path. The ledger answers "why?":
the opening credits, each spend with the invoice it paid for, each grant. They are written in
one transaction, so the balance is always the sum of the entries, which the tests assert. A
counter alone could never explain a wrong number, and a purchase would have nowhere to be
recorded.

**3. "What does a credit pay for, and why only that?"**

Storing an invoice: that is what the organization keeps, and what costs the operator storage
and the work around it. Validating without storing stays free within its rate limits, so the
validator remains a free tool; explanations and repairs of a stored invoice are part of what was
paid for. One price per invoice is simple to explain on a bill; per-size or per-explanation
prices would be new kinds of entries, not a new design.

## The one concept to explain unaided

**A balance is a sum of entries**: never edit history, write the change and its reason
together, and let the database refuse what must never happen (a negative balance) instead of
checking in application code first.

## Supporting facts worth remembering

- Off by default (`SEF_BILLING=off`) and in the public demo; `credits` turns it on, with
  `SEF_STARTING_CREDITS` (25) for each organization.
- The account is opened lazily, on the first spend or grant; until then `GET /billing` shows the
  starting credits without writing anything.
- `GET /billing` is for whoever may store invoices (an ERP's API key too); the ledger is the
  owner's; `make grant-credits` is the operator's.
