# M3 — `fix/api-unexpected-errors-readable`

## Three questions a senior engineer would ask

**1. "The API had CORS configured. Why did a 500 have no CORS headers?"**

Because of where the 500 was made. Starlette answers an exception that no handler took in its
outermost layer, `ServerErrorMiddleware`, which wraps the CORS middleware; an answer made there
never passes through it. The browser then hides the answer from the page, which sees only a
network error and cannot tell a bug from a server that is down.

**2. "Why not register an exception handler for `Exception`?"**

Starlette gives such a handler to the same outermost layer, so its answer would have no CORS
headers either. The fix is a middleware placed innermost, inside CORS and the charset's, that
answers the exception with a JSON 500, which the outer layers then dress like any other answer.

**3. "Doesn't catching every exception hide bugs?"**

It would if it stopped there. The middleware raises the exception again once its answer is sent,
so the server logs the traceback exactly as before; Starlette's outer layer sees that the answer
has begun and sends nothing more. And it does not touch an answer that had already begun, such
as a stream that fails halfway: that one cannot be replaced.

## The one concept to explain unaided

**Middleware is an onion.** A response gets what every layer between where it was made and the
outside adds to it, and nothing from the layers outside that place.

## Supporting facts worth remembering

- `app.add_middleware` puts each new middleware outside the ones added before: the first added
  is the innermost.
- httpx's `ASGITransport(raise_app_exceptions=False)` lets a test read the 500 that the server
  would send; with the default, the test sees the exception, as the server does.
- The web application now says that a request failed, rather than that the API does not answer.
