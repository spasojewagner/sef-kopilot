# 19. Jobs: a row that is the truth, fenced attempts that continue, inline or arq runners, progress over SSE

- Status: accepted; amends [0016](0016-stored-invoices.md), under which a stored invoice's
  report is now its latest, and `validated_at` tells when the validator made it
- Date: 2026-11-05
- Deciders: Marko Spasojević
- Technical story: milestone M2, branch `feat/api-jobs-sse`

## Context and problem statement

SEF's rules change: the rulebook and the technical instruction are amended, and with them the
rule sets. An invoice stored as valid may be invalid under the rules a server has now, and an
organization may store thousands. Validating all of them again takes minutes, far longer than a
request should, so it runs as a job, the first of several (explanations, repairs and sending
to SEF follow). Four things were open:

- where a job's state lives, and what carries the news that one waits;
- what happens when a worker dies, or a job runs twice;
- how a client follows a job;
- what validating stored invoices again does to their reports and to the quota.

## Decision drivers

- A job outlives the process that runs it: none is lost, and none does its work twice.
- The tests run in-process, without Redis (the brief).
- Free tiers: Render's free web service runs one process and no background worker; Neon's
  compute suspends when idle; Upstash counts every command.
- Tenant isolation, scopes and the quota hold as for every request (ADR-0013, ADR-0016).
- Boring, explainable choices.

## Considered options

Where a job's state lives:

1. **A `jobs` table in PostgreSQL; a queue carries only a job's id.** Chosen.
2. arq's own records in Redis: the job, its status and its result.

What makes running a job twice safe:

1. **A fencing token: taking a job on counts an attempt, and every later write requires the
   attempt to be the latest; progress may share the transaction of the work it counts.**
   Chosen.
2. A lock held for the length of the job (`SELECT … FOR UPDATE`, an advisory lock).
3. A lease with heartbeats.

What runs jobs:

1. **A `JobRunner` with two implementations: inline in the API's event loop (the default),
   and arq on Redis with separate workers that sweep unfinished jobs onto the queue.** Chosen.
2. arq only.
3. A queue in PostgreSQL that workers poll (`SELECT … FOR UPDATE SKIP LOCKED`).

How a client follows a job:

1. **Server-sent events, from a stream that reads the job's row once a second.** Chosen.
2. WebSockets.
3. The client polls `GET /jobs/{id}`.
4. LISTEN/NOTIFY, to push each change to the stream.

## Decision outcome

**The table.** `jobs` (migration 0006) holds the organization, the member who started the job
(forgotten when their account is deleted), its kind (`revalidation`), its parameters, its
status (`queued`, `running`, `succeeded`, `failed`), its progress, its result or error, and
two counters: `version`, which grows with every change, and `attempts`, the times a worker
took it on. A constraint keeps `finished_at` set exactly when the job has finished. A partial
unique index allows a member one unfinished job of each kind, so that two requests at once
cannot both start one.

**Running a job.** Each step is a transaction on the job's row. Taking a job on works from
`queued` or `running`, so that a job whose worker died can be taken on again; it counts one
attempt more. Every report of progress, and the end, are written only `WHERE attempts = mine
AND status = 'running'`: an attempt given up for dead learns at its next write that it was
superseded, and stops without touching its successor's work. A finished job is left alone. A
job that fails records `the job could not be completed`, or the message of a `JobError`
written for its member; only the type of the error is logged, never what it said about an
invoice.

**Continuing.** An attempt sees the progress of the attempts before it. A handler may write its
progress in the transaction of the work the progress counts, so that the two are committed
together or not at all: an attempt that continues repeats nothing, and a superseded attempt,
whose transaction fails, leaves nothing behind. The queue may deliver a job more than once; its
effect happens once.

**The runners.** `SEF_JOBS=inline` (the default) runs each job as a task of the API's own
event loop. The API takes on again, when it starts, the jobs left unfinished, and cuts short
the running ones when it stops; their rows say so. `SEF_JOBS=arq` puts each job's id on a
Redis queue (`REDIS_URL`), and `python -m sef_api.jobs.worker` runs it with a database engine
and a validator of its own:

- arq takes each id once, so a job put there while it waits or runs is not put there again,
  and keeps no results, so that a job cut short can go back at once;
- a worker sweeps every unfinished job onto the queue when it starts and then once a minute;
  a job the API could not put there (the API then answers 202 all the same and logs it), a
  job whose worker died, or whose attempt ran past its hour, goes back and continues;
- the API does not resume jobs itself in this mode.

