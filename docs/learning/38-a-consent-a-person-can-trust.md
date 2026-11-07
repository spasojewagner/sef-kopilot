# 38. A consent a person can trust: what the page shows, and what it refuses

When an assistant connects to the MCP endpoint, it does not get a password. It sends the
person's browser to the API's authorization server, which keeps the request and sends the
person to the web application to decide (ADR-0044):

```text
assistant ── browser ──▶ API  /oauth/authorize?client_id…&redirect_uri…&code_challenge…
                         API  302 ──▶ web  /oauth/consent?request=…
                                      web ── GET  /oauth/requests/{id}         (Bearer) ──▶ API
                                      web ── POST /oauth/requests/{id}/approval (Bearer) ──▶ API
assistant ◀── browser ── redirect_uri?code=…&state=…&iss=… ◀── the API's answer
```

The page is where the protocol meets a person, so it is built against three ways of fooling one.

**A name that lies.** Registration is open (RFC 7591): any client may call itself "Claude", or
"SEF Kopilot". The page therefore says the name is the client's own and unchecked, and shows
what the server did check: the host of the redirect URI, which must be one the client
registered, compared exactly. `claude.ai` is a site; `127.0.0.1:6274` or `cursor://…` is an
application on the person's own computer (RFC 8252), and the page says so.

**A request someone else started.** An attacker can begin an authorization with a client of
their own and send the link: "connect your invoices here". If the person allows it, the code
goes to the attacker's address, and only the attacker can use it, because only they hold the
PKCE verifier. Nothing in the protocol can tell this from a real request; the person can. So
the page asks them to allow only what they have just connected themselves, and shows where the
answer goes and which organization and account it will act in.

**A page under another page.** Shown in an invisible frame beneath a game that says "click
here", the page could be approved by a person who never saw it (clickjacking). Every page of the
application is served with `frame-ancestors 'none'` and `X-Frame-Options: DENY`, which RFC 9700
(§4.16) asks of an authorization server; the browser refuses to draw it in any frame.

**Why the approval needs no CSRF token.** A cross-site request forgery rides on what the
browser adds by itself, a cookie. The page sends the person's access token from its own memory
in an `Authorization` header, which another site's form cannot set, and the API takes the
decision from a signed-in person only, never an API key. The answer to the decision is the
redirect URI with the code, built by the server, so the page never composes where the code goes.

**What it does not do.** It cannot tell a careless click from a decision, and it keeps no list
of trusted clients: each request is decided as it comes. What a consent leads to, the code
exchanged for tokens, is the token endpoint's to bound.
