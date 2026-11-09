"""How credits are bought (ADR-0060): a provider of payments behind an interface, so that the
ledger (ADR-0059) never depends on one.

A provider does two things. It opens a checkout, a page of its own where an owner pays for a
pack of credits, and names it by a reference; and it reads what it later reports, verifying
that the report is its own, into the payment of a checkout, if the report says one was paid.
The credits are written to the ledger once a reference, however often the report comes.
Stripe's sandbox is the one provider (:mod:`sef_api.billing.stripe`); a server without one
sells no credits, and its operator grants them.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

__all__ = ["Checkout", "Pack", "Paid", "PaymentError", "PaymentProvider", "UnverifiedReportError"]


@dataclass(frozen=True)
class Pack:
    """Credits sold together, at a price in the currency's smallest unit (cents)."""

    credits: int
    price: int


@dataclass(frozen=True)
class Checkout:
    """A checkout the provider opened: where the owner pays, and its reference."""

    reference: str
    url: str


@dataclass(frozen=True)
class Paid:
    """A checkout the provider reports paid: whose, for how many credits, and its reference."""

    reference: str
    organization_id: uuid.UUID
    credits: int


class PaymentError(Exception):
    """The provider did not open a checkout; the message says why, never what was sent."""


class UnverifiedReportError(Exception):
    """A report that cannot be shown to be the provider's: not signed by it, or too old."""


class PaymentProvider(Protocol):
    """Where credits are bought."""

    #: The provider's name, for the ledger and the logs.
    name: str
    #: The currency of every price, in lower case (ISO 4217).
    currency: str

    async def checkout(
        self,
        organization_id: uuid.UUID,
        pack: Pack,
        *,
        success_url: str,
        cancel_url: str,
    ) -> Checkout:
        """Open a checkout for ``pack``, for the organization; :class:`PaymentError` when the
        provider does not."""
        ...

    def paid(self, payload: bytes, signature: str | None) -> Paid | None:
        """The payment the report ``payload`` tells of, if it tells of one;
        :class:`UnverifiedReportError` when it is not the provider's own."""
        ...

    async def aclose(self) -> None:
        """Release what the provider holds open."""
        ...
