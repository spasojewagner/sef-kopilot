"""Password hashing with argon2id, off the event loop.

The parameters are OWASP's recommended minimum for argon2id (19 MiB of memory, two passes, one
lane): every hash costs a few dozen milliseconds of CPU, so guessing is slow, and little memory,
so a free-tier instance survives several sign-ins at once. Hashing runs in a worker thread, and
the event loop keeps serving other requests meanwhile. A hash records its own parameters, so
raising them later only needs :func:`needs_rehash` at sign-in.
"""

from __future__ import annotations

import asyncio
import secrets
from functools import cache
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

__all__ = [
    "MAXIMUM_LENGTH",
    "MINIMUM_LENGTH",
    "hash_password",
    "needs_rehash",
    "verify_password",
]

#: A new password's length: long enough for a passphrase, short enough to bound hashing work.
MINIMUM_LENGTH: Final = 12
MAXIMUM_LENGTH: Final = 128

MEMORY_KIB: Final = 19 * 1024
TIME_COST: Final = 2
PARALLELISM: Final = 1

_HASHER: Final = PasswordHasher(
    time_cost=TIME_COST, memory_cost=MEMORY_KIB, parallelism=PARALLELISM
)


@cache
def _dummy_hash() -> str:
    """A hash of a random password, verified when the e-mail address is unknown."""
    return _HASHER.hash(secrets.token_urlsafe(16))


async def hash_password(password: str) -> str:
    """The argon2id hash of ``password``, in PHC string format (salt and parameters included)."""
    return await asyncio.to_thread(_HASHER.hash, password)


async def verify_password(password_hash: str | None, password: str) -> bool:
    """Whether ``password`` matches ``password_hash``.

    Without a hash (no such user) a dummy hash is checked instead, so that the answer takes as
    long as for a real account and timing does not tell which e-mail addresses exist.
    """
    candidate = password_hash if password_hash is not None else _dummy_hash()
    try:
        await asyncio.to_thread(_HASHER.verify, candidate, password)
    except (VerificationError, InvalidHashError):
        return False
    return password_hash is not None


def needs_rehash(password_hash: str) -> bool:
    """Whether ``password_hash`` was made with other parameters than the current ones."""
    return _HASHER.check_needs_rehash(password_hash)
