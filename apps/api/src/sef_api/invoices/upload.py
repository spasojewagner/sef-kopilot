"""Reading an invoice, or a document to read one from, from a request body, within the limits.

The body is the document itself: an invoice as ``application/xml`` (or ``text/xml``), a PDF or a
picture of one (``application/pdf``, ``image/jpeg``, ``image/png``, ``image/webp``) to be read
into an invoice's fields (ADR-0062). It is read in chunks and refused (413) as soon as it grows
past the limit, whether or not the client declared its length, so an oversized upload is never
held in memory whole; a declared length over the limit is refused before anything is read. A
body that does not arrive within the time allowed is refused (408), so that a client sending it
slowly does not hold the request open. Any other media type is refused (415). What the bytes
contain is the business of whoever reads them: unreadable XML, a DOCTYPE or an entity is a
violation in the validator's report, because its parser refuses them (``einvoice_core.xml``);
a PDF or a picture is opened by :mod:`sef_api.extraction.documents`.
"""

from __future__ import annotations

import asyncio
from typing import Final

from fastapi import HTTPException, Request, status

__all__ = [
    "DOCUMENT_MEDIA_TYPES",
    "UPLOAD_MEDIA_TYPES",
    "XML_MEDIA_TYPES",
    "read_document",
    "read_invoice",
]

#: The media types an invoice may be sent as.
XML_MEDIA_TYPES: Final = frozenset({"application/xml", "text/xml"})
#: The media types of a document an invoice is read from: a PDF, or a picture of one.
DOCUMENT_MEDIA_TYPES: Final = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/webp"}
)
#: Every media type read here, in chunks within its own limit, and so not by
#: :class:`sef_api.bodies.LimitBodies`.
UPLOAD_MEDIA_TYPES: Final = XML_MEDIA_TYPES | DOCUMENT_MEDIA_TYPES


def media_type_of(request: Request) -> str:
    """The request body's media type, without its parameters, in lower case."""
    return request.headers.get("content-type", "").split(";", 1)[0].strip().lower()


async def _read(request: Request, *, limit: int, seconds: float, what: str) -> bytes:
    too_large = HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE, f"the {what} is larger than {limit} bytes"
    )
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    body = bytearray()
    try:
        async with asyncio.timeout(seconds):
            async for chunk in request.stream():
                body += chunk
                if len(body) > limit:
                    raise too_large
    except TimeoutError:
        raise HTTPException(
            status.HTTP_408_REQUEST_TIMEOUT, f"the {what} was not received within {seconds:g} s"
        ) from None
    return bytes(body)


async def read_invoice(request: Request, *, limit: int, seconds: float) -> bytes:
    """The request body, if it is XML, at most ``limit`` bytes long and received within
    ``seconds``."""
    if media_type_of(request) not in XML_MEDIA_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "send the invoice as the request body, with Content-Type: application/xml",
        )
    return await _read(request, limit=limit, seconds=seconds, what="invoice")


async def read_document(request: Request, *, limit: int, seconds: float) -> tuple[str, bytes]:
    """The request body and its media type, if it is a PDF or a picture, at most ``limit``
    bytes long and received within ``seconds``."""
    media_type = media_type_of(request)
    if media_type not in DOCUMENT_MEDIA_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "send the PDF or the picture as the request body, with Content-Type: "
            "application/pdf, image/jpeg, image/png or image/webp",
        )
    return media_type, await _read(request, limit=limit, seconds=seconds, what="document")
