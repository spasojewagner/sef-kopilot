# M2 — `feat/api-invoices-by-verdict`

## Three questions a senior engineer would ask

**1. "Why a partial index, and not `valid` added to the index you already have?"**

Because the query looks for few rows. After a revalidation the interesting invoices are the
invalid ones, a handful among thousands. `(organization_id, created_at, id) WHERE NOT valid`
holds only them: small, and every entry it reads is one the listing returns. A composite
`(organization_id, valid, created_at, id)` would hold every invoice again, as large as the
existing index, to serve a query that wants a few rows. The valid ones need nothing new: they
are most of the rows, and the existing index with a filter that almost always passes finds a
page of them at once.

**2. "The migration builds the index `CONCURRENTLY`. What can go wrong with that?"**

It cannot run inside a transaction, so Alembic's `autocommit_block` commits the migrations
before it first. It scans the table twice and waits for the transactions open on it, so it
takes longer than a plain build, but it holds no writes back, which on the invoices table is
the point. And it can fail half-way (a deadlock, a cancelled session), leaving the index
behind marked invalid: still updated on every write, never used to read. The upgrade drops
whatever an earlier attempt left before it builds, and the downgrade drops it concurrently too.
The tables are small today; the habit is for the day they are not (learning note 06).

**3. "Does it matter how the filter is written, `valid = false` or `valid = $1`?"**

Yes. The planner uses a partial index only if it can prove, while planning, that the query's
predicate implies the index's. `valid = false` is a constant and simplifies to `NOT valid`. A
parameter is known in a custom plan but not in a generic one, and asyncpg prepares and caches
statements: after five executions PostgreSQL may keep a generic plan, which could no longer use
the index. SQLAlchemy writes a comparison with Python's `False` as the constant, and a test
checks both the statement's text and that its plan reads the index.

## The one concept to explain unaided

**A partial index serves only the queries that imply its predicate.** It holds the rows a
`WHERE` selects; the planner must prove the query's conditions imply that `WHERE` at planning
time, so the predicate belongs in the statement as a constant, not as a parameter.

## Supporting facts worth remembering

- `GET /invoices?valid=false|true`: a filter on the verdict of the latest report, with the
  same keyset pages; the cursor is a position in time, so it continues a filtered list as it
  would the whole one. A client still sees only what they submitted.
- Migration 0009: `ix_invoices_invalid_organization_id_created_at_id`, built and dropped
  `CONCURRENTLY` inside `autocommit_block`.
- The test seeds 40 invoices, 4 invalid, drops the listing's other index inside its own
  transaction and turns sequential scans off, so that the plan reads the partial index exactly
  when the planner may; `EXPLAIN` of the listing's own statement names it.
- `alembic check` compares an index's name and columns with the model's, not its predicate: a
  test compares the model's `WHERE` with the database's, and another undoes 0009 and looks for
  the index, which the upgrade's "drop what a failed attempt left" would otherwise hide.
- Retention of stored invoices and deleting finished jobs are split off: how long accounting
  documents are kept is a legal decision for the maintainer.
