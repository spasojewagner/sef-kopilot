# 50. An organization's SEF key is kept sealed with Fernet, under a key the environment holds

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M5)
- Technical story: milestone M5, branch `feat/sef-keys`; the brief's per-tenant SEF API key
  "stored encrypted (Fernet, key from env), never logged"

## Context and problem statement

Sending an invoice to SEF takes the organization's own API key, which its administrator
generates in SEF's settings and which signs everything sent in the organization's name. The
API sends an invoice when a member asks, and asks SEF about its status later, in the
background, when nobody is there to type the key. So the key must be kept, by a service that
keeps every organization's. How is it kept so that a copy of the database, a backup or a log is
not the organization's key?

## Decision drivers

- A copy of the database alone opens no key; the key never reaches a log, an answer or a report.
- The secret that opens the keys lives in the environment only, and can be replaced.
- Self-hosted: no external service is called, and nothing is paid for.
- Boring cryptography from a maintained library, nothing of our own.
- A token in the wrong place is refused: one organization's key never signs for another.

## Considered options

1. **Fernet (`cryptography`) under `SEF_FERNET_KEY`, the organization's id sealed with the key,
   several keys while it is rotated.** Chosen.
2. PostgreSQL's `pgcrypto`, encrypting in SQL.
3. A key management service or a vault (AWS KMS, HashiCorp Vault).
4. Keep no key: the caller sends it with every request.

## Decision outcome

**Sealed with Fernet.** The key is sealed with Fernet (AES-128 in CBC mode and HMAC-SHA256,
with a random IV and a timestamp) under `SEF_FERNET_KEY`, and the table `sef_keys` keeps the
token, one an organization, with when it was set. The key is read once, from the request that
sets it, as a `SecretStr`; it is answered, logged and reported nowhere, and a body that fails
the checks is refused with what was wrong and without what was sent.

**Bound to its organization.** Fernet authenticates no data beside the message, so a token
copied to another organization's row would open there. The message is the organization's id
with the key, and a token whose id is not its row's is refused as unreadable.

**Rotated without a gap.** `SEF_FERNET_KEY` may hold several keys separated by commas: the
first seals, every one opens (Fernet's `MultiFernet`). To replace the secret, put the new key
first, run `make rotate-sef-keys`, which seals every stored key again under it in one
transaction, then remove the old one. A token that no key opens stops the command, and nothing
is changed.

**Who sets it.** An owner (`organization:manage`), signed in: `PUT /organization/sef-key` sets
or replaces the key and `DELETE` removes it, each under the organization's lock, recorded in the
audit log and logged as a security event, neither with the key. An API key or an MCP client
cannot: neither may hold the permission (ADR-0017). Every member sees whether a key is set, and
since when (`GET /organization`), never the key.

**Off without the secret.** Without `SEF_FERNET_KEY`, setting a key answers 503 and says why;
the rest of the API works as before.

### Consequences

Good:

- A database dump, a backup or a replica holds tokens that open nothing without the
  environment's secret.
- The secret is replaced without a moment in which a stored key cannot be read.
- No external service, no new running part; `cryptography` is already installed with the API,
  through the MCP SDK's `pyjwt[crypto]`, and becomes a declared dependency.

Bad / accepted:

- Anyone who holds both the database and `SEF_FERNET_KEY`, such as the running API itself, opens
  every key: this protects copies of the data, not a compromised server.
- Losing `SEF_FERNET_KEY` loses every stored key; each owner sets theirs again (SEF's own key is
  not lost, only our copy).
- Fernet's AES-128 is not AES-256; its construction is well studied and enough for a token of
  this kind.

## Pros and cons of the options

### `pgcrypto`

- Good: no code of our own around the cipher.
- Bad: the secret travels in every SQL statement, where the database's log and its statistics
  can keep it; the database alone then holds both halves.

### A key management service or a vault

- Good: the secret never sits in the API's environment; access is audited by the service.
- Bad: an external, often paid, service for every self-hosted deployment, which must reach it;
  out of the brief's free tiers.

### Keep no key

- Good: nothing to protect.
- Bad: the status of a sent invoice could not be asked in the background, and every client,
  from an MCP assistant to an ERP, would carry the organization's SEF key.
