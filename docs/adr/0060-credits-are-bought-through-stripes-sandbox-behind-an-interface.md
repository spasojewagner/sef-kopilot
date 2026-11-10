# 60. Credits are bought through Stripe's sandbox, behind an interface, and counted once a payment

- Status: accepted
- Date: 2026-11-09
- Deciders: the team (milestone M6)
- Technical story: milestone M6, branch `feat/api-stripe-checkout`; the credits of ADR-0059, the
  brief's "Stripe sandbox only, credits per invoice; webhooks verified; never real charges",
  the maintainer's decision of 2026-11-09 that Stripe, which does not take payments for
  businesses in Serbia, is built and tested without an account and is off in the public demo

## Context and problem statement

Credits are kept in the API's own ledger (ADR-0059); an operator who sells them needs a way to
take payments. The brief names Stripe's sandbox. Stripe does not onboard businesses in Serbia
and the project holds no account, so the integration cannot be tried against a real dashboard;
yet it must be right in the ways that matter: a payment is credited once and only once, an event
anyone could send is not believed, and no real card is ever charged. How are credits sold, and
how is that trusted without an account?

## Decision drivers

- The ledger does not depend on a provider; a provider is one implementation of an interface.
- An event is believed only when it is shown to be Stripe's, and a payment is counted once
  however often it is reported.
- Sandbox only, enforced by the code, not by a promise.
- Tested offline: against Stripe's documented formats, and against a server that checks each
  request against Stripe's own API description.

## Considered options

1. **Stripe Checkout, hosted by Stripe, over plain HTTP at a pinned API version; events verified
   by their HMAC signature; purchases written to the ledger under the payment's reference,
   unique.** Chosen.
2. Stripe's Python SDK.
3. Payment Intents with a card form in the web application.

## Decision outcome

**The interface.** `PaymentProvider` (`sef_api.billing.payments`) opens a checkout for a pack of
credits, naming it by a reference, and reads a provider's report into the payment of a checkout,
if the report tells of one, raising when the report cannot be shown to be the provider's.
Stripe is the one implementation (`StripeCheckout`); a server without it sells nothing, and its
operator grants credits.

**The checkout.** An owner asks for one of the packs the settings put on sale
(`SEF_CREDIT_PACKS`, `credits:price` in cents of `SEF_CREDIT_CURRENCY`): `POST /billing/checkout`
creates a Checkout Session in payment mode, form-encoded as Stripe's API reference shows it, at
`Stripe-Version: 2026-10-28.endive`, with an idempotency key, the organization and the credits in
its metadata, and the organization page of `SEF_WEB_URL` to come back to. The owner pays on
Stripe's page; nothing about a card reaches the API.

**The event.** `POST /billing/stripe-events` is the one request that no one signs in for. Before
anything is read, the `Stripe-Signature` header must hold a `v1` signature that is the
HMAC-SHA256, under the endpoint's secret, of the time it names, a dot and the body as it came,
compared in constant time, of a time less than five minutes old; other schemes are ignored, so
no one can downgrade to them. Otherwise 400, and nothing changes. A verified
`checkout.session.completed` whose payment is `paid`, or a later
`checkout.session.async_payment_succeeded`, adds the pack's credits as a `purchase` entry under
the Checkout Session's id; the column is unique and the insert does nothing on a conflict, so a
payment reported twice, or by two events, is counted once. Every other event is acknowledged
and ignored, as Stripe asks.

**Sandbox only.** The settings refuse a key that is not a sandbox key (`sk_test_`, `rk_test_`),
a webhook secret that is not an endpoint's (`whsec_`), and Stripe without billing on. An event
marked `livemode` is never turned into credits.

**Tested without an account.** Events are signed in the tests as Stripe signs them; the
checkout's request is compared field by field with the API reference, and sent in CI to
`stripe-mock` (`stripe/stripe-mock:v0.206.0`, Stripe's own server that checks each request
against its OpenAPI description).

### Consequences

Good:

- A payment is credited once, by a constraint, whatever Stripe retries; a forged or replayed
  event changes nothing.
- No card data touches the API, and no new dependency enters it.
- Another provider is one class: the ledger, the routes and the web page do not change.

Bad / accepted:

- Never tried against a real Stripe account here: the formats are Stripe's documented ones and
  `stripe-mock`'s; the first operator with a sandbox account is the first to see a real event.
- A payment whose event never arrives is not credited until Stripe delivers it (Stripe retries
  for three days); there is no reconciliation job that asks Stripe.
- Prices are set in the settings, not in Stripe's catalogue: a change of price is a deploy.

## Pros and cons of the options

### Stripe's Python SDK

- Good: verification and request building are the SDK's.
- Bad: a large dependency for one request and one signature, with its own HTTP client and
  retries; the tests would mock the SDK instead of the HTTP Stripe documents.

### Payment Intents with a card form

- Good: the payment stays on the product's page.
- Bad: card fields in the web application bring PCI scope and Stripe.js; Checkout keeps every
  card detail on Stripe's page.
