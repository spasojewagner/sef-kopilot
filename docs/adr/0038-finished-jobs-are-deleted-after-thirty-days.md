# 38. Finished jobs are deleted after thirty days, where they run

- Status: accepted
- Date: 2026-11-07
- Deciders: Marko Spasojević (the period, on 2026-11-06), the implementation by the team
- Technical story: milestone M4, branch `feat/api-job-retention`; the consequence ADR-0019
  accepted ("finished jobs accumulate"), and `SECURITY.md` V14

## Context and problem statement

A job's row keeps what was done for an organization: its parameters, its progress, and its
result or the reason it failed (ADR-0019). Nothing deleted it, so every revalidation ever run was
kept, which data protection's storage limitation and the table's size both argue against. The
maintainer decided the period: a finished job is kept for 30 days after it ends. Where, how often
and how should the deletion run?

## Decision drivers

- A job under way is never touched, however old it is: it may be continuing an attempt.
- One deployment of one process (the demo, `SEF_JOBS=inline`) and one with workers
  (`SEF_JOBS=arq`) both delete, with no scheduler of their own.
- The free instance sleeps after 15 minutes and starts again many times a day.
- No cost on the jobs' own writes, which are frequent (progress, version).

## Considered options

1. **Where the jobs run: the API's process with `SEF_JOBS=inline`, at its start and every six
   hours; each worker with `SEF_JOBS=arq`, at its start and every day at 03:17.** Chosen.
2. Always the API's process, whichever runs the jobs.
3. A scheduled job outside the application (a cron of the platform).
4. An index on `finished_at` for the deletion.

## Decision outcome

**The period is `SEF_JOB_RETENTION_DAYS`**, 30 by default, between 1 and 3 650. A job is deleted
when `finished_at` is older than the period: a job under way has no `finished_at`, so the
deletion cannot reach it.

**The deletion runs where the jobs run**, as the sweep that resumes them does. With
`SEF_JOBS=inline` the API's process deletes when it starts and then every six hours while it
runs; on the free plan, which starts the process many times a day, the start alone keeps the
table within a few days of the period. With `SEF_JOBS=arq` each worker deletes when it starts and
then every day at 03:17 (UTC), as one of its arq cron jobs beside the sweep. Several processes
deleting the same rows is harmless: a row is deleted once, and the others find nothing.

**A failure is logged by the kind of its error and tried again** the next time; it never stops
the process or a worker. **No index**: the deletion reads the table a few times a day, and the
table holds at most the period's jobs, while an index would cost every write of every job.

### Consequences

Good:

- A job's parameters, progress and result live 30 days after it ends, and no longer.
- No scheduler, no platform setting and no migration: the processes that run the jobs delete
  them.
- A job under way is safe by construction, not by a condition someone could get wrong.

Bad / accepted:

- With `SEF_JOBS=arq` and every worker stopped, nothing deletes; the first worker to start does.
- A stream of a job deleted while someone follows it ends, as for a job that is gone (ADR-0019);
  a job 30 days after its end has no follower.
- The deletion reads the whole table each time, which is bounded by the period.

## Pros and cons of the options

### Always the API's process

- Good: one place.
- Bad: with workers, the API's processes are many and may be scaled to none of the jobs' work;
  the jobs' housekeeping belongs with the jobs, as their sweep does.

### A scheduled job outside the application

- Good: the application does nothing on its own.
- Bad: one more thing for each deployment to set up, and none on Render's free plan.

### An index on `finished_at`

- Good: the deletion reads only the rows it deletes.
- Bad: every insert and every update of progress pays for it, to save a few reads a day of a
  table the period keeps small.
