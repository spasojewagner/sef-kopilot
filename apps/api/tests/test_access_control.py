"""Access control across the whole API, checked against the application's real routes so that a
new endpoint cannot slip past it.

- Every route is one the audit understands: an API route, one of FastAPI's documentation
  pages, or the MCP endpoint behind its own guard (``RequireCredential``; its tools and what each
  requires are audited in ``test_mcp.py``). A mounted application or a websocket route fails
  the audit until it is guarded and added here.
- Every endpoint is public by name, open by name to any signed-in caller, or guarded by a
  permission. What each guarded endpoint requires is pinned in ``GUARDED``: the permission,
  and whether it changes the members and so checks the role again under the organization's
  lock. A member whose role lacks the permission is refused (403).
- Every guarded endpoint has a cross-tenant case: another organization's owner, who holds every
  permission there is, tries it on this organization's data and finds nothing. The owner's API
  key, which holds every permission a key may hold, finds nothing either, and is refused the
  endpoints that no key may use.
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
from sef_api.auth.permissions import KEY_PERMISSIONS, ROLE_PERMISSIONS, Permission
from sef_api.billing import ledger
from sef_api.main import create_app
from sef_api.mcp.access import RequireCredential
from sef_api.members import invitations
from sef_api.models import (
    ApiKey,
    AuditEvent,
    Invitation,
    Job,
    Membership,
    ModelKey,
    Organization,
    RefreshToken,
    Repair,
    Role,
    SefKey,
    SefSubmission,
    StoredInvoice,
    User,
)

from .conftest import REPOSITORY_ROOT, settings_for
from .documents import picture
from .factories import (
    KEYRING,
    Key,
    Office,
    api_key,
    bearer,
    job,
    model_key,
    office,
    sef_key,
    stored_invoice,
)

Endpoint = tuple[str, str]

#: A valid synthetic SEF invoice, for the endpoints that take a document.
INVOICE = REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "srb-final-invoice.xml"

#: Primer's key to SEF, and the one Ogled's owner sets for Ogled.
PRIMER_SEF_KEY, OGLED_SEF_KEY = "primer-sef-key-4711", "ogled-sef-key-0815"
#: Primer's own key to a model, and the one Ogled's owner sets for Ogled.
PRIMER_MODEL_KEY, OGLED_MODEL_KEY = "primer-model-key-4711", "ogled-model-key-0815"

#: Endpoints anyone may call: probes, and the ways to obtain or end a session.
PUBLIC: set[Endpoint] = {
    ("GET", "/health"),
    ("GET", "/ready"),
    ("POST", "/auth/register"),
    ("POST", "/auth/login"),
    ("POST", "/auth/accept-invitation"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    # How an MCP client registers itself with the authorization server (RFC 7591), where it
    # sends a person to be asked, and where it exchanges what it was given for tokens.
    ("POST", "/oauth/register"),
    ("GET", "/oauth/authorize"),
    ("POST", "/oauth/token"),
    # The documents that send a client there (RFC 9728, RFC 8414).
    ("GET", "/.well-known/oauth-protected-resource/mcp"),
    ("GET", "/.well-known/oauth-protected-resource"),
    ("GET", "/.well-known/oauth-authorization-server"),
    # Where Stripe sends its events, each verified by its signature before anything is read.
    ("POST", "/billing/stripe-events"),
}
#: Endpoints for any signed-in caller, about the caller only.
SIGNED_IN: set[Endpoint] = {
    ("GET", "/auth/me"),
    # A person decides, for themselves, what a client may do for them.
    ("GET", "/oauth/requests/{request_id}"),
    ("POST", "/oauth/requests/{request_id}/approval"),
    ("POST", "/oauth/requests/{request_id}/refusal"),
}


@dataclass(frozen=True)
class Walked:
    endpoints: dict[Endpoint, APIRoute]
    #: The routes to the MCP endpoint, each behind the guard that admits API keys.
    mcp: list[str]
    #: Routes that are none of the above, nor FastAPI's documentation pages.
    unknown: list[BaseRoute]


def walk(app: FastAPI) -> Walked:
    documentation = {
        app.openapi_url,
        app.docs_url,
        app.redoc_url,
        app.swagger_ui_oauth2_redirect_url,
    }
    found: dict[Endpoint, APIRoute] = {}
    mcp: list[str] = []
    unknown: list[BaseRoute] = []

    def visit(routes: Iterable[BaseRoute]) -> None:
        for route in routes:
            if isinstance(route, APIRoute):
                found.update({(method, route.path): route for method in route.methods or ()})
            elif (included := getattr(route, "original_router", None)) is not None:
                # FastAPI keeps an included router as one route that holds it.
                visit(included.routes)
            elif type(route) is Route and isinstance(route.endpoint, RequireCredential):
                mcp.append(route.path)
            elif not (type(route) is Route and route.path in documentation):
                unknown.append(route)

    visit(app.routes)
    return Walked(found, mcp, unknown)


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
    """Two organizations. Primer has an open invitation, a stored invoice, its client's API key,
    a job the client started, a key to SEF, its own key to a model and credits the operator
    gave; Ogled's owner has a key with every permission a key may hold."""

    primer: Office
    ogled: Office
    invitation: Invitation
    invoice: StoredInvoice
    key: Key
    ogled_key: Key
    job: Job


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
    key = await api_key(
        session,
        primer.organization,
        primer.client,
        Permission.INVOICES_VALIDATE,
        Permission.INVOICES_SUBMIT,
    )
    ogled_key = await api_key(session, ogled.organization, ogled.owner)
    started = await job(session, primer.organization, primer.client)
    await sef_key(session, primer.organization, PRIMER_SEF_KEY)
    await model_key(session, primer.organization, PRIMER_MODEL_KEY)
    await ledger.grant(session, primer.organization.id, ledger.CreditTerms(starting=0), count=5)
    return World(primer, ogled, issued.invitation, invoice, key, ogled_key, started)


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
    media_type: str = "application/xml"

    async def send(self, api: AsyncClient, method: str, world: World, **headers: str) -> Response:
        """The request, with a JSON body, or a document of its media type: an XML invoice, or
        a PDF or a picture of one."""
        if isinstance(self.body, bytes):
            headers["Content-Type"] = self.media_type
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
    await _the_world_as_it_was(session)


