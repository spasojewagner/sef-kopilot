# 48. Unexpected errors are reported to Sentry where the operator chooses, without what a person sent

- Status: accepted
- Date: 2026-11-08
- Deciders: the team (milestone M4)
- Technical story: milestone M4, branch `feat/api-error-tracking`; the guardrails that no
  invoice content reaches a log or a trace, and that a self-hosted deployment calls out to
  nothing but its language model's provider

## Context and problem statement

An unexpected error in production is seen today in Render's log, if someone reads it. An error
tracker groups them, says when one is new and shows where it was raised. But an error report is
built from what the process holds when it fails: the request with its headers and body, the
variables of every frame, the exception's message, the log lines before it. In this API, that
is an invoice, a password, a token. What may be reported, to whom, and when?

## Decision drivers

- Nothing a person sent leaves the deployment in a report: no invoice, credential or token.
- Off unless the operator turns it on; a self-hosted deployment calls out to nothing it did not
  choose.
- Enough to fix the error: its type, where it was raised, the route, the release.
- A free plan, and one dependency.

## Considered options

1. **Sentry's SDK, on with `SENTRY_DSN`, every category of collected data off, and a scrubber of
   our own in front of the network.** Chosen.
2. The SDK with its defaults (`send_default_pii` off).
3. No error tracker: the platform's log, with the request id (`X-Request-ID`).

## Decision outcome

**Off unless `SENTRY_DSN` is set.** The API, when its application is created, and each worker,
when it starts, report to the project of `SENTRY_DSN`; without it the SDK is not started.

**Collected as little as the SDK can.** Every category of `data_collection` that holds what a
person sent is off: user and address, cookies, request headers, query, bodies, the frames'
variables, queries to the database, queues, model inputs. No breadcrumbs are kept and no
performance traces are taken. A line logged at error is reported; no line becomes a breadcrumb.

**Scrubbed again by our own code, last.** `before_send` keeps the request as its method and its
URL without query, drops the user, breadcrumbs and extra data, removes the frames' variables, and
replaces the exception's message and a log line's arguments: a message may quote what the
code was given (`could not read <Invoice>…`). What stays says where the error happened: its
type, its stack of files, functions and lines with the code around them, the route, the
release and the environment. A test reports an error raised while holding an invoice, a token
and a query, and finds none of them in what would be sent.

**A second wall in the organization's settings.** Sentry's own data scrubbers are required and
no IP address is stored, so a mistake in the code is not the last line.

### Consequences

Good:

- An unexpected error is seen, grouped and dated, with where it was raised, and a report holds
  nothing a person sent.
- A self-hosted deployment without the variable sends nothing.

Bad / accepted:

- Without its message, an error says less: what was being read is learned from the code and the
  route, or from the request's lines in the log, by its id.
- The free plan's monthly quota of errors is small; past it, reports stop until the month turns.
- One more dependency, `sentry-sdk`, and its integrations patch the frameworks it finds, even
  when it sends nothing (they do nothing without a client).

## Pros and cons of the options

### The SDK's defaults

- Good: richer reports, with messages and request data.
- Bad: the request body, the frames' variables and messages would carry invoices and tokens to
  a third party.

### No error tracker

- Good: nothing leaves the deployment.
- Bad: errors are found only by reading the log; nothing says that one is new.
