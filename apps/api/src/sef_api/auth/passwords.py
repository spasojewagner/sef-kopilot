"""Password hashing with argon2id, off the event loop.

The parameters are OWASP's recommended minimum for argon2id (19 MiB of memory, two passes, one
lane): every hash costs a few dozen milliseconds of CPU, so guessing is slow, and little memory,
so a free-tier instance survives several sign-ins at once. Hashing runs in a worker thread, and
the event loop keeps serving other requests meanwhile. A hash records its own parameters, so
raising them later only needs :func:`needs_rehash` at sign-in.

A new password is also refused when it is among the 10,000 most common passwords that meet the
length a new one needs, compared in lower case (ASVS 6.2.4): the list ships with the API
(``common-passwords.txt.gz``, from SecLists; its licence beside it), so checking it asks no one
outside, as a self-hosted deployment makes no calls it was not told to.
"""

from __future__ import annotations

import asyncio
import gzip
import secrets
import unicodedata
from functools import cache
from importlib.resources import files
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

__all__ = [
    "MAXIMUM_LENGTH",
    "MINIMUM_LENGTH",
    "hash_password",
    "is_common",
    "is_personal",
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


@cache
def _common() -> frozenset[str]:
    """The common passwords, in lower case, read once."""
    listed = files("sef_api.auth").joinpath("common-passwords.txt.gz")
    with listed.open("rb") as packed, gzip.open(packed, "rt", encoding="utf-8") as lines:
        return frozenset(line.rstrip("\n") for line in lines if line.strip())


def is_common(password: str) -> bool:
    """Whether ``password`` is among the most common passwords, whatever its case."""
    return password.lower() in _common()


#: The shortest address or name a password is checked for: shorter ones are parts of many words.
SHORTEST_PERSONAL: Final = 4


def _letters_and_digits(text: str) -> str:
    """``text``'s letters and digits in lower case, without their marks: č is c, and đ d."""
    plain = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    return "".join(
        character
        for character in plain
        if character.isalnum() and not unicodedata.combining(character)
    )


def is_personal(password: str, *words: str) -> bool:
    """Whether ``password`` holds one of ``words`` of at least four letters and digits, such
    as the name of the address it signs in with or its organization's, whatever the case and
    whatever is between them (ASVS 6.2.11): a password that an organization's name gives away
    is shown to every member, and one that the address gives away is guessed first."""
    held = _letters_and_digits(password)
    return any(
        len(word) >= SHORTEST_PERSONAL and word in held for word in map(_letters_and_digits, words)
    )
