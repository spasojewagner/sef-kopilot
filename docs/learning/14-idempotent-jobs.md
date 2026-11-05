# Idempotent jobs: delivered at least once, done once

A queue cannot promise to deliver a job exactly once. A worker can take a job, do the work and
die before it says so; the queue, hearing nothing, gives the job to another worker. Reliable
queues (arq, Celery, SQS) therefore deliver **at least once**. Doing the work **once** is the
job's own business.

## Three tools

1. **The row is the truth.** A job's state lives in the database, and the queue carries only
   "job 42 waits". Losing the queue loses nothing: a sweep puts every unfinished job back.
2. **A fencing token.** Taking a job on increments `attempts` and returns the new value. Every
   later write says `WHERE id = 42 AND attempts = <mine> AND status = 'running'`. A worker that
   was given up for dead and wakes up writes nothing, because its token is stale.
3. **A checkpoint in the work's transaction.** Write the work and the progress that counts it
   in one transaction: both are committed or neither is. A new attempt continues after the
   last checkpoint and repeats nothing. A stale attempt's transaction fails at the fence and
   takes its work with it.

```text
claim:  UPDATE jobs SET attempts = attempts + 1, status = 'running'
        WHERE id = 42 AND status IN ('queued', 'running') RETURNING attempts, progress
work:   BEGIN;
        UPDATE invoices SET report = ... WHERE id = 7;
        UPDATE jobs SET progress = '{"last": 7, ...}'
        WHERE id = 42 AND attempts = 2 AND status = 'running';   -- no row: roll back, stop
        COMMIT;
```

## And besides

- Make the work itself repeatable where you can: the same bytes under the same rules give the
  same report.
- Deduplicate on the way in: one id per job on the queue (arq's `_job_id`), and a unique index
  for "one unfinished job per member and kind", so that two clicks start one job.
- Bound each attempt, here to an hour. With checkpoints, a long job is a series of attempts.
- A lock is no substitute: held for minutes, it pins a connection, and a worker that hangs
  without dying holds it for ever.

## In this repository

- `apps/api/src/sef_api/jobs/runs.py`: taking a job on, the fenced writes, and
  `Progress.report(..., session=...)` for a checkpoint.
- `invoices/revalidation.py`: one invoice per transaction, its new report and its count
  together. `jobs/worker.py`: the sweep.
- `test_jobs.py`, `test_revalidation.py` and `test_worker.py` supersede attempts, cut them
  short and resume them on purpose.
- The decisions are recorded in ADR-0019.
