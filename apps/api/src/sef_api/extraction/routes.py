"""``/invoices/extract`` and ``/invoices/draft``: an invoice read from a PDF or a picture, and a
UBL invoice made from its fields once a person confirmed them (ADR-0062, beta).

Two steps, with a person between them. ``extract`` reads a document's fields with the reading
model and answers them; nothing is stored, and nothing of the document outlives the request.
The person checks the fields against the document and corrects them. ``draft`` writes the UBL
invoice those fields describe, in code and without a model; it is then validated, stored,
explained and repaired as any other invoice is, by the endpoints of ``/invoices``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.auth.dependencies import Principal, require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.extraction.documents import (
    Document,
    DocumentTooLargeError,
    UnreadableDocumentError,
    open_document,
)
from sef_api.extraction.draft import draft
from sef_api.extraction.fields import InvoiceFields
from sef_api.extraction.reader import Reader, ReadingError, ReadingTimeoutError
from sef_api.invoices.routes import MODEL_REQUEST, VALIDATION, count
from sef_api.invoices.upload import DOCUMENT_MEDIA_TYPES, read_document
from sef_api.llm import LLMError
from sef_api.model_choice import reader_for
from sef_api.settings import Settings

__all__ = ["DocumentRead", "Extraction", "opened", "read_by", "router"]

router = APIRouter(prefix="/invoices", tags=["invoices"])

Session = Annotated[AsyncSession, Depends(get_session)]
CanValidate = Annotated[Principal, Depends(require(Permission.INVOICES_VALIDATE))]


class DocumentRead(BaseModel):
    """What the document was."""

    kind: Literal["pdf", "picture"] = Field(description="A PDF, or a picture of an invoice.")
    pages: int = Field(description="The pages shown to the model.")
    text: bool = Field(
        description="Whether a page had a text layer, which the model was given with its "
        "picture; a scanned PDF and a picture have none."
    )


class Extraction(BaseModel):
    """An invoice's fields as the reading model read them from a document, for a person to
    confirm."""

    fields: InvoiceFields = Field(
        description="The fields, null where the model saw none; to be checked against the "
        "document before `POST /invoices/draft` makes an invoice of them."
    )
    document: DocumentRead
    model: str = Field(description="The provider and the model that read the document.")


_EXTRACT_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "description": "The document: a PDF of at most three pages, or a JPEG, PNG or WebP "
        "picture of an invoice.",
        "content": {
            media_type: {"schema": {"type": "string", "format": "binary"}}
            for media_type in sorted(DOCUMENT_MEDIA_TYPES)
        },
    }
}

_EXTRACT_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_408_REQUEST_TIMEOUT: {
        "model": Problem,
        "description": "The document was not received in time.",
    },
    status.HTTP_413_CONTENT_TOO_LARGE: {
        "model": Problem,
        "description": "The document has more bytes, pages or pixels than this server reads.",
    },
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
        "model": Problem,
        "description": "Not a PDF, a JPEG, a PNG or a WebP picture.",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": Problem,
        "description": "The document cannot be opened (damaged, protected by a password, or "
        "not what its media type says), or the model's answers never had the form of an "
        "invoice's fields.",
    },
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": Problem,
        "description": "Too many requests to the language model by the caller, or in their "
        "organization; try again after `Retry-After` seconds.",
    },
    status.HTTP_502_BAD_GATEWAY: {
        "model": Problem,
        "description": "The language model gave no answer.",
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "No language model is configured on this server, or the organization's "
        "own key to one cannot be opened.",
    },
    status.HTTP_504_GATEWAY_TIMEOUT: {
        "model": Problem,
        "description": "The model did not read the document in time.",
    },
}


@router.post(
    "/extract",
    summary="Read an invoice from a PDF or a picture (beta)",
    description=(
        "Reads the fields of the invoice that a PDF or a picture shows, with a language model "
        "that reads pictures: the parties, the dates, the lines, the VAT and the totals, null "
        "where the document shows none. A person checks them against the document; "
        "`POST /invoices/draft` then makes a UBL invoice of them. The model is shown each page "
        "as a picture, with its text where the PDF has a text layer; nothing is stored, and "
        "the pictures are made anew without the document's metadata. Beta: the model can "
        "misread, which is why a person confirms and the validator judges."
    ),
    openapi_extra=_EXTRACT_BODY,
    responses=_EXTRACT_RESPONSES,
)
async def extract(
    request: Request, response: Response, caller: CanValidate, session: Session
) -> Extraction:
    count(request, caller, MODEL_REQUEST)
    settings = cast(Settings, request.app.state.settings)
    async with reader_for(request, session, caller.organization_id) as reader:
        if reader is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "no language model is configured on this server",
            )
        # The permission check and the model's key were this request's database work.
        await session.commit()
        media_type, data = await read_document(
            request, limit=settings.max_document_bytes, seconds=settings.upload_seconds
        )
        document = await opened(data, media_type)
        del data
        extraction = await read_by(reader, document, seconds=settings.extraction_seconds)
    response.headers["Cache-Control"] = "no-store"
    return extraction


async def opened(data: bytes, media_type: str) -> Document:
    """The document in ``data``, opened into pages; the HTTP error ``extract`` answers when it
    cannot be."""
    try:
        return await open_document(data, media_type)
    except DocumentTooLargeError as error:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(error)) from None
    except UnreadableDocumentError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None


async def read_by(reader: Reader, document: Document, *, seconds: float) -> Extraction:
    """The fields ``reader`` reads from ``document`` within ``seconds``; the HTTP error
    ``extract`` answers when it gives none."""
    try:
        reading = await reader.read(document, seconds=seconds)
    except ReadingTimeoutError as error:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(error)) from None
    except ReadingError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    except LLMError as error:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"the language model did not answer: {error}"
        ) from None
    return Extraction(
        fields=reading.fields,
        document=DocumentRead(
            kind=document.kind, pages=len(document.pages), text=document.has_text
        ),
        model=reading.model,
    )


@router.post(
    "/draft",
    summary="Make a UBL invoice of an invoice's fields (beta)",
    description=(
        "Writes the UBL 2.1 invoice, or credit note for type code 381, that the fields "
        "describe, as `POST /invoices/extract` answers them and a person corrected them. It is "
        "written in code, without a model: every element comes from a field, or from SRB-CIUS "
        "where the profile fixes it, and nothing is computed or filled in, so a field left "
        "empty leaves its element out. Validate it with `POST /invoices/validate`, store it "
        "with `POST /invoices`. Nothing is stored here."
    ),
    response_class=Response,
    responses={
        status.HTTP_200_OK: {
            "content": {"application/xml": {"schema": {"type": "string"}}},
            "description": "The UBL 2.1 invoice or credit note.",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "model": Problem,
            "description": "Too many validations by the caller, or in their organization; try "
            "again after `Retry-After` seconds.",
        },
    },
)
async def make_draft(request: Request, fields: InvoiceFields, caller: CanValidate) -> Response:
    count(request, caller, VALIDATION)
    return Response(
        draft(fields), media_type="application/xml", headers={"Cache-Control": "no-store"}
    )
