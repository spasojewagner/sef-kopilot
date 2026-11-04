"""The lock that orders concurrent work on one organization's members and sessions (ADR-0013).

It is a transaction-level PostgreSQL advisory lock keyed by the organization's id.

- A change to who belongs to the organization, or in which role, takes it exclusively. Such
  changes take turns.
- Signing in, refreshing and signing out take it shared. They run side by side, but never
  while the members change. A session therefore cannot be issued to someone at the moment
  they are removed, and the two cannot deadlock over the person's refresh tokens.
- PostgreSQL grants these locks in the order they were asked for. A shared request does not
  overtake an exclusive one that is already waiting, so a stream of sign-ins cannot keep a
  change waiting for ever. Row locks would allow that.

Every path takes this lock before any row lock, and none takes it shared first and exclusively
later. The locks are therefore always taken in the same order.
"""

from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["advisory_key", "lock_organization"]


def advisory_key(organization_id: uuid.UUID) -> int:
    """The organization's lock key: the first eight bytes of its id as a signed 64-bit integer,
    PostgreSQL's ``bigint``. Two organizations share a key with odds of about 2⁻⁶⁰, and then
    they merely wait for each other."""
    return int.from_bytes(organization_id.bytes[:8], "big", signed=True)


async def lock_organization(
    session: AsyncSession, organization_id: uuid.UUID, *, shared: bool = False
) -> None:
    """Hold the organization's lock until the transaction ends: exclusively to change its
    members, shared to issue, renew or end a session in it."""
    take = func.pg_advisory_xact_lock_shared if shared else func.pg_advisory_xact_lock
    await session.execute(select(take(literal(advisory_key(organization_id), BigInteger))))