async def _rules_are_everyones(response: Response, session: AsyncSession, w: World) -> None:
    """The rules are the published rule sets', the same for every organization; looking them up
    leaves no trace."""
    assert response.status_code == 200
    assert response.json()["rule" if "rule" in response.json() else "rules"]
    await _the_world_as_it_was(session)


async def _explanation_keeps_nothing(response: Response, session: AsyncSession, w: World) -> None:
    """An explanation answers with the report and its explanations, and leaves no trace."""
    assert response.status_code == 200
    assert response.json()["report"]["profile"] == "srb"
    await _the_world_as_it_was(session)


async def _reading_keeps_nothing(response: Response, session: AsyncSession, w: World) -> None:
    """A document read answers with its fields, read by the server's model, not by the model of
    the organization whose key that is, and leaves no trace."""
    assert response.status_code == 200
    assert response.json()["model"] == "test/reading"
    assert response.json()["fields"]["number"] == "RF-2026-000123"
    await _the_world_as_it_was(session)


async def _drafting_keeps_nothing(response: Response, session: AsyncSession, w: World) -> None:
    """A draft answers with the invoice its fields make, and leaves no trace."""
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/xml"
    await _the_world_as_it_was(session)


async def _the_world_as_it_was(session: AsyncSession) -> None:
    counts = {
        model.__tablename__: await session.scalar(select(func.count()).select_from(model))
        for model in (
            Organization,
            User,
            Membership,
            Invitation,
            RefreshToken,
            StoredInvoice,
            ApiKey,
            Job,
        )
    }
    assert counts == {
        "organizations": 2,
        "users": 6,
        "memberships": 6,
        "invitations": 1,
        "refresh_tokens": 0,
        "invoices": 1,
        "api_keys": 2,
        "jobs": 1,
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


async def _primers_invoice_takes_no_repair(
    response: Response, session: AsyncSession, w: World
) -> None:
    await _primers_invoice_is_not_found(response, session, w)
    assert await session.scalar(select(func.count()).select_from(Repair)) == 0


async def _primers_invoice_is_not_decided(
    response: Response, session: AsyncSession, w: World
) -> None:
    """Nothing is decided for Primer: another organization's member finds no such invoice, and
    its API key is refused, as every key is, before anything is looked up."""
    assert (response.status_code, response.json()["detail"]) in {
        (404, "no such invoice in this organization"),
        (
            403,
            "a person decides on a repair: sign in to decide, an API key or an MCP client cannot",
        ),
    }
    assert await session.scalar(select(func.count()).select_from(AuditEvent)) == 0


async def _primers_invoice_is_not_sent(response: Response, session: AsyncSession, w: World) -> None:
    """Primer's invoice is not found, and nothing is sent to SEF in anyone's name."""
    assert response.status_code == 404
    assert await session.scalar(select(func.count()).select_from(SefSubmission)) == 0


async def _primers_invoice_is_not_found(
    response: Response, session: AsyncSession, w: World
) -> None:
    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such invoice in this organization"},
    )


