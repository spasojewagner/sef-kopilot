"""Clients known by a metadata document (ADR-0045): the fetch, which reaches only the public
internet and reads only a small JSON document, and the authorization requests of such clients."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Sequence
from functools import partial
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.main import create_app
from sef_api.models import OAuthClient
from sef_api.oauth import documents
from sef_api.oauth.documents import DocumentError

from .conftest import settings_for
from .test_invoices_validate import application
from .test_oauth_authorization import CALLBACK, SERVER, authorize

#: A client's metadata document, at a host of the public internet.
DOCUMENT_URL = "https://assistant.example/oauth/client.json"
PUBLIC = "93.184.215.14"


def described(**changes: Any) -> dict[str, Any]:
    """A metadata document that will do, with ``changes``."""
    return {
        "client_id": DOCUMENT_URL,
        "client_name": "Asistent",
        "redirect_uris": [CALLBACK],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
    } | changes


class Host:
    """The client's host as a test plays it: what its name resolves to, and how it answers."""

    def __init__(
        self,
        *addresses: str,
        answer: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> None:
        self.addresses = list(addresses or [PUBLIC])
        self.answer = answer or (lambda _: answer_of()())
        self.resolved: list[tuple[str, int]] = []
        self.asked: list[httpx.Request] = []

    async def resolve(self, host: str, port: int) -> Sequence[str]:
        self.resolved.append((host, port))
        return self.addresses

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.asked.append(request)
        return self.answer(request)

    def fetch(self, client_id: str = DOCUMENT_URL) -> Any:
        return documents.fetch(
            client_id, resolve=self.resolve, transport=httpx.MockTransport(self.handle)
        )

    def fetcher(self) -> Any:
        return partial(
            documents.fetch, resolve=self.resolve, transport=httpx.MockTransport(self.handle)
        )


async def test_the_document_is_fetched_from_the_address_checked() -> None:
    host = Host()

    document = await host.fetch()

    assert (document.client_name, document.redirect_uris) == ("Asistent", [CALLBACK])
    assert host.resolved == [("assistant.example", 443)]
    (request,) = host.asked
    # To the address that was checked, with the host's name for TLS and in the request.
    assert str(request.url) == f"https://{PUBLIC}/oauth/client.json"
    assert request.extensions["sni_hostname"] == "assistant.example"
    assert request.headers["Host"] == "assistant.example"
    assert request.headers["Accept-Encoding"] == "identity"


@pytest.mark.parametrize(
    "client_id",
    [
        "https://assistant.example",
        "https://assistant.example/",
        "https://assistant.example/client.json?version=2",
        "https://assistant.example/client.json#me",
        "https://someone@assistant.example/client.json",
        "https://assistant.example/a/../client.json",
        "https://assistant.example/./client.json",
        "https://[::1/client.json",
        "https://assistant.example:99999/client.json",
        f"https://assistant.example/{'x' * 1000}",
    ],
)
async def test_only_a_url_a_client_may_be_known_by_is_fetched(client_id: str) -> None:
    host = Host()

    with pytest.raises(DocumentError, match="client_id"):
        await host.fetch(client_id)

    assert host.resolved == []


@pytest.mark.parametrize(
    "addresses",
    [
        ["127.0.0.1"],
        ["10.0.0.7"],
        ["172.16.4.2"],
        ["192.168.1.10"],
        ["169.254.169.254"],  # a cloud's metadata service
        ["100.64.0.1"],
        ["0.0.0.0"],
        ["::1"],
        ["fc00::1"],
        ["fe80::1%eth0"],
        ["::ffff:127.0.0.1"],
        ["224.0.0.1"],
        # One address of the server's own network among public ones is one too many.
        [PUBLIC, "10.0.0.7"],
        [],
    ],
)
async def test_a_host_off_the_public_internet_is_not_asked(addresses: list[str]) -> None:
    host = Host(*addresses) if addresses else Host()
    host.addresses = addresses

    with pytest.raises(DocumentError, match="not on the public internet"):
        await host.fetch()

    assert host.asked == []


async def test_a_host_that_does_not_resolve_is_not_asked() -> None:
    async def nowhere(host: str, port: int) -> Sequence[str]:
        raise OSError("no such host")

    with pytest.raises(DocumentError, match="does not resolve"):
        await documents.fetch(DOCUMENT_URL, resolve=nowhere)


class Unread(httpx.AsyncByteStream):
    """A body as it comes, which nothing decodes on the way."""

    def __init__(self, body: bytes) -> None:
        self.body = body

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self.body


def answer_of(
    status: int = 200, body: bytes | None = None, **headers: str
) -> Callable[[], httpx.Response]:
    """An answer, made when a test runs: ``body`` as it comes, JSON by default."""
    sent = json.dumps(described()).encode() if body is None else body
    named = {"Content-Type": "application/json"} | {
        name.replace("_", "-"): value for name, value in headers.items()
    }
    return lambda: httpx.Response(status, headers=named, stream=Unread(sent))


def json_of(**changes: Any) -> Callable[[], httpx.Response]:
    return answer_of(body=json.dumps(described(**changes)).encode())


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        # A redirect is not followed: it could lead anywhere, the server's own network included.
        (answer_of(302, Location="https://10.0.0.7/client.json"), "was answered 302"),
        (answer_of(404), "was answered 404"),
        (answer_of(Content_Type="text/html"), "not application/json"),
        (answer_of(Content_Encoding="gzip"), "came encoded"),
        (json_of(logo_uri="y" * 6000), "larger than 5120 bytes"),
        (answer_of(body=b"{"), "not JSON"),
        (json_of(client_id="https://assistant.example/other.json"), "names another client_id"),
        (json_of(client_secret="s3cret"), "client_secret"),
        (json_of(token_endpoint_auth_method="client_secret_basic"), "token_endpoint_auth_method"),
        (json_of(client_name=None), "client_name"),
        (json_of(redirect_uris=["http://assistant.example/back"]), "redirect_uris"),
        (answer_of(body=json.dumps([described()]).encode()), "the document"),
    ],
)
async def test_an_answer_that_is_no_document_will_not_do(
    answer: Callable[[], httpx.Response], reason: str
) -> None:
    host = Host(answer=lambda _: answer())

    with pytest.raises(DocumentError, match=reason):
        await host.fetch()

    assert len(host.asked) == 1


