"""Finished jobs are deleted once they are older than ``SEF_JOB_RETENTION_DAYS`` (ADR-0038).

A job's row keeps its parameters, its progress and its result or error, which say what was done
for an organization; after the retention period they are deleted with it. Jobs under way are
never deleted. Where jobs run, the deletion runs: in the API's process with ``SEF_JOBS=inline``,
when it starts and then every few hours; in each worker with ``SEF_JOBS=arq``, when it starts and
then once a day.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Final

from sef_api.db import Database
from sef_api.jobs import store

__all__ = ["FORGET_EVERY_SECONDS", "forget_old_jobs", "keep_forgetting_old_jobs"]

logger = logging.getLogger(__name__)

#: How often the API's process deletes the old finished jobs while it runs, after its start.
FORGET_EVERY_SECONDS: Final = 6 * 3600


async def forget_old_jobs(
    database: Database, retention_days: int, *, now: datetime | None = None
) -> int:
    """Delete the jobs that finished more than ``retention_days`` before ``now``; how many."""
    before = (now if now is not None else datetime.now(UTC)) - timedelta(days=retention_days)
    async with database.sessions() as session:
        forgotten = await store.forget_finished(session, before=before)
    if forgotten:
        logger.info(
            "deleted %d jobs that finished more than %d days ago", forgotten, retention_days
        )
    return forgotten


async def keep_forgetting_old_jobs(database: Database, retention_days: int) -> None:
    """Delete the old finished jobs now, then every :data:`FORGET_EVERY_SECONDS`, until
    cancelled. A deletion that fails, while the database does not answer, is logged by the kind
    of its error and tried again the next time."""
    while True:
        try:
            await forget_old_jobs(database, retention_days)
        except Exception as error:
            logger.warning("the old finished jobs were not deleted: %s", type(error).__name__)
        await asyncio.sleep(FORGET_EVERY_SECONDS)
