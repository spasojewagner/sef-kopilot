# M2 — `feat/api-rate-limits`

## Three questions a senior engineer would ask

**1. "Why limit wrong passwords per e-mail address and not only per IP address?"**

Because the attacker chooses the IP address and the victim chooses the account. A botnet
guessing at one account from ten thousand addresses stays within any per-address limit, so the
count that stops it is per account: ten wrong passwords in fifteen minutes, then one every 90
seconds. Three details make it safe. The count is checked before the password, so a
held-back guess costs no argon2 hash and its answer cannot tell right from wrong. An address
without an account is counted alike, so being held back reveals nothing. Accepting an
invitation counts with sign-in, so an invitation's code cannot be used to guess where sign-in
would refuse. The cost is that an attacker can keep one person locked out while the guessing
lasts; the count drains on its own and nothing is locked for good.

**2. "Why GCRA rather than a counter per minute?"**

A fixed window lets twice the limit through around its edge: the whole limit at the end of
one minute and again at the start of the next. Its `Retry-After` is the end of the window, not
the moment a request would actually be allowed. GCRA keeps one number per key, the time the
next request would arrive were requests evenly spaced. It allows a burst of *n*, then one
every period / *n*, exactly as a token bucket would, and the time to wait falls out of the
same subtraction. It needs no timer and no list of past requests, and integer nanoseconds of a
monotonic clock mean no rounding refuses a request the limit allows.

**3. "The counts live in memory. What happens with four workers, or a restart?"**

With four workers each counts its own, so the limits are four times as loose; after a restart
every count starts afresh. The deployment runs one process, as the validator's admission
already assumes (ADR-0015), so in-memory counts are exact there and cost nothing to run. The
limiter's three methods, `wait`, `hit` and `forget`, are all a shared store would have to
provide: Redis with the same arithmetic in a Lua script, when Redis arrives for jobs and the
API needs more than one process. Memory is bounded at 100 000 keys, because keys such as
e-mail addresses are chosen by the attacker.

## The one concept to explain unaided

**A rate limit is only as good as its key.** Count by what the attacker cannot multiply: an
account for password guessing, a tenant for shared capacity, a credential for one integration,
an address only for scripts. And take the address the server saw, never a header the client
wrote.

## Supporting facts worth remembering

- Per address: sign-in 30 a minute, registration 10 an hour, refresh and sign-out 60 a minute
  together, accepting an invitation 10 a minute.
- Per e-mail address: 10 wrong passwords in 15 minutes, at sign-in and when an invitation is
  accepted; the right one starts the count afresh.
- Per caller (a member, or one API key): `SEF_VALIDATIONS_PER_MINUTE`, 60. Per organization:
  `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE`, 300. Storing counts as a validation, and the count
  comes before the body is read.
- 429 with `Retry-After` in whole seconds, documented in OpenAPI on every limited endpoint.
- `X-Forwarded-For` is ignored unless uvicorn is told to trust the proxy that sets it.
