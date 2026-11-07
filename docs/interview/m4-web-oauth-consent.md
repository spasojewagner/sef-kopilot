# M4 — `feat/web-oauth-consent`

## Three questions a senior engineer would ask

**1. "Anyone can register a client called 'Claude'. What on your consent page can a person
actually trust?"**

The address it takes them back to. The server compared the redirect URI with the ones the
client registered, exactly, so the host is what the code will reach; the page shows it, and
says when it is an application on the person's own computer (the loopback interface, or a
scheme of its own). The name is the client's claim and is shown as unchecked. The organization
and account it will act in are shown too, with a way to sign in with another.

**2. "Why is `frame-ancestors 'none'` on every page, and not a full Content-Security-Policy?"**

Framing is how a consent is clickjacked: the page drawn invisibly under one that has the person
press "Allow". RFC 9700 asks an authorization server to prevent it, and no page of ours is
meant to be framed, so one rule for every path is simpler than a list. A policy for scripts is
another matter: Next.js's inline scripts would need a nonce, which means rendering every page
per request, or the hashes of each build's scripts; that choice belongs with the hosting.

**3. "The approval is a POST from the browser. Where is the CSRF protection?"**

There is no cookie to ride on. The page sends the access token it keeps in memory in an
`Authorization` header; a form on another site cannot set that header, and CORS lets only the
web application's origin send it. The API also refuses an API key: only a person decides.

## The one concept to explain unaided

**Consent phishing**: a code is useful only to whoever holds the PKCE verifier, that is, to
whoever started the authorization. The protocol cannot tell a request the person started from
one an attacker started and sent them as a link; the consent page exists so that the person
can.

## Supporting facts worth remembering

- The API sends the person to `SEF_WEB_URL/oauth/consent?request=…`; the page opens in the
  browser's language, and the language links keep the query.
- A visitor who is not signed in signs in on the page and stays (`SignInForm`'s `onSignedIn`).
- The golden path ends with a client registering, the person allowing it on the page, and the
  client's `code`, `state` and `iss`; the end-to-end test's API is its own authorization server.
