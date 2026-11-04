"""Access control across the whole API, checked against the application's real routes so that a
new endpoint cannot slip past it.

- Every route is one the audit understands: an API route, or one of FastAPI's documentation
  pages. A mounted application or a websocket route fails the audit until it is guarded and
  added here.
- Every endpoint is public by name, open by name to any signed-in caller, or guarded by a
  permission. What each guarded endpoint requires is pinned in ``GUARDED``: the permission,
  and whether it changes the members and so checks the role again under the organization's
  lock. A member whose role lacks the permission is refused (403).
- Every guarded endpoint has a cross-tenant case: another organization's owner, who holds every
  permission there is, tries it on this organization's data and finds nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import BaseRoute, Route

from sef_api.auth.dependencies import current_principal, require
from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.main import create_app
from sef_api.members import invitations
from sef_api.models import (
    Invitation,
    Membership,
    Organization,
    RefreshToken,
    Role,
    StoredInvoice,
    User,
)

from .conftest import REPOSITORY_ROOT, settings_for
from .factories import Office, bearer, office, stored_invoice

Endpoint = tuple[str, str]

#: A valid synthetic SEF invoice, for the endpoints that take a document.
INVOICE = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "srb-final-invoice.xml"

#: Endpoints anyone may call: probes, and the ways to obtain or end a session.
PUBLIC: set[Endpoint] = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/accept-invitation"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
}
#: Endpoints for any signed-in caller, about the caller only.
SIGNED_IN: set[Endpoint] = {("GET", "/auth/me")}


@dataclass(frozen=True)
class Walked:
    endpoints: dict[Endpoint, APIRoute]
    #: Routes that are neither API routes nor FastAPI's documentation pages.
    unknown: list[BaseRoute]


def walk(app: FastAPI) -> Walked:
    documentation = {
        app.openapi_url,
        app.docs_url,
        app.redoc_url,
        app.swagger_ui_oauth2_redirect_url,
    }
    found: dict[Endpoint, APIRoute] = {}
    unknown: list[BaseRoute] = []

    def visit(routes: Iterable[BaseRoute]) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                found.update({(method, route.path): route for method in route.methods or ()})
            elif (included := getattr(route, "original_router", None)) is not None:
                # FastAPI keeps an included router as one route that holds it.
                visit(included.routes)
            elif not (type(route) is Route and route.path in documentation):
                unknown.append(route)

    visit(app.routes)
    return Walked(found, unknown)


def calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from calls(dependency)


def requirements(route: APIRoute) -> set[tuple[Permission, bool]]:
    """The permissions a route requires, each with whether it changes the members."""
    used = set(calls(route.dependant))
    return {
        (permission, changes)
        for permission in Permission
        for changes in (False, True)
        if require(permission, changes_members=changes) in used
    }


@pytest.fixture(scope="module")
def app() -> FastAPI:
    return create_app(settings_for())


# --- the world the cases run in ----------------------------------------------------------------


@dataclass(frozen=True)
class World:
    """Two organizations; Primer has an open invitation and a stored invoice."""

    primer: Office
    ogled: Office
    invitation: Invitation
    invoice: StoredInvoice


@pytest.fixture
async def world(session: AsyncSession) -> World:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    ogled = await office(session, "Ogled", "ogled.example")
    issued = await invitations.invite(
        session,
        primer.organization.id,
        primer.owner.id,
        email="nova@primer.example",
        role=Role.ACCOUNTANT,
    )
    invoice = await stored_invoice(session, primer.organization, primer.client)
    return World(primer, ogled, issued.invitation, invoice)


async def role_in_primer(session: AsyncSession, world: World, user_id: Any) -> Role | None:
    return await session.scalar(
        select(Membership.role).where(
            Membership.organization_id == world.primer.organization.id,
            Membership.user_id == user_id,
        )
    )


async def primer_invitation_is_open(session: AsyncSession, world: World) -> bool:
    revoked = await session.scalar(
        select(Invitation.revoked_at).where(Invitation.id == world.invitation.id)
    )
    return revoked is None


# --- the guarded endpoints ---------------------------------------------------------------------

CrossTenantCheck = Callable[[Response, AsyncSession, World], Awaitable[None]]


@dataclass(frozen=True)
class Guarded:
    """A guarded endpoint: the permission it requires, whether it changes the members, a request
    for Primer's data, and what must hold after another organization's owner has made it."""

    permission: Permission
    changes_members: bool
    url: Callable[[World], str]
    body: dict[str, Any] | bytes | None
    cross_tenant: CrossTenantCheck

    async def send(self, api: AsyncClient, method: str, world: World, **headers: str) -> Response:
        """The request, with a JSON body or an XML document."""
        if isinstance(self.body, bytes):
            headers["Content-Type"] = "application/xml"
            return await api.request(method, self.url(world), content=self.body, headers=headers)
        return await api.request(method, self.url(world), json=self.body, headers=headers)


async def _lists_only_ogleds_members(response: Response, session: AsyncSession, w: World) -> None:
    assert {item["user"]["email"] for item in response.json()} == {
        "owner@ogled.example",
        "accountant@ogled.example",
        "client@ogled.example",
    }


async def _primers_client_keeps_the_role(
    response: Response, session: AsyncSession, w: World
) -> None:
    assert response.status_code == 404
    assert await role_in_primer(session, w, w.primer.client.id) is Role.CLIENT


async def _primers_accountant_stays(response: Response, session: AsyncSession, w: World) -> None:
    assert response.status_code == 404
    assert await role_in_primer(session, w, w.primer.accountant.id) is Role.ACCOUNTANT


async def _lists_no_invitations(response: Response, session: AsyncSession, w: World) -> None:
    assert response.json() == []


async def _primers_invitation_stays_open(
    response: Response, session: AsyncSession, w: World
) -> None:
    """Inviting the address Primer invited is Ogled's own business; Primer's stays open."""
    assert response.status_code == 201
    assert await primer_invitation_is_open(session, w)


async def _primers_invitation_is_not_found(
    response: Response, session: AsyncSession, w: World
) -> None:
    assert response.status_code == 404
    assert await primer_invitation_is_open(session, w)


async def _validation_keeps_nothing(response: Response, session: AsyncSession, w: World) -> None:
    """A validation answers with its report and leaves no trace in any organization."""
    assert response.status_code == 200
    assert response.json()["profile"] == "srb"
    counts = {
        model.__tablename__: await session.scalar(select(func.count()).select_from(model))
        for model in (Organization, User, Membership, Invitation, RefreshToken, StoredInvoice)
    }
    assert counts == {
        "organizations": 2,
        "users": 6,
        "memberships": 6,
        "invitations": 1,
        "refresh_tokens": 0,
        "invoices": 1,
    }


async def _stored_in_ogled(response: Response, session: AsyncSession, w: World) -> None:
    """An invoice is stored in the caller's organization; Primer's are as they were."""
    assert response.status_code == 201
    stored = (await session.scalars(select(StoredInvoice.organization_id))).all()
    assert sorted(map(str, stored)) == sorted(
        [str(w.primer.organization.id), str(w.ogled.organization.id)]
    )


async def _primers_invoice_stays(response: Response, session: AsyncSession, w: World) -> None:
    assert response.status_code == 404
    assert await session.scalar(select(StoredInvoice.id)) == w.invoice.id


async def _lists_no_invoices(response: Response, session: AsyncSession, w: World) -> None:
    assert response.json() == {"invoices": [], "next": None}


async def _primers_invoice_is_not_found(
    response: Response, session: AsyncSession, w: World
) -> None:
    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such invoice in this organization"},
    )


GUARDED: dict[Endpoint, Guarded] = {
    ("POST", "/invoices"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda _: "/invoices",
        INVOICE.read_bytes(),
        _stored_in_ogled,
    ),
    ("GET", "/invoices"): Guarded(
        Permission.INVOICES_SUBMIT, False, lambda _: "/invoices", None, _lists_no_invoices
    ),
    ("GET", "/invoices/{invoice_id}"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}",
        None,
        _primers_invoice_is_not_found,
    ),
    ("DELETE", "/invoices/{invoice_id}"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}",
        None,
        _primers_invoice_stays,
    ),
    ("GET", "/invoices/{invoice_id}/content"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/content",
        None,
        _primers_invoice_is_not_found,
    ),
    ("POST", "/invoices/validate"): Guarded(
        Permission.INVOICES_VALIDATE,
        False,
        lambda _: "/invoices/validate",
        INVOICE.read_bytes(),
        _validation_keeps_nothing,
    ),
    ("GET", "/members"): Guarded(
        Permission.MEMBERS_READ, False, lambda _: "/members", None, _lists_only_ogleds_members
    ),
    ("PATCH", "/members/{user_id}"): Guarded(
        Permission.MEMBERS_MANAGE,
        True,
        lambda w: f"/members/{w.primer.client.id}",
        {"role": "owner"},
        _primers_client_keeps_the_role,
    ),
    ("DELETE", "/members/{user_id}"): Guarded(
        Permission.MEMBERS_MANAGE,
        True,
        lambda w: f"/members/{w.primer.accountant.id}",
        None,
        _primers_accountant_stays,
    ),
    ("GET", "/invitations"): Guarded(
        Permission.MEMBERS_MANAGE, False, lambda _: "/invitations", None, _lists_no_invitations
    ),
    ("POST", "/invitations"): Guarded(
        Permission.MEMBERS_MANAGE,
        True,
        lambda _: "/invitations",
        {"email": "nova@primer.example", "role": "client"},
        _primers_invitation_stays_open,
    ),
    ("DELETE", "/invitations/{invitation_id}"): Guarded(
        Permission.MEMBERS_MANAGE,
        True,
        lambda w: f"/invitations/{w.invitation.id}",
        None,
        _primers_invitation_is_not_found,
    ),
}


def lacking(permission: Permission) -> list[Role]:
    return [role for role in Role if permission not in ROLE_PERMISSIONS[role]]


# --- the audit ---------------------------------------------------------------------------------


def test_every_route_is_one_the_audit_understands(app: FastAPI) -> None:
    assert walk(app).unknown == []


def test_the_audit_sees_every_operation_the_api_documents(app: FastAPI) -> None:
    documented = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }

    assert set(walk(app).endpoints) == documented


def test_every_endpoint_is_public_signed_in_or_guarded_as_pinned(app: FastAPI) -> None:
    required = {endpoint: requirements(route) for endpoint, route in walk(app).endpoints.items()}

    assert {e for e, needs in required.items() if not needs} == PUBLIC | SIGNED_IN
    assert {e: needs for e, needs in required.items() if needs} == {
        endpoint: {(guarded.permission, guarded.changes_members)}
        for endpoint, guarded in GUARDED.items()
    }


def test_public_endpoints_need_no_access_token_and_signed_in_ones_do(app: FastAPI) -> None:
    routes = walk(app).endpoints

    assert [e for e in sorted(PUBLIC) if current_principal in set(calls(routes[e].dependant))] == []
    assert all(current_principal in set(calls(routes[e].dependant)) for e in SIGNED_IN)


# --- the requests ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("endpoint", "role"),
    [(e, role) for e in sorted(GUARDED) for role in lacking(GUARDED[e].permission)],
    ids=lambda value: " ".join(value) if isinstance(value, tuple) else str(value),
)
async def test_a_member_whose_role_lacks_the_permission_is_refused(
    api: AsyncClient, world: World, endpoint: Endpoint, role: Role
) -> None:
    guarded = GUARDED[endpoint]
    member = {Role.ACCOUNTANT: world.primer.accountant, Role.CLIENT: world.primer.client}[role]

    response = await guarded.send(
        api, endpoint[0], world, **bearer(member, world.primer.organization, role)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": f"requires the permission {guarded.permission}"}


@pytest.mark.parametrize("endpoint", sorted(GUARDED), ids=" ".join)
async def test_an_organization_cannot_reach_into_another(
    api: AsyncClient, session: AsyncSession, world: World, endpoint: Endpoint
) -> None:
    guarded = GUARDED[endpoint]

    response = await guarded.send(api, endpoint[0], world, **world.ogled.as_owner())

    await guarded.cross_tenant(response, session, world)


async def test_a_token_for_an_organization_the_caller_does_not_belong_to_is_refused(
    api: AsyncClient, world: World
) -> None:
    """Should a token ever name the wrong organization, the membership check still holds."""
    wrong = bearer(world.ogled.owner, world.primer.organization, Role.OWNER)

    response = await api.get("/members", headers=wrong)

    assert response.status_code == 401
