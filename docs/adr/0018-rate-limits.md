# 18. Rate limits: GCRA in the API's process, per address, per e-mail address, per caller and per organization

- Status: accepted
- Date: 2026-11-04
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-rate-limits`

## Context and problem statement

The API's public endpoints are open to anyone. Each sign-in costs a password hash, each
registration creates rows, and each refresh is a database lookup. Validating an invoice is the
most expensive request of all. Admission bounds how many validations run at once (ADR-0015),
but nothing bounded how often a client could ask. A script could guess passwords at one
account, create accounts without end, or keep the validator busy for every other tenant.

Four things were open:

- what to count, and by which key;
- with which algorithm;
- where the counts live;
- what a client is told.

## Decision drivers

- Stop a guess at one account from many addresses, and a script from one address.
- Being held back must reveal nothing, such as whether an account exists.
- One tenant must not crowd out the others.
- An office of people behind one address must not be held back by its own work.
- A client must be told when to try again.
- No new service until one is needed; boring, explainable choices.

## Considered options

What to count:

1. **Per address on the public endpoints, per e-mail address for wrong passwords, and per
   caller and per organization for validations.** Chosen.
2. Per address only.

The algorithm:

1. **GCRA, the generic cell rate algorithm: one moment per key, a burst and a pace.** Chosen.
2. A fixed window: a counter per minute.
3. A sliding log: every request's time.

Where the counts live:

1. **In the API's process, behind methods a shared store can implement.** Chosen.
2. Redis, shared by every process.
3. PostgreSQL.

## Decision outcome

**What is counted.**

| What | Key | Limit |
| --- | --- | --- |
| signing in | address | 30 a minute |
| registering | address | 10 an hour |
| refreshing and signing out | address | 60 a minute, together |
| accepting an invitation | address | 10 a minute |
| wrong passwords, at sign-in and when an invitation is accepted | e-mail address | 10 in 15 minutes |
| validating, storing included | caller: a member signed in, or one API key | `SEF_VALIDATIONS_PER_MINUTE` (60) |
| validating, storing included | organization | `SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE` (300) |

The limits per address are generous enough for an office behind one address and tight enough
to slow a script down. The limit per e-mail address is what stops a guess at one account, from
however many addresses it comes:

- it is checked before the password, so a held-back guess costs no password hash, and its
  answer cannot tell a right password from a wrong one;
- an address without an account is counted like any other, so being held back reveals
  nothing;
- the right password starts the count afresh.

Accepting an invitation checks an existing account's password too, and counts with sign-in
through the same guard. A validation counts against its caller and its organization at once,
and only when both allow it, before the body is read.

**The algorithm.** GCRA keeps one moment per key: when the next request would arrive were
requests evenly spaced. A request is allowed while that moment is no further ahead than the
burst may reach. A limit of *n* per period then allows *n* at once, or one every period / *n*:
what a token bucket of *n* tokens would allow. It needs no timer and no list of requests, and
the time to wait comes out of the same arithmetic. Times are integer nanoseconds of a
monotonic clock, so that no rounding refuses a request the limit allows.

**Where the counts live.** In the API's process, as the validator's admission does
(ADR-0015). The deployment runs one process: Render's free service, or one container when
self-hosted. One lock makes a check and its count one step. The limiter keeps at most 100 000
keys: the keys whose counts have run out go first, then those nearest to running out, so that
the ones being held back stay. `wait`, `hit` and `forget` are all a shared store would have to
implement, Redis with the same arithmetic in a script, when there is more than one process.

**The address.** The limiter keys on the address the server saw (`request.client`). Behind a
proxy, uvicorn must be told which proxy to trust (`--forwarded-allow-ips`), and the address is
then the one that proxy reports. The API never reads `X-Forwarded-For` itself: a header the
client writes would let it pick a fresh count for every request.

**The answer.** 429 Too Many Requests (RFC 6585), with `Retry-After` in whole seconds and a
detail that names what was counted, such as "too many sign-in attempts; try again in 2 s".
Every limited endpoint documents it in OpenAPI.

### Consequences

Good:

- A guess at one account gets ten tries in a quarter of an hour, then one every 90 seconds,
  from however many addresses. A script from one address is slowed on every public endpoint.
- No tenant can monopolize the validator over time, and no caller can monopolize their
  organization's share.
- A client knows exactly when to retry.
- No new service.

Bad / accepted:

- With several processes, each counts its own, so the limits multiply by the number of
  processes. A shared store is the change to make then.
- A restart forgets every count.
- An attacker can hold one account back by guessing at it, which locks the person out for
  as long as the guessing goes on. The count drains at one try every 90 seconds, and nothing
  is locked for good. Notifying the person comes with e-mail.
- Many people behind one address share its counts. The limits are set for an office, not for
  a whole country behind a carrier's NAT.
- Requests with a valid access token or API key are counted only when they validate. Other
  reads are bounded by the database and by a proxy in front, if any.

## Pros and cons of the options

### Per address only

- Bad: a botnet guesses at one account from thousands of addresses, each well within its
  limit.

### A fixed window

- Good: the simplest counter there is.
- Bad: twice the limit fits around a window's edge, at the end of one minute and the start of
  the next, and the wait it reports is to the end of the window, not to the next free place.

### A sliding log

- Good: exact.
- Bad: memory grows with the limit, a list of times per key, where GCRA keeps one number.

### Redis

- Good: shared by every process and every instance.
- Bad: a service the API does not need yet. The free tier also counts every command, and
  every limited request would spend one. It arrives for jobs (`feat/api-jobs-sse`), and the
  counts can move to it then.

### PostgreSQL

- Good: shared, with no new service.
- Bad: a write on every limited request, on the database every other request needs.