async def _revalidating_in_ogled(response: Response, session: AsyncSession, w: World) -> None:
    """A revalidation is started for the caller in the caller's organization; Primer's job is
    as it was."""
    assert response.status_code == 202
    started = (
        await session.execute(
            select(Job.organization_id, Job.submitted_by).where(Job.id == response.json()["id"])
        )
    ).one()
    assert tuple(started) == (w.ogled.organization.id, w.ogled.owner.id)
    primers = (
        await session.execute(select(Job.status, Job.version).where(Job.id == w.job.id))
    ).one()
    assert tuple(primers) == ("queued", 0)


async def _primers_job_is_not_found(response: Response, session: AsyncSession, w: World) -> None:
    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such job in this organization"},
    )


async def _issued_in_ogled(response: Response, session: AsyncSession, w: World) -> None:
    """A key is issued for the caller in the caller's organization; Primer's are as they were."""
    assert response.status_code == 201
    assert response.json()["acts_for"] == str(w.ogled.owner.id)
    holders = (await session.execute(select(ApiKey.organization_id, ApiKey.user_id))).all()
    assert sorted(holders) == sorted(
        [
            (w.primer.organization.id, w.primer.client.id),
            (w.ogled.organization.id, w.ogled.owner.id),
            (w.ogled.organization.id, w.ogled.owner.id),
        ]
    )


async def _lists_only_ogleds_keys(response: Response, session: AsyncSession, w: World) -> None:
    assert [key["id"] for key in response.json()] == [str(w.ogled_key.row.id)]


async def _primers_key_still_works(response: Response, session: AsyncSession, w: World) -> None:
    assert (response.status_code, response.json()) == (
        404,
        {"detail": "no such API key in this organization"},
    )
    assert await session.scalar(select(ApiKey.revoked_at).where(ApiKey.id == w.key.row.id)) is None


async def _shows_ogled(response: Response, session: AsyncSession, w: World) -> None:
    assert response.status_code == 200
    assert response.json()["id"] == str(w.ogled.organization.id)


async def _primer_keeps_its_invoices(response: Response, session: AsyncSession, w: World) -> None:
    """Ogled's owner sets Ogled's period; Primer keeps its invoices as it did."""
    assert (response.status_code, response.json()["id"]) == (200, str(w.ogled.organization.id))
    periods = dict(
        (await session.execute(select(Organization.id, Organization.invoice_retention_days))).all()
    )
    assert periods == {w.primer.organization.id: None, w.ogled.organization.id: 1}


async def sef_keys(session: AsyncSession) -> dict[str, str]:
    """The organizations' SEF keys, opened, by the organizations' names."""
    stored = await session.execute(
        select(Organization.id, Organization.name, SefKey.token).join(SefKey)
    )
    return {
        name: KEYRING.open(organization_id, token).get_secret_value()
        for organization_id, name, token in stored.all()
    }


async def _primer_keeps_its_sef_key(response: Response, session: AsyncSession, w: World) -> None:
    """Ogled's owner sets Ogled's key; Primer's is as it was."""
    assert response.status_code == 200
    assert await sef_keys(session) == {
        "Primer Računovodstvo": PRIMER_SEF_KEY,
        "Ogled": OGLED_SEF_KEY,
    }


async def _primers_sef_key_stays(response: Response, session: AsyncSession, w: World) -> None:
    """Ogled's owner removes Ogled's key, which it has not; Primer's stays."""
    assert response.status_code == 204
    assert await sef_keys(session) == {"Primer Računovodstvo": PRIMER_SEF_KEY}


async def model_keys(session: AsyncSession) -> dict[str, str]:
    """The organizations' own keys to a model, opened, by the organizations' names."""
    stored = await session.execute(
        select(Organization.id, Organization.name, ModelKey.token).join(ModelKey)
    )
    return {
        name: KEYRING.open(organization_id, token, "model").get_secret_value()
        for organization_id, name, token in stored.all()
    }


