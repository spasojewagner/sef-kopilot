"""Jobs: work done in the background for an organization (ADR-0019).

A job's row in ``jobs`` is its truth: what it does, for whom, how far it has come and how it
ended. A runner only carries the news that a job waits to a worker, which runs it with
:func:`~sef_api.jobs.runs.run_job`. Taking a job on, reporting its progress and finishing it
are each a short transaction of their own, so that anyone can follow the job while it runs, and
a job cut short can be taken on again.
"""
