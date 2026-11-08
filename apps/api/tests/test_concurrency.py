"""Requests at the same moment, on real sessions that commit: the organization's lock decides the
order, and the outcome is the same whichever request comes first.

Where the order matters, a step is held at a gate so that the other request certainly arrives
while the first one holds the lock.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import delete, func, select, update

from sef_api.auth import dependencies
from sef_api.auth import service as auth
from sef_api.auth.passwords import hash_password
from sef_api.auth.service import TokenSettings
from sef_api.auth.tokens import new_opaque_token, opaque_token_digest
from sef_api.db import Database
from sef_api.locks import lock_organization
from sef_api.main import create_app
from sef_api.members import invitations
from sef_api.members import service as members
from sef_api.models import (
    AuditEvent,
    Invitation,
    Membership,
    OAuthAuthorization,
    Organization,
    RefreshToken,
    Role,
    SefKey,
    User,
)
from sef_api.oauth import tokens as oauth_tokens
from sef_api.organization import service as organization_service
from sef_api.rate_limits import Limit, PasswordAttempts, RateLimiter

from .conftest import TEST_JWT_SECRET, settings_for
from .factories import bearer, sef_key
from .test_oauth_authorization import CALLBACK, SERVER, VERIFIER, authorize, sent_to, sent_to_uri

TOKENS = TokenSettings(
    secret=TEST_JWT_SECRET,
    access_lifetime=timedelta(minutes=15),
    refresh_lifetime=timedelta(days=30),
)
PASSWORD = "a long passphrase"
#: Long enough for a request that is not held up to finish.
SETTLE_SECONDS = 0.5


def unlimited() -> PasswordAttempts:
    """A count of failed passwords that never holds anyone back: these tests are about order."""
    return PasswordAttempts(RateLimiter(), Limit(1_000, timedelta(minutes=1)))


@pytest.fixture
async def primer(committed_database: Database) -> tuple[Organization, User, User]:
    """Primer with two owners, committed."""
    async with committed_database.sessions() as setup:
        organization = Organization(name="Primer")
        owners = [
            User(email=f"{name}@primer.example", password_hash=await hash_password(PASSWORD))
            for name in ("ana", "milan")
        ]
        setup.add_all([organization, *owners])
        await setup.flush()
        setup.add_all(
            Membership(organization_id=organization.id, user_id=owner.id, role=Role.OWNER)
            for owner in owners
        )
        await setup.commit()
    return organization, owners[0], owners[1]


async def live_sessions(database: Database, user: User) -> int | None:
    async with database.sessions() as check:
        return await check.scalar(
            select(func.count())
            .select_from(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        )


async def owners(database: Database) -> int | None:
    async with database.sessions() as check:
        return await check.scalar(
            select(func.count()).select_from(Membership).where(Membership.role == Role.OWNER)
        )


@dataclass(frozen=True)
class Gate:
    reached: asyncio.Event
    release: asyncio.Event


def gate(
    monkeypatch: pytest.MonkeyPatch, module: object, name: str, *, after: bool = False
) -> Gate:
    """Hold the first call of ``module.name`` until released, before it runs or, with
    ``after``, once it has run; later calls pass straight on."""
    held_at = Gate(asyncio.Event(), asyncio.Event())
    original: Callable[..., Awaitable[Any]] = getattr(module, name)

    async def hold() -> None:
        if not held_at.reached.is_set():
            held_at.reached.set()
            await held_at.release.wait()

    async def held(*args: Any, **kwargs: Any) -> Any:
        if after:
            result = await original(*args, **kwargs)
            await hold()
            return result
        await hold()
        return await original(*args, **kwargs)

    monkeypatch.setattr(module, name, held)
    return held_at


async def while_held(
    held: Awaitable[Any], then: Callable[[], Awaitable[Any]], at: Gate, *, then_waits: bool
) -> list[Any]:
    """Run ``held`` up to the gate, then ``then``; release the gate and return both results.

    With ``then_waits``, ``then`` must still be waiting for the lock after a while; without, it
    must finish while ``held`` is held. Both always run to the end before anything is asserted,
    so a failure never leaves a transaction open.
    """
    first = asyncio.ensure_future(held)
    second: asyncio.Future[Any] | None = None
    waited = False
    try:
        await asyncio.wait_for(at.reached.wait(), timeout=SETTLE_SECONDS * 10)
        second = asyncio.ensure_future(then())
        if then_waits:
            await asyncio.sleep(SETTLE_SECONDS)
            waited = not second.done()
        else:
            await asyncio.wait_for(asyncio.shield(second), timeout=SETTLE_SECONDS * 10)
    finally:
        at.release.set()
        settled = await asyncio.gather(
            *(task for task in (first, second) if task is not None), return_exceptions=True
        )
    for result in settled:
        if isinstance(result, BaseException):
            raise result
    if then_waits:
        assert waited, "the second request did not wait for the organization's lock"
    return list(settled)


async def a_session(
    database: Database, organization: Organization, user: User, *, spent: bool = False
) -> str:
    """A refresh token of ``user`` in ``organization``, committed; returns the token."""
    token = new_opaque_token()
    async with database.sessions() as session:
        session.add(
            RefreshToken(
                organization_id=organization.id,
                user_id=user.id,
                family_id=uuid.uuid4(),
                digest=opaque_token_digest(token),
                expires_at=datetime.now(UTC) + timedelta(days=30),
                used_at=datetime.now(UTC) if spent else None,
            )
        )
        await session.commit()
    return token


async def a_family(
    database: Database, organization: Organization, user: User, *, spent: int
) -> list[str]:
    """One session of ``user``: ``spent`` spent tokens and the current one, committed."""
    family, tokens = uuid.uuid4(), [new_opaque_token() for _ in range(spent + 1)]
    async with database.sessions() as session:
        session.add_all(
            RefreshToken(
                organization_id=organization.id,
                user_id=user.id,
                family_id=family,
                digest=opaque_token_digest(token),
                expires_at=datetime.now(UTC) + timedelta(days=30),
                used_at=datetime.now(UTC) if index < spent else None,
            )
            for index, token in enumerate(tokens)
        )
        await session.commit()
    return tokens


async def outcome(action: Awaitable[Any]) -> str:
    try:
        await action
    except (
        members.LastOwnerError,
        auth.InvalidRefreshTokenError,
        auth.NotAMemberError,
        auth.InvalidInvitationError,
        auth.AuthenticationError,
    ) as refused:
        return f"refused: {type(refused).__name__}"
    return "done"


# --- the last owner ----------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["demotion", "removal"])
async def test_two_owners_cannot_both_step_down_at_once(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    """Ana's change is held once it has counted two owners; Milan's waits for the lock and
    counts again after Ana's has committed."""
    organization, ana, milan = primer
    held_at = gate(monkeypatch, members, "_keep_an_owner", after=True)

    async def step_down(owner: User) -> str:
        async with committed_database.sessions() as session:
            if change == "demotion":
                return await outcome(
                    members.change_role(session, organization.id, owner.id, Role.CLIENT)
                )
            return await outcome(members.remove(session, organization.id, owner.id))

    results = await while_held(step_down(ana), lambda: step_down(milan), held_at, then_waits=True)

    assert results == ["done", "refused: LastOwnerError"]
    assert await owners(committed_database) == 1


