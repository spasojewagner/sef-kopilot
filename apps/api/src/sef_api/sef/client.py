"""A client of SEF's public API for sales invoices: an invoice imported as UBL, and where it
stands since (ADR-0051).

The contract is the OpenAPI document that SEF publishes, ``/swagger/public_v1/swagger.json``:
every operation takes the organization's key in the header ``ApiKey``; ``POST
/api/publicApi/sales-invoice/ubl`` takes the document as ``application/xml`` and answers with
the ids SEF gave it, and ``GET /api/publicApi/sales-invoice?invoiceId=`` with its status.

An invoice is imported with a ``requestId`` of ours, the same on every attempt, so that a
request tried again after an answer that never came does not import it twice. An answer of 429
or 5xx, or a request that fails on the way, is tried again up to :attr:`SefClient.ATTEMPTS`
times; any other is a :class:`SefError` that says what kind of failure it was. What SEF answers
when it refuses an invoice may quote the invoice: it is kept for the member who sent it, and
never logged.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal

import httpx
from pydantic import SecretStr

__all__ = ["FINAL", "Imported", "SefClient", "SefError", "SefStatus", "Standing"]


class SefStatus(StrEnum):
    """Where a sales invoice stands in SEF (``SalesInvoiceStatus``)."""

    NEW = "New"
    DRAFT = "Draft"
    SENDING = "Sending"
    SENT = "Sent"
    MISTAKE = "Mistake"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    CANCELLED = "Cancelled"
    STORNO = "Storno"
    PAID = "Paid"
    OVERDUE = "OverDue"
    ARCHIVED = "Archived"
    DELETED = "Deleted"
    UNKNOWN = "Unknown"


#: The statuses after which nothing more happens to an invoice in SEF that we need to ask about:
#: its buyer decided, or its seller cancelled, reversed or deleted it.
FINAL: Final = frozenset(
    {
        SefStatus.APPROVED,
        SefStatus.REJECTED,
        SefStatus.CANCELLED,
        SefStatus.STORNO,
        SefStatus.DELETED,
    }
)


@dataclass(frozen=True)
class Imported:
    """The ids SEF gave an invoice it imported."""

    sales_invoice_id: int
    invoice_id: int | None


@dataclass(frozen=True)
class Standing:
    """Where an invoice stands in SEF: its status, when SEF last changed it, and the comment
    its buyer wrote with a decision, if any."""

    status: SefStatus
    changed_at: datetime | None
    comment: str | None


SefFailure = Literal["refused", "unauthorized", "unavailable", "unreadable"]


class SefError(Exception):
    """SEF did not do what was asked.

    ``kind`` says why: ``refused``, an answer of 4xx other than 401 or 403, with SEF's own
    words in ``detail``, which may quote the invoice and are for the member who sent it alone;
    ``unauthorized``, 401 or 403, the organization's key; ``unavailable``, no answer, 429 or
    5xx, after every attempt; ``unreadable``, an answer that is not what the contract says.
    The message names the kind and the status, never what was sent or what SEF wrote.
    """

    def __init__(
        self, kind: SefFailure, *, status: int | None = None, detail: str | None = None
    ) -> None:
        super().__init__(f"SEF: {kind}" + ("" if status is None else f" ({status})"))
        self.kind: SefFailure = kind
        self.status = status
        self.detail = detail


class SefClient:
    """SEF's public API at ``base_url``, with one organization's key."""

    SEND_PATH: Final = "/api/publicApi/sales-invoice/ubl"
    STATUS_PATH: Final = "/api/publicApi/sales-invoice"
    ATTEMPTS: Final = 3
    TIMEOUT_SECONDS: Final = 30.0
    MAX_WAIT_SECONDS: Final = 10.0
    #: The most of SEF's words on a refusal that are kept.
    MAX_DETAIL: Final = 2000

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr,
        *,
        client: httpx.AsyncClient | None = None,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        self._backoff = backoff_seconds

    async def send(self, document: bytes, request_id: uuid.UUID) -> Imported:
        """Import ``document``, a UBL sales invoice, with SEF's own validation, not to the
        central invoice register (CIR); the same ``request_id`` on every attempt."""
        response = await self._ask(
            "POST",
            self.SEND_PATH,
            params={
                "requestId": str(request_id),
                "sendToCir": "No",
                "executeValidation": "true",
            },
            content=document,
            headers={"Content-Type": "application/xml"},
        )
        body = _json(response)
        sales_invoice_id = _id(body.get("salesInvoiceId"))
        invoice_id = _id(body.get("invoiceId"))
        if sales_invoice_id is None or (body.get("invoiceId") is not None and invoice_id is None):
            raise SefError("unreadable", status=response.status_code)
        return Imported(sales_invoice_id=sales_invoice_id, invoice_id=invoice_id)

    async def standing(self, sales_invoice_id: int) -> Standing:
        """Where the sales invoice ``sales_invoice_id`` stands now."""
        response = await self._ask(
            "GET", self.STATUS_PATH, params={"invoiceId": str(sales_invoice_id)}
        )
        body = _json(response)
        named = body.get("status")
        if not isinstance(named, str) or named not in SefStatus:
            raise SefError("unreadable", status=response.status_code)
        status = SefStatus(named)
        changed = body.get("lastModifiedUtc")
        comment = body.get("comment")
        try:
            changed_at = datetime.fromisoformat(changed) if isinstance(changed, str) else None
        except ValueError:
            changed_at = None
        if changed_at is not None and changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=UTC)  # the field is UTC, without saying so
        return Standing(
            status=status,
            changed_at=changed_at,
            comment=comment[: self.MAX_DETAIL] if isinstance(comment, str) and comment else None,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _ask(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str],
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        sent = {"ApiKey": self._api_key.get_secret_value(), "Accept": "application/json"}
        sent |= headers or {}
        status: int | None = None
        for attempt in range(self.ATTEMPTS):
            if attempt:
                await asyncio.sleep(min(self._backoff * 2 ** (attempt - 1), self.MAX_WAIT_SECONDS))
            try:
                response = await self._client.request(
                    method, self._base + path, params=params, content=content, headers=sent
                )
            except httpx.HTTPError:
                status = None
                continue
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS or response.is_server_error:
                status = response.status_code
                continue
            if response.status_code in {httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN}:
                raise SefError("unauthorized", status=response.status_code)
            if response.is_client_error:
                raise SefError(
                    "refused",
                    status=response.status_code,
                    detail=response.text[: self.MAX_DETAIL] or None,
                )
            if response.status_code != httpx.codes.OK:
                raise SefError("unreadable", status=response.status_code)
            return response
        raise SefError("unavailable", status=status)


def _json(response: httpx.Response) -> dict[str, object]:
    try:
        body = response.json()
    except ValueError:
        raise SefError("unreadable", status=response.status_code) from None
    if not isinstance(body, dict):
        raise SefError("unreadable", status=response.status_code)
    return body


def _id(value: object) -> int | None:
    """``value`` if it is an id as SEF gives them, a positive integer; None otherwise."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None
