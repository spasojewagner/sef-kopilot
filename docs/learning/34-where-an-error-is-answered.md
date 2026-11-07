# 34. Where an error is answered decides what it carries

An ASGI application is an onion: each middleware wraps the one inside it, and a response passes
outward through every layer above the place where it was made. A layer adds what it adds only to
responses that pass through it.

```text
ServerErrorMiddleware   (Starlette's, outermost: answers an exception nobody took)
  CORSMiddleware        adds Access-Control-Allow-Origin on the way out
    DeclareUTF8         adds charset=utf-8 to JSON
      LimitBodies       answers 413
        AnswerUnexpectedErrors   answers 500 here, inside them all
          ExceptionMiddleware    HTTPException, registered handlers
            the routes
```

**The bug.** A route raised an exception that no handler took. It went outward through every
middleware, which do not catch, up to Starlette's `ServerErrorMiddleware`, which answered 500.
That answer was made outside `CORSMiddleware`, so it had no CORS headers. A browser hides the
answer of a cross-origin request without them: the page saw a network error, the same as for an
API that is down, and said "the API does not answer".

**The fix.** Answer the exception innermost, so that the 500 passes outward through the CORS
and charset layers like every other answer, and then raise it again: the outer layers do not
catch it, `ServerErrorMiddleware` sees that the answer has begun and sends nothing more, and the
server logs the traceback as before.

**Two rules for such a layer.**

- Never replace an answer that has begun. Once `http.response.start` has gone out, the status
  and headers are on the wire; a second start is a protocol error.
- Never swallow the exception. An error answered but not raised disappears from the logs, and
  a bug that nobody sees is a bug that stays.

**Why registering a handler for `Exception` is not enough.** Starlette gives a handler for
`Exception` (or 500) to `ServerErrorMiddleware`, the outermost layer, so its answer still
carries no CORS headers. The place of the code that answers matters, not the kind of handler.

**The test that proves it** asks with an `Origin` header and reads the 500's
`Access-Control-Allow-Origin`; a second test proves the exception still reaches the server.
