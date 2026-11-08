"""Where the invoices SEF imported stand: asked of SEF until each is final (ADR-0051).

Where the jobs run, once a minute: the API's process with ``SEF_JOBS=inline``, each worker with
``SEF_JOBS=arq``. An imported invoice is due a minute after it was last asked about while it was
sent within the hour, then every quarter of an hour on its first day, then every six hours, for
thirty days; once SEF says it is final (its buyer decided, or its seller cancelled, reversed or
deleted it) it is asked about no more.

The invoices due are claimed in a transaction of their own, which marks them asked, so that two
processes never ask about one; SEF is asked outside any transaction; what it answered is written
in another. A failure is logged with its kind, never with what SEF wrote, and the invoice is
asked about again when it is next due.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

import httpx
from sqlalchemy import ColumnElement, and_, case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sef_api.db import Database
from sef_api.models import SefKey, SefSubmission, SubmissionState
from sef_api.sef.client import FINAL, SefClient, SefError, Standing
from sef_api.sef.keys import Keyring, UnreadableKeyError

__all__ = ["BATCH", "WATCH_EVERY_SECONDS", "keep_watching", "watch_once"]

logger = logging.getLogger(__name__)

#: Seconds between two rounds.
WATCH_EVERY_SECONDS: Final = 60
#: The most invoices one round asks about.
BATCH: Final = 20
#: How long after it was sent an invoice is asked about at all.
WATCHED_FOR: Final = timedelta(days=30)


@dataclass(frozen=True)
class _Due:
    submission_id: uuid.UUID
    organization_id: uuid.UUID
    sales_invoice_id: int
    token: str


def _due(now: datetime) -> list[ColumnElement[bool]]:
    """The conditions of an imported invoice that is due to be asked about at ``now``."""
    interval = case(
        (SefSubmission.sent_at > now - timedelta(hours=1), timedelta(minutes=1)),
        (SefSubmission.sent_at > now - timedelta(days=1), timedelta(minutes=15)),
        else_=timedelta(hours=6),
    )
    return [
        SefSubmission.state == SubmissionState.IMPORTED,
        or_(
            SefSubmission.sef_status.is_(None),
            SefSubmission.sef_status.not_in([status.value for status in FINAL]),
        ),
        SefSubmission.sent_at > now - WATCHED_FOR,
        or_(SefSubmission.checked_at.is_(None), SefSubmission.checked_at + interval <= now),
    ]


async def _claim(session: AsyncSession, now: datetime) -> list[_Due]:
    """The invoices due, at most :data:`BATCH`, marked asked about at ``now``, and committed."""
    chosen = (
        select(SefSubmission.id)
        .where(*_due(now))
        .order_by(SefSubmission.checked_at.nulls_first(), SefSubmission.sent_at)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    claimed = await session.execute(
        update(SefSubmission)
        .where(SefSubmission.id.in_(chosen))
        .values(checked_at=now)
        .returning(SefSubmission.id, SefSubmission.organization_id, SefSubmission.sales_invoice_id)
    )
    rows = claimed.all()
    tokens = dict(
        (
            await session.execute(
                select(SefKey.organization_id, SefKey.token).where(
                    SefKey.organization_id.in_({row.organization_id for row in rows})
                )
            )
        ).all()
    )
    await session.commit()
    return [
        _Due(row.id, row.organization_id, row.sales_invoice_id, tokens[row.organization_id])
        for row in rows
        if row.sales_invoice_id is not None and row.organization_id in tokens
    ]


async def _ask(
    due: _Due, keyring: Keyring, http: httpx.AsyncClient, base_url: str
) -> Standing | None:
    """Where the invoice stands, as SEF says; None, logged with its kind, when SEF cannot say."""
    try:
        api_key = keyring.open(due.organization_id, due.token)
    except UnreadableKeyError:
        logger.warning("an organization's key to SEF cannot be opened with SEF_FERNET_KEY")
        return None
    try:
        return await SefClient(base_url, api_key, client=http).standing(due.sales_invoice_id)
    except SefError as error:
        logger.warning("SEF was not asked where an invoice stands: %s", error)
        return None


async def watch_once(
    database: Database,
    keyring: Keyring,
    http: httpx.AsyncClient,
    base_url: str,
    *,
    now: datetime | None = None,
) -> int:
    """Ask SEF where the invoices due stand, and keep what it says; how many it said."""
    moment = now or datetime.now(UTC)
    async with database.sessions() as session:
        claimed = await _claim(session, moment)
    answered = 0
    for due in claimed:
        standing = await _ask(due, keyring, http, base_url)
        if standing is None:
            continue
        async with database.sessions() as session:
            await session.execute(
                update(SefSubmission)
                .where(
                    and_(
                        SefSubmission.id == due.submission_id,
                        SefSubmission.state == SubmissionState.IMPORTED,
                    )
                )
                .values(
                    sef_status=standing.status.value,
                    detail=standing.comment or SefSubmission.detail,
                )
            )
            await session.commit()
        answered += 1
    if claimed:
        logger.info("SEF said where %d of %d invoices stand", answered, len(claimed))
    return answered


async def keep_watching(
    database: Database, keyring: Keyring | None, http: httpx.AsyncClient, base_url: str
) -> None:
    """Ask SEF where the invoices due stand, now and every :data:`WATCH_EVERY_SECONDS`, until
    cancelled; a round that fails is logged with its kind and tried again the next time. Without
    a keyring, no key can be opened, and nothing is asked."""
    if keyring is None:
        return
    while True:
        try:
            await watch_once(database, keyring, http, base_url)
        except Exception as error:
            logger.warning("SEF was not asked where the invoices stand: %s", type(error).__name__)
        await asyncio.sleep(WATCH_EVERY_SECONDS)
