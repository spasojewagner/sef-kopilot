# 36. The pages wait for a sleeping API, and say that it is waking up

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević
- Technical story: milestone M3, branch `feat/web-api-waking-up`; the consequence ADR-0035
  accepted

## Context and problem statement

The public demo's API runs on Render's free plan (ADR-0035), which stops the instance after 15
minutes without a request. The next request starts it again: the image is ready in about 35 s on
its share of a CPU (ADR-0034), and Render says to expect up to a minute, during which the request
waits or fails. Every request of the web application gave up after 10 s. So the first visitor
after a pause read, in the footer and under every button, that the API does not answer, while it
was starting. How should the pages behave while the API wakes?

## Decision drivers

- A visitor who arrives while the API sleeps is told what is happening and kept waiting, rather
  than told that something failed.
- No write is sent twice: an upload, a repair's approval or a sign-in whose outcome is unknown is
  read again, not repeated (learning note 29).
- An API that is up answers as fast as before, and one that is down is still said to be down.
- Nothing paid, and no traffic that keeps a free instance awake for nobody.

## Considered options

1. **Ask `/health` first when the API has not answered for a while, wait for it, then send the
   request once.** Chosen.
2. Give every request a timeout of two minutes.
3. Send the request; when it fails to reach the API, wait until the API answers and send it
   again.
4. Keep the API awake: a scheduled request every ten minutes.
5. A paid instance, which does not sleep.

## Decision outcome

**The browser remembers when the API last answered** this tab: any answer below 500, since a
platform's error while the instance starts is a 5xx, and a page can read an answer only with the
API's CORS headers. For ten minutes after it, less than the 15 after which the instance sleeps,
the API is taken to be awake, and a request is sent at once.

**Otherwise a request first waits** (`whenAwake` in `apps/web/src/lib/api.ts`): it asks
`/health`, each time for up to 30 s and again 2 s after a failure, until the API answers or two
minutes have passed. All the requests that wait share one wake-up. The request is then sent once,
and its own timeout counts from there. A request whose signal aborts stops waiting, and the
wake-up goes on for the others. If the API never answers, the request fails with the last error,
as before, and the page says that the API does not answer. A refusal of `/health` is an answer:
the API is awake, and the request goes.

**The health check waits the same way**, so it is not tried again when it fails.

**The pages say so.** Once a wake-up has gone three seconds without an answer, the footer says
that the API is waking up, and a notice above every page says that a server idle for a while
takes about a minute to wake, and that what the visitor sends waits and goes as soon as it
answers. A polite status region holds the notice, so that a screen reader announces it. Both go
once the API answers. A wait over within three seconds shows nothing.

### Consequences

Good:

- The first visit after a pause shows the API waking, then working, and an upload sent meanwhile
  goes once the API is up.
- No request is sent twice, so a write's outcome never becomes unknown because of the wait.
- An awake API costs nothing more: a request is sent at once for ten minutes after any answer,
  and a page that asks after that sends one `GET /health` first.
- The demo's free hours are spent only when someone uses it.

Bad / accepted:

- An API that is down is said to be waking up for two minutes before it is said to be down, the
  first time a page asks it after a pause.
- An API that went down within ten minutes of its last answer is not waited for: its requests
  fail as before, and the visitor tries again.
- A request may wait up to two minutes before its own timeout begins: a button says that it is
  sending meanwhile, with the notice above it.

## Pros and cons of the options

### A timeout of two minutes for every request

- Good: one number changes.
- Bad: a request to an API that is down hangs for two minutes; a request that is merely slow is
  not told apart from a sleeping API; nothing can say that the API is waking up rather than slow.

### Sending again after a failure

- Good: an awake API pays nothing, not even the check.
- Bad: a write that timed out may have been done; sending it again could store an invoice twice
  or decide a repair twice, which learning note 29 and ADR-0032 exist to prevent.

### A scheduled request to keep it awake

- Good: no visitor ever meets a sleeping API.
- Bad: about 730 hours a month of an instance that serves nobody, against Render's 750 free hours
  for the whole workspace, which the maintainer shares with other services; and it defeats the
  purpose of a free tier's sleep.

### A paid instance

- Good: no sleep at all.
- Bad: a paid service, which the brief rules out for the demo.
