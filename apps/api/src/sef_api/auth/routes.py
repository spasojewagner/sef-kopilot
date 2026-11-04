"""``/auth``: sign up, sign in, refresh, sign out, and who am I."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth import service
from sef_api.auth.dependencies import Principal, current_principal, get_token_settings
from sef_api.auth.service import SignedIn, TokenSettings
from sef_api.db import get_session
from sef_api.models import Membership, Organization, Role, User

router = APIRouter(prefix="/auth", tags=["auth"])

Session = Annotated[AsyncSession, Depends(get_session)]
Tokens = Annotated[TokenSettings, Depends(get_token_settings)]

#: Long enough for a passphrase, short enough to bound the work of hashing it.
NewPassword = Annotated[str, Field(min_length=12, max_length=128)]
Password = Annotated[str, Field(min_length=1, max_length=128)]
OrganizationName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


class RegisterRequest(BaseModel):
    email: EmailStr = Field(description="The address to sign in with; stored in lower case.")
    password: NewPassword = Field(description="12 to 128 characters.")
    organization_name: OrganizationName = Field(
        description="The organization this account starts with; the person becomes its owner."
    )


class LoginRequest(BaseModel):
    email: EmailStr
    password: Password
    organization_id: uuid.UUID | None = Field(
        default=None,
        description="Required when the person is a member of more than one organization.",
    )


class RefreshRequest(BaseModel):
    refresh_token: Annotated[str, Field(min_length=1, max_length=256)]


class UserOut(BaseModel):
    id: uuid.UUID
    email: str


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str


class MembershipOut(BaseModel):
    organization: OrganizationOut
    role: Role


class TokenResponse(BaseModel):
    """A new pair of tokens and what they are for."""

    token_type: Literal["bearer"] = "bearer"
    access_token: str = Field(description="Send as `Authorization: Bearer <access_token>`.")
    expires_in: int = Field(description="Seconds until the access token expires.")
    refresh_token: str = Field(description="Good for one `POST /auth/refresh`, then spent.")
    refresh_expires_in: int = Field(description="Seconds until the refresh token expires.")
    user: UserOut
    organization: OrganizationOut
    role: Role


class MeResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut
    role: Role


class OrganizationChoice(BaseModel):
    detail: str
    organizations: list[MembershipOut]


class Problem(BaseModel):
    detail: str


def _tokens(signed_in: SignedIn) -> TokenResponse:
    now = datetime.now(UTC)
    return TokenResponse(
        access_token=signed_in.access_token,
        expires_in=round((signed_in.access_expires_at - now).total_seconds()),
        refresh_token=signed_in.refresh_token,
        refresh_expires_in=round((signed_in.refresh_expires_at - now).total_seconds()),
        user=UserOut(id=signed_in.user.id, email=signed_in.user.email),
        organization=OrganizationOut(
            id=signed_in.organization.id, name=signed_in.organization.name
        ),
        role=signed_in.role,
    )


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Create an account and its organization",
    description="Creates the account, an organization owned by it, and signs the person in.",
    responses={status.HTTP_409_CONFLICT: {"model": Problem, "description": "E-mail taken."}},
)
async def register(body: RegisterRequest, session: Session, tokens: Tokens) -> TokenResponse:
    try:
        signed_in = await service.register(
            session,
            tokens,
            email=body.email,
            password=body.password,
            organization_name=body.organization_name,
        )
    except service.EmailTakenError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "an account with this e-mail address exists already"
        ) from None
    return _tokens(signed_in)


@router.post(
    "/login",
    summary="Sign in",
    description=(
        "Checks the e-mail address and password and returns tokens for one organization. A "
        "member of several organizations names one in `organization_id`; without it the "
        "answer is 409 with the list to choose from."
    ),
    response_model=TokenResponse,
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": Problem, "description": "Wrong credentials."},
        status.HTTP_403_FORBIDDEN: {"model": Problem, "description": "Not a member."},
        status.HTTP_409_CONFLICT: {
            "model": OrganizationChoice,
            "description": "Several organizations; choose one.",
        },
    },
)
async def login(body: LoginRequest, session: Session, tokens: Tokens) -> TokenResponse | Response:
    try:
        signed_in = await service.login(
            session,
            tokens,
            email=body.email,
            password=body.password,
            organization_id=body.organization_id,
        )
    except service.AuthenticationError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid e-mail address or password",
            headers=_UNAUTHORIZED,
        ) from None
    except service.NotAMemberError:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "not a member of this organization"
        ) from None
    except service.OrganizationRequiredError as choice:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=OrganizationChoice(
                detail="choose an organization: send its id as organization_id",
                organizations=[
                    MembershipOut(
                        organization=OrganizationOut(id=organization.id, name=organization.name),
                        role=role,
                    )
                    for organization, role in choice.memberships
                ],
            ).model_dump(mode="json"),
        )
    return _tokens(signed_in)


@router.post(
    "/refresh",
    summary="Exchange a refresh token for a new pair",
    description=(
        "Spends the refresh token and returns a new access token and a new refresh token for "
        "the same session. A refresh token presented a second time ends the session."
    ),
    responses={status.HTTP_401_UNAUTHORIZED: {"model": Problem}},
)
async def refresh(body: RefreshRequest, session: Session, tokens: Tokens) -> TokenResponse:
    try:
        signed_in = await service.refresh(session, tokens, refresh_token=body.refresh_token)
    except service.InvalidRefreshTokenError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "invalid or expired refresh token",
            headers=_UNAUTHORIZED,
        ) from None
    return _tokens(signed_in)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign out",
    description="Ends the session of the refresh token; an unknown token changes nothing.",
)
async def logout(body: RefreshRequest, session: Session) -> None:
    await service.logout(session, refresh_token=body.refresh_token)


@router.get(
    "/me",
    summary="Who am I",
    description=(
        "The person, organization and role of the access token; 401 once the account or its "
        "membership is gone."
    ),
    responses={status.HTTP_401_UNAUTHORIZED: {"model": Problem}},
)
async def me(
    principal: Annotated[Principal, Depends(current_principal)], session: Session
) -> MeResponse:
    row = (
        await session.execute(
            select(User, Organization)
            .join(Membership, Membership.user_id == User.id)
            .join(Organization, Organization.id == Membership.organization_id)
            .where(User.id == principal.user_id, Organization.id == principal.organization_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "the account or its membership no longer exists",
            headers=_UNAUTHORIZED,
        )
    user, organization = row
    return MeResponse(
        user=UserOut(id=user.id, email=user.email),
        organization=OrganizationOut(id=organization.id, name=organization.name),
        role=principal.role,
    )