async def _primer_keeps_its_model_key(response: Response, session: AsyncSession, w: World) -> None:
    """Ogled's owner sets Ogled's key to a model; Primer's is as it was."""
    assert response.status_code == 200
    assert await model_keys(session) == {
        "Primer Računovodstvo": PRIMER_MODEL_KEY,
        "Ogled": OGLED_MODEL_KEY,
    }


async def _primers_model_key_stays(response: Response, session: AsyncSession, w: World) -> None:
    """Ogled's owner removes Ogled's key to a model, which it has not; Primer's stays."""
    assert response.status_code == 204
    assert await model_keys(session) == {"Primer Računovodstvo": PRIMER_MODEL_KEY}


async def _billing_is_off(response: Response, session: AsyncSession, w: World) -> None:
    """Billing is off on the audit's server: no organization's credits are shown; whose are
    shown where it is on is tested with billing (test_billing.py)."""
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "balance": None,
        "starting": None,
        "per_invoice": None,
        "packs": [],
    }


async def _sells_nothing(response: Response, session: AsyncSession, w: World) -> None:
    """The audit's server sells no credits; a checkout is for the caller's own organization,
    tested with Stripe (test_stripe.py)."""
    assert response.status_code == 503


async def _lists_none_of_primers_credits(
    response: Response, session: AsyncSession, w: World
) -> None:
    """Ogled's owner lists Ogled's ledger, which is empty, and none of Primer's grant."""
    assert response.status_code == 200
    assert response.json() == []


