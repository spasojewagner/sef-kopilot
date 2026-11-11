"""The MCP endpoint, for a client that signed its person in with OAuth 2.1 (ADR-0044): the
challenge that sends it to the authorization server, the access tokens it accepts, and what
their scopes, the consent and the member's role allow."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx2
import jwt
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import delete, update

from sef_api.auth import dependencies
from sef_api.auth.permissions import ROLE_PERMISSIONS, Permission
from sef_api.db import Database
from sef_api.models import Membership, Role, User
from sef_api.oauth import authorization as authorizations
from sef_api.oauth import tokens as oauth_tokens

from .conftest import TEST_JWT_SECRET
from .factories import join, organization
from .test_mcp import POSTED, VALID, Served, asking, initialize, serving, text_of
from .test_oauth_authorization import CALLBACK, CHALLENGE, ISSUER, SERVER, VERIFIER
from .test_oauth_documents import DOCUMENT_URL, Host

#: The challenge of a refusal: where the endpoint's metadata is, and the scopes to ask for.
METADATA = f'resource_metadata="{ISSUER}/.well-known/oauth-protected-resource/mcp"'
SCOPE = 'scope="invoices:validate invoices:submit"'
#: The challenge of a refusal of a credential that came and will not do.
INVALID = f'Bearer error="invalid_token", {METADATA}, {SCOPE}'


@pytest.fixture
async def served(committed_database: Database, database_url: str) -> AsyncIterator[Served]:
    async with serving(
        committed_database,
        database_url,
        SEF_PUBLIC_URL=SERVER["SEF_PUBLIC_URL"],
        SEF_WEB_ORIGINS=SERVER["SEF_WEB_ORIGINS"],
        SEF_WEB_URL=SERVER["SEF_WEB_URL"],
    ) as running_app:
        yield running_app


def query_of(uri: str) -> dict[str, str]:
    return {name: values[0] for name, values in parse_qs(urlsplit(uri).query).items()}


async def signed_in(
    served: Served, *, scope: str | None = None, as_owner: bool = False, client: str | None = None
) -> dict[str, Any]:
    """The tokens of a client that registered, or is ``client``, sent its person to be asked,
    and exchanged the code their consent issued: the person is Primer's client, or its owner."""
    async with served.http() as http:
        if client is None:
            registered = await http.post(
                "/oauth/register",
                json={
                    "redirect_uris": [CALLBACK],
                    "grant_types": ["authorization_code", "refresh_token"],
                },
            )
            client = registered.json()["client_id"]
        asked = await http.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client,
                "redirect_uri": CALLBACK,
                "code_challenge": CHALLENGE,
                "code_challenge_method": "S256",
                "state": "xyz",
                **({} if scope is None else {"scope": scope}),
            },
        )
        person = served.primer.as_owner() if as_owner else served.primer.as_client()
        approved = await http.post(
            f"/oauth/requests/{query_of(asked.headers['Location'])['request']}/approval",
            headers=person,
        )
        code = query_of(approved.json()["redirect_uri"])["code"]
        exchanged = await http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client,
                "code_verifier": VERIFIER,
            },
        )
    assert exchanged.status_code == 200
    return {"client": client, "code": code, **exchanged.json()}


def bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@asynccontextmanager
async def connected(served: Served, headers: Mapping[str, str]) -> AsyncIterator[Client]:
    """A client of the SDK, connected to the application with ``headers``."""
    http = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=served.app), base_url="http://test", headers=headers
    )
    async with http, Client(streamable_http_client("http://test/mcp", http_client=http)) as client:
        yield client


async def initialized(served: Served, headers: Mapping[str, str]) -> Any:
    async with served.http({**headers, **POSTED}) as http:
        return await http.post("/mcp", json=initialize())


def assert_refused(answer: Any, detail: str) -> None:
    """``answer`` is a 401 for ``detail``, whose challenge sends the client to sign in again."""
    assert (answer.status_code, answer.json()) == (401, {"detail": detail})
    assert answer.headers["WWW-Authenticate"] == INVALID


async def test_a_client_that_signed_its_person_in_validates_an_invoice(served: Served) -> None:
    tokens = await signed_in(served)

    async with connected(served, bearer(tokens["access_token"])) as client:
        offered = sorted(tool.name for tool in (await client.list_tools()).tools)
        result = await client.call_tool("validate_invoice", {"xml": VALID})

    assert offered == [
        "draft_invoice",
        "explain_errors",
        "explain_invoice",
        "extract_from_pdf",
        "get_invoice",
        "get_job",
        "get_repair",
        "get_rule",
        "get_sef_status",
        "list_invoices",
        "propose_fix",
        "revalidate_invoices",
        "search_rules",
        "send_to_sef_demo",
        "store_invoice",
        "validate_invoice",
    ]
    assert not result.is_error
    assert '"valid":true' in text_of(result).replace(" ", "")


