# M4 — `feat/api-error-tracking`

## Three questions a senior engineer would ask

**1. "An error tracker sees everything the process held when it failed. How do you keep invoices
out of it?"**

With three walls, each enough on its own for what it covers. The SDK is asked to collect
nothing a person sent: every category of its `data_collection` that holds a request, a user, a
body or a frame's variables is off, and no breadcrumbs are kept. Then our own `before_send`
keeps the request as its method and path, drops the user and extra data, and replaces the
exception's message and a log line's arguments, since a message may quote what the code was
given. Last, the Sentry organization requires its own scrubbers and stores no IP address. A test
raises an error while holding an invoice, a token and a query, and finds none in the report.

**2. "Without the message, can you still fix the error?"**

Usually: the type, the stack with the code around each frame, the route and the release say
where and what failed. When the input matters, the request's lines in the platform's log, found
by its `X-Request-ID`, say what happened around it, still without the invoice. It is the
trade-off ADR-0048 accepts: less in the report, nothing private outside the deployment.

**3. "Why read `SENTRY_DSN` yourself rather than let the SDK find it?"**

So that nothing starts unless the settings say so, and the variable is checked and kept secret
like the others (`SecretStr`). A self-hosted deployment without it sends nothing anywhere; a test
holds that, and the tests' own reports go to a transport that keeps them in memory, never to
the network.

## The one concept to explain unaided

**Defence in depth for data leaving the system**: decide what a report may hold, then enforce it
at each layer that could add more (the SDK's collection, our scrubber, the service's settings),
and test the result, not the configuration alone.

## Supporting facts worth remembering

- The API reports when its application is created; each worker when it starts.
- The free Developer plan has a small monthly quota; past it, reports stop until the month turns.
