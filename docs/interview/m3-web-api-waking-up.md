# M3 — `feat/web-api-waking-up`

## Three questions a senior engineer would ask

**1. "Why not simply raise the timeout to two minutes?"**

Because a timeout cannot tell a sleeping API from a dead one, and cannot say which it is. With
two minutes everywhere, a page whose API is down hangs for two minutes on every click, and a
slow request looks like a sleeping one. Asking `/health` first separates the two questions: is
the API there, and what is the answer. The first can be asked again safely, for as long as the
platform needs to wake; the second is asked once, with its usual timeout.

**2. "Why wait before sending instead of retrying after a failure?"**

Because a write must not be sent twice. A request that timed out may have been done: an upload
stored, a repair approved. Sending it again could do it twice, which is why the pages read a
write's outcome again rather than repeat it (ADR-0032). Waiting before the request is sent is
always safe, since nothing has happened yet. So the browser repeats only `GET /health`, and
sends the request once the API has answered it.

**3. "Doesn't every request now pay for an extra round trip?"**

No. The browser remembers when the API last answered; for ten minutes after any answer, which is
less than the 15 after which the instance sleeps, requests go at once. Only the first request
after a pause asks `/health` first, one short request when the API is awake. The requests that
find it asleep share one wake-up rather than each knocking on their own.

## The one concept to explain unaided

**Waiting before is safe, retrying after is not.** A sleeping service is met by asking the one
question that changes nothing, whether it is up, until it is, and only then sending the request
that may change something, once.

## Supporting facts worth remembering

- Ten minutes awake after any answer below 500; two minutes to wake, `/health` asked for up to
  30 s at a time, 2 s apart; the notice after 3 s.
- The image is ready in about 35 s on a tenth of a CPU (ADR-0034); Render says up to a minute.
- A refusal of `/health` is an answer: the API is awake.
- The notice is a polite status region, always in the page, empty until needed.
