# M2 — `feat/api-jobs-sse`

## Three questions a senior engineer would ask

**1. "Your queue can deliver a job twice. How do you make sure its work is not done twice?"**

By not trusting the queue with anything but "job 42 waits". The job's row is the truth.
Taking a job on increments `attempts`, which becomes the attempt's fencing token, and every
later write requires `attempts = mine AND status = 'running'`. A worker given up for dead that
wakes up learns at its next write that it was superseded, and stops. The revalidation job
writes each invoice's new report and its count in the progress in one transaction, so a new
attempt continues after the last invoice done and repeats nothing, while a stale attempt's
transaction fails at the fence and takes its report with it. Delivery is at least once; the
effect is once. Tests supersede an attempt mid-invoice, cut one short at shutdown and resume
it, and let a worker's attempt run past its time limit.

**2. "Why server-sent events, and why does the stream poll the database instead of being
pushed changes?"**

Progress only ever flows from server to client, and SSE is plain HTTP: it passes the proxies
WebSockets need upgrade support for, and resumption is part of the protocol. Each event's id is
the job's `version`, so `Last-Event-ID` resumes exactly. The stream reads one row by primary
key once a second, in a session of its own, and holds no connection while it waits.
LISTEN/NOTIFY would push changes, but it needs a listening connection in every process, it
does not pass PgBouncer in transaction mode, as hosted PostgreSQL uses it, and it loses what is
sent while it reconnects, so the row would still be read. The permission check is a
dependency, so a 404 comes before the stream begins. The stream ends after five minutes, so
access is checked again on reconnect.

**3. "What happens when Redis goes down, or a worker dies halfway?"**

Nothing is lost, because nothing lives only in Redis. A job the API could not put on the queue
waits queued in its row, and the API answers 202 all the same. Every worker sweeps all
unfinished jobs onto the queue when it starts and once a minute. arq takes each id once, so
jobs already queued or running are untouched, and keeps no results, so a job cut short can go
back at once. A dead worker's job goes back with the next sweep, and its next attempt
continues from the checkpoint. With one process, `SEF_JOBS=inline` runs jobs in the API's own
event loop, with no Redis at all, and resumes unfinished ones at startup. That is also how the
tests run.

## The one concept to explain unaided

**At-least-once delivery plus fenced, checkpointed writes gives an exactly-once effect.** The
queue may repeat itself; the database decides, with a token that makes a stale worker's writes
fail and a checkpoint that commits the work and its count together.

## Supporting facts worth remembering

- `jobs` (migration 0006): status `queued → running → succeeded | failed`, `version` for
  readers, `attempts` as the fencing token, a partial unique index for one unfinished job per
  member and kind (a second `POST` answers 409 with `Location`).
- `POST /invoices/revalidations` → 202 and `Location: /jobs/{id}`; the caller's scope, the
  invoices stored by the time it started, one per transaction, larger reports held to the
  quota under the upload lock (`kept`), counts of `valid`, `invalid`, `kept`, `failed` and
  `deleted`. `validated_at` (migration 0007) says when a report was made.
- `GET /jobs/{id}/events`: event `job`, `id` = version, a reading a second, a comment every
  15 s, the end with the finished job or after 5 minutes.
- `SEF_JOBS=inline` by default; `SEF_JOBS=arq` with `REDIS_URL` and
  `python -m sef_api.jobs.worker`; an attempt runs at most an hour.
- Render's free tier runs no background worker, so a free deployment runs jobs inline.
