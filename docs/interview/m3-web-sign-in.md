# M3 — `feat/web-sign-in`

## Three questions a senior engineer would ask

**1. "Local storage for a refresh token? Isn't an `HttpOnly` cookie the safe choice?"**

An `HttpOnly` cookie keeps a token from being read, but it needs a server of the web application
to hold it, and the web application is static pages today. The API is on another site, so a
cookie it set itself would be a third-party cookie, which Safari and Firefox block; it would
also bring CSRF to an API that ERPs call with tokens. What remains is the risk of XSS: a script
in the page can read local storage. Three things bound it. The access token is never stored,
only kept in the tab's memory. The API rotates refresh tokens and revokes the whole session
when a spent one comes back, so a stolen copy works until one of the person's tabs refreshes
again. And the pages keep scripts out: React escapes what it renders, no third-party script is
loaded, and a Content-Security-Policy comes with the hosting. No storage stops a script from
acting as the person while the page is open; the question is what it can take away. If the
hosting gives the web application a server, a back end for the front end can replace the module
that keeps the session, and the pages keep calling `authorized()`.

**2. "Two tabs, one refresh token, strict rotation. How do you avoid signing people out?"**

Two tabs that refresh at once present the same token, and the API takes the second for a thief.
So a refresh runs under a lock of the Web Locks API, `sef-kopilot.refresh`, which only one tab of
the browser holds at a time. The tab reads the refresh token only after it has the lock, because
the token it knew may have been spent by the tab before it. Within a tab, requests that arrive
together share one refresh. Each tab keeps its own access token in memory, so a tab's refresh
does not disturb another. A tab hears from the `storage` event when another signs out or another
visitor signs in, and drops an access token that is no longer the stored visitor's. I checked it
against the real API: two tabs reloaded at the same moment, refreshed one after the other, and the
session survived.

**3. "What does a page see when the access token expires, or the session ends somewhere else?"**

Nothing, in the first case. The access token is replaced 30 s before it expires, and a request
the API refuses with 401 gets a new token and is sent once more. When the refresh itself is
refused, the session has ended: the browser forgets it, `authorized()` throws `SignedOutError`,
and the header offers to sign in. The header also asks `/auth/me` when a page opens, so a session
that was revoked, by a sign-out elsewhere or a replayed token, ends here at once. An API that
cannot be reached keeps the session, and the next request tries again. When the visitor changes,
their cached answers are forgotten, so the next person at a shared computer does not see them.

## The one concept to explain unaided

**Strict rotation makes the refresh token a baton.** Whoever spends it passes the new one on, and
only one may hold it; that is why the tabs take turns, and read the token only once the lock is
theirs.

## Supporting facts worth remembering

- Local storage: `sef-kopilot.session` holds `refreshToken`, `refreshExpiresAt` and `identity`.
  The access token is in memory only, replaced 30 s early.
- The lock is `sef-kopilot.refresh`. Without the Web Locks API (Safari before 15.4), refreshes do
  not take turns.
- A refused refresh (401) forgets the session; an unreachable API keeps it. `SignedOutError` is an
  `ApiError` with status 401, which the query cache does not retry.
- Signing out forgets first, then calls `POST /auth/logout`.
- Errors are in the visitor's language: 401, 403, 409, 422, 429 (with `Retry-After`), and an API
  that cannot be reached. The API's own reasons are for developers.
- A query key that starts with `api` is the same for everyone; every other key is a visitor's,
  and is forgotten at sign-out.
