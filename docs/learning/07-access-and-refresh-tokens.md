# Access tokens, refresh tokens and rotation

A token is a bearer instrument: whoever holds it is you. Everything below follows from that.

## Two tokens, two jobs

| | Access token | Refresh token |
| --- | --- | --- |
| Sent | with every request, `Authorization: Bearer …` | only to `POST /auth/refresh` |
| Form | JWT, signed, self-contained | 256 random bits, opaque |
| Checked by | signature and claims, no database | the database |
| Lives | 15 minutes | 30 days, but each one is used once |
| Revoked by | expiry | the server, at any time |

The access token is cheap to check and therefore cannot be revoked; it is kept short. The
refresh token can be revoked because the server looks it up; it is used rarely and never travels
with ordinary requests.

## Rotation and reuse detection

Every refresh spends the token and issues the next one, in the same family:

```text
sign-in ──► R1 ──refresh──► R2 ──refresh──► R3        (R1, R2 spent; R3 live)
                 thief replays R1 ──► family revoked: R3 dies too, everyone signs in again
```

A spent token can only reappear if someone copied it. Whether the thief or the person refreshes
first, the second use reveals the copy and ends the session for both, which bounds a theft to one
access-token lifetime.

## Store what cannot be used

Passwords are guessable, so they get a slow, salted, memory-hard hash (argon2id). Refresh tokens
are 256 random bits, so a plain SHA-256 digest suffices: nothing can be guessed, and a leaked
table holds no token that works.

## Verifying a JWT: the checklist

- Accept a fixed list of algorithms (here HS256 only): this refuses `alg: none` and HS/RS
  confusion.
- Require and check `exp`, `iat`, `iss`, `aud`, and the claims you rely on; check the type
  (`at+jwt`), so a token minted for something else is refused.
- Never act on claims before the signature has been verified.
- Keep tokens out of URLs and logs; they are credentials.

## In this repository

`apps/api/src/sef_api/auth/` (tokens, passwords, the service and the routes); the decision is
ADR-0012.