async def test_a_host_that_cannot_be_reached_says_so() -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(DocumentError, match="could not be fetched"):
        await Host(answer=refused).fetch()


async def test_a_slow_host_is_given_up_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(documents, "FETCH_SECONDS", 0.05)

    async def slowly(host: str, port: int) -> Sequence[str]:
        await asyncio.sleep(1)
        return [PUBLIC]

    with pytest.raises(DocumentError, match="did not come within"):
        await documents.fetch(
            DOCUMENT_URL, resolve=slowly, transport=httpx.MockTransport(Host().handle)
        )


def fetching(host: Host) -> Callable[[FastAPI], None]:
    """Lets the application fetch documents from ``host``."""

    def change(app: FastAPI) -> None:
        app.state.client_documents = host.fetcher()

    return change


async def test_a_client_known_by_its_document_is_asked_about(session: AsyncSession) -> None:
    host = Host()
    enabled = SERVER | {"SEF_CLIENT_METADATA_DOCUMENTS": "true"}

    async with application(session, fetching(host), **enabled) as api:
        first = await authorize(api, DOCUMENT_URL)
        host.answer = lambda _: json_of(client_name="Asistent 2")()
        second = await authorize(api, DOCUMENT_URL)

    assert (first.status_code, second.status_code) == (302, 302)
    assert first.headers["Location"].startswith(f"{SERVER['SEF_WEB_URL']}/oauth/consent?request=")
    # Read at each request: the client is as its document says now.
    assert len(host.asked) == 2
    client = await session.get(OAuthClient, DOCUMENT_URL, populate_existing=True)
    assert client is not None
    assert (client.name, client.redirect_uris, client.grant_types) == (
        "Asistent 2",
        [CALLBACK],
        ["authorization_code", "refresh_token"],
    )


async def test_a_document_that_will_not_do_stops_the_request(session: AsyncSession) -> None:
    host = Host(answer=lambda _: answer_of(404)())
    enabled = SERVER | {"SEF_CLIENT_METADATA_DOCUMENTS": "true"}

    async with application(session, fetching(host), **enabled) as api:
        answer = await authorize(api, DOCUMENT_URL)

    # No redirect URI can be trusted: the browser is told here.
    assert (answer.status_code, answer.json()) == (
        400,
        {"detail": "the client's metadata document was answered 404"},
    )
    assert await session.get(OAuthClient, DOCUMENT_URL) is None


async def test_without_documents_such_a_client_is_unknown(session: AsyncSession) -> None:
    """Off by default: a self-hosted server calls out to nothing it did not choose, and a client
    once known by its document, while they were fetched, is unknown now."""
    session.add(
        OAuthClient(
            id=DOCUMENT_URL,
            name="Asistent",
            redirect_uris=[CALLBACK],
            grant_types=["authorization_code"],
        )
    )
    await session.flush()
    served: list[FastAPI] = []

    async with application(session, served.append, **SERVER) as api:
        answer = await authorize(api, DOCUMENT_URL)

    assert served[0].state.client_documents is None
    assert (answer.status_code, answer.json()) == (
        400,
        {"detail": "no client is registered with this client_id"},
    )


def test_the_setting_lets_the_server_fetch() -> None:
    app = create_app(settings_for(**SERVER, SEF_CLIENT_METADATA_DOCUMENTS="true"))

    assert app.state.client_documents is documents.fetch


async def test_authorization_requests_are_counted_by_address(session: AsyncSession) -> None:
    """Each may make the server fetch a document: a stranger cannot make it fetch at will."""
    host = Host()
    enabled = SERVER | {"SEF_CLIENT_METADATA_DOCUMENTS": "true"}

    async with application(session, fetching(host), **enabled) as api:
        answers = [(await authorize(api, DOCUMENT_URL)).status_code for _ in range(31)]

    assert answers == [302] * 30 + [429]
    assert len(host.asked) == 30