async def test_a_client_known_by_its_document_signs_in_as_well(served: Served) -> None:
    """A client with no registration, whose metadata document the server fetches (ADR-0045),
    goes through every step to a tool call, its URL for a client_id."""
    host = Host()
    served.app.state.client_documents = host.fetcher()
    tokens = await signed_in(served, client=DOCUMENT_URL)

    async with connected(served, bearer(tokens["access_token"])) as client:
        result = await client.call_tool("validate_invoice", {"xml": VALID})

    assert not result.is_error
    assert (
        jwt.decode(tokens["access_token"], options={"verify_signature": False})["client_id"]
        == DOCUMENT_URL
    )
    assert len(host.asked) == 1


async def test_without_a_credential_the_challenge_names_the_metadata(served: Served) -> None:
    anonymous = await initialized(served, {})

    assert (anonymous.status_code, anonymous.json()) == (401, {"detail": "not signed in"})
    assert anonymous.headers["WWW-Authenticate"] == f"Bearer {METADATA}, {SCOPE}"


async def test_a_token_not_issued_for_the_endpoint_is_refused(served: Served) -> None:
    tokens = await signed_in(served)
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    # Signed as the server signs its tokens: only the claims differ.
    key = oauth_tokens._key(TEST_JWT_SECRET)
    for_elsewhere = jwt.encode(
        claims | {"aud": f"{ISSUER}/elsewhere"}, key, headers={"typ": "at+jwt"}
    )
    expired = jwt.encode(
        claims | {"exp": datetime.now(UTC) - timedelta(seconds=1)}, key, headers={"typ": "at+jwt"}
    )

    answers = [
        await initialized(served, served.primer.as_client()),  # the web application's
        await initialized(served, bearer(for_elsewhere)),
        await initialized(served, bearer(expired)),
        await initialized(served, bearer("not-a-token")),
    ]

    for answer in answers:
        assert_refused(answer, "invalid or expired access token")


async def test_a_revoked_consent_stops_its_access_tokens(served: Served) -> None:
    tokens = await signed_in(served)
    before = await initialized(served, bearer(tokens["access_token"]))
    # The code comes back: someone else may hold it, and the consent ends.
    async with served.http() as http:
        replayed = await http.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": tokens["code"],
                "client_id": tokens["client"],
                "code_verifier": VERIFIER,
            },
        )
    after = await initialized(served, bearer(tokens["access_token"]))

    assert before.status_code == 200
    assert replayed.status_code == 400
    assert_refused(after, "the consent behind this access token was revoked")


@pytest.mark.parametrize("claim", ["sub", "org", "client_id"])
async def test_a_token_naming_someone_else_than_its_consent_is_refused(
    served: Served, committed_database: Database, claim: str
) -> None:
    """Were the key ever to sign a token whose person, organization or client is not the
    consent's, the consent read on every request would still refuse it."""
    tokens = await signed_in(served)
    async with committed_database.sessions() as session:
        elsewhere = await organization(session, "Ogledni Biro")
        # The person is a member there too: only the consent stands in the token's way.
        person = await session.get(User, served.primer.client.id)
        assert person is not None
        await join(session, elsewhere, person, Role.CLIENT)
        other_organization = str(elsewhere.id)
        await session.commit()
    claims = jwt.decode(tokens["access_token"], options={"verify_signature": False})
    someone_else = {
        "sub": str(served.primer.owner.id),
        "org": other_organization,
        # A client of the same person, with a consent of its own.
        "client_id": (await signed_in(served))["client"],
    }
    forged = jwt.encode(
        claims | {claim: someone_else[claim]},
        oauth_tokens._key(TEST_JWT_SECRET),
        headers={"typ": "at+jwt"},
    )

    answer = await initialized(served, bearer(forged))

    assert_refused(answer, "the consent behind this access token was revoked")


async def test_a_member_deactivated_or_gone_is_refused(
    served: Served, committed_database: Database
) -> None:
    tokens = await signed_in(served)
    person = served.primer.client.id
    async with committed_database.sessions() as session:
        await session.execute(update(User).where(User.id == person).values(is_active=False))
        await session.commit()
    deactivated = await initialized(served, bearer(tokens["access_token"]))
    async with committed_database.sessions() as session:
        await session.execute(update(User).where(User.id == person).values(is_active=True))
        await session.execute(delete(Membership).where(Membership.user_id == person))
        await session.commit()
    gone = await initialized(served, bearer(tokens["access_token"]))

    # What became of the person is not the client's to know.
    assert_refused(deactivated, "invalid or expired access token")
    # The consent went with the membership.
    assert_refused(gone, "the consent behind this access token was revoked")


