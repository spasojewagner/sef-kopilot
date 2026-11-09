"""Stripe's sandbox as the provider of payments (ADR-0060): a Checkout Session for a pack of
credits, and the events Stripe sends when one is paid, verified by their signature.

Only Stripe's sandbox: the settings refuse a live key, and a live event is never turned into
credits. The API is spoken over plain HTTP, form-encoded as Stripe's API reference shows it, at
a pinned version; the tests send it to ``stripe-mock`` too, which checks each request against
Stripe's OpenAPI description.

An event is Stripe's when one of the ``v1`` signatures of its ``Stripe-Signature`` header is the
HMAC-SHA256, under the endpoint's secret, of the time it names, a dot and the body as it came;
and when that time is less than five minutes old, so that a captured event cannot be sent again
later. Signatures of other schemes are ignored, so that no one can downgrade to them.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, Final

import httpx
from pydantic import SecretStr

from sef_api.billing.payments import Checkout, Pack, Paid, PaymentError, UnverifiedReportError

__all__ = ["API_VERSION", "TOLERANCE_SECONDS", "StripeCheckout", "sign"]

logger = logging.getLogger(__name__)

#: The version of Stripe's API the requests are written for.
API_VERSION: Final = "2026-10-28.endive"
#: How old a signed event may be, as Stripe's own libraries allow.
TOLERANCE_SECONDS: Final = 300
#: How long a request to Stripe may take.
TIMEOUT_SECONDS: Final = 10.0
#: The events that tell of a paid checkout: paid at once, or later, by a delayed method.
_COMPLETED: Final = "checkout.session.completed"
_PAID_LATER: Final = "checkout.session.async_payment_succeeded"


def sign(payload: bytes, secret: str, timestamp: int) -> str:
    """The ``Stripe-Signature`` header Stripe would send with ``payload``: for the tests, and
    the scheme written down once."""
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def _verified(payload: bytes, header: str | None, secret: str, now: float) -> None:
    if not header:
        raise UnverifiedReportError("the event has no Stripe-Signature")
    timestamp: str | None = None
    signatures: list[str] = []
    for part in header.split(","):
        scheme, _, value = part.strip().partition("=")
        if scheme == "t":
            timestamp = value
        elif scheme == "v1":
            signatures.append(value)
    if timestamp is None or not timestamp.isdigit() or not signatures:
        raise UnverifiedReportError("the Stripe-Signature names no time or no v1 signature")
    expected = sign(payload, secret, int(timestamp)).rpartition("v1=")[2]
    if not any(hmac.compare_digest(expected, signature) for signature in signatures):
        raise UnverifiedReportError("no signature of the event is Stripe's")
    if int(timestamp) < now - TOLERANCE_SECONDS:
        raise UnverifiedReportError("the event was signed more than five minutes ago")


def _paid_session(event: Any) -> dict[str, Any] | None:
    """The Checkout Session a verified event reports paid, if it reports one."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    session = (event.get("data") or {}).get("object")
    if kind not in (_COMPLETED, _PAID_LATER) or not isinstance(session, dict):
        return None
    if kind == _COMPLETED and session.get("payment_status") != "paid":
        return None  # a delayed method: async_payment_succeeded follows when it is paid
    if event.get("livemode") or session.get("livemode"):
        logger.warning("a live payment was reported to a sandbox-only server; nothing granted")
        return None
    return session


class StripeCheckout:
    """Stripe Checkout, in its sandbox, as the provider of payments."""

    name = "stripe"

    def __init__(
        self,
        secret_key: SecretStr,
        webhook_secret: SecretStr,
        *,
        currency: str,
        base_url: str = "https://api.stripe.com",
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.currency = currency
        self._webhook_secret = webhook_secret
        self._clock = clock
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            headers={
                "Authorization": f"Bearer {secret_key.get_secret_value()}",
                "Stripe-Version": API_VERSION,
            },
        )

    async def checkout(
        self,
        organization_id: uuid.UUID,
        pack: Pack,
        *,
        success_url: str,
        cancel_url: str,
    ) -> Checkout:
        form = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(organization_id),
            "metadata[organization_id]": str(organization_id),
            "metadata[credits]": str(pack.credits),
            "line_items[0][quantity]": "1",
            "line_items[0][price_data][currency]": self.currency,
            "line_items[0][price_data][unit_amount]": str(pack.price),
            "line_items[0][price_data][product_data][name]": f"SEF Kopilot: {pack.credits} credits",
        }
        try:
            answer = await self._http.post(
                "/v1/checkout/sessions",
                data=form,
                # A retried request opens no second checkout.
                headers={"Idempotency-Key": str(uuid.uuid4())},
            )
        except httpx.HTTPError as error:
            raise PaymentError(f"Stripe did not answer ({type(error).__name__})") from None
        if not answer.is_success:
            raise PaymentError(f"Stripe answered {answer.status_code} ({_error_type(answer)})")
        try:
            session = answer.json()
            return Checkout(reference=str(session["id"]), url=str(session["url"]))
        except (ValueError, KeyError, TypeError):
            raise PaymentError("Stripe's answer names no checkout") from None

    def paid(self, payload: bytes, signature: str | None) -> Paid | None:
        _verified(payload, signature, self._webhook_secret.get_secret_value(), self._clock())
        try:
            session = _paid_session(json.loads(payload))
        except ValueError:
            return None
        if session is None:
            return None
        metadata = session.get("metadata") or {}
        try:
            return Paid(
                reference=str(session["id"]),
                organization_id=uuid.UUID(str(metadata["organization_id"])),
                credits=int(metadata["credits"]),
            )
        except (KeyError, ValueError, TypeError):
            logger.warning("a paid checkout names no organization or no credits; nothing granted")
            return None

    async def aclose(self) -> None:
        await self._http.aclose()


def _error_type(answer: httpx.Response) -> str:
    """The kind of error Stripe's answer names, never its message, which may repeat the
    request."""
    try:
        error = answer.json().get("error") or {}
    except (ValueError, AttributeError):
        return "no error named"
    return str(error.get("code") or error.get("type") or "no error named")
