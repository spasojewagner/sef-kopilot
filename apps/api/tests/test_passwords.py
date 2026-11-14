"""argon2id password hashes: format, parameters, verification, rehashing."""

from __future__ import annotations

from argon2 import PasswordHasher

from sef_api.auth.passwords import (
    MAXIMUM_LENGTH,
    MINIMUM_LENGTH,
    _common,
    hash_password,
    is_common,
    needs_rehash,
    verify_password,
)

PASSWORD = "correct horse battery staple"


async def test_a_hash_is_argon2id_with_owasps_minimum_parameters() -> None:
    hashed = await hash_password(PASSWORD)

    assert hashed.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert PASSWORD not in hashed


async def test_the_right_password_verifies_and_a_wrong_one_does_not() -> None:
    hashed = await hash_password(PASSWORD)

    assert await verify_password(hashed, PASSWORD)
    assert not await verify_password(hashed, PASSWORD.upper())


async def test_the_same_password_hashes_differently_each_time() -> None:
    assert await hash_password(PASSWORD) != await hash_password(PASSWORD)


async def test_without_an_account_nothing_verifies() -> None:
    assert not await verify_password(None, PASSWORD)


async def test_a_damaged_hash_verifies_nothing() -> None:
    assert not await verify_password("$argon2id$not-a-hash", PASSWORD)


async def test_a_hash_made_with_other_parameters_needs_rehashing() -> None:
    weaker = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)

    assert needs_rehash(weaker)
    assert not needs_rehash(await hash_password(PASSWORD))


def test_the_common_passwords_meet_the_length_a_new_one_needs_and_are_in_lower_case() -> None:
    common = _common()

    assert len(common) == 10_000
    assert all(MINIMUM_LENGTH <= len(each) <= MAXIMUM_LENGTH for each in common)
    assert all(each == each.lower() for each in common)
    assert is_common("Qwerty123456")
    assert not is_common("kiseli kupus na pijaci u sredu")
