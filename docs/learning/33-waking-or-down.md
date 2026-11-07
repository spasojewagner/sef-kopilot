# 33. Waking or down: a cold start, seen from the browser

A free instance that sleeps is a cold start you cannot avoid, only meet well. From the browser,
a sleeping API and a dead one look the same for the first seconds: no answer. What tells them
apart is **time**, and **what you know from before**.

```text
last answer < 10 min ago  ──►  awake: send at once, fail as before
no answer for 10 min      ──►  maybe asleep: ask /health until it answers (≤ 2 min)
                                 ├─ answers ─────────► send the request, once
                                 ├─ > 3 s, no answer ► say "the API is waking up"
                                 └─ 2 min, no answer ► down: say so
```

**Why ten minutes.** The platform stops the instance after 15 minutes without a request. An
answer less than ten minutes old means it cannot have slept since, with room to spare.

**Wait before, never retry after.** Waiting before a request is sent is always safe: nothing has
happened yet. Retrying after a failure is safe only for a read. A write that timed out may have
been done (learning note 29): sending it again could store an invoice twice. So the browser asks
the one question that is safe to repeat, `GET /health`, and sends the write only once the API is
there.

**Share the wait.** Five requests that find the API asleep do not each knock five times: they
wait on one wake-up. A request whose page is left stops waiting; the wake-up goes on for the
others.

**Say it after a moment, not at once.** Most checks answer in milliseconds; a notice that
flickered on every page load would be noise. Three seconds without an answer is long enough to
mean something, and short enough that the visitor has not left yet.

**Say what to do.** "The API is waking up" alone invites a reload, which only starts over. The
notice says how long it takes and that what is sent will go: the visitor's best move is to wait.

**Accessibility.** The notice lives in a polite status region that is always in the page, empty
until it is needed: a region that appears with its content may never be announced.

**The cost.** An API that is down is called waking for two minutes, the first time after a
pause. That is the price of not knowing; the alternatives are a dead API that looks alive
forever (a long timeout) or a write sent twice (a retry).
