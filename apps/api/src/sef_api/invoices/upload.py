"""Reading an invoice from a request body, within the limits.

The body is the document itself, sent as ``application/xml`` (or ``text/xml``). It is read in
chunks and refused (413) as soon as it grows past the limit, whether or not the client declared
its length, so an oversized upload is never held in memory whole; a declared length over the
limit is refused before anything is read. A body that does not arrive within the time allowed
is refused (408), so that a client sending it slowly does not hold the request open. Any other
media type is refused (415). What the bytes contain is the validator's business: unreadable
XML, a DOCTYPE or an entity is a violation in its report, because its parser refuses them
(``einvoice_core.xml``).
"""

from __future__ import annotations

import asyncio
from typing import Final

from fastapi import HTTPException, Request, status

__all__ = ["XML_MEDIA_TYPES", "read_invoice"]

#: The media types an invoice may be sent as.
XML_MEDIA_TYPES: Final = frozenset({"application/xml", "text/xml"})


def _too_large(limit: int) -> HTTPException:
    return HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE, f"the invoice is larger than {limit} bytes"
    )


async def read_invoice(request: Request, *, limit: int, seconds: float) -> bytes:
    """The request body, if it is XML, at most ``limit`` bytes long and received within
    ``seconds``."""
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in XML_MEDIA_TYPES:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "send the invoice as the request body, with Content-Type: application/xml",
        )
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large(limit)
    body = bytearray()
    try:
        async with asyncio.timeout(seconds):
            async for chunk in request.stream():
                body += chunk
                if len(body) > limit:
                    raise _too_large(limit)
    except TimeoutError:
        raise HTTPException(
            status.HTTP_408_REQUEST_TIMEOUT, f"the invoice was not received within {seconds:g} s"
        ) from None
    return bytes(body)
