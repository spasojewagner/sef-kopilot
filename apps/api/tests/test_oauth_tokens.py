"""``/oauth/token``: a code a consent issued exchanged for tokens, and a refresh token for new
ones (OAuth 2.1 §4.1.3 and §4.3, ADR-0044); the access token is for the MCP endpoint alone."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType

import jwt
import pytest
from httpx import AsyncClient, Response
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth import tokens as web_tokens
from sef_api.auth.permissions import Permission
from sef_api.auth.tokens import opaque_token_digest
from sef_api.models import Membership, OAuthAuthorization, OAuthRefreshToken, Role, User
from sef_api.oauth import authorization as authorizations
from sef_api.oauth import tokens as oauth_tokens

from .conftest import TEST_JWT_SECRET
from .factories import Office, office
from .test_invoices_validate import application
from .test_oauth_authorization import (
    CALLBACK,
    ISSUER,
    VERIFIER,
    authorize,
    sent_to,
    sent_to_uri,
    server,
)

RESOURCE = f"{ISSUER}/mcp"
#: What an MCP client registers: a code for tokens, and refresh tokens for new ones.
GRANTS = ("authorization_code", "refresh_token")
#: The characters an error's description may hold (RFC 6749 §5.2).
DESCRIBABLE = {chr(c) for c in (0x20, 0x21, *range(0x23, 0x5C), *range(0x5D, 0x7F))}


async def registered(api: AsyncClient, *uris: str, grants: tuple[str, ...] = GRANTS) -> str:
    response = await api.post(
        "/oauth/register",
        json={"redirect_uris": list(uris or [CALLBACK]), "grant_types": list(grants)},
    )
    assert response.status_code == 201
    return str(response.json()["client_id"])


async def consented(
    api: AsyncClient,
    primer: Office,
    *uris: str,
    as_owner: bool = False,
    scope: str | None = None,
    grants: tuple[str, ...] = GRANTS,
) -> tuple[str, str]:
    """A client's id, and the code the consent of one of Primer's members issued it."""
    client = await registered(api, *uris, grants=grants)
    _, query = sent_to(await authorize(api, client, scope=scope))
    approved = await api.post(
        f"/oauth/requests/{query['request']}/approval",
        headers=primer.as_owner() if as_owner else primer.as_client(),
    )
    assert approved.status_code == 200
    _, answer = sent_to_uri(approved.json()["redirect_uri"])
    return client, answer["code"]


def exchange(client: str, code: str, /, **changes: str | None) -> dict[str, str | None]:
    return {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client,
        "code_verifier": VERIFIER,
        "redirect_uri": CALLBACK,
        "resource": RESOURCE,
    } | changes


def renewal(client: str, refresh_token: str, /, **changes: str | None) -> dict[str, str | None]:
    return {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client,
        "resource": RESOURCE,
    } | changes


async def token(api: AsyncClient, form: dict[str, str | None]) -> Response:
    return await api.post(
        "/oauth/token", data={name: value for name, value in form.items() if value is not None}
    )


def refused(response: Response) -> tuple[int, str]:
    """The status and the error of an answer that refuses, which no cache keeps and whose
    description holds only the characters OAuth allows, never what the client sent."""
    assert response.headers["Cache-Control"] == "no-store"
    assert set(response.json()["error_description"]) <= DESCRIBABLE
    return response.status_code, response.json()["error"]


async def consent_of(session: AsyncSession, code_or_id: str) -> OAuthAuthorization:
    found = await session.scalar(
        select(OAuthAuthorization).where(
            (OAuthAuthorization.id == code_or_id)
            | (OAuthAuthorization.code_sha256 == opaque_token_digest(code_or_id))
        )
    )
    assert found is not None
    await session.refresh(found)
    return found


# --- a code for tokens -------------------------------------------------------------------------


async def test_a_code_is_exchanged_for_tokens_for_the_mcp_endpoint(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        consent_id = (await consent_of(session, code)).id
        answer = await token(api, exchange(client, code))

    assert answer.status_code == 200
    assert (answer.headers["Cache-Control"], answer.headers["Pragma"]) == ("no-store", "no-cache")
    issued = answer.json()
    assert (issued["token_type"], issued["expires_in"], issued["scope"]) == (
        "Bearer",
        900,
        "invoices:validate",
    )
    assert jwt.get_unverified_header(issued["access_token"])["typ"] == "at+jwt"
    claims = oauth_tokens.decode_access_token(
        issued["access_token"], issuer=ISSUER, audience=RESOURCE, secret=TEST_JWT_SECRET
    )
    assert (claims.user_id, claims.organization_id, claims.client_id) == (
        primer.client.id,
        primer.organization.id,
        client,
    )
    assert (claims.scopes, claims.authorization_id) == (("invoices:validate",), consent_id)
    assert timedelta(minutes=14) < claims.expires_at - datetime.now(UTC) <= timedelta(minutes=15)
    # The refresh token is kept as its digest, never as itself.
    kept = await session.scalar(select(OAuthRefreshToken))
    assert kept is not None
    assert kept.digest == opaque_token_digest(issued["refresh_token"])
    assert kept.authorization_id == consent_id
    assert (await consent_of(session, consent_id)).exchanged_at is not None


async def test_the_access_token_is_for_the_mcp_endpoint_alone(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        access = (await token(api, exchange(client, code))).json()["access_token"]
    web, _ = web_tokens.issue_access_token(
        primer.client.id,
        primer.organization.id,
        Role.CLIENT,
        secret=TEST_JWT_SECRET,
        lifetime=timedelta(minutes=15),
    )

    with pytest.raises(web_tokens.InvalidTokenError):
        web_tokens.decode_access_token(access, secret=TEST_JWT_SECRET)
    with pytest.raises(oauth_tokens.InvalidTokenError):
        oauth_tokens.decode_access_token(
            web, issuer=ISSUER, audience=RESOURCE, secret=TEST_JWT_SECRET
        )
    for issuer, audience in ((ISSUER, f"{ISSUER}/other"), ("https://other.example", RESOURCE)):
        with pytest.raises(oauth_tokens.InvalidTokenError):
            oauth_tokens.decode_access_token(
                access, issuer=issuer, audience=audience, secret=TEST_JWT_SECRET
            )
    # Signed with a key of its own: the API's key itself does not verify it.
    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(access, TEST_JWT_SECRET, algorithms=["HS256"], audience=RESOURCE)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"code_verifier": "x" * 43}, "invalid_grant"),
        ({"code_verifier": "too-short"}, "invalid_request"),
        ({"client_id": "another-client"}, "invalid_grant"),
        ({"redirect_uri": "https://assistant.example/elsewhere"}, "invalid_grant"),
        ({"resource": f"{ISSUER}/api"}, "invalid_target"),
        ({"code": "not-a-code-this-server-issued"}, "invalid_grant"),
        ({"code": None}, "invalid_request"),
        ({"code_verifier": None}, "invalid_request"),
    ],
)
async def test_a_code_will_not_do_with_anything_but_what_began_it(
    session: AsyncSession, changes: dict[str, str | None], error: str
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        answer = await token(api, exchange(client, code, **changes))
        # What will not do spends nothing: the code still does, once.
        after = await token(api, exchange(client, code))

    assert refused(answer) == (400, error)
    assert after.status_code == 200


async def test_the_resource_is_compared_as_resources_are(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        answer = await token(api, exchange(client, code, resource="HTTPS://API.example/mcp/"))

    assert answer.status_code == 200


async def test_a_code_presented_twice_revokes_every_token_it_led_to(
    session: AsyncSession,
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        first = await token(api, exchange(client, code))
        second = await token(api, exchange(client, code))
        renewed = await token(api, renewal(client, first.json()["refresh_token"]))

    assert first.status_code == 200
    assert refused(second) == (400, "invalid_grant")
    assert second.json()["error_description"] == (
        "the code was used already: every token it led to is revoked"
    )
    assert refused(renewed) == (400, "invalid_grant")
    assert (await consent_of(session, code)).revoked_at is not None


async def test_an_expired_code_will_not_do(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        await session.execute(
            update(OAuthAuthorization)
            .where(OAuthAuthorization.code_sha256 == opaque_token_digest(code))
            .values(code_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        answer = await token(api, exchange(client, code))

    assert refused(answer) == (400, "invalid_grant")
    assert answer.json()["error_description"] == "the code has expired"


async def test_the_redirect_uri_may_be_left_out_since_pkce_binds_the_code(
    session: AsyncSession,
) -> None:
    """OAuth 2.1 §4.1.3: given, it must be the one the code was sent to; left out, the code is
    still bound to whoever began, by its verifier."""
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        one, code = await consented(api, primer)
        two, other = await consented(api, primer, CALLBACK, "https://assistant.example/second")
        with_one = await token(api, exchange(one, code, redirect_uri=None))
        with_two = await token(api, exchange(two, other, redirect_uri=None))

    assert (with_one.status_code, with_two.status_code) == (200, 200)


async def test_a_client_that_did_not_register_refreshes_gets_no_refresh_token(
    session: AsyncSession,
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer, grants=("authorization_code",))
        answer = await token(api, exchange(client, code))
        consent_id = (await consent_of(session, code)).id
        # Were it to hold one, from before the rule, it could not spend it.
        held = "a-refresh-token-of-a-client-without-the-grant"
        session.add(
            OAuthRefreshToken(
                authorization_id=consent_id,
                digest=opaque_token_digest(held),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        await session.flush()
        renewed = await token(api, renewal(client, held))

    assert answer.status_code == 200
    assert "refresh_token" not in answer.json()
    assert (
        await session.scalar(
            select(OAuthRefreshToken).where(OAuthRefreshToken.digest != opaque_token_digest(held))
        )
        is None
    )
    assert refused(renewed) == (400, "unauthorized_client")


async def test_a_resource_that_is_no_uri_is_the_wrong_target(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        exchanged = await token(api, exchange(client, code, resource="http://["))
        first = (await token(api, exchange(client, code))).json()
        renewed = await token(api, renewal(client, first["refresh_token"], resource="http://["))

    assert refused(exchanged) == (400, "invalid_target")
    assert refused(renewed) == (400, "invalid_target")


async def test_a_consent_given_to_the_server_at_another_address_issues_nothing(
    session: AsyncSession,
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
    async with server(session, SEF_PUBLIC_URL="https://moved.example") as api:
        answer = await token(api, exchange(client, code, resource=None))

    assert refused(answer) == (400, "invalid_grant")


async def test_the_role_is_read_again_when_the_code_is_exchanged(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
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
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    owner = primer.owner.id
    async with server(session) as api:
        client, code = await consented(
            api, primer, as_owner=True, scope="invoices:validate members:manage"
        )
        # The owner becomes an accountant between the consent and the exchange.
        await session.execute(
            update(Membership).where(Membership.user_id == owner).values(role=Role.ACCOUNTANT)
        )
        answer = await token(api, exchange(client, code))

    assert answer.json()["scope"] == "invoices:validate"


# --- a refresh token for new ones --------------------------------------------------------------


async def test_a_refresh_token_is_spent_once_and_replaced(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        first = (await token(api, exchange(client, code))).json()
        second = await token(api, renewal(client, first["refresh_token"]))
        third = await token(api, renewal(client, second.json()["refresh_token"]))

    assert (second.status_code, third.status_code) == (200, 200)
    assert len({first["refresh_token"], second.json()["refresh_token"]}) == 2
    kept = (await session.scalars(select(OAuthRefreshToken))).all()
    assert len(kept) == 3
    assert sum(token.used_at is None for token in kept) == 1


async def test_a_refresh_token_presented_again_revokes_the_consent(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        first = (await token(api, exchange(client, code))).json()
        second = (await token(api, renewal(client, first["refresh_token"]))).json()
        replayed = await token(api, renewal(client, first["refresh_token"]))
        # The token the rightful client holds now is revoked with the rest.
        latest = await token(api, renewal(client, second["refresh_token"]))

    assert refused(replayed) == (400, "invalid_grant")
    assert replayed.json()["error_description"] == (
        "the refresh token was used already: every token of the consent is revoked"
    )
    assert refused(latest) == (400, "invalid_grant")
    assert latest.json()["error_description"] == "the consent was revoked"


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"client_id": "another-client"}, "invalid_grant"),
        ({"refresh_token": "not-one-this-server-issued"}, "invalid_grant"),
        ({"resource": f"{ISSUER}/api"}, "invalid_target"),
        ({"scope": "invoices:validate invoices:submit"}, "invalid_scope"),
        ({"scope": " "}, "invalid_scope"),
        ({"scope": 'invoices:validate "quoted"'}, "invalid_scope"),
        ({"client_id": None}, "invalid_request"),
    ],
)
async def test_a_refresh_will_not_do_with_anything_but_the_consent(
    session: AsyncSession, changes: dict[str, str | None], error: str
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        refresh_token = (await token(api, exchange(client, code))).json()["refresh_token"]
        answer = await token(api, renewal(client, refresh_token, **changes))
        after = await token(api, renewal(client, refresh_token))

    assert refused(answer) == (400, error)
    assert after.status_code == 200


async def test_an_expired_refresh_token_will_not_do(session: AsyncSession) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(api, primer)
        refresh_token = (await token(api, exchange(client, code))).json()["refresh_token"]
        await session.execute(
            update(OAuthRefreshToken).values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
        answer = await token(api, renewal(client, refresh_token))

    assert refused(answer) == (400, "invalid_grant")
    assert answer.json()["error_description"] == "the refresh token has expired"


async def test_a_refresh_may_ask_for_fewer_scopes_and_the_role_is_read_again(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
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
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    async with server(session) as api:
        client, code = await consented(
            api, primer, as_owner=True, scope="invoices:validate members:manage"
        )
        both = (await token(api, exchange(client, code))).json()
        fewer = (
            await token(api, renewal(client, both["refresh_token"], scope="invoices:validate"))
        ).json()
        # The owner becomes an accountant: managing members is no longer the role's to grant.
        await session.execute(
            update(Membership)
            .where(Membership.user_id == primer.owner.id)
            .values(role=Role.ACCOUNTANT)
        )
        demoted = (await token(api, renewal(client, fewer["refresh_token"]))).json()

    assert both["scope"] == "invoices:validate members:manage"
    assert fewer["scope"] == "invoices:validate"
    assert demoted["scope"] == "invoices:validate"


async def test_a_member_no_longer_active_or_no_longer_a_member_gets_no_tokens(
    session: AsyncSession,
) -> None:
    primer = await office(session, "Primer Računovodstvo", "primer.example")
    # Read before a refused request rolls the session back, which expires what it holds.
    person = primer.client.id
    async with server(session) as api:
        client, code = await consented(api, primer)
        refresh_token = (await token(api, exchange(client, code))).json()["refresh_token"]
        await session.execute(update(User).where(User.id == person).values(is_active=False))
        inactive = await token(api, renewal(client, refresh_token))
        await session.execute(update(User).where(User.id == person).values(is_active=True))
        await session.execute(delete(Membership).where(Membership.user_id == person))
        removed = await token(api, renewal(client, refresh_token))

    assert refused(inactive) == (400, "invalid_grant")
    # Why is the member's business, not the client's.
    assert inactive.json()["error_description"] == "the consent no longer grants any scope"
    # The consent and its tokens went with the membership.
    assert refused(removed) == (400, "invalid_grant")
    assert await session.scalar(select(OAuthRefreshToken)) is None


# --- the request itself ------------------------------------------------------------------------


async def test_a_token_request_is_a_form_naming_each_parameter_once(
    session: AsyncSession,
) -> None:
    async with server(session) as api:
        as_json = await api.post("/oauth/token", json={"grant_type": "authorization_code"})
        twice = await api.post(
            "/oauth/token",
            content="grant_type=refresh_token&client_id=a&client_id=b",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        once_empty = await api.post(
            "/oauth/token",
            content="grant_type=&grant_type=refresh_token&client_id=a&refresh_token=b",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        not_utf8 = await api.post(
            "/oauth/token",
            content="grant_type=refresh_token&client_id=%FF%FE",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        crowded = await api.post(
            "/oauth/token",
            content="&".join(f"p{n}=v" for n in range(21)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        nameless = await token(api, {"client_id": "a"})
        password = await token(api, {"grant_type": "password", "client_id": "a"})

    for answer in (as_json, twice, once_empty, not_utf8, crowded, nameless):
        assert refused(answer) == (400, "invalid_request")
    assert twice.json()["error_description"] == "a parameter is given more than once"
    assert once_empty.json()["error_description"] == "a parameter is given more than once"
    assert not_utf8.json()["error_description"] == "the body is no form"
    assert crowded.json()["error_description"] == "the body is no form"
    assert refused(password) == (400, "unsupported_grant_type")


async def test_token_requests_are_counted_by_address(session: AsyncSession) -> None:
    async with server(session) as api:
        answers = [(await token(api, {})).status_code for _ in range(61)]

    assert answers == [400] * 60 + [429]


async def test_without_a_public_url_there_are_no_tokens(session: AsyncSession) -> None:
    async with application(session) as api:
        answer = await token(api, {"grant_type": "authorization_code"})

    assert (answer.status_code, answer.json()) == (
        404,
        {"detail": "this server has no authorization server"},
    )
    assert answer.headers["Cache-Control"] == "no-store"
