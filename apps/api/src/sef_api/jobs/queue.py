"""The Redis queue that carries jobs to the workers when ``SEF_JOBS=arq`` (ADR-0019).

The queue carries a job's id and nothing else: the job's row stays the truth. arq takes each id
once, so putting a job on the queue while it waits there, or while a worker runs it, does
nothing. A job's result is not kept, so that a job cut short can be put there again at once.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from typing import Final

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.exceptions import RedisError

__all__ = ["TASK", "ArqRunner", "put", "redis_settings"]

logger = logging.getLogger(__name__)

#: What a worker calls the work of running a job.
TASK: Final = "run_job"


def redis_settings(url: str) -> RedisSettings:
    """arq's settings for the Redis server at ``url``."""
    return RedisSettings.from_dsn(url)


async def put(redis: ArqRedis, job_id: uuid.UUID) -> bool:
    """Put the job on the queue, unless it waits there or runs; whether it was put there."""
    return await redis.enqueue_job(TASK, str(job_id), _job_id=str(job_id)) is not None


class ArqRunner:
    """Puts each job on the queue for a worker to run.

    It connects when it is first used, so that the API starts without Redis as it starts without
    its database. A job it cannot put on the queue waits in the database, queued: a worker's
    sweep puts it there within a minute of Redis answering again.
    """

    def __init__(self, settings: RedisSettings) -> None:
        # No retries: a request does not wait for Redis, the sweep does.
        self._settings = dataclasses.replace(settings, conn_retries=0)
        self._redis: ArqRedis | None = None
        self._connecting = asyncio.Lock()

    async def enqueue(self, job_id: uuid.UUID) -> None:
        try:
            await put(await self._connected(), job_id)
        except (RedisError, OSError) as error:
            logger.warning("job %s was not put on the queue: %s", job_id, type(error).__name__)

    async def _connected(self) -> ArqRedis:
        async with self._connecting:
            if self._redis is None:
                self._redis = await create_pool(self._settings)
            return self._redis

    async def stop(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