**Validating stored invoices again.** `POST /invoices/revalidations` answers 202 with the job,
and `Location` names it. The job takes on the invoices the caller may see, as `GET /invoices`
lists them, that were stored by the time it was started; a later one was validated with the
current rules when it was stored. It takes them in the order of their ids, one at a time: it
reads the document, validates it holding no connection, then, in one transaction, replaces
the report and counts the invoice in the progress, which names the last one done. A larger
report is held to the quota under the same lock as an upload: an invoice whose new report
would not fit keeps its old one and is counted as `kept`. The progress and the result count
`total`, `done`, `valid`, `invalid`, `kept`, `failed` (too large, too slow, refused by the rule
sets) and `deleted` (meanwhile). Without a validator the job fails with `the validator cannot
run on this server`. A member has one revalidation under way at a time: another request answers
409 with the one under way in `Location`.

**When the report was made.** `invoices.validated_at` (migration 0007, filled from
`created_at` for the invoices stored before) tells when the validator made an invoice's report,
and every answer about a stored invoice carries it. This amends ADR-0016: a stored report is the
latest, not the first.

**Following a job.** `GET /jobs/{id}` reads it, within the same scope as invoices, with
`Cache-Control: no-store`. `GET /jobs/{id}/events` is a stream of server-sent events: a `job`
event with the job at once and whenever its `version` grows, whose `id` is that version, so
that a client that reconnects with `Last-Event-ID` is sent only what changed after it; the
stream, too, is sent with `Cache-Control: no-store`. Whether the caller may see the job is
decided before the stream begins (a 404 in JSON), and the request's connection then goes back
to the pool: the stream reads the row once a second in a
short session of its own. It ends with the finished job, or after five minutes, when the
client reconnects and is authorized again. FastAPI sends a comment every 15 seconds on a quiet
stream, so that proxies keep it open. A browser's `EventSource` cannot send an `Authorization`
header, so clients read the stream with `fetch`.

### Consequences

Good:

- A job survives a dead worker, a restart, a lost queue and a duplicate delivery, and its
  effect happens once: the database says what is done, the queue only what to do next.
- One process needs no Redis, and the tests run in it; the same handlers run in arq workers
  when there are more.
- A client sees progress within a second, through any proxy that passes HTTP, and resumes
  where it stopped.
- The quota holds exactly, against uploads and revalidations at once.

Bad / accepted:

- Every open stream reads one row a second, by primary key. Reads are not rate limited
  (ADR-0018), and a stream ends after five minutes.
- A stream outlives the access token it was opened with by up to five minutes; a member removed
  meanwhile sees their job's counts until then.
- A job's scope is fixed when it starts: a member whose role changes meanwhile has their job
  finish as it was started.
- Inline jobs take turns with requests at the API's one validator. Several API processes in
  inline mode would each take on every unfinished job when they start: the attempts supersede
  each other, so the work is wasted but correct.
- Render's free web service has no background worker: a free deployment runs jobs inline, and
  arq needs a worker process somewhere (`chore/infra-deploy` decides).
- Finished jobs accumulate; a retention policy is still to come.
- An invoice whose new report would not fit keeps a report made under older rules; its
  `validated_at` and the job's `kept` say so.
- arq 0.28 closes its connections with a method redis-py deprecated; the test suite ignores
  that one warning.

## Pros and cons of the options

### arq's own records

- Good: one place, no table.
- Bad: what a member reads, and what must survive, would live in a cache with expiry, on a free
  tier that counts every command; and the inline runner would need a second store.

### A lock held for the length of the job

- Good: no second attempt can start.
- Bad: a transaction, and a pooled connection, held for minutes; a lock dies with its
  connection, so a worker that hangs without dying holds it for ever.

### A lease with heartbeats

- Good: a dead worker is noticed sooner.
- Bad: a write every few seconds per job, and still a fencing token for the worker that wakes
  after its lease ran out; the fence alone already makes a second attempt safe.

### arq only

- Good: one runner to maintain.
- Bad: Redis for every test, every developer and the free deployment, which runs one process.

### A queue in PostgreSQL

- Good: no Redis at all, and the queue is the row.
- Bad: every worker polls the database, which keeps Neon's compute from suspending and spends
  its free hours; the brief fixes arq.

### WebSockets

- Good: both directions, binary frames.
- Bad: a second protocol through proxies and load balancers, with its own authentication and
  reconnection, for messages that only ever go one way; SSE is plain HTTP and resumes by
  design.

### The client polls

- Good: nothing new on the server.
- Bad: a request, its authentication and its permission check every second per client, and the
  client must work out what changed.

### LISTEN/NOTIFY

- Good: a change arrives at once, without reading the row.
- Bad: a listening connection held in every process, which does not pass the poolers of hosted
  PostgreSQL (PgBouncer in transaction mode), and a notification is lost while it is
  reconnecting; the row would still have to be read.
