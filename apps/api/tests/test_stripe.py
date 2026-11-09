"""Stripe's sandbox as the provider of payments (ADR-0060): a Checkout Session asked for as
Stripe's API reference shows, and against ``stripe-mock`` where it runs; events verified by
their signature, as Stripe signs them, before anything is read; live keys and live payments
refused."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from sef_api.billing.payments import Pack, Paid, PaymentError, UnverifiedReportError
from sef_api.billing.stripe import API_VERSION, StripeCheckout, sign
from sef_api.settings import Settings

from .conftest import TEST_STRIPE_URL as STRIPE_MOCK
from .conftest import settings_for

#: Plainly fake: a sandbox key's shape, and an endpoint's signing secret's.
SECRET_KEY = SecretStr("sk_test_not-a-real-key")
WEBHOOK_SECRET = "whsec_not-a-real-secret"
NOW = 1_794_250_000
WEB = "http://localhost:3000"
STRIPE = {
    "SEF_BILLING": "credits",
    "SEF_STARTING_CREDITS": "2",
    "STRIPE_SECRET_KEY": SECRET_KEY.get_secret_value(),
    "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
    "SEF_WEB_ORIGINS": WEB,
    "SEF_WEB_URL": WEB,
}


def stripe(
    answer: Callable[[httpx.Request], httpx.Response] | None = None,
    *,
    asked: list[httpx.Request] | None = None,
    now: float = NOW,
) -> StripeCheckout:
    def handle(request: httpx.Request) -> httpx.Response:
        if asked is not None:
            asked.append(request)
        if answer is not None:
            return answer(request)
        return httpx.Response(
            200,
            json={"id": "cs_test_4711", "url": "https://checkout.stripe.com/c/pay/cs_test_4711"},
        )

    return StripeCheckout(
        SECRET_KEY,
        SecretStr(WEBHOOK_SECRET),
        currency="eur",
        transport=httpx.MockTransport(handle),
        clock=lambda: now,
    )


def event(
    organization: Any,
    *,
    kind: str = "checkout.session.completed",
    paid: str = "paid",
    count: int = 100,
    reference: str = "cs_test_4711",
    livemode: bool = False,
) -> bytes:
    """An event as Stripe sends it, the fields that matter filled in."""
    return json.dumps(
        {
            "id": "evt_test_1",
            "object": "event",
            "type": kind,
            "livemode": livemode,
            "data": {
                "object": {
                    "id": reference,
                    "object": "checkout.session",
                    "mode": "payment",
                    "payment_status": paid,
                    "status": "complete",
                    "livemode": livemode,
                    "client_reference_id": str(organization),
                    "metadata": {"organization_id": str(organization), "credits": str(count)},
                }
            },
        }
    ).encode()


# --- the signature -----------------------------------------------------------------------------


def test_an_event_signed_as_stripe_signs_is_read() -> None:
    organization = uuid.uuid4()
    payload = event(organization)

    paid = stripe().paid(payload, sign(payload, WEBHOOK_SECRET, NOW))

    assert paid == Paid(reference="cs_test_4711", organization_id=organization, credits=100)


@pytest.mark.parametrize(
    ("header", "why"),
    [
        (None, "has no Stripe-Signature"),
        ("", "has no Stripe-Signature"),
        ("v1=00", "names no time or no v1 signature"),
        (f"t={NOW}", "names no time or no v1 signature"),
        ("t=soon,v1=00", "names no time or no v1 signature"),
        (f"t={NOW},v1=00", "no signature of the event is Stripe's"),
    ],
)
def test_an_event_without_stripe_s_signature_is_refused(header: str | None, why: str) -> None:
    with pytest.raises(UnverifiedReportError, match=why):
        stripe().paid(event(uuid.uuid4()), header)


def test_a_signature_under_another_secret_or_of_another_body_is_refused() -> None:
    payload = event(uuid.uuid4())

    with pytest.raises(UnverifiedReportError, match="is Stripe's"):
        stripe().paid(payload, sign(payload, "whsec_another-one", NOW))
    with pytest.raises(UnverifiedReportError, match="is Stripe's"):
        stripe().paid(payload + b" ", sign(payload, WEBHOOK_SECRET, NOW))


def test_only_v1_signatures_count_and_any_of_them_may_be_the_one() -> None:
    """Stripe signs with each active secret while one is rolled; a v0 signature, which Stripe
    adds to test events, is never accepted in place of v1."""
    payload = event(uuid.uuid4())
    right = sign(payload, WEBHOOK_SECRET, NOW).rpartition("v1=")[2]
    wrong = sign(payload, "whsec_rolled-away", NOW).rpartition("v1=")[2]

    assert stripe().paid(payload, f"t={NOW},v1={wrong},v1={right}") is not None
    with pytest.raises(UnverifiedReportError):
        stripe().paid(payload, f"t={NOW},v0={right}")


def test_an_event_signed_more_than_five_minutes_ago_is_refused() -> None:
    payload = event(uuid.uuid4())
    signed = sign(payload, WEBHOOK_SECRET, NOW - 301)

    with pytest.raises(UnverifiedReportError, match="more than five minutes ago"):
        stripe().paid(payload, signed)
    assert stripe(now=NOW - 1).paid(payload, sign(payload, WEBHOOK_SECRET, NOW - 300))


# --- what an event reports ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "counted"),
    [
        ({}, True),
        ({"kind": "checkout.session.async_payment_succeeded", "paid": "unpaid"}, True),
        ({"paid": "unpaid"}, False),
        ({"kind": "checkout.session.expired"}, False),
        ({"kind": "payment_intent.succeeded"}, False),
    ],
)
def test_only_a_paid_checkout_is_a_payment(changes: dict[str, Any], counted: bool) -> None:
    payload = event(uuid.uuid4(), **changes)

    assert (stripe().paid(payload, sign(payload, WEBHOOK_SECRET, NOW)) is not None) is counted


def test_a_live_payment_is_never_turned_into_credits(caplog: pytest.LogCaptureFixture) -> None:
    payload = event(uuid.uuid4(), livemode=True)

    with caplog.at_level(logging.WARNING, logger="sef_api.billing.stripe"):
        assert stripe().paid(payload, sign(payload, WEBHOOK_SECRET, NOW)) is None

    assert "a live payment was reported to a sandbox-only server" in caplog.text


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        json.dumps({"type": "checkout.session.completed", "data": {"object": "x"}}).encode(),
        json.dumps(
            {
                "type": "checkout.session.completed",
                "data": {"object": {"id": "cs_test_1", "payment_status": "paid", "metadata": {}}},
            }
        ).encode(),
    ],
)
def test_a_signed_event_that_names_no_payment_grants_nothing(payload: bytes) -> None:
    assert stripe().paid(payload, sign(payload, WEBHOOK_SECRET, NOW)) is None


# --- the checkout ------------------------------------------------------------------------------


async def test_a_checkout_is_asked_for_as_stripe_s_api_reference_shows() -> None:
    asked: list[httpx.Request] = []
    organization = uuid.uuid4()
    provider = stripe(asked=asked)

    opened = await provider.checkout(
        organization, Pack(credits=500, price=4000), success_url=f"{WEB}/ok", cancel_url=f"{WEB}/no"
    )
    await provider.aclose()

    assert (opened.reference, opened.url) == (
        "cs_test_4711",
        "https://checkout.stripe.com/c/pay/cs_test_4711",
    )
    (request,) = asked
    assert (request.method, str(request.url)) == (
        "POST",
        "https://api.stripe.com/v1/checkout/sessions",
    )
    assert request.headers["Authorization"] == "Bearer sk_test_not-a-real-key"
    assert request.headers["Stripe-Version"] == API_VERSION
    assert uuid.UUID(request.headers["Idempotency-Key"])
    assert dict(parse_qsl(request.content.decode())) == {
        "mode": "payment",
        "success_url": f"{WEB}/ok",
        "cancel_url": f"{WEB}/no",
        "client_reference_id": str(organization),
        "metadata[organization_id]": str(organization),
        "metadata[credits]": "500",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "eur",
        "line_items[0][price_data][unit_amount]": "4000",
        "line_items[0][price_data][product_data][name]": "SEF Kopilot: 500 credits",
    }


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        (
            lambda _: httpx.Response(
                402, json={"error": {"type": "card_error", "message": "echo of the request"}}
            ),
            "Stripe answered 402 (card_error)",
        ),
        (
            lambda _: httpx.Response(400, json={"error": {"code": "parameter_missing"}}),
            "Stripe answered 400 (parameter_missing)",
        ),
        (lambda _: httpx.Response(500, text="<html>"), "Stripe answered 500 (no error named)"),
        (lambda _: httpx.Response(200, json={"id": "cs_test_1"}), "names no checkout"),
    ],
)
async def test_a_checkout_stripe_does_not_open_says_why_without_what_was_sent(
    answer: Callable[[httpx.Request], httpx.Response], why: str
) -> None:
    provider = stripe(answer)
    with pytest.raises(PaymentError, match=re.escape(why)) as refused:
        await provider.checkout(uuid.uuid4(), Pack(100, 1000), success_url=WEB, cancel_url=WEB)
    await provider.aclose()

    assert "echo" not in str(refused.value)


async def test_stripe_out_of_reach_is_named() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    provider = stripe(unreachable)
    with pytest.raises(PaymentError, match=r"Stripe did not answer \(ConnectError\)"):
        await provider.checkout(uuid.uuid4(), Pack(100, 1000), success_url=WEB, cancel_url=WEB)
    await provider.aclose()


@pytest.mark.skipif(STRIPE_MOCK is None, reason="stripe-mock is not running (SEF_TEST_STRIPE_URL)")
async def test_stripe_mock_takes_the_checkout_as_stripe_s_api_describes_it() -> None:
    """``stripe-mock`` checks each request against Stripe's OpenAPI description: a parameter
    misnamed or of the wrong type is refused there as Stripe would."""
    assert STRIPE_MOCK is not None
    provider = StripeCheckout(
        SECRET_KEY, SecretStr(WEBHOOK_SECRET), currency="eur", base_url=STRIPE_MOCK
    )
    try:
        opened = await provider.checkout(
            uuid.uuid4(), Pack(100, 1000), success_url=f"{WEB}/ok", cancel_url=f"{WEB}/no"
        )
    finally:
        await provider.aclose()

    assert opened.reference.startswith("cs_test_")
    assert opened.url.startswith("https://checkout.stripe.com/")


# --- the settings ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"STRIPE_SECRET_KEY": "sk_live_not-a-real-key"}, "sandbox"),
        ({"STRIPE_SECRET_KEY": "rk_live_not-a-real-key"}, "sandbox"),
        ({"STRIPE_WEBHOOK_SECRET": "not-a-signing-secret"}, "whsec_"),
        ({"STRIPE_WEBHOOK_SECRET": None}, "set together"),
        ({"SEF_BILLING": "off"}, "SEF_BILLING=credits"),
        ({"SEF_CREDIT_PACKS": "100"}, "credits:price"),
        ({"SEF_CREDIT_PACKS": "100:10"}, "50 to 1 000 000"),
        ({"SEF_CREDIT_PACKS": "100:1000,100:900"}, "twice"),
    ],
)
def test_the_settings_refuse_a_live_key_and_what_cannot_be_sold(
    changes: dict[str, str | None], why: str
) -> None:
    values: dict[str, str | None] = {
        "SEF_ENVIRONMENT": "test",
        "DATABASE_URL": "postgresql+asyncpg://x@localhost/x",
    }
    values |= STRIPE | changes
    with pytest.raises(ValidationError, match=why):
        Settings.from_values({name: value for name, value in values.items() if value is not None})


def test_the_packs_are_read_as_credits_and_cents() -> None:
    settings = settings_for(**STRIPE, SEF_CREDIT_PACKS=" 50:600 , 1000:7500")
    assert settings.credit_packs == ((50, 600), (1000, 7500))


def test_the_scheme_is_the_one_stripe_documents() -> None:
    """``t=`` and ``v1=``: the HMAC-SHA256 of the time, a dot and the body, in hexadecimal."""
    header = sign(b"{}", "whsec_x", 1)
    assert header.startswith("t=1,v1=")
    assert len(header.rpartition("v1=")[2]) == 64