# --- sessions and removals ---------------------------------------------------------------------


@pytest.mark.parametrize("renewal", ["refresh", "sign-in"])
async def test_a_session_renewed_during_a_removal_does_not_survive_it(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
    renewal: str,
) -> None:
    """The renewal holds the organization in share mode, so the removal waits for it and then
    revokes the session it issued."""
    organization, _, milan = primer
    token = await a_session(committed_database, organization, milan)
    held_at = gate(monkeypatch, auth, "_sign_in")

    async def renew() -> None:
        async with committed_database.sessions() as session:
            if renewal == "refresh":
                await auth.refresh(session, TOKENS, refresh_token=token)
            else:
                await auth.login(
                    session,
                    TOKENS,
                    email="milan@primer.example",
                    password=PASSWORD,
                    guard=unlimited(),
                )

    async def remove() -> None:
        async with committed_database.sessions() as session:
            await members.remove(session, organization.id, milan.id)

    await while_held(renew(), remove, held_at, then_waits=True)

    assert await live_sessions(committed_database, milan) == 0


async def test_a_replayed_token_during_a_removal_does_not_deadlock(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Revoking the replayed token's family and the removal's revocation lock the same rows;
    the organization's lock makes them take turns instead of waiting for each other."""
    organization, _, milan = primer
    tokens = await a_family(committed_database, organization, milan, spent=2)
    held_at = gate(monkeypatch, auth, "_revoke_family")

    async def replay() -> str:
        async with committed_database.sessions() as session:
            return await outcome(auth.refresh(session, TOKENS, refresh_token=tokens[1]))

    async def remove() -> str:
        async with committed_database.sessions() as session:
            return await outcome(members.remove(session, organization.id, milan.id))

    results = await while_held(replay(), remove, held_at, then_waits=True)

    assert results == ["refused: InvalidRefreshTokenError", "done"]
    assert await live_sessions(committed_database, milan) == 0


async def test_a_sign_in_held_up_by_a_removal_finds_the_membership_gone(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milan has chosen the organization; before he takes its lock, he is removed."""
    organization, _, milan = primer
    held_at = gate(monkeypatch, auth, "lock_organization")

    async def sign_in() -> str:
        async with committed_database.sessions() as session:
            return await outcome(
                auth.login(
                    session,
                    TOKENS,
                    email="milan@primer.example",
                    password=PASSWORD,
                    guard=unlimited(),
                )
            )

    async def remove() -> str:
        async with committed_database.sessions() as session:
            return await outcome(members.remove(session, organization.id, milan.id))

    results = await while_held(sign_in(), remove, held_at, then_waits=False)

    assert results == ["refused: NotAMemberError", "done"]
    assert await live_sessions(committed_database, milan) == 0


async def test_a_refresh_held_up_while_its_account_is_deleted_finds_nothing(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, _, milan = primer
    token = await a_session(committed_database, organization, milan)
    held_at = gate(monkeypatch, auth, "lock_organization")

    async def renew() -> str:
        async with committed_database.sessions() as session:
            return await outcome(auth.refresh(session, TOKENS, refresh_token=token))

    async def delete_the_account() -> None:
        async with committed_database.sessions() as session:
            await session.execute(delete(User).where(User.id == milan.id))
            await session.commit()

    results = await while_held(renew(), delete_the_account, held_at, then_waits=False)

    assert results[0] == "refused: InvalidRefreshTokenError"


# --- the tokens of one session ----------------------------------------------------------------


@pytest.mark.parametrize("ending", ["sign-out", "replay"])
async def test_a_session_ended_during_its_refresh_does_not_survive(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    """A thief refreshes the current token while the person signs out or replays an old one;
    the session's tokens are locked, so the ending waits and then revokes the new token too."""
    organization, _, milan = primer
    old, current = await a_family(committed_database, organization, milan, spent=1)
    held_at = gate(monkeypatch, auth, "_sign_in")

    async def refresh() -> str:
        async with committed_database.sessions() as session:
            return await outcome(auth.refresh(session, TOKENS, refresh_token=current))

    async def end() -> str:
        async with committed_database.sessions() as session:
            if ending == "sign-out":
                return await outcome(auth.logout(session, refresh_token=old))
            return await outcome(auth.refresh(session, TOKENS, refresh_token=old))

    results = await while_held(refresh(), end, held_at, then_waits=True)

    assert results[0] == "done"
    assert await live_sessions(committed_database, milan) == 0


async def test_two_replays_of_one_session_at_once_do_not_deadlock(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, _, milan = primer
    first, second, _ = await a_family(committed_database, organization, milan, spent=2)
    held_at = gate(monkeypatch, auth, "_revoke_family")

    async def replay(token: str) -> str:
        async with committed_database.sessions() as session:
            return await outcome(auth.refresh(session, TOKENS, refresh_token=token))

    results = await while_held(replay(first), lambda: replay(second), held_at, then_waits=True)

    assert results == ["refused: InvalidRefreshTokenError"] * 2
    assert await live_sessions(committed_database, milan) == 0


async def test_a_sign_out_waits_for_a_change_to_the_members(
    committed_database: Database, primer: tuple[Organization, User, User]
) -> None:
    organization, _, milan = primer
    token = await a_session(committed_database, organization, milan)
    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id)  # a change to the members
        try:
            signing_out = asyncio.ensure_future(sign_out(committed_database, token))
            await asyncio.sleep(SETTLE_SECONDS)
            waited = not signing_out.done()
        finally:
            await holder.rollback()
    await signing_out

    assert waited
    assert await live_sessions(committed_database, milan) == 0


async def sign_out(database: Database, token: str) -> None:
    async with database.sessions() as session:
        await auth.logout(session, refresh_token=token)


@pytest.mark.parametrize("token_is", ["revoked", "expired before it was spent", "unknown"])
async def test_a_token_that_can_do_nothing_takes_no_lock(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    token_is: str,
) -> None:
    """So a former member's old tokens cannot hold up the organization's changes."""
    organization, _, milan = primer
    token = await a_session(committed_database, organization, milan)
    async with committed_database.sessions() as session:
        stored = select(RefreshToken).where(RefreshToken.user_id == milan.id)
        changed = (await session.scalars(stored)).one()
        if token_is == "revoked":
            changed.revoked_at = datetime.now(UTC)
        elif token_is == "expired before it was spent":
            changed.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        else:
            token = new_opaque_token()
        await session.commit()
    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id)  # a change to the members
        try:
            async with committed_database.sessions() as session:
                refused = await asyncio.wait_for(
                    outcome(auth.refresh(session, TOKENS, refresh_token=token)),
                    timeout=SETTLE_SECONDS * 4,
                )
            await asyncio.wait_for(sign_out(committed_database, token), SETTLE_SECONDS * 4)
        finally:
            await holder.rollback()

    assert refused == "refused: InvalidRefreshTokenError"


async def test_a_sign_in_does_not_overtake_a_change_that_waits(
    committed_database: Database, primer: tuple[Organization, User, User]
) -> None:
    """The lock serves requests in the order they came: while a change waits for a sign-in in
    progress, the next sign-in waits behind the change, so sign-ins cannot starve it."""
    organization, _, milan = primer
    order: list[str] = []

    async def change() -> None:
        async with committed_database.sessions() as session:
            await members.remove(session, organization.id, milan.id)
        order.append("change")

    async def sign_in() -> None:
        async with committed_database.sessions() as session:
            await auth.login(
                session, TOKENS, email="ana@primer.example", password=PASSWORD, guard=unlimited()
            )
        order.append("sign-in")

    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id, shared=True)  # a sign-in in progress
        try:
            changing = asyncio.ensure_future(change())
            await asyncio.sleep(SETTLE_SECONDS)
            signing_in = asyncio.ensure_future(sign_in())
            await asyncio.sleep(SETTLE_SECONDS)
            both_waited = not changing.done() and not signing_in.done()
        finally:
            await holder.rollback()
    await asyncio.gather(changing, signing_in)

    assert both_waited
    assert order == ["change", "sign-in"]


