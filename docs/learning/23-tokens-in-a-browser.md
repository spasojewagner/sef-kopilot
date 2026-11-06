# 23. Tokens in a browser: where to keep them, and what can reach them there

A browser that calls an API in a person's name holds two secrets: a short access token sent with
each request, and a long refresh token that gets a new one. Every place to keep them trades one
risk for another.

| Place                     | Survives a reload | Shared by tabs | An injected script reads it | Sent by the browser on its own |
| ------------------------- | ----------------- | -------------- | --------------------------- | ------------------------------ |
| the tab's memory          | no                | no             | while the page is open      | no                             |
| session storage           | yes               | no (copied)    | yes                         | no                             |
| local storage             | yes               | yes            | yes                         | no                             |
| `HttpOnly` cookie         | yes               | yes            | no                          | yes: CSRF                      |

Two attacks frame the choice. **XSS**: a script that gets into the page acts as the person, and
reads whatever a script can read. **CSRF**: another site makes the browser send a request, and
the browser adds the cookies it holds for the target by itself. Tokens a script sends in
`Authorization` are safe from CSRF. Tokens in an `HttpOnly` cookie are safe from being read,
but need a server of the web application to hold them, and a defence against CSRF.

SEF Kopilot keeps the access token in memory and the refresh token in local storage (ADR-0027).
What makes that acceptable is the API's **rotation**: each refresh spends the token and issues
the next, and a spent token that comes back revokes the whole session. A thief who copies the
token can use it, but the next time the person's own tab refreshes, both are signed out.

Rotation makes the refresh token a baton: whoever spends it passes the new one on, and only one
may hold it. Two tabs that refresh at once would both present the same token, and the API would
take the second for a thief:

```text
tab A ─ lock ─ read R1 ─ spend R1 → R2, keep R2 ─ unlock
tab B ─────── wait ──────────────────────────────── lock ─ read R2 ─ spend R2 → R3 ─ unlock
```

So the tabs take turns (`navigator.locks`), and each reads the token only once it holds the
lock: the one it knew may be spent already. Within a tab, requests that arrive together share
one refresh.

What still reaches the tokens: a script injected into the page. No storage choice stops a script
from acting as the person while the page is open. The defence is keeping scripts out: escaping
what is rendered (React does), loading no third-party script, and a Content-Security-Policy.

The question to ask of any token storage: if a script got into this page, what could it take
away with it, and for how long would it work?
