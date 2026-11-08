# M5 — `feat/sef-keys`

## Three questions a senior engineer would ask

**1. "You encrypt the key, but the API holds the secret that decrypts it. What does that buy?"**

It protects every copy of the data that is not the running server: a database dump, a backup,
a replica, a support export, a stolen laptop with a snapshot. Each holds tokens that open nothing
without `SEF_FERNET_KEY`, which only the environment has. It does not protect against someone
who controls the running API, and the ADR says so; a vault or a KMS would narrow that further,
at the cost of an external service that a self-hosted deployment would have to reach.

**2. "Fernet has no associated data. Why does that matter here, and what did you do?"**

Without associated data, a token says nothing about where it belongs: copied from Primer's row
into Ogled's, it would open there, and Ogled's invoices would go out under Primer's key. The
message sealed is the organization's id with the key, and opening checks the id against the
row's, so a moved token is refused as unreadable. A test moves one and finds the rotation
refusing to touch anything.

**3. "How do you replace the secret without an outage?"**

`SEF_FERNET_KEY` takes several keys separated by commas, read as a `MultiFernet`: the first
seals, every one opens. Deploy the new key first with the old one after it; run `make
rotate-sef-keys`, which seals every stored token again under the new key in one transaction,
or stops and changes nothing if a token does not open; then remove the old key. At no moment is
a stored key unreadable.

## The one concept to explain unaided

**A secret at rest is two halves kept apart**: the sealed token in the database and the key
that opens it in the environment, authenticated so a changed token does not open, and bound to
its row so a moved one does not either.

## Supporting facts worth remembering

- A CHECK on `sef_keys.token` accepts a Fernet token only (`gAAAAA…`): a bug that stored a key
  in the clear fails at the database.
- FastAPI's 422 repeated what it refused, a password too short included; the API's answer now
  keeps each error's place, reason and limits, and never the value.
- Only an owner signed in sets or removes the key: `organization:manage` is no permission an API
  key or an MCP client may hold.