# --- a change by someone who is losing the right to make it ------------------------------------


async def test_a_demoted_owners_change_in_flight_is_refused(
    committed_api: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milan passes the first check as an owner; Ana demotes him before his change takes the
    lock; the check under the lock refuses it."""
    organization, ana, milan = primer
    held_at = gate(monkeypatch, dependencies, "lock_organization")

    milans_change = committed_api.patch(
        f"/members/{ana.id}",
        json={"role": "client"},
        headers=bearer(milan, organization, Role.OWNER),
    )

    async def demote_milan() -> Response:
        return await committed_api.patch(
            f"/members/{milan.id}",
            json={"role": "client"},
            headers=bearer(ana, organization, Role.OWNER),
        )

    refused, demotion = await while_held(milans_change, demote_milan, held_at, then_waits=False)

    assert demotion.status_code == 200
    assert refused.status_code == 403
    async with committed_database.sessions() as check:
        role = await check.scalar(select(Membership.role).where(Membership.user_id == ana.id))
    assert role is Role.OWNER


async def test_a_period_set_in_flight_by_a_demoted_owner_is_refused(
    committed_api: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milan passes the first check as an owner and asks for a period that would delete Primer's
    invoices; Ana demotes him before his change takes the lock; the check under the lock refuses
    it, and Primer keeps every invoice."""
    organization, ana, milan = primer
    held_at = gate(monkeypatch, organization_service, "lock_organization")

    milans_period = committed_api.patch(
        "/organization",
        json={"invoice_retention_days": 1},
        headers=bearer(milan, organization, Role.OWNER),
    )

    async def demote_milan() -> Response:
        return await committed_api.patch(
            f"/members/{milan.id}",
            json={"role": "accountant"},
            headers=bearer(ana, organization, Role.OWNER),
        )

    refused, demotion = await while_held(milans_period, demote_milan, held_at, then_waits=False)

    assert demotion.status_code == 200
    assert refused.status_code == 403
    async with committed_database.sessions() as check:
        kept = await check.scalar(
            select(Organization.invoice_retention_days).where(Organization.id == organization.id)
        )
        recorded = await check.scalar(select(func.count()).select_from(AuditEvent))
    assert (kept, recorded) == (None, 0)


@pytest.mark.parametrize(
    ("method", "body"),
    [("PUT", {"api_key": "0815-0815-0815-0815"}), ("DELETE", None)],
    ids=["setting", "removing"],
)
async def test_a_sef_key_changed_in_flight_by_a_demoted_owner_is_refused(
    committed_api: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    body: dict[str, str] | None,
) -> None:
    """Milan passes the first check as an owner and asks to replace or remove Primer's key to
    SEF; Ana demotes him before his change takes the lock; the check under the lock refuses it,
    and Primer's key is as it was."""
    organization, ana, milan = primer
    async with committed_database.sessions() as session:
        sealed = await sef_key(session, organization, "4711-4711-4711-4711")
        await session.commit()
    held_at = gate(monkeypatch, organization_service, "lock_organization")

    milans_change = committed_api.request(
        method, "/organization/sef-key", json=body, headers=bearer(milan, organization, Role.OWNER)
    )

    async def demote_milan() -> Response:
        return await committed_api.patch(
            f"/members/{milan.id}",
            json={"role": "accountant"},
            headers=bearer(ana, organization, Role.OWNER),
        )

    refused, demotion = await while_held(milans_change, demote_milan, held_at, then_waits=False)

    assert demotion.status_code == 200
    assert refused.status_code == 403
    async with committed_database.sessions() as check:
        kept = await check.scalar(select(SefKey.token))
        recorded = await check.scalar(select(func.count()).select_from(AuditEvent))
    assert (kept, recorded) == (sealed.token, 0)


async def test_the_lock_is_not_taken_by_a_caller_without_the_permission(
    committed_api: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
) -> None:
    """A client's refused request returns while an owner's change holds the organization."""
    organization, ana, _ = primer
    async with committed_database.sessions() as setup:
        client = User(email="jovana@primer.example", password_hash="-")
        setup.add(client)
        await setup.flush()
        setup.add(Membership(organization_id=organization.id, user_id=client.id, role=Role.CLIENT))
        await setup.commit()
    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id)  # an owner's change

        refused = await asyncio.wait_for(
            committed_api.delete(
                f"/members/{ana.id}", headers=bearer(client, organization, Role.CLIENT)
            ),
            timeout=SETTLE_SECONDS * 4,
        )

        assert refused.status_code == 403
        await holder.rollback()


