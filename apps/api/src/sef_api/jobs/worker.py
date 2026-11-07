"""A worker that runs the jobs the API puts on the Redis queue (``SEF_JOBS=arq``, ADR-0019):
``python -m sef_api.jobs.worker``, beside the API, as many as there is work for.

A worker has a database engine and a validator of its own. When it starts, and then once a
minute, it sweeps: it puts every unfinished job on the queue. The jobs that wait there, or run,
stay as they are; a job that never reached the queue, or was lost with it, runs after all. An
attempt that runs longer than :data:`ATTEMPT_SECONDS` is cut short and swept back onto the
queue, and the next attempt continues where it stopped. When it starts, and then once a day, it
deletes the jobs that finished longer ago than the retention period (ADR-0038).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

from arq import cron, func
from arq.worker import run_worker

from sef_api.db import Database
from sef_api.invoices.validator import validator_for
from sef_api.jobs import store
from sef_api.jobs.kinds import HANDLERS
from sef_api.jobs.queue import TASK, put, redis_settings
from sef_api.jobs.runs import JobContext, run_job
from sef_api.retention import forget_old_jobs
from sef_api.settings import Settings

__all__ = ["ATTEMPT_SECONDS", "forget", "main", "options", "run", "shutdown", "startup", "sweep"]

logger = logging.getLogger(__name__)

#: Seconds one attempt at a job may run before the worker cuts it short.
ATTEMPT_SECONDS: Final = 3600


async def startup(ctx: dict[str, Any]) -> None:
    """Connect to the database and start the validator, which compiles every rule set."""
    settings: Settings = ctx["settings"]
    validator = validator_for(settings)
    await validator.start()
    if validator.problem is not None:
        logger.warning("the validator cannot run: %s", validator.problem)
    database = Database.connect(settings.database_url.get_secret_value())
    ctx["context"] = JobContext(database, validator, settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    context: JobContext = ctx["context"]
    await context.validator.stop()
    await context.database.engine.dispose()


async def run(ctx: dict[str, Any], job_id: str) -> None:
    """Run the job; its row, not arq, records how it ended."""
    await run_job(ctx["context"], uuid.UUID(job_id), HANDLERS)


async def sweep(ctx: dict[str, Any]) -> int:
    """Put every unfinished job on the queue; how many were not there."""
    context: JobContext = ctx["context"]
    async with context.database.sessions() as session:
        waiting = await store.unfinished(session)
    swept = [job_id for job_id in waiting if await put(ctx["redis"], job_id)]
    if swept:
        logger.info("the sweep put %d unfinished jobs on the queue", len(swept))
    return len(swept)


async def forget(ctx: dict[str, Any]) -> int:
    """Delete the jobs that finished longer ago than the retention period; how many."""
    context: JobContext = ctx["context"]
    return await forget_old_jobs(context.database, context.settings.job_retention_days)


def options(settings: Settings, redis_url: str) -> dict[str, Any]:
    """What a worker serves, for arq: running jobs, the sweep, the deletion of old jobs, and with
    which settings."""
    return {
        "functions": [func(run, name=TASK, timeout=ATTEMPT_SECONDS, keep_result=0)],
        "cron_jobs": [
            cron(sweep, run_at_startup=True),  # at second 0 of every minute
            cron(forget, hour={3}, minute={17}, run_at_startup=True),  # at 03:17 every day
        ],
        "on_startup": startup,
        "on_shutdown": shutdown,
        "redis_settings": redis_settings(redis_url),
        "ctx": {"settings": settings},
    }


def main(settings: Settings | None = None) -> None:
    """Run a worker until it is stopped."""
    settings = settings if settings is not None else Settings()
    if settings.redis_url is None:
        raise SystemExit("REDIS_URL must name the Redis server of the job queue")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_worker(options(settings, settings.redis_url.get_secret_value()))


if __name__ == "__main__":
    main()
