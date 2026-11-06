# 27. A visitor's tokens in the browser: the access token in memory, the refresh token in local storage, one refresh at a time

- Status: accepted
- Date: 2026-11-06
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-sign-in`, split from `feat/web-upload-report`
  because every endpoint of invoices needs a token; the question ADR-0026 left open

## Context and problem statement

The web application signs people in with the API's tokens (ADR-0012). The access token is a
JWT good for 15 minutes, sent in `Authorization`. The refresh token is good for 30 days and
spent on use, and a spent one presented again revokes the whole session. The pages call the API
from the browser across origins, and the web application is meant for static hosting
(ADR-0026). Where does the browser keep the tokens, so that a reload or a second tab stays
signed in, a stolen copy is worth little, and two tabs do not end the session by spending one
token twice?

## Decision drivers

- A script injected into the page (XSS) can read any token a script can read. A cookie the
  browser sends by itself brings cross-site request forgery (CSRF).
- A session survives a reload and serves several tabs: an accountant keeps several open.
- The API's strict rotation: a refresh token presented twice ends the session for everyone.
- The web application has no server of its own today, and the API is on another site.
- No change to the API's tokens.

## Considered options

1. **The access token in the tab's memory; the refresh token and whose it is in local storage;
   the tabs taking turns to refresh, with the Web Locks API.** Chosen.
2. Both tokens in memory only.
3. The refresh token in session storage.
4. A server of the web application that keeps the tokens and gives the browser an `HttpOnly`
   cookie (a back end for the front end).
5. The API setting the refresh token as a cookie itself.

## Decision outcome

**Where each token is** (`src/lib/session.ts`). The access token, its expiry and whose it is
stay in a variable of the tab, and are replaced 30 s before the token expires. Local storage
keeps `sef-kopilot.session`: the refresh token, when it expires, and the identity the API gave
with it (user, organization, role). The access token is never stored. When the browser refuses
local storage, as a private window may, the session lives in the tab's memory alone.

**One refresh at a time.** A refresh runs under the lock `sef-kopilot.refresh`
(`navigator.locks`). It reads the refresh token after it has the lock, since another tab may
have spent the one this tab knew. Requests of one tab at the same moment share one refresh. A
refresh the API refuses (401) ends the session here; one that cannot reach the API keeps it, and
the next request tries again.

**Requests.** `authorized()` sends the access token. When the API refuses it, the token is
replaced once and the request sent again. With no session left it throws `SignedOutError`, an
`ApiError` with status 401, which the query cache does not retry.

**Signing out** forgets the session at once, then asks the API to revoke it
(`POST /auth/logout`). If the API cannot be reached, the session is forgotten here, and its
refresh token expires unused.

**Other tabs** hear of every change through the `storage` event. A tab whose access token
belongs to a visitor that local storage no longer holds drops it. When a visitor signs out, or
another signs in, the visitor's cached answers are forgotten: a query key that starts with `api`
is the same for everyone, and every other key is a visitor's. The header asks `/auth/me`, which
ends here a session the API has ended.

No cookie is set, and the API's CORS keeps refusing credentials.

### Consequences

Good:

- A reload or a new tab stays signed in, with no server of the web application.
- No cookie: nothing for CSRF to use.
- An access token is never stored. A stolen copy of the refresh token is noticed when one of the
  person's tabs refreshes next: the API revokes the session for the thief and the person alike.
- The tabs never spend one token twice.

Bad / accepted:

- A script injected into the page can read the refresh token, and use it elsewhere while the
  person's tabs are closed; reuse detection ends the session only when one of them refreshes
  again. The defence is keeping scripts out: React escapes what it renders, the pages load no
  third-party script, and `chore/infra-deploy` adds the Content-Security-Policy with the
  hosting (`SECURITY.md`, V3).
- A browser without the Web Locks API (Safari before 15.4) refreshes without taking turns; two of
  its tabs refreshing at the same moment end the session.
- Every page load spends a refresh token, because the access token is not stored. The API allows
  60 refreshes a minute from one address.

## Pros and cons of the options

### Both tokens in memory only

- Good: nothing is left in storage for a script to read later.
- Bad: a reload or a new tab signs the person out. While the page is open, an injected script
  can use the tokens anyway.

### The refresh token in session storage

- Good: it is gone with the tab.
- Bad: a new tab signs in again, and a duplicated tab copies the token, so that two tabs spend
  one token and end the session. A script reads it as it reads local storage.

### A server of the web application that keeps the tokens

- Good: no script can read the tokens, and the browser holds an `HttpOnly`, `SameSite` cookie.
  The IETF's draft on OAuth for browser-based applications recommends it.
- Bad: the web application needs a server, which static hosting does not give, and every request
  crosses one more service, with its own cold start on free tiers. The cookie needs a defence
  against CSRF. `chore/infra-deploy` decides the hosting and can revisit this; only
  `src/lib/session.ts` would change, and the pages keep calling `authorized()`.

### The API's own cookie

- Good: no server for the web application.
- Bad: the API and the web application are on different sites, so it would be a third-party
  cookie, which Safari and Firefox block. It would bring CSRF to an API that ERPs and MCP
  clients call with tokens.
