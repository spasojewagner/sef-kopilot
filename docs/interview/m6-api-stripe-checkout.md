# M6 — `feat/api-stripe-checkout`

## Three questions a senior engineer would ask

**1. "Your webhook endpoint is public. What stops me posting 'organization X paid'?"**

The signature. Stripe signs each event with the endpoint's secret: `v1` is the HMAC-SHA256 of
the timestamp, a dot and the raw body. The API recomputes it over the body exactly as it arrived,
compares in constant time against every `v1` in the header, ignores other schemes so no one can
downgrade, and refuses a timestamp older than five minutes so a captured event cannot be replayed.
Without the secret, a forged event gets 400 and nothing is read; the tests sign events exactly
as Stripe does, under the right secret and under wrong ones.

**2. "Stripe retries. How do you avoid crediting a payment twice?"**

A purchase is written to the ledger under the Checkout Session's id, in a column with a unique
constraint, with `INSERT … ON CONFLICT DO NOTHING RETURNING id`: the second delivery, or the
second event that reports the same payment (`completed` and `async_payment_succeeded`), inserts
nothing, and the balance is only raised when the insert happened, in the same transaction.
Idempotency by a constraint, not by a read-then-write.

**3. "You have no Stripe account. How do you know the checkout request is right?"**

Two ways. The tests compare the form field by field with Stripe's API reference; and CI sends it
to `stripe-mock`, Stripe's own mock server, which validates every request against Stripe's
OpenAPI description and refuses a misnamed or mistyped parameter as Stripe would. What neither
can prove is a real event from a real dashboard; the ADR says so, and the first operator with a
sandbox account is the first to see one.

## The one concept to explain unaided

**A webhook is a request anyone can send**: believe it only when it carries a signature only the
provider can make over the exact bytes, with a time inside the signature to stop replays, and
make acting on it idempotent, because even genuine events arrive more than once.

## Supporting facts worth remembering

- Sandbox only: `sk_test_`/`rk_test_` keys, `whsec_` secrets; a live key refuses to start, a live
  event adds nothing.
- Checkout is hosted by Stripe: no card data ever reaches the API.
- Packs come from `SEF_CREDIT_PACKS` (`credits:price` in cents); Stripe version
  `2026-10-28.endive`, pinned per request.
