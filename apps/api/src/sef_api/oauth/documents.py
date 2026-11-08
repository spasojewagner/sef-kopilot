"""Clients that introduce themselves by a metadata document (ADR-0045).

A client whose ``client_id`` is an ``https`` URL describes itself in the JSON document at that
URL (draft-ietf-oauth-client-id-metadata-document), and needs no registration. Where the
operator allows it (``SEF_CLIENT_METADATA_DOCUMENTS``), the authorization server fetches the
document at every authorization request, from an address it has checked as public, and reads it
as it reads a registration.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

import httpx
from pydantic import Field, ValidationError, field_validator

from sef_api.oauth.clients import ClientMetadata

__all__ = [
    "MAX_DOCUMENT_BYTES",
    "ClientDocument",
    "DocumentError",
    "Resolver",
    "fetch",
    "is_document_id",
    "resolve_host",
]

#: The largest document read; the draft suggests 5 KiB.
MAX_DOCUMENT_BYTES: Final = 5 * 1024
#: How long the whole fetch may take, from resolving the host to the last byte.
FETCH_SECONDS: Final = 5.0
#: The longest ``client_id`` taken for a document's address.
MAX_CLIENT_ID_LENGTH: Final = 1000
#: The port of ``https``, which a ``Host`` header leaves out.
HTTPS_PORT: Final = 443

#: Resolves a host and a port to the addresses to connect to.
Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


class DocumentError(ValueError):
    """A client's metadata document that could not be fetched, or will not do."""


def is_document_id(client_id: str) -> bool:
    """Whether ``client_id`` names a metadata document rather than a registered client."""
    return client_id.startswith("https://")


def _address_of(client_id: str) -> tuple[str, int]:
    """The host and port of a document's URL, if the URL is one the draft allows a client to be
    identified by; :class:`DocumentError` otherwise."""
    if len(client_id) > MAX_CLIENT_ID_LENGTH:
        raise DocumentError(f"the client_id has more than {MAX_CLIENT_ID_LENGTH} characters")
    try:
        parts = urlsplit(client_id)
        port = parts.port or HTTPS_PORT
    except ValueError:
        raise DocumentError("the client_id is no URL") from None
    segments = parts.path.split("/")
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or "#" in client_id
        or parts.query
        or "?" in client_id
        or parts.path in ("", "/")
        or "." in segments
        or ".." in segments
    ):
        raise DocumentError(
            "the client_id is no URL a client may be identified by: https, a host and a path, "
            "with no user, query, fragment or dot segment"
        )
    return parts.hostname, port


async def resolve_host(host: str, port: int) -> Sequence[str]:
    """The addresses ``host`` resolves to, for a TCP connection to ``port``."""
    found = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in found]


def _public(address: str) -> bool:
    """Whether ``address`` is one of the internet's, and not one of a network of its own: the
    loopback interface, a private or a link-local network, or a reserved block."""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    return ip.is_global and not ip.is_multicast


class ClientDocument(ClientMetadata):
    """A client's metadata document: what a registration says, and the ``client_id`` it is
    published under. A name is required, as MCP asks, and a secret refused."""

    client_id: str
    client_name: str = Field(min_length=1, max_length=100)
    client_secret: None = None
    client_secret_expires_at: None = None

    @field_validator("token_endpoint_auth_method")
    @classmethod
    def _check_auth_method(cls, method: str | None) -> str | None:
        if method not in (None, "none"):
            raise ValueError(
                "every client of this server is public: token_endpoint_auth_method none"
            )
        return method


@dataclass(frozen=True)
class _Answer:
    status: int
    content_type: str
    encoding: str
    body: bytes


async def _get(
    url: str, host: str, port: int, address: str, transport: httpx.AsyncBaseTransport | None
) -> _Answer:
    """GET ``url`` from ``address``, with ``host`` for TLS and its certificate, reading at most
    one byte more than a document may have. The body is read as it came, asked for unencoded:
    a compressed one could hold far more than it weighs."""
    literal = f"[{address}]" if ":" in address else address
    target = urlsplit(url)._replace(netloc=f"{literal}:{port}").geturl()
    async with (
        httpx.AsyncClient(transport=transport, follow_redirects=False, trust_env=False) as http,
        http.stream(
            "GET",
            target,
            headers={
                "Host": host if port == HTTPS_PORT else f"{host}:{port}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
            extensions={"sni_hostname": host},
        ) as answer,
    ):
        body = bytearray()
        async for chunk in answer.aiter_raw():
            body += chunk
            if len(body) > MAX_DOCUMENT_BYTES:
                break
        return _Answer(
            answer.status_code,
            answer.headers.get("content-type", ""),
            answer.headers.get("content-encoding", "identity"),
            bytes(body),
        )


async def fetch(
    client_id: str,
    *,
    resolve: Resolver = resolve_host,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ClientDocument:
    """The metadata document ``client_id`` names, fetched as ADR-0045 says; a
    :class:`DocumentError` that says why it will not do otherwise."""
    host, port = _address_of(client_id)
    try:
        async with asyncio.timeout(FETCH_SECONDS):
            try:
                addresses = await resolve(host, port)
            except OSError:
                raise DocumentError("the client_id's host does not resolve") from None
            if not addresses or not all(_public(address) for address in addresses):
                raise DocumentError("the client_id's host is not on the public internet")
            try:
                answer = await _get(client_id, host, port, addresses[0], transport)
            except httpx.HTTPError:
                raise DocumentError("the client's metadata document could not be fetched") from None
    except TimeoutError:
        raise DocumentError(
            f"the client's metadata document did not come within {FETCH_SECONDS:g} s"
        ) from None
    if answer.status != httpx.codes.OK:
        raise DocumentError(f"the client's metadata document was answered {answer.status}")
    if answer.content_type.partition(";")[0].strip().lower() != "application/json":
        raise DocumentError("the client's metadata document is not application/json")
    if answer.encoding.strip().lower() not in ("", "identity"):
        raise DocumentError("the client's metadata document came encoded, not as it is")
    if len(answer.body) > MAX_DOCUMENT_BYTES:
        raise DocumentError(
            f"the client's metadata document is larger than {MAX_DOCUMENT_BYTES} bytes"
        )
    try:
        content = json.loads(answer.body)
    except ValueError:
        raise DocumentError("the client's metadata document is not JSON") from None
    try:
        document = ClientDocument.model_validate(content)
    except ValidationError as invalid:
        fields = sorted(
            {
                ".".join(str(part) for part in error["loc"]) or "the document"
                for error in invalid.errors()
            }
        )
        raise DocumentError(
            f"the client's metadata document will not do: {', '.join(fields)}"
        ) from None
    if document.client_id != client_id:
        raise DocumentError("the client's metadata document names another client_id")
    return document
