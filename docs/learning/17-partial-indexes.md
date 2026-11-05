# Partial indexes: an index of the few rows a query looks for

After a revalidation an organization asks for its invalid invoices: a few among thousands of
valid ones. The listing's index, `(organization_id, created_at, id)`, finds the organization's
invoices newest first, but then reads every valid one on the way to the next invalid one. A
**partial index** holds only the rows a predicate selects:

```sql
CREATE INDEX ix_invoices_invalid_organization_id_created_at_id
    ON invoices (organization_id, created_at, id) WHERE NOT valid;
```

It is as small as the invalid invoices are few, and every entry it reads is one the query wants.

## When the planner may use it

Only when it can **prove** that the query's `WHERE` implies the index's predicate, and it must
prove it while planning:

| The query says | The planner can use the index |
| --- | --- |
| `NOT valid` | yes: the same predicate |
| `valid = false` | yes: a constant, simplified to `NOT valid` |
| `valid = $1` (a parameter) | in a custom plan, made with the value: yes; in a generic plan, made for any value: no |

A prepared statement is planned again for each execution at first, then, after five, it may
keep one generic plan if that is not much costlier. asyncpg prepares and caches statements, so
a predicate that matters to an index belongs in the statement's text. SQLAlchemy writes a
comparison with Python's `False` as `valid = false`, a constant, which is why the listing can
use the index in any plan.

## Why not `(organization_id, valid, created_at, id)`

That index would hold every invoice, valid or not: as large as the table's index already is,
for a query that wants a few rows. The valid ones need no index of their own: they are most of
the rows, and the existing index finds them with a filter that almost always passes.

## Building it without stopping writes

`CREATE INDEX` holds back writes to the table while it builds; `CREATE INDEX CONCURRENTLY` does
not, but scans the table twice, waits for open transactions and cannot run inside a
transaction. A concurrent build that fails leaves the index behind, marked invalid: the
migration drops whatever an earlier attempt left before it builds. Alembic runs such a step in
`op.get_context().autocommit_block()`.

## Checking it

`EXPLAIN` shows which index a plan reads. On a table of a few rows a sequential scan is
cheaper than any index, and which of two indexes wins depends on statistics. The test turns
sequential scans off (`SET LOCAL enable_seqscan = off`) and drops the other index inside its
own transaction, so that the plan reads the partial index exactly when the planner may.

## In this repository

- Migration 0009 and `StoredInvoice.__table_args__`; `store.page_of` filters on `valid`.
- `test_invoices_read.py` checks the statement's predicate and the plan of the listing.
