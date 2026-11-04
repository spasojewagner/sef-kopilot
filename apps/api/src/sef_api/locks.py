"""The locks that order concurrent work on one organization: one on its members and sessions
(ADR-0013), one on its stored invoices (ADR-0016). Both are transaction-level PostgreSQL
advisory locks keyed by the organization's id.

The lock on the members:

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

The lock on the stored invoices is taken to store one: adding up what the organization stores
and storing one more cannot interleave with another upload, so the quota holds exactly. It
uses PostgreSQL's other key space, two 32-bit keys, which never meets the first. No path takes
both locks.
"""

from __future__ import annotations

import uuid
from typing import Final

from sqlalchemy import BigInteger, Integer, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["advisory_key", "lock_invoice_storage", "lock_organization"]

#: The first of the two keys of the lock on an organization's stored invoices: "SEF" and 1.
_STORAGE: Final = 0x53454601


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


async def lock_invoice_storage(session: AsyncSession, organization_id: uuid.UUID) -> None:
    """Hold the lock on the organization's stored invoices until the transaction ends."""
    await _lock_in_two_keys(session, _STORAGE, organization_id)


async def _lock_in_two_keys(session: AsyncSession, what: int, organization_id: uuid.UUID) -> None:
    """Hold a lock in the two-key space: ``what`` it orders, and the first four bytes of the
    organization's id. Two organizations that share them merely wait for each other."""
    key = int.from_bytes(organization_id.bytes[:4], "big", signed=True)
    await session.execute(
        select(func.pg_advisory_xact_lock(literal(what, Integer), literal(key, Integer)))
    )
