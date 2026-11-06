# M3 — `test/api-worker-sweep-race`

## Three questions a senior engineer would ask

**1. "How do you know it was the clock, and not a bug in the worker?"**

The assertion said the job had succeeded after the first worker, and in that test only a sweep
can make that happen: the first attempt waits until it is cut short, and nothing but a sweep
puts a job cut short back on the queue. The worker sweeps when it starts and at second 0 of
every minute. arq queues a cron job whose next run is less than a second away, deferred until
then, and a worker in burst mode runs until its queue is empty, deferred jobs included. So a
first worker still alive in the last second before a minute waited for that minute's sweep,
which put the job back, and the second attempt ran in the first worker. Started three seconds
before a full minute, the test failed twice out of twice; with the fix it passed at the same
moment, its first worker ending before the minute instead of waiting for it.

**2. "Why change the test and not the worker?"**

The worker is right: a job cut short must go back on the queue, through whichever sweep comes
first, and in production the sweep every minute is the point. The test checks a state in
between, the job still running after the first worker, which holds only if no other sweep
comes between the two workers, so the test has to own that schedule. Freezing time would also
freeze arq's polling, which reads the same clock; retrying a failed test hides the race; waiting
for a safe moment of the minute makes the suite slower and is still a race.

**3. "Then the tests no longer run the worker as production does?"**

In one field: the minute of the periodic sweep, moved half an hour away with
`dataclasses.replace`, so the name, the sweep at startup and its uniqueness stay as production
has them. A test pins the production schedule (at startup, then at second 0 of every minute),
so a change to it fails a test instead of going unnoticed. What the test is about, the sweep at
startup, the attempt cut short and the next one continuing from its progress, runs unchanged.

## The one concept to explain unaided

**A test owns every clock it depends on.** A schedule tied to the wall clock makes a test's
outcome depend on when it runs; the test either controls that schedule or asserts only what
holds whatever the schedule does.

## Supporting facts worth remembering

- `cron(sweep, run_at_startup=True)` runs at startup and then at every match of
  `second=0` (any minute), at microsecond 123 456 by arq's default.
- arq queues a cron job when its next run is within `2 × max(poll_delay, 0.5)` seconds, with
  `_defer_until`; a burst worker stops only when the queue, deferred jobs included, is empty.
- The window: the first worker of that test alive in the last second before a minute, with its
  attempt already cut short when the sweep runs; the CI run that failed was
  `fix/api-json-charset`'s, whose change has nothing to do with workers.
