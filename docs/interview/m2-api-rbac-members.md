# M2 — `feat/api-rbac-members`

## Three questions a senior engineer would ask

**1. "How do you make sure that the next endpoint does not forget the permission check, or the
filter by organization?"**

The tests check both for every endpoint, so remembering is not enough on its own. A route
audit reads the application's routes. Every endpoint is public by name, open by name to any
signed-in caller, or depends on `require()` with the permission pinned for it in a table; a
mounted application or a websocket route fails the audit outright. The audit also has to see
every operation in the OpenAPI document, so that it cannot pass with nothing to check.

For every guarded endpoint, a role without the permission must get 403, and a cross-tenant
case has another organization's owner, who holds every permission, try the endpoint and find
nothing. A missing case fails the suite.

An independent review found that weakening one endpoint's permission still passed the first
version of the audit; pinning the permission closed that gap. Seeded faults (an unguarded
route, a weaker permission, a query without the organization) now each fail the tests.

**2. "The access token already carries the role. Why read the membership again?"**

So that removing an accountant, deactivating an account or changing a role takes effect on the
next request. Trusting the token would leave up to 15 minutes of access to the clients' data.
It costs one primary-key lookup, on requests that query the database anyway. The role in the
token is only a hint for the client; `GET /auth/me` reports the role held now.

**3. "Two owners demote each other at the same moment. What happens?"**

One succeeds and the other gets 409. Each change locks the organization's row first
(`FOR NO KEY UPDATE`), so the second one waits. Under READ COMMITTED its next statement then
sees the first one's commit and counts a single owner. The test holds the first change at a
gate after it has counted, so the second certainly arrives in between; without the lock, both
succeed every time.

Sign-ins and refreshes take the same lock in share mode, so they never overlap a change to
the members. It is an advisory lock because PostgreSQL grants those in arrival order; with row
locks, a stream of sign-ins could starve a change, and a test shows the difference. Every path
takes this lock first, and the tokens of one session are then locked by id, so nothing
deadlocks. The review had found a replay that deadlocked with a removal, and tokens that
survived a removal or a sign-out; all of them are tests now.

## The one concept to explain unaided

**Authorization is decided per object, not per endpoint.** "May managers edit members?" is half
the question. The other half is "is *this* member in *your* organization?" That half belongs
in every query, as the caller's `organization_id`. Another organization's object is therefore
*not found* (404), never *forbidden* (403), which would confirm that it exists.

## Supporting facts worth remembering

- Permissions:
  - The owner holds all of them.
  - An accountant has `members:read`.
  - A client has neither members permission.
- `require()` answers 401 when the account or membership has ended, and 403 when the role lacks
  the permission.
- Invitations:
  - The code is 256 random bits, shown once, valid for seven days; only its digest is stored.
  - A partial unique index keeps one open invitation per address and organization.
  - Accepting creates the account, or asks for the existing account's password, checked before
    the lock.
  - An invitation stops working when its issuer is removed, demoted or deactivated, so an
    ousted owner cannot return through one.
- For endpoints that change the members the role is checked again under the lock, so a
  demotion at the same moment cannot let a change through; reading endpoints take no lock.
- A token that can do nothing (unknown, revoked, expired unspent) takes no lock at all.
- Not yet: API keys (after the invoice endpoints), rate limiting, leaving an organization oneself, row-level
  security.
