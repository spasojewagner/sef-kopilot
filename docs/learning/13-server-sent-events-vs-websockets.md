# Server-sent events vs. WebSockets

Both keep a connection open so that a server can tell a client about a change without being
asked. They differ in direction, in what they ride on, and in what they give for free.

| | Server-sent events | WebSockets |
| --- | --- | --- |
| Direction | server → client | both |
| Protocol | plain HTTP: a response that does not end, `text/event-stream` | an HTTP request upgraded to another protocol (RFC 6455) |
| Proxies, CDNs, HTTP/2 | as any response (with buffering off: `X-Accel-Buffering: no`) | every hop must support the upgrade |
| Reconnecting | built in: the browser reconnects and sends `Last-Event-ID` | the application's own |
| Authentication | the request's, before the stream begins | the upgrade request's; a browser sends no custom header |
| Data | text (UTF-8) | text or binary |

## The wire format

```text
event: job
id: 4
data: {"status": "succeeded", "version": 4}

: ping
```

An event is lines of `field: value` ended by an empty line. A line that starts with `:` is a
comment: sent now and then, it keeps a quiet stream from an idle timeout.

## Choosing

- Progress, notifications, a model's tokens: the server talks and the client listens, so SSE.
- Chat, collaborative editing, games: both talk all the time, so WebSockets.
- Polling (the client asks every few seconds) works anywhere, but each time pays a request, its
  authentication and its query, and the client must work out what changed.

## Pitfalls

- A browser's `EventSource` cannot send an `Authorization` header. With bearer tokens, read
  the stream with `fetch` and a small parser, or a library such as
  `@microsoft/fetch-event-source`.
- Decide everything that can fail before the first byte: once the status line is sent, a 404
  is impossible.
- A stream holds a connection open; it must not hold a database connection or a transaction
  with it.
- A stream outlives the token it was opened with. End it after a while, and let the client
  reconnect, so that access is checked again.
- Make each event's `id` a position the server can resume from, here the job's `version`, and
  honour `Last-Event-ID`.

## In this repository

- `apps/api/src/sef_api/jobs/routes.py`: `GET /jobs/{id}/events` with FastAPI's
  `EventSourceResponse`, which reads the job once a second and ends after five minutes.
- `apps/api/tests/streams.py`: a client that speaks ASGI to the application, so that a test
  sees each event as it is sent; `test_jobs.py` follows a job from its start to its end.
- The decisions are recorded in ADR-0019.
