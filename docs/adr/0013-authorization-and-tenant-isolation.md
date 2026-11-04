# 13. Authorization: permissions per role, checked against the current membership, tenant isolation proven by tests

- Status: accepted; amended by [0017](0017-api-keys.md), under which a caller with an API key
  may do what both the role and the key allow
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-rbac-members`

## Context and problem statement

An organization is the tenant (ADR-0011), and a session belongs to one organization and carries
the person's role there (ADR-0012). The brief asks for the roles owner, accountant and client
with RBAC. Several things are still open. What each role may do, and how an endpoint states
what it needs. How current the role must be when access is decided. How to make sure that no
endpoint reads or changes another organization's data, now and for every endpoint still to
come. How people join an organization when the stack has no mail service. And how the rule that
an organization always has an owner survives two requests at the same moment. API keys for
machine clients follow after the invoice endpoints (`feat/api-keys`).

## Decision drivers

- Broken object-level authorization is the most common API vulnerability (OWASP API Security
  Top 10, API1:2023). The defence has to be built into the structure and checked by tests,
  because remembering it in every endpoint does not scale.
- When an accounting office removes an accountant, the accountant must lose access to its
  clients' data at once, not when a token expires.
- The policy lives in one place; endpoints say what they need, not who may call them.
- No external services: no mail, no policy server.
- Boring, explainable code.

## Considered options

1. **Permissions per role in one table; a `require(permission)` dependency that reads the
   membership from the database; the organization only from the access token; another
   organization's objects answer 404; a route audit and a cross-tenant case for every guarded
   endpoint; invitations as one-time codes; changes to an organization's members and its
   sessions ordered by one advisory lock per organization.** Chosen.
2. Role checks in each endpoint (`if role is not Role.OWNER`).
3. Trust the role in the access token and skip the database.
4. A policy engine (Casbin, OPA, Cedar).
5. PostgreSQL row-level security now.
6. The organization in the path (`/organizations/{id}/members`).
7. Adding existing accounts by e-mail address instead of invitations.
8. Invitation links sent by e-mail.

## Decision outcome

Option 1. Concretely:

- **Permissions.** `Permission` values are named `area:action`. `ROLE_PERMISSIONS` maps every
  role to its permissions and cannot be changed at run time. The owner holds every permission
  there is. An accountant has `members:read`. A client has neither members permission:

  | Permission | owner | accountant | client |
  | --- | :-: | :-: | :-: |
  | `members:read`: see the members and their roles | yes | yes | no |
  | `members:manage`: invite people, change roles, remove members | yes | no | no |

  Later branches add their own permissions (invoices, repairs, sending to SEF, API keys) to the
  same table.
- **Checking.** An endpoint asks with `require(permission)`, one cached dependency per
  permission. Authentication stays free of the database (ADR-0012). Authorization is not: on
  every guarded request, `require()` reads the caller's membership joined with the account,
  which is one primary-key lookup. It answers 401 when the membership or the account has ended,
  and 403 when the role lacks the permission. It then hands the endpoint the role read from the
  database. This amends ADR-0012 for guarded endpoints: a removed member, a deactivated account
  or a changed role takes effect on the next request. The token's role claim is a hint for the
  client. `GET /auth/me` reports the role held now for the same reason.

  An endpoint that changes the members asks with `require(permission, changes_members=True)`.
  A caller who passes the check is then checked once more after the organization is locked
  (see Concurrency), and the endpoint's change runs under that lock, so the role cannot change
  between the check and the change. A caller who fails the first check never takes the lock,
  and an endpoint that only reads, such as the list of invitations, takes none.
- **Tenant scoping.** The organization comes only from the access token. Paths and bodies never
  name it. Every service function takes the caller's organization and filters every query by
  it. An object of another organization is therefore not found (404), never forbidden (403),
  so nothing tells the caller that it exists.
- **Proof by tests.**
  - A route audit reads the application's routes. Every route must be an API route or one of
    FastAPI's documentation pages, so a mounted application or a websocket route fails the
    audit until it is guarded and added to it.
  - Every endpoint must be public by name, open by name to any signed-in caller (`/auth/me`),
    or depend on `require()` as pinned for it in the test's table: with which permission, and
    whether it changes the members.
  - The audit must also see every operation that the OpenAPI document lists, so that a router
    it fails to walk breaks the test instead of letting it pass with nothing to check.
  - For every guarded endpoint, a member whose role lacks the permission is refused (403). A
    cross-tenant case also has the owner of another organization, who holds every permission,
    try the endpoint on this organization's data and find nothing.
  - Most tests share one rolled-back transaction across their requests. The tests about
    commits, locks and concurrency use real sessions that commit, as in production. In them,
    one request is held at a gate so that the other certainly arrives at the wrong moment.
- **Members.** `GET /members` needs `members:read`; changing a role and removing a member need
  `members:manage`. Removing a member revokes their refresh tokens in that organization. An
  organization keeps at least one active owner, so demoting or removing the last one answers 409.
  A deactivated owner cannot act, so it does not count.
- **Concurrency.** One lock per organization orders the work on its members and sessions
  (`sef_api.locks`). It is a transaction-level PostgreSQL advisory lock keyed by the
  organization's id.
  - Changes to the members take it exclusively. These are role changes, removals, and issuing,
    revoking or accepting invitations. They take turns, so two owners who step down at the
    same moment cannot both succeed.
  - Signing in, refreshing and signing out take it shared. They run side by side, but never at
    the same time as a change to the members, so a session renewed while its holder is removed
    is revoked by the removal.
  - PostgreSQL grants advisory locks in the order they were asked for, so a stream of sign-ins
    cannot keep a change waiting: a shared request queues behind an exclusive one that is
    already waiting. Row locks (`FOR SHARE` against `FOR NO KEY UPDATE`) do not queue this
    way, which a test shows.
  - A refresh, a replay or a sign-out then locks every token of its session, ordered by id.
    Two of them in one session take turns instead of deadlocking, and the second one's next
    statement sees what the first wrote. So a sign-out or a replay during a refresh also
    revokes the token that the refresh issued.
  - A token that can do nothing takes no lock: unknown, revoked, or expired before it was
    spent. A former member's old tokens therefore cannot hold the organization up.
  - Every path takes the organization's lock before any row lock and before it changes a row,
    and no path takes it shared first and exclusively later. The locks are therefore always
    taken in the same order.
  - Slow work happens before the lock. In particular, accepting an invitation checks or hashes
    the password first, so a wrong password holds nothing up.
- **Invitations.** `POST /invitations` returns a code once: 256 random bits, valid for seven
  days. The owner passes it on, and only its SHA-256 digest is stored. A partial unique index
  keeps one open invitation per address and organization, and inviting the address again
  replaces it. `POST /auth/accept-invitation` redeems the code once:
  - When the address has no account, it creates one with the given password (12 to 128
    characters).
  - When the address has an account, the password must be that account's, so a code alone
    never opens someone's account.
  - It adds the membership in the invited role, unless the person is a member already, then
    signs the person in to the organization.

  An invitation stops working when the owner who issued it may no longer invite: removing or
  demoting them withdraws their open invitations, and accepting checks the issuer once more
  (which also covers deactivated and deleted accounts). Otherwise an owner who is being
  removed could first invite another address as owner and come back through it.
- **Not yet.**
  - Rate limiting of `accept-invitation`, which shares the `SECURITY.md` item with sign-in.
  - API keys, after the invoice endpoints (`feat/api-keys`).
  - Invitation e-mails.
  - Leaving an organization oneself.
  - Transferring ownership in one step.
  - The required permission in each operation's OpenAPI entry.
  - Row-level security, which waits for invoices (ADR-0011).

### Consequences

Good:

- The policy is one table. A forgotten guard, or a query that forgets the organization, fails
  CI instead of shipping.
- Removal, deactivation and role changes act at once.
- No external service is involved, and no new library.

Bad / accepted:

- One extra indexed query per guarded request. Changes to an organization's members wait for
  the sign-ins and refreshes in progress in that organization, and those wait for the change:
  milliseconds, for rare operations. There is no lock timeout yet: the transactions are short
  and end with their request.
- Advisory locks are invisible to someone reading the schema. `sef_api.locks` and this record
  are where they are explained.
- A departing owner's invitations must be issued again by another owner.
- The owner must pass the code on safely, outside the product. An account created from an
  invitation has an unverified address, as one created by registration does.
- The route audit reads FastAPI's route structure. The OpenAPI cross-check turns a change in
  FastAPI into a failing test rather than a silent pass.

## Pros and cons of the options

### Role checks in each endpoint

- Good: nothing to learn.
- Bad: the policy is scattered; each new endpoint must remember it; API keys with narrower
  scopes would need every check rewritten.

### Trust the role in the token

- Good: no query.
- Bad: a removed accountant keeps reading the office's clients for up to 15 minutes; every
  guarded endpoint reads the database anyway, so the saving is one primary-key lookup.

### A policy engine

- Good: expressive, auditable policies.
- Bad: a new language and a dependency (or a server) for a three-role table; to be reconsidered
  if policies come to depend on attributes, such as one client seeing only its own invoices.

### Row-level security now

- Good: the database itself refuses cross-tenant rows.
- Bad: needs a per-transaction tenant setting and careful pooling; the tables that matter
  (invoices) do not exist yet. The tests above protect today's tables; ADR-0011 keeps RLS on
  the list.

### The organization in the path

- Good: explicit URLs.
- Bad: it repeats what the token already says; every endpoint must then compare the two, and a
  forgotten comparison is exactly the bug this ADR is about.

### Adding existing accounts by address

- Good: no codes.
- Bad: the person must have registered first, which creates an organization they do not want,
  and they are added without having agreed to it.

### Invitation links by e-mail

- Good: the usual experience.
- Bad: needs a mail service, which the free-tier stack lacks and the self-hosted mode must not
  call; a later branch can send the same code by mail.
