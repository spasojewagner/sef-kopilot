# 21. CORS: which pages may read the API's answers

A browser runs scripts from many origins, an origin being a scheme, a host and a port:
`http://localhost:3000` and `http://127.0.0.1:8000` are two. By default a script may send a
request to another origin but may not read the answer; that is the same-origin policy. CORS
(cross-origin resource sharing) is how a server tells the browser which other origins' scripts
may read its answers.

```text
page at http://localhost:3000                      API at http://127.0.0.1:8000
  fetch(".../health") ─────────────────────────►  GET /health
                                                   Origin: http://localhost:3000
  reads the answer  ◄────────────────────────────  200 OK
                                                   Access-Control-Allow-Origin: http://localhost:3000
```

A request that is not "simple" (a header such as `Authorization`, a JSON body, `PATCH` or
`DELETE`) is asked about first. The browser sends a preflight, and the real request only if
the answer allows it:

```text
OPTIONS /invoices/validate   Origin, Access-Control-Request-Method: POST,
                             Access-Control-Request-Headers: authorization, content-type
  ◄── 200  Allow-Origin, Allow-Methods, Allow-Headers, Max-Age: 600
POST /invoices/validate      (now, and without asking again for ten minutes)
```

**What CORS protects is the visitor.** A page at another origin cannot read what the API says
to the visitor's browser: answers to requests that carry the visitor's cookies, or that only
the visitor's network can reach.

**What it does not protect is the API.** `curl`, a server, or any program outside a browser
ignores CORS. A simple request from a page at another origin still reaches the API and is
handled; the browser only hides the answer. So the API authenticates and authorizes every
request whatever its origin, and CORS is a layer on top, never the lock.

**The choices here** (`SEF_WEB_ORIGINS`, ADR-0026):

- A list of origins, never `*`, and only `https://` ones in production.
- No credentials: `Access-Control-Allow-Credentials` is never sent, so the browser sends no
  cookie. The token travels in `Authorization`, which a page at another origin does not have.
- A page reads only a few "safelisted" headers of an answer unless the API names more. It
  names `Location` and `Retry-After`.
- A refusal carries the CORS headers too: the middleware wraps every other one, so a page can
  read why its request was refused (a 413 for a body too long, say). Without them the page
  would see only a network error, which is what it sees of an unexpected failure: Starlette
  answers a 500 outside every middleware.

The question to ask of any CORS setting: who can read this answer? Here it is a page at a
listed origin, and anyone outside a browser who holds a valid token.