async def test_a_token_may_do_what_its_scopes_and_the_role_both_allow(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        authorizations,
        "SCOPES",
        MappingProxyType(
            {
                "invoices:validate": Permission.INVOICES_VALIDATE,
                "members:manage": Permission.MEMBERS_MANAGE,
            }
        ),
    )
    managing = await signed_in(served, scope="members:manage", as_owner=True)
    validating = asking("tools/call", name="validate_invoice", arguments={"xml": VALID})

    async with served.http(bearer(managing["access_token"]) | POSTED) as http:
        refused = await http.post("/mcp", json=validating)

    # The role allows it and the scopes do not: the client is asked to step up, for what it
    # holds and what the tool needs, and the tool never runs (ADR-0046).
    assert (refused.status_code, refused.json()) == (
        403,
        {"detail": "a call needs invoices:validate, which the person has not allowed this client"},
    )
    assert refused.headers["WWW-Authenticate"] == (
        f'Bearer error="insufficient_scope", {METADATA}, scope="invoices:validate members:manage"'
    )


async def test_the_role_that_decides_is_the_members_own_as_it_is_now(
    served: Served, committed_database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool needs its permission in the role the member holds when the request comes, read
    again every time: a token does not carry it, and nothing stands in for it."""
    tokens = await signed_in(served, as_owner=True)
    # A client's role without the permission; an owner's keeps every one.
    monkeypatch.setattr(
        dependencies,
        "ROLE_PERMISSIONS",
        MappingProxyType(
            {
                role: allowed - {Permission.INVOICES_VALIDATE} if role is Role.CLIENT else allowed
                for role, allowed in ROLE_PERMISSIONS.items()
            }
        ),
    )

    async with connected(served, bearer(tokens["access_token"])) as client:
        as_owner = await client.call_tool("validate_invoice", {"xml": VALID})
        async with committed_database.sessions() as session:
            await session.execute(
                update(Membership)
                .where(Membership.user_id == served.primer.owner.id)
                .values(role=Role.CLIENT)
            )
            await session.commit()
        as_client = await client.call_tool("validate_invoice", {"xml": VALID})

    assert not as_owner.is_error
    assert as_client.is_error
    assert text_of(as_client) == (
        "Error executing tool validate_invoice: requires the permission invoices:validate"
    )


async def test_an_api_key_is_still_taken(served: Served) -> None:
    answer = await initialized(served, served.key.header())

    assert answer.status_code == 200


async def test_an_api_key_refused_is_sent_to_sign_in_too(
    served: Served, committed_database: Database
) -> None:
    """A key that does not work, or whose member is no longer active, is refused in the routes'
    words, and with the challenge any refusal here carries."""
    unknown = await initialized(served, bearer(f"{served.key.secret}x"))
    async with committed_database.sessions() as session:
        await session.execute(
            update(User).where(User.id == served.primer.client.id).values(is_active=False)
        )
        await session.commit()
    inactive = await initialized(served, served.key.header())

    assert_refused(unknown, "invalid, expired or revoked API key")
    assert_refused(inactive, "the account or its membership is no longer active")


async def test_an_mcp_client_is_counted_on_its_own(
    committed_database: Database, database_url: str
) -> None:
    """An assistant that runs away holds back itself and the organization, not the person's
    own work: its validations are counted against its consent, apart from theirs."""
    async with serving(
        committed_database,
        database_url,
        SEF_PUBLIC_URL=SERVER["SEF_PUBLIC_URL"],
        SEF_WEB_ORIGINS=SERVER["SEF_WEB_ORIGINS"],
        SEF_WEB_URL=SERVER["SEF_WEB_URL"],
        SEF_VALIDATIONS_PER_MINUTE="1",
    ) as served:
        tokens = await signed_in(served)
        async with connected(served, bearer(tokens["access_token"])) as client:
            first = await client.call_tool("validate_invoice", {"xml": VALID})
            second = await client.call_tool("validate_invoice", {"xml": VALID})
        # The same person, signed in to the web application, has their own count.
        async with served.http(served.primer.as_client()) as http:
            by_the_person = await http.post(
                "/invoices/validate",
                content=VALID.encode(),
                headers={"Content-Type": "application/xml"},
            )

    assert not first.is_error
    assert second.is_error
    assert text_of(second).startswith(
        "Error executing tool validate_invoice: too many validations; try again in "
    )
    assert by_the_person.status_code == 200
