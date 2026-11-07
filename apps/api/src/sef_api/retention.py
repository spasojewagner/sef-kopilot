"""What is kept for a while, and then deleted: finished jobs, once they are older than
``SEF_JOB_RETENTION_DAYS`` (ADR-0038); and the stored invoices of an organization that set a
retention period, once they were stored longer ago than that (ADR-0039).

A job's row keeps its parameters, its progress and its result or error, which say what was done
for an organization; after the retention period they are deleted with it. Jobs under way are
never deleted. An invoice goes with its document, its report and its repairs; an organization
that set no period keeps every invoice until a member deletes it.

Where jobs run, the deletions run: in the API's process with ``SEF_JOBS=inline``, when it starts
and then every few hours; in each worker with ``SEF_JOBS=arq``, when it starts and then once a
day. Each deletion is done on its own, so that one that fails leaves the other done.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Final

from sef_api.db import Database
from sef_api.invoices import store as invoice_store
from sef_api.jobs import store as job_store

__all__ = [
    "FORGET_EVERY_SECONDS",
    "forget_old_invoices",
    "forget_old_jobs",
    "forget_what_is_past_retention",
    "keep_forgetting",
]

logger = logging.getLogger(__name__)

#: How often the API's process deletes what is past its retention while it runs, after its
#: start.
FORGET_EVERY_SECONDS: Final = 6 * 3600


async def forget_old_jobs(
    database: Database, retention_days: int, *, now: datetime | None = None
) -> int:
    """Delete the jobs that finished more than ``retention_days`` before ``now``; how many."""
    before = (now if now is not None else datetime.now(UTC)) - timedelta(days=retention_days)
    async with database.sessions() as session:
        forgotten = await job_store.forget_finished(session, before=before)
    if forgotten:
        logger.info(
            "deleted %d jobs that finished more than %d days ago", forgotten, retention_days
        )
    return forgotten


async def forget_old_invoices(database: Database, *, now: datetime | None = None) -> int:
    """Delete the invoices that organizations stored longer ago than their retention period,
    before ``now``; how many."""
    async with database.sessions() as session:
        forgotten = await invoice_store.forget_past_retention(
            session, now=now if now is not None else datetime.now(UTC)
        )
    if forgotten:
        logger.info("deleted %d invoices kept past their organization's period", forgotten)
    return forgotten


async def forget_what_is_past_retention(database: Database, job_retention_days: int) -> None:
    """Delete the old finished jobs, then the invoices kept past their organization's period.
    A deletion that fails, while the database does not answer, is logged by the kind of its
    error, and the other is done all the same."""
    try:
        await forget_old_jobs(database, job_retention_days)
    except Exception as error:
        logger.warning("the old finished jobs were not deleted: %s", type(error).__name__)
    try:
        await forget_old_invoices(database)
    except Exception as error:
        logger.warning(
            "the invoices past their retention were not deleted: %s", type(error).__name__
        )


async def keep_forgetting(database: Database, job_retention_days: int) -> None:
    """Delete what is past its retention now, then every :data:`FORGET_EVERY_SECONDS`, until
    cancelled; a deletion that fails is tried again the next time."""
    while True:
        await forget_what_is_past_retention(database, job_retention_days)
        await asyncio.sleep(FORGET_EVERY_SECONDS)
