# Rate limits: what to count, by which key, and how

A rate limit answers one question per request: may this client do this again yet? Three
choices decide whether it protects anything: the key, the algorithm and where the counts live.

## The key is the design

| Threat | Key | Here |
| --- | --- | --- |
| a script hammering a public endpoint | client address | sign-in 30 a minute, registration 10 an hour |
| guessing one account's password from a botnet | **the account**, by e-mail address | 10 wrong passwords in 15 minutes |
| one tenant crowding out the others | organization | 300 validations a minute |
| one integration crowding out its colleagues | caller (a person, or one API key) | 60 validations a minute |

- A limit per address alone lets a botnet guess at one account from thousands of addresses.
- Count wrong passwords **before** checking the next one: a held-back guess then costs no
  password hash, and its answer cannot tell right from wrong.
- Count addresses that **no account has** as well, or being held back would reveal which
  accounts exist.
- Take the address the server saw. `X-Forwarded-For` is written by whoever sends the request;
  trust it only from your own proxy (uvicorn's `--forwarded-allow-ips`).

## The algorithm: GCRA

A token bucket holds *n* tokens, refilled one every period / *n*; a request takes one. GCRA,
the generic cell rate algorithm, computes the same answer from one number per key: the moment
the next request would arrive were requests evenly spaced (the TAT).

```text
T = period / n          τ = period − T            (the burst: n requests at once)
tat = max(tat, now)
allowed  when tat − now ≤ τ   →  tat = tat + T
refused  otherwise            →  Retry-After = tat − τ − now
```

- No timer, no list of requests, and the exact time to wait.
- A fixed window (a counter per minute) lets twice the limit through around the window's edge.
  A sliding log is exact but keeps every request's time.

## Where the counts live

- **In the process**: nothing to run, but each worker counts its own, and a restart forgets.
  It suits one process, which is what this API runs.
- **Redis**: shared by every process, and costs a round trip per limited request. The same
  arithmetic runs in a Lua script, so that the check and the count stay one step.
- Bound the memory either way. Keys are attacker-chosen (any e-mail address), so drop the
  counts that have run out first.

## The answer

`429 Too Many Requests` with `Retry-After: <seconds>` (RFC 6585), and a detail that says what
was counted. Document it in OpenAPI, so that client generators know to back off.

## In this repository

- `apps/api/src/sef_api/rate_limits.py`: the limiter, what is counted and the limits.
- `auth/service.py`: the password guard, checked before every password.
  `invoices/routes.py`: validations counted per caller and per organization.
- `apps/api/tests/test_rate_limits.py` (the algorithm, on a clock the test moves) and
  `test_rate_limited_requests.py` (every limited endpoint).
- The decisions are recorded in ADR-0018.