GUARDED: dict[Endpoint, Guarded] = {
    ("GET", "/jobs/{job_id}"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/jobs/{w.job.id}",
        None,
        _primers_job_is_not_found,
    ),
    ("GET", "/jobs/{job_id}/events"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/jobs/{w.job.id}/events",
        None,
        _primers_job_is_not_found,
    ),
    ("GET", "/api-keys"): Guarded(
        Permission.API_KEYS_ISSUE, False, lambda _: "/api-keys", None, _lists_only_ogleds_keys
    ),
    ("DELETE", "/api-keys/{key_id}"): Guarded(
        Permission.API_KEYS_ISSUE,
        False,
        lambda w: f"/api-keys/{w.key.row.id}",
        None,
        _primers_key_still_works,
    ),
    ("POST", "/api-keys"): Guarded(
        Permission.API_KEYS_ISSUE,
        False,
        lambda _: "/api-keys",
        {"name": "ERP", "permissions": ["invoices:validate"]},
        _issued_in_ogled,
    ),
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
    ("POST", "/invoices/revalidations"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda _: "/invoices/revalidations",
        None,
        _revalidating_in_ogled,
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
    ("POST", "/invoices/{invoice_id}/explanations"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/explanations",
        None,
        _primers_invoice_is_not_found,
    ),
    ("GET", "/invoices/{invoice_id}/explanations"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/explanations",
        None,
        _primers_invoice_is_not_found,
    ),
    ("POST", "/invoices/{invoice_id}/repairs"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/repairs",
        {"patches": [{"xpath": "/ubl:Invoice/cbc:Note", "op": "remove", "reason": "why"}]},
        _primers_invoice_takes_no_repair,
    ),
    ("POST", "/invoices/{invoice_id}/repairs/suggestion"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/repairs/suggestion",
        None,
        _primers_invoice_takes_no_repair,
    ),
    ("POST", "/invoices/{invoice_id}/sef"): Guarded(
        Permission.INVOICES_SEND,
        False,
        lambda w: f"/invoices/{w.invoice.id}/sef",
        None,
        _primers_invoice_is_not_sent,
    ),
    ("GET", "/invoices/{invoice_id}/sef"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/sef",
        None,
        _primers_invoice_is_not_found,
    ),
    ("GET", "/invoices/{invoice_id}/repairs"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/repairs",
        None,
        _primers_invoice_is_not_found,
    ),
    ("GET", "/invoices/{invoice_id}/repairs/{repair_id}"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/repairs/{w.invoice.id}",
        None,
        _primers_invoice_is_not_found,
    ),
    ("POST", "/invoices/{invoice_id}/repairs/{repair_id}/approval"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/repairs/{w.invoice.id}/approval",
        None,
        _primers_invoice_is_not_decided,
    ),
    ("POST", "/invoices/{invoice_id}/repairs/{repair_id}/rejection"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda w: f"/invoices/{w.invoice.id}/repairs/{w.invoice.id}/rejection",
        None,
        _primers_invoice_is_not_decided,
    ),
    ("POST", "/invoices/validate"): Guarded(
        Permission.INVOICES_VALIDATE,
        False,
        lambda _: "/invoices/validate",
        INVOICE.read_bytes(),
        _validation_keeps_nothing,
    ),
    ("POST", "/invoices/explain"): Guarded(
        Permission.INVOICES_VALIDATE,
        False,
        lambda _: "/invoices/explain",
        INVOICE.read_bytes(),
        _explanation_keeps_nothing,
    ),
    ("POST", "/invoices/extract"): Guarded(
        Permission.INVOICES_VALIDATE,
        False,
        lambda _: "/invoices/extract",
        picture(),
        _reading_keeps_nothing,
        media_type="image/jpeg",
    ),
    ("POST", "/invoices/draft"): Guarded(
        Permission.INVOICES_VALIDATE,
        False,
        lambda _: "/invoices/draft",
        {"number": "RF-2026-000123", "issue_date": "2026-10-05"},
        _drafting_keeps_nothing,
    ),
    ("GET", "/rules"): Guarded(
        Permission.INVOICES_VALIDATE, False, lambda _: "/rules?q=BR-01", None, _rules_are_everyones
    ),
    ("GET", "/rules/{rule_id}"): Guarded(
        Permission.INVOICES_VALIDATE, False, lambda _: "/rules/BR-01", None, _rules_are_everyones
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
    ("GET", "/organization"): Guarded(
        Permission.ORGANIZATION_READ, False, lambda _: "/organization", None, _shows_ogled
    ),
    ("PATCH", "/organization"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/organization",
        {"invoice_retention_days": 1},
        _primer_keeps_its_invoices,
    ),
    ("PUT", "/organization/sef-key"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/organization/sef-key",
        {"api_key": OGLED_SEF_KEY},
        _primer_keeps_its_sef_key,
    ),
    ("DELETE", "/organization/sef-key"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/organization/sef-key",
        None,
        _primers_sef_key_stays,
    ),
    ("PUT", "/organization/model-key"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/organization/model-key",
        {"provider": "openai", "api_key": OGLED_MODEL_KEY},
        _primer_keeps_its_model_key,
    ),
    ("DELETE", "/organization/model-key"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/organization/model-key",
        None,
        _primers_model_key_stays,
    ),
    ("GET", "/billing"): Guarded(
        Permission.INVOICES_SUBMIT,
        False,
        lambda _: "/billing",
        None,
        _billing_is_off,
    ),
    ("GET", "/billing/entries"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/billing/entries",
        None,
        _lists_none_of_primers_credits,
    ),
    ("POST", "/billing/checkout"): Guarded(
        Permission.ORGANIZATION_MANAGE,
        False,
        lambda _: "/billing/checkout",
        {"credits": 100},
        _sells_nothing,
    ),
}


def lacking(permission: Permission) -> list[Role]:
    return [role for role in Role if permission not in ROLE_PERMISSIONS[role]]


# --- the audit ---------------------------------------------------------------------------------


def test_every_route_is_one_the_audit_understands(app: FastAPI) -> None:
    walked = walk(app)

    assert walked.unknown == []
    assert walked.mcp == ["/mcp"]


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


@pytest.mark.parametrize(
    "endpoint", sorted(e for e in GUARDED if GUARDED[e].permission in KEY_PERMISSIONS), ids=" ".join
)
async def test_an_api_key_cannot_reach_into_another_organization(
    api: AsyncClient, session: AsyncSession, world: World, endpoint: Endpoint
) -> None:
    guarded = GUARDED[endpoint]

    response = await guarded.send(api, endpoint[0], world, **world.ogled_key.header())

    await guarded.cross_tenant(response, session, world)


@pytest.mark.parametrize(
    "endpoint",
    sorted(e for e in GUARDED if GUARDED[e].permission not in KEY_PERMISSIONS),
    ids=" ".join,
)
async def test_an_api_key_is_refused_what_no_key_may_do(
    api: AsyncClient, world: World, endpoint: Endpoint
) -> None:
    guarded = GUARDED[endpoint]

    response = await guarded.send(api, endpoint[0], world, **world.ogled_key.header())

    assert response.status_code == 403
    assert response.json() == {"detail": f"requires the permission {guarded.permission}"}


async def test_a_token_for_an_organization_the_caller_does_not_belong_to_is_refused(
    api: AsyncClient, world: World
) -> None:
    """Should a token ever name the wrong organization, the membership check still holds."""
    wrong = bearer(world.ogled.owner, world.primer.organization, Role.OWNER)

    response = await api.get("/members", headers=wrong)

    assert response.status_code == 401
