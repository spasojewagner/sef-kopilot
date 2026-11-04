# M2 — `feat/api-settings-database`

## Three questions a senior engineer would ask

**1. "Why not run the tests on SQLite? It would be faster."**

Because SQLite is not the database the product runs on. CHECK and cascade behaviour, transactional
DDL, `gen_random_uuid()`, time zones, and later pgvector and `pg_trgm`, all differ or do not exist.
Tests would pass where production fails. The suite instead creates a database of its own on a real
PostgreSQL 16 (Docker locally, a service container in CI), migrates it once, and rolls each test
back with savepoints, so the code under test can still commit. The whole API suite runs in a few
seconds.

**2. "How do you make sure one organization never sees another's data?"**

One rule and one test pattern. Every table that holds a tenant's data has `organization_id`, a
foreign key and an index that begins with it. Every query goes through the service layer, which
filters by the caller's organization, and every endpoint gets a test in which a member of another
organization makes the same request. People are global and join organizations through
memberships, because an accountant works for several companies. Row-level security in PostgreSQL
was considered and deferred: with a connection pool, each transaction would have to set the
tenant, and nothing worth protecting is stored yet. It stays an option as a second line.

**3. "How do you know the migrations match the models and can be undone?"**

The tests prove both. They apply every migration to an empty database and run `alembic check`,
which fails if the models describe a different schema. They undo everything and apply it again,
and undo each step on its own. CI also runs `upgrade head`, `downgrade -1` and `upgrade head` from
the command line. Constraint names come from a naming convention, so a later migration can address
them on every database.

## The one concept to explain unaided

**A migration is code that runs once against data you cannot recreate.** That is why it is
reviewed like code, written with an exact way back, tested in both directions, never edited after
it has run, and, for a change without downtime, split into expand and contract steps.

## Supporting facts worth remembering

- Settings: pydantic-settings, `DATABASE_URL` as `SecretStr`, required in production, never echoed
  by a validation error.
- One engine per application (`pool_pre_ping` for Neon), one session per request, explicit commits.
- `/ready` answers 503 when `SELECT 1` does not return within two seconds.
- Revision ids `0001`, `0002`, …; enumerations as VARCHAR with CHECK; UUID keys; `timestamptz`.
