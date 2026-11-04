# M2 — `feat/api-keys`

## Three questions a senior engineer would ask

**1. "Passwords get argon2id. Why does an API key get plain SHA-256?"**

A slow, salted hash defends against guessing. People choose passwords from a small space, and
an attacker with a stolen table tries billions of guesses offline; argon2id makes each guess
cost time and memory. A key is 256 random bits from `secrets`, so there is nothing to guess,
even at a trillion tries a second. A fast digest is therefore enough. It needs no salt, and it
is also the lookup: one probe in a unique index. argon2id on every request would cost about
50 ms and 19 MiB, and finding the row would need a key id beside the secret. Refresh tokens and
invitation codes are stored the same way.

**2. "A key belongs to a member, not to the organization. What happens when the member
leaves?"**

The key is deleted with the membership, through a composite foreign key with
`ON DELETE CASCADE`. Offboarding needs no extra step: an employee who copied the key leaves with
nothing that works. The schema also prevents a subtle bug. If keys only checked the membership
when used, a person removed and later invited back would find their old keys working again.
The cost is that an integration stops when the member it acts for leaves, so integration keys
are best issued by an owner. Rotating is issuing a new key before revoking the old one. An
organization-level service account is the option to revisit if this hurts.

**3. "How do you stop a key from doing more than it should?"**

Twice. When a key is issued, it gets chosen permissions, only among those keys may hold (work on
invoices) and only ones the member's role grants. When it is used, every request asks one
question, `may(p)`: the member's role grants `p` now, and the key holds `p`. Demote an
accountant to client and their key loses `invoices:manage` at once. A key cannot invite people
or issue keys, so a leaked one cannot let an accomplice in or survive its own revocation. The
route audit sends every endpoint another organization's key: it finds nothing where keys may
go, and is refused everywhere else.

## The one concept to explain unaided

**What a credential allows is an intersection, computed on every request.** A request with a
key may do what the member's role grants at that moment and the key holds. Each side can only
narrow the other. A role that changed after the key was issued counts at once, and removing the
member removes the key.

## Supporting facts worth remembering

- A key is `sefk_` and 43 characters of base64url; the first 12 are shown as its prefix, and
  the table keeps the SHA-256 digest. A rule in `.gitleaks.toml` recognizes a leaked key.
- `POST /api-keys`: 201 and `no-store`, the key shown once; 403 for a permission the role does
  not grant; 422 for one no key may hold; 409 beyond 20 keys that work.
- `GET /api-keys` lists the keys that work, the newest first, without the keys.
  `DELETE /api-keys/{id}` revokes one at once; revoking it again changes nothing.
- `api_keys:issue` for every role (one's own keys), `api_keys:manage` for owners (every key of
  the organization).
- `Authorization: Bearer`, the prefix telling a key from a JWT; 401 for an unknown, revoked or
  expired key, and for a deactivated account's.
- Storing an invoice checks again that the key still works, as it checks the membership.
- Every answer that carries a credential is `no-store` (RFC 6749). This branch fixed it for the
  tokens and invitation codes as well.
