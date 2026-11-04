"""Who is calling: the principal behind an access token (a FastAPI dependency)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sef_api.auth.service import TokenSettings
from sef_api.auth.tokens import InvalidTokenError, decode_access_token
from sef_api.models import Role

__all__ = ["Principal", "current_principal", "get_token_settings"]

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
