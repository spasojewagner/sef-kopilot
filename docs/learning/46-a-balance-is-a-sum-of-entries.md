# A balance is a sum of entries

Anything that counts money, or something that stands for it like credits, faces two questions
an auditor will ask: *what is the balance?* and *why is it that?* A single counter answers the
first and can never answer the second. Accountants solved this centuries ago with a ledger.

```
credit_accounts               credit_entries (only ever added)
organization  balance         number  kind     delta  invoice
Primer        23         ◄──  1       opening  +25
                         ◄──  2       spend     −1    3f2c…
                         ◄──  3       spend     −1    9a01…
                              ───────────────────────
                              sum              23   = balance
```

Three rules keep the two in step:

1. **Write both, or neither.** The change of the balance and its entry are one transaction. A
   crash between them leaves neither.
2. **Never edit an entry.** A mistake is corrected by a new entry (a grant, a refund), so the
   history stays true. The balance is a cache of the sum, kept for speed; the entries are the
   truth.
3. **Let the database refuse what must never happen.** `CHECK (balance >= 0)` and a spend
   written as `UPDATE … SET balance = balance - 1 WHERE balance > 0 RETURNING balance`: when
   two requests race for the last credit, the second waits for the first's row lock, then
   finds no row to update, and is refused. No application lock, no read-then-write gap.

Why not compute the balance from the entries every time? You can, and for an audit you should
(the tests assert that the sum equals the balance). But the hot path, storing an invoice, needs
one row it can lock and test in a single statement; summing a growing table under a lock would
get slower with every invoice.

The same shape serves a payment provider later: a purchase is one more kind of entry, written
once per payment (its id unique), and the provider never holds the books.
