# M4 — `feat/api-job-retention`

## Three questions a senior engineer would ask

**1. "How do you make sure a job under way is never deleted?"**

By what the deletion asks, not by a status check someone could get wrong. A job is deleted when
its `finished_at` is older than the period; a job under way has no `finished_at` (a constraint of
the table says that a job has one exactly when it has succeeded or failed), so the condition
cannot be true for it, however long ago it started. A test keeps a job running for 40 days and
one queued 40 days ago, and both survive.

**2. "Who runs the deletion, with no scheduler?"**

Whoever runs the jobs, as with the sweep that resumes them. With `SEF_JOBS=inline` the API's
process deletes at its start and every six hours; on the free plan, which starts it many times a
day, the start alone is enough. With workers, each one deletes at its start and once a day, as an
arq cron job. Several of them deleting at once is harmless: a row goes once.

**3. "Why no index on `finished_at`?"**

Because of who pays. The deletion reads the table a few times a day, and the table holds at most
the period's jobs. An index would be updated by every insert and every progress write of every
job, to save those few reads. If jobs grew to millions a month, the index would earn its place,
and adding it is one migration.

## The one concept to explain unaided

**Retention is storage limitation made executable**: decide how long a kind of data is kept, then
have the code that owns that data delete it, on a schedule that its deployment already gives it.

## Supporting facts worth remembering

- `SEF_JOB_RETENTION_DAYS`, 30 by default, between 1 and 3 650.
- The deletion logs how many it deleted, and a failure only by the kind of its error.
- Stored invoices are next: kept until their organization sets a period, none by default.