async def test_sign_ins_do_not_wait_for_each_other(
    committed_database: Database, primer: tuple[Organization, User, User]
) -> None:
    """Share mode: a session held open in the organization does not delay another sign-in."""
    organization, _, _ = primer
    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id, shared=True)
        async with committed_database.sessions() as session:
            signed_in = await asyncio.wait_for(
                auth.login(
                    session,
                    TOKENS,
                    email="ana@primer.example",
                    password=PASSWORD,
                    guard=unlimited(),
                ),
                timeout=SETTLE_SECONDS * 4,
            )
        await holder.rollback()

    assert signed_in.organization.id == organization.id


# --- invitations -------------------------------------------------------------------------------


async def open_invitations(database: Database) -> int | None:
    async with database.sessions() as check:
        return await check.scalar(
            select(func.count())
            .select_from(Invitation)
            .where(Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None))
        )


async def test_two_invitations_of_one_address_at_once_leave_one_open(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second waits for the lock, then replaces the first instead of colliding with it."""
    organization, ana, milan = primer
    held_at = gate(monkeypatch, invitations, "lock_organization", after=True)

    async def invite(owner: User) -> str:
        async with committed_database.sessions() as session:
            await invitations.invite(
                session, organization.id, owner.id, email="nova@primer.example", role=Role.CLIENT
            )
        return "done"

    results = await while_held(invite(ana), lambda: invite(milan), held_at, then_waits=True)

    assert results == ["done", "done"]
    assert await open_invitations(committed_database) == 1


async def test_a_code_accepted_twice_at_once_admits_one_person(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    organization, ana, _ = primer
    async with committed_database.sessions() as session:
        issued = await invitations.invite(
            session, organization.id, ana.id, email="nova@primer.example", role=Role.CLIENT
        )
    held_at = gate(monkeypatch, auth, "lock_organization", after=True)

    async def accept() -> str:
        async with committed_database.sessions() as session:
            return await outcome(
                auth.accept_invitation(
                    session, TOKENS, code=issued.code, password=PASSWORD, guard=unlimited()
                )
            )

    results = await while_held(accept(), accept, held_at, then_waits=True)

    assert results == ["done", "refused: InvalidInvitationError"]


async def test_an_invitation_withdrawn_while_it_is_being_accepted_is_refused(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Milan's invitation is being redeemed when Ana demotes him; under the lock, the redemption
    finds it withdrawn."""
    organization, _, milan = primer
    async with committed_database.sessions() as session:
        issued = await invitations.invite(
            session, organization.id, milan.id, email="nova@primer.example", role=Role.OWNER
        )
    held_at = gate(monkeypatch, auth, "lock_organization")

    async def accept() -> str:
        async with committed_database.sessions() as session:
            return await outcome(
                auth.accept_invitation(
                    session, TOKENS, code=issued.code, password=PASSWORD, guard=unlimited()
                )
            )

    async def demote_milan() -> str:
        async with committed_database.sessions() as session:
            return await outcome(
                members.change_role(session, organization.id, milan.id, Role.CLIENT)
            )

    results = await while_held(accept(), demote_milan, held_at, then_waits=False)

    assert results == ["refused: InvalidInvitationError", "done"]


async def test_an_account_deactivated_while_it_joins_is_refused(
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The password was right; by the time the lock is taken, the account is deactivated."""
    organization, ana, _ = primer
    async with committed_database.sessions() as session:
        nova = User(email="nova@ogled.example", password_hash=await hash_password(PASSWORD))
        session.add(nova)
        await session.commit()
    async with committed_database.sessions() as session:
        issued = await invitations.invite(
            session, organization.id, ana.id, email="nova@ogled.example", role=Role.CLIENT
        )
    held_at = gate(monkeypatch, auth, "lock_organization")

    async def accept() -> str:
        async with committed_database.sessions() as session:
            return await outcome(
                auth.accept_invitation(
                    session, TOKENS, code=issued.code, password=PASSWORD, guard=unlimited()
                )
            )

    async def deactivate() -> None:
        async with committed_database.sessions() as session:
            await session.execute(update(User).where(User.id == nova.id).values(is_active=False))
            await session.commit()

    results = await while_held(accept(), deactivate, held_at, then_waits=False)

    assert results[0] == "refused: AuthenticationError"


async def test_a_wrong_password_for_an_invitation_holds_nothing_up(
    committed_database: Database, primer: tuple[Organization, User, User]
) -> None:
    """The password is checked before the organization is locked, so a code holder guessing
    passwords cannot stall the organization's changes."""
    organization, ana, _ = primer
    async with committed_database.sessions() as session:
        session.add(User(email="nova@ogled.example", password_hash=await hash_password(PASSWORD)))
        await session.commit()
    async with committed_database.sessions() as session:
        issued = await invitations.invite(
            session, organization.id, ana.id, email="nova@ogled.example", role=Role.CLIENT
        )
    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id)  # a change to the members in progress
        async with committed_database.sessions() as session:
            refused = await asyncio.wait_for(
                outcome(
                    auth.accept_invitation(
                        session, TOKENS, code=issued.code, password="x", guard=unlimited()
                    )
                ),
                timeout=SETTLE_SECONDS * 4,
            )
        await holder.rollback()

    assert refused == "refused: AuthenticationError"


async def test_listing_the_invitations_takes_no_lock(
    committed_api: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
) -> None:
    """Reading is not a change: it does not wait for a sign-in in progress, nor hold one up."""
    organization, ana, _ = primer
    async with committed_database.sessions() as holder:
        await lock_organization(holder, organization.id, shared=True)  # a sign-in in progress
        try:
            listed = await asyncio.wait_for(
                committed_api.get("/invitations", headers=bearer(ana, organization, Role.OWNER)),
                timeout=SETTLE_SECONDS * 4,
            )
        finally:
            await holder.rollback()

    assert listed.status_code == 200


@pytest.fixture
async def authorization_server(
    committed_database: Database, database_url: str
) -> AsyncIterator[AsyncClient]:
    """A client of an application that is also an authorization server, as in production: each
    request gets a session of its own and commits for real."""
    app = create_app(settings_for(database_url, **SERVER))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    await app.state.database.engine.dispose()


async def a_consent(api: AsyncClient, organization: Organization, owner: User) -> tuple[str, str]:
    """A client registered for codes and refresh tokens, and the code an owner's consent issued
    it, committed."""
    registered = await api.post(
        "/oauth/register",
        json={"redirect_uris": [CALLBACK], "grant_types": ["authorization_code", "refresh_token"]},
    )
    client = str(registered.json()["client_id"])
    _, query = sent_to(await authorize(api, client))
    approved = await api.post(
        f"/oauth/requests/{query['request']}/approval",
        headers=bearer(owner, organization, Role.OWNER),
    )
    _, answer = sent_to_uri(approved.json()["redirect_uri"])
    return client, answer["code"]


def an_exchange(client: str, code: str) -> dict[str, str]:
    return {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client,
        "code_verifier": VERIFIER,
        "redirect_uri": CALLBACK,
    }


async def revoked(database: Database, client: str) -> bool:
    async with database.sessions() as check:
        moment = await check.scalar(
            select(OAuthAuthorization.revoked_at).where(OAuthAuthorization.client_id == client)
        )
    return moment is not None


async def test_of_two_exchanges_of_one_code_at_once_the_second_revokes_the_consent(
    authorization_server: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first exchange holds the consent's row when it reads the member's role; the second
    waits for it, then finds the code spent: someone else has it, and the consent ends."""
    organization, ana, _ = primer
    client, code = await a_consent(authorization_server, organization, ana)
    held_at = gate(monkeypatch, oauth_tokens, "_role_of")

    first, second = await while_held(
        authorization_server.post("/oauth/token", data=an_exchange(client, code)),
        lambda: authorization_server.post("/oauth/token", data=an_exchange(client, code)),
        held_at,
        then_waits=True,
    )

    assert (first.status_code, second.status_code) == (200, 400)
    assert second.json()["error"] == "invalid_grant"
    assert await revoked(committed_database, client)


async def test_of_two_refreshes_with_one_token_at_once_the_second_revokes_the_consent(
    authorization_server: AsyncClient,
    committed_database: Database,
    primer: tuple[Organization, User, User],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first refresh holds the consent's row; the second waits for it, then finds the token
    spent, and the consent ends: the token the first refresh issued is refused too."""
    organization, ana, _ = primer
    client, code = await a_consent(authorization_server, organization, ana)
    issued = (
        await authorization_server.post("/oauth/token", data=an_exchange(client, code))
    ).json()
    renewal = {
        "grant_type": "refresh_token",
        "refresh_token": issued["refresh_token"],
        "client_id": client,
    }
    held_at = gate(monkeypatch, oauth_tokens, "_role_of")

    first, second = await while_held(
        authorization_server.post("/oauth/token", data=renewal),
        lambda: authorization_server.post("/oauth/token", data=renewal),
        held_at,
        then_waits=True,
    )
    latest = await authorization_server.post(
        "/oauth/token",
        data=renewal | {"refresh_token": first.json()["refresh_token"]},
    )

    assert (first.status_code, second.status_code, latest.status_code) == (200, 400, 400)
    assert await revoked(committed_database, client)
