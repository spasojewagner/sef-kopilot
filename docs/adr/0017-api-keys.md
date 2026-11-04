# 17. API keys: a member's credentials for machine clients, narrowed to the work on invoices

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-keys`
- Amends: [0012](0012-authentication-and-tokens.md), under which the principal is read from an
  access token without the database, and [0013](0013-authorization-and-tenant-isolation.md),
  under which a caller may do what their role grants

## Context and problem statement

ERPs are the API's main machine clients: BizniSoft, Minimax, Pantheon and others would validate
and store invoices for a member every night. Neither credential the API has fits them. A
person's password in an ERP's configuration cannot be narrowed, and every administrator of
that ERP can read it. An access token lasts 15 minutes, and a refresh token belongs to an
interactive session that one replay ends (ADR-0012).

Machine clients need a credential of their own. Five questions were open:

- whose credential a key is, and what happens to it when people come and go;
- what a key may do;
- how it is stored and how it travels;
- how it ends;
- how many there may be.

## Decision drivers

- Least privilege: a leaked key must do as little as possible, and nothing beyond invoices.
- No access outlives a membership (ADR-0013).
- Authorization stays one table and one question, and tenant isolation is tested on every
  endpoint (ADR-0013).
- A key that leaks into code or a document should be found by a secret scanner.
- Boring, explainable choices.

## Considered options

Whose key:

1. **A member's: it acts for the member who issued it, never with more than their role grants
   at the moment of the request, and goes with their membership.** Chosen.
2. The organization's: a service account with permissions of its own, outliving the members.

What a key may hold:

1. **Chosen permissions among the ones for work on invoices, each granted by the member's
   role.** Chosen.
2. Everything the member's role grants.

How it is stored:

1. **The SHA-256 digest of 256 random bits.** Chosen.
2. An argon2id hash, as for passwords.
3. Encrypted, so that it can be shown again.

How it travels:

1. **`Authorization: Bearer`, told from an access token by its `sefk_` prefix.** Chosen.
2. A header of its own, such as `X-API-Key`.

How it ends:

1. **When it is revoked, or at an expiry chosen when it is issued.** Chosen.
2. An expiry for every key.

## Decision outcome

**The key.** `POST /api-keys` issues `sefk_` and 43 characters of base64url: 256 random bits
from `secrets`. It is shown once, in an answer marked `Cache-Control: no-store`. The table
`api_keys` (migration 0005) keeps:

- the key's SHA-256 digest, unique, by which a request finds the key;
- its first 12 characters as `prefix`, by which people tell their keys apart (42 bits of the
  key's 256);
- a name, the permissions, the time of issue, an optional expiry and the time of revocation.

A password needs a slow, salted hash because people choose guessable ones. 256 random bits
cannot be guessed, so the digest needs neither salt nor slowness, as for refresh tokens
(ADR-0012). The prefix also lets a secret scanner recognize a key: a rule in `.gitleaks.toml`
finds one in a commit and in the history, and a test keeps the rule in step with the keys.

**Whose.** A key belongs to a membership: a composite foreign key to `memberships` deletes it
with the membership. Removing a member removes their keys. A person removed and invited back
does not find their old keys working again, which a check of the current membership alone
would allow. A deactivated account's keys answer 401, as its access tokens do.

**What it may do.** `KEY_PERMISSIONS` holds `invoices:validate`, `invoices:submit` and
`invoices:manage`. A key administers no member and issues no key, so a leaked key can neither
let anyone in nor outlive its revocation. When a key is issued, the member's role must grant
each permission asked for (403 otherwise). When it is used, `Principal.may()` answers for every
permission: the member's role at that moment grants it, read from the membership as for an
access token (ADR-0013), and the key holds it. A demoted member's keys lose what the new role
does not grant. The scope of a list of invoices follows the same question: a key without
`invoices:manage` sees its member's invoices only, even an owner's key.

**How it travels.** A client sends `Authorization: Bearer sefk_…`. `current_principal` tells a
key from a JWT by the prefix, finds the key by its digest with the member's role in one query,
and answers 401 for a key that is unknown, revoked or expired. For an API key, then, the
principal is no longer read without the database (amending ADR-0012). Proxies, clients and
loggers already treat the `Authorization` header as secret; a header of its own would have to
be taught to each of them. Storing an invoice outlasts the moment the key was checked, so it
checks again that the key still works, as it checks the membership (ADR-0016).

**Managing keys.** `api_keys:issue`, which every role holds, issues keys for oneself and sees
and revokes one's own. `api_keys:manage`, which only owners hold, sees and revokes every key of
the organization, as a scope in the query (ADR-0016). `GET /api-keys` lists the keys that work,
the newest first, without the keys themselves. `DELETE /api-keys/{id}` stops one at once.
Revoking it again changes nothing and keeps the first revocation's time. A key outside the
scope, or of another organization, is not found.

**How it ends, and how many.** A key works until it is revoked or reaches its optional expiry.
A member has at most 20 keys that work, enough for each ERP and for rotation. Counting them and
issuing one more run under a transaction-level advisory lock on the organization's keys, in the
two-key space with the invoice storage lock (`sef_api.locks`), so concurrent requests cannot
pass the limit (409 beyond it).

**Credentials out of caches.** Every answer that carries a credential now sends
`Cache-Control: no-store`, as RFC 6749 requires: the tokens of registration, sign-in,
accepting an invitation and refreshing, an invitation's code, and a new key. Before this
branch, the token and invitation answers did not.

### Consequences

Good:

- A leaked key is narrow: work on invoices, for one member of one organization, never beyond
  the member's role. Scanners recognize it, and an owner sees and revokes it.
- Offboarding needs no extra step: removing a member removes their keys.
- Authorization is still one question, `may()`. `require()` asks it, and so do the scopes of
  invoices and keys.
- Rotation without downtime: issue a second key, switch the client over, revoke the first.

Bad / accepted:

- An integration stops when the member it acts for leaves. Its keys are best issued by an
  owner. A service account is the option to revisit if this hurts.
- A key without an expiry lives until it is revoked. The list shows how old each key is.
- When each key was last used is not recorded yet, so an owner cannot tell an idle key from a
  busy one. That comes with the security event log (`SECURITY.md`, V16).
- A request with a key costs one indexed lookup more than one with an access token.
- A demoted member's keys keep the permissions they were given and use them again if the
  member is promoted. What a key does is always bounded by the role at that moment.

## Pros and cons of the options

### The organization's key

- Good: an integration outlives the person who set it up (Stripe's model).
- Bad: an employee who leaves with a copy of the key keeps access until someone remembers to
  revoke it. It also needs a second kind of principal with permissions of its own, invoices
  stored by a key rather than a person, and a scope for what a key submitted.

### Everything the role grants

- Bad: an owner's key could invite people and issue keys, so a leaked one would become a
  takeover of the organization.

### An argon2id hash

- Good: the right choice for passwords, which people choose and attackers guess.
- Bad: 256 random bits cannot be guessed, so slowness buys nothing. It would cost about 50 ms
  and 19 MiB on every request, and finding the row would need a key id beside the secret.

### Encrypted keys

- Bad: a leaked database and its encryption key would reveal every key, and nothing needs a
  key back.

### A header of its own

- Good: explicit.
- Bad: one more header for every proxy and logger to redact, and two ways to authenticate
  where one does.

### An expiry for every key

- Good: forgotten keys die on their own.
- Bad: machine credentials that expire break integrations at night. Until use is recorded, an
  owner cannot tell a forgotten key from a busy one. An expiry is offered per key instead.
