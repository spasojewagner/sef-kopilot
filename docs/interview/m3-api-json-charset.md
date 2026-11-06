# M3 — `fix/api-json-charset`

## Three questions a senior engineer would ask

**1. "JSON is UTF-8 by definition. Why send a charset at all?"**

RFC 8259 says so, and defines no `charset` parameter for `application/json`: a compliant
client needs none. Windows PowerShell 5.1 is not one. `Invoke-RestMethod` decodes a body whose
type names no charset as ISO-8859-1, so the two bytes of `č` became `Ä` and a control code,
and the three bytes of the model's „ and “ became `â` and two control codes, the second of
which a console reads as the start and end of a hidden string. The maintainer's first live
explanation showed exactly that. PowerShell 5.1 ships with Windows, and the people who will
call this API from an ERP's scripts often have nothing newer; the parameter costs nothing for
any other client.

**2. "Why middleware, and not a JSON response class with the charset in its media type?"**

A response class is used only by the routes that return it. FastAPI's own answers (a 422 for a
malformed request, the 404 of an unknown path, the OpenAPI document) are built by its own
handlers, which a default response class does not reach. Its media type is also the key of the
content in the OpenAPI document, which would then read `application/json; charset=utf-8`
everywhere and confuse generated clients. A middleware that rewrites the one header on the way
out covers every answer and leaves the documentation as it is.

**3. "What does the middleware leave alone, and how do you know?"**

Everything else. It changes only a `content-type` that is exactly `application/json`; the event
streams already say `text/event-stream; charset=utf-8`, and an invoice downloaded as
`application/xml` names its encoding in its own declaration. A test drives the middleware with
an XML answer and a header that merely contains `application/json`, both left untouched, and
another checks that a scope that is not HTTP (the lifespan) passes straight through.

## The one concept to explain unaided

**A media type's parameters are part of the contract clients actually read.** The standard can
make a parameter meaningless, but a client that guesses differently decides what the user
sees; declaring UTF-8 removes the guess.

## Supporting facts worth remembering

- `sef_api.charset.DeclareUTF8`, a pure ASGI middleware added in `create_app`; it rewrites the
  headers of `http.response.start` and nothing else.
- Newer PowerShell releases read JSON as UTF-8 without the parameter; 5.1, which ships with
  Windows, is the one that needed it.
- The bytes the API sent were always right: the fix changes what a client is told, not what it
  receives.
