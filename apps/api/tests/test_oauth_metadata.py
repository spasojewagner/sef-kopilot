"""The documents that send an MCP client to the authorization server: the endpoint's protected
resource metadata (RFC 9728) and the server's own (RFC 8414)."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from .test_invoices_validate import application
from .test_oauth_authorization import ISSUER, server


@pytest.mark.parametrize(
    "path", ["/.well-known/oauth-protected-resource/mcp", "/.well-known/oauth-protected-resource"]
)
async def test_the_mcp_endpoint_names_its_authorization_server(
    session: AsyncSession, path: str
) -> None:
    async with server(session) as api:
        answer = await api.get(path, headers={"Origin": "https://inspector.example"})

    assert answer.status_code == 200
    assert answer.json() == {
        "resource": f"{ISSUER}/mcp",
        "authorization_servers": [ISSUER],
        "scopes_supported": ["invoices:validate"],
        "bearer_methods_supported": ["header"],
        "resource_name": "SEF Kopilot",
    }
    # Public, for a client of any origin, a browser's included.
    assert answer.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize("documents", ["false", "true"])
async def test_the_authorization_server_says_what_it_supports(
    session: AsyncSession, documents: str
) -> None:
    async with server(session, SEF_CLIENT_METADATA_DOCUMENTS=documents) as api:
        answer = await api.get("/.well-known/oauth-authorization-server")

    assert answer.status_code == 200
    assert answer.json() == {
        "issuer": ISSUER,
        "authorization_endpoint": f"{ISSUER}/oauth/authorize",
        "token_endpoint": f"{ISSUER}/oauth/token",
        "registration_endpoint": f"{ISSUER}/oauth/register",
        "scopes_supported": ["invoices:validate"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
        # Clients known by a metadata document, where the operator allows them (ADR-0045).
        "client_id_metadata_document_supported": documents == "true",
    }
    assert answer.headers["Access-Control-Allow-Origin"] == "*"


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
    ],
)
async def test_without_a_public_url_there_are_no_documents(
    session: AsyncSession, path: str
) -> None:
    async with application(session) as api:
        answer = await api.get(path)

    assert (answer.status_code, answer.json()) == (
        404,
        {"detail": "this server has no authorization server"},
    )
