# M4 — `feat/api-security-events`

## Three questions a senior engineer would ask

**1. "What makes something a security event, and what stays out of it?"**

A decision about who may do what: a sign-in succeeded or refused, a credential refused, a token
presented a second time, a consent or a repair decided. Each is logged with fields that
identify it (ids, the client's address, a reason) and never with what a person typed: a refused
sign-in does not log the e-mail address tried, since people type passwords into the wrong
field. The audit log in the database stays the record an organization accounts with; these
lines are for whoever watches the service.

**2. "Why configure JSON logs in a file uvicorn reads, not in the application?"**

Because the process's logging is the deployment's to decide, not a library's or a test's:
`create_app` runs in every test, where pytest's own handlers must stay. The container's start
command passes `--log-config` with a `dictConfig` file that writes every line, uvicorn's own
included, as JSON; development keeps the server's plain lines. A test loads the file and checks
the start command names it.

**3. "How does a line know which request it belongs to?"**

A context variable, set by an ASGI middleware around everything, which the formatter reads; the
same id is sent back as `X-Request-ID`, so a person reporting a failure gives the id that finds
its lines. A client's own id is kept only if it is a plain token of at most 64 characters, so
that a header cannot write into a log line.

## The one concept to explain unaided

**Observability without disclosure**: log the decision and who it concerned, never the payload;
the line must be safe to read for whoever runs the service.

## Supporting facts worth remembering

- A reused refresh token ends every session of its family and logs `session.refresh-reused`; a
  reused code or refresh token of the authorization server revokes the consent and logs
  `oauth.code-reused` or `oauth.refresh-reused`.
- A key's use, and when each key was last used, follow in a branch of their own.
