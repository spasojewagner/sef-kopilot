# M5 — `feat/api-keys-send-to-sef`

## Three questions a senior engineer would ask

**1. "A key that leaks can now send invoices in the organization's name. Why accept that?"**

Because the ERP is the client that issues invoices all day, and without it the API stops at the
last step of the ERP's work. The risk is bounded on every side: only an owner's or an
accountant's key can hold the permission, and only if they tick it; it sends only invoices the
validator passes, only those the key may see, only to the SEF demo; the audit log names the key
behind each sending; and a revocation, or the member's demotion, stops it on the next request,
because a key allows what its member's role grants at that moment, not when it was issued.

**2. "How do you change a CHECK constraint on a live table, and undo it?"**

Drop the constraint and create it again with the new list, in one migration; PostgreSQL checks
the existing rows when it is created, which all pass since the list only grew. Undoing is the
hard direction: rows may hold the new value, so the downgrade first takes `invoices:send` from
every key and revokes a key that held nothing else, giving it a permission the old list knows
so that the other constraint (at least one permission) holds, then restores the old check. A
test inserts both kinds of key and undoes the migration.

**3. "Why did the MCP tests change who holds the keys?"**

The test that checks each tool's permission issued its keys to the office's client, whose role
grants everything a key could hold until now. Sending is not the client's, so a key of theirs
that holds it still sends nothing: the role bounds the key. The test now issues the accountant's
keys, whose role grants every permission a key may hold, and a separate test shows a client's
key holding the permission and refused.

## The one concept to explain unaided

**A credential's power is the intersection of what it holds and what its owner may do now**:
the key's permissions are chosen at issue, the role is read on every request, and either side
shrinking shrinks the key.

## Supporting facts worth remembering

- Alembic's autogenerate compares tables, columns and indexes, not CHECK constraints; a test
  builds a database from the models and compares the checks PostgreSQL writes back for it with
  the migrated database's.

- The keys page offers sending only to owners and accountants, unticked.
- Migration 0022 is the first to change a CHECK constraint's list; the downgrade moves the data
  before it narrows the check.
