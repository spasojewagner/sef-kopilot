"""Who is calling and what they may do: FastAPI dependencies for authentication and
authorization.

:func:`current_principal` authenticates: it reads the access token and needs no database.
:func:`require` authorizes: it admits a caller whose role *now* grants a permission, reading the
membership from the database, so that removing a member, deactivating an account or changing a
role takes effect at once instead of when the access token expires (ADR-0013).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from functools import cache
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.auth.service import TokenSettings
from sef_api.auth.tokens import InvalidTokenError, decode_access_token
from sef_api.db import get_session
from sef_api.locks import lock_organization
from sef_api.models import Membership, Role, User

__all__ = [
    "Principal",
    "check_again",
    "current_principal",
    "current_role",
    "get_token_settings",
    "no_longer_active",
    "require",
]

_BEARER = HTTPBearer(
    auto_error=False,
    scheme_name="access token",
    description="An access token from `POST /auth/login`, `/auth/register` or `/auth/refresh`.",
)


@dataclass(frozen=True)
class Principal:
    """The caller: a person acting in one organization with one role."""

    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: Role

    def may(self, permission: Permission) -> bool:
        """Whether the caller may do what ``permission`` allows: their role grants it."""
        return permission in ROLE_PERMISSIONS[self.role]


def get_token_settings(request: Request) -> TokenSettings:
    """The application's token settings (a FastAPI dependency)."""
    return cast(TokenSettings, request.app.state.tokens)


async def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
    tokens: Annotated[TokenSettings, Depends(get_token_settings)],
) -> Principal:
    """The principal of the request's access token; 401 without a valid one."""
    if credentials is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="not signed in",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        claims = decode_access_token(credentials.credentials, secret=tokens.secret)
    except InvalidTokenError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired access token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from None
    return Principal(claims.user_id, claims.organization_id, claims.role)


async def current_role(session: AsyncSession, principal: Principal) -> Role | None:
    """The principal's role in their organization now; None once the membership is gone or
    the account is deactivated."""
    return await session.scalar(
        select(Membership.role)
        .join(User, User.id == Membership.user_id)
        .where(
            Membership.user_id == principal.user_id,
            Membership.organization_id == principal.organization_id,
            User.is_active.is_(True),
        )
    )


def no_longer_active() -> HTTPException:
    """401 for a valid access token whose account or membership has ended since it was issued."""
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="the account or its membership is no longer active",
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def require(
    permission: Permission, *, changes_members: bool = False
) -> Callable[..., Awaitable[Principal]]:
    """A dependency that admits callers whose current role grants ``permission``.

    It answers 401 without a valid access token or once the caller's account or membership has
    ended, and 403 when the role does not grant the permission. It returns the principal with
    the role read from the database. There is one dependency per permission and variant, so a
    route audit can tell what a route requires.

    An endpoint that changes the organization's members asks with ``changes_members``. A caller
    who passes is then checked once more after the organization is locked, and the endpoint's
    change runs under that lock, so the role cannot change between the check and the change. A
    caller who fails never takes the lock, and a reading endpoint takes none.
    """
    return _require(permission, changes_members)


@cache
def _require(permission: Permission, changes_members: bool) -> Callable[..., Awaitable[Principal]]:
    async def authorize(
        principal: Annotated[Principal, Depends(current_principal)],
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Principal:
        permitted = await _permitted(session, principal, permission)
        if changes_members:
            await lock_organization(session, principal.organization_id)
            permitted = await _permitted(session, principal, permission)
        return permitted

    return authorize


async def check_again(
    session: AsyncSession, principal: Principal, permission: Permission
) -> Principal:
    """Check, in the transaction about to change something, that the caller still holds
    ``permission``: for a request whose work outlasts the transaction in which :func:`require`
    checked it, such as an upload and its validation. 401 or 403 as :func:`require` answers."""
    return await _permitted(session, principal, permission)


async def _permitted(
    session: AsyncSession, principal: Principal, permission: Permission
) -> Principal:
    """The principal with the role it holds now, when that lets it do ``permission``."""
    role = await current_role(session, principal)
    if role is None:
        raise no_longer_active()
    permitted = replace(principal, role=role)
    if not permitted.may(permission):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, detail=f"requires the permission {permission}"
        )
    return permitted
