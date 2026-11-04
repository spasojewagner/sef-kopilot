# Authorization in a multi-tenant API

Authentication answers *who is calling*. Authorization answers *may they do this, to this
object, in this organization*. Most API breaches come from answering the second question too
loosely.

## Three checks on every guarded request

```text
request ──► who is it?       access token: signature, expiry, claims        401 if not
        ──► may they?        the role held now grants the permission        403 if not
        ──► this object?     the query is filtered by the caller's org      404 if not theirs
```

1. **Authentication** reads the token and needs no database.
2. **Authorization** reads the role the person holds *now*, from the membership, and checks the
   permission the endpoint asks for. Endpoints ask for a permission (`members:manage`), never
   for a role, so the policy is one table that can change without touching the endpoints.
3. **Object scoping** is part of the query itself: `WHERE organization_id = :caller_org`. The
   organization comes from the token; a path or a body never names it.

## BOLA: the bug to design against

Broken object-level authorization is OWASP's API1:2023. In a typical case, an endpoint checks
that the caller is signed in, and even that they may manage members, but not that *this* member
belongs to *their* organization. Then `PATCH /members/{id}` with another tenant's id works.

Remembering a check in every endpoint does not fix this. What fixes it is a service layer whose
every query takes the organization, and a test that tries the attack.

## 404, not 403

For an object in another organization, the answer is 404. A 403 would confirm that the id
exists. 403 is for an object in the caller's own organization that their role may not touch.

## A role from the token or from the database

A role carried in the token costs nothing to check, but it goes stale: a removed accountant
would keep access until the token expires. Reading the membership costs one primary-key lookup
on a request that queries the database anyway. In return, removal, deactivation and role
changes act on the very next request. Here the token's role is only a hint for the user
interface.

## Deny by default, then prove it

A test lists every route of the application. Each route must be public by name, or open to any
signed-in caller by name, or guarded by a permission. Every guarded route must also have a
cross-tenant case: the owner of another organization, holding every permission, tries the route
and finds nothing.

An endpoint added without a guard fails CI, and so does one added without its cross-tenant
case.

## Invariants under concurrency

"An organization keeps at least one owner" cannot be checked with a `SELECT count(*)` followed
by an `UPDATE`. Two owners who step down at the same moment both count two owners. Every change
to an organization's members therefore locks the organization's row first. The changes take
turns, and the second one counts again after the first one has committed.

The same check-then-act trap applies to permissions. A role read before the lock may change
before the action. So for changes to the members, the role is checked once more under the
lock that the change then runs under.

Sessions take the same lock in share mode. Sign-ins and refreshes run side by side but wait for
a change to the members, so a session cannot be issued to someone at the moment they are
removed. The lock is a PostgreSQL advisory lock, granted in the order it was asked for, so
sign-ins cannot starve a change; row locks would let them.

One rule keeps all of this free of deadlocks: every path takes the organization's lock first,
before any row lock, and rows it then locks together it locks in one order (the tokens of a
session by id).

## In this repository

- `apps/api/src/sef_api/auth/permissions.py`: the policy table.
- `auth/dependencies.py`: `require()`.
- `locks.py`: the organization's lock.
- `members/`: members and invitations.
- `tests/test_access_control.py`: the route audit and the cross-tenant cases.
- `tests/test_concurrency.py`: requests held at a gate to prove each ordering.

The decision is recorded in ADR-0013.
