# Alembic migration safety

A migration changes a database that already holds data, often while the previous version of
the code is still running. Code can be redeployed; data cannot. Five rules keep a migration safe.

**1. The migration is the source of truth, not the models.** `alembic revision --autogenerate`
compares the models with a database and drafts a script. It sees a renamed column as a drop and
an add (losing the data), and it knows nothing about data that must move. Read every draft, fix
it, and let a test prove that models and migrations agree (`alembic check` on a freshly migrated
database).

**2. Every step has a way back.** `downgrade()` undoes exactly what `upgrade()` did, and the
tests undo each step and apply it again. When undoing must lose data (dropping a column that has
values), the downgrade is still written and its docstring says so.

**3. Never edit a migration that has run.** Databases that already applied it will not apply it
again, so an edit splits the history in two. Fix forward with a new revision.

**4. Expand, then contract.** To change a schema without downtime:

```text
release n     add the new column (nullable) or table; code writes old and new
backfill      copy existing rows into the new shape, in batches
release n+1   code reads the new shape only
release n+2   drop the old column or table
```

A `NOT NULL` column on a table with rows needs a default or a backfill before the constraint.

**5. Mind the locks.** Most `ALTER TABLE` forms take an exclusive lock for as long as they run.
On a large table, build indexes with `CREATE INDEX CONCURRENTLY` (outside a transaction), and add
constraints as `NOT VALID` first, then `VALIDATE CONSTRAINT`. The tables here are small today;
the habit matters later.

## Names matter

With a naming convention on the metadata every constraint and index gets a deterministic name
(`ck_users_email_lower_case`, `fk_memberships_user_id_users`), so a later migration can drop or
change it by name on every database, and a failing insert names the rule it broke.

## In this repository

Commands in `apps/api/README.md`; the tests in `apps/api/tests/test_migrations.py` check that the
migrations build exactly the models' schema and that every step can be undone; CI also runs
`upgrade head`, `downgrade -1` and `upgrade head` from the command line. Decision: ADR-0011.
