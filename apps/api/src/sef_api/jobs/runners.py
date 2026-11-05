"""Runners: what carries the news that a job waits to the worker that runs it. The inline runner
is here; :class:`~sef_api.jobs.queue.ArqRunner` puts jobs on the Redis queue of the workers.

A runner never decides what a job is or how it ends; the job's row does. Enqueueing a job twice
is therefore harmless: the second run takes the job on again, and the first, superseded, stops.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Protocol

__all__ = ["InlineRunner", "JobRunner"]


class JobRunner(Protocol):
    """Has jobs run by a worker."""

    async def enqueue(self, job_id: uuid.UUID) -> None:
        """Have the job with ``job_id`` run."""

    async def stop(self) -> None:
        """Let go of whatever the runner holds, when the application stops."""


class InlineRunner:
    """Runs each job as a task of the API's own event loop: for tests, for development and for
    a deployment of one process.

    A job cut short because the process stops stays unfinished in the database, and is
    enqueued again when the process starts.
    """

    def __init__(self, run: Callable[[uuid.UUID], Awaitable[None]]) -> None:
        self._run = run
        self._tasks: set[asyncio.Task[None]] = set()

    async def enqueue(self, job_id: uuid.UUID) -> None:
        task = asyncio.get_running_loop().create_task(self._go(job_id), name=f"job {job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _go(self, job_id: uuid.UUID) -> None:
        await self._run(job_id)

    async def drain(self) -> None:
        """Wait until every job enqueued so far has run, the ones they enqueue included."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def stop(self) -> None:
        """Cut the running jobs short; their rows say they have not finished."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
