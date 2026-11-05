"""Validating stored invoices again, with the rules this server has now: a job, since an
organization may store thousands of them (ADR-0019).

The job takes on the invoices its scope holds that were stored by the time it was started, in
the order of their ids, one at a time:

1. it reads the document, in a transaction of its own;
2. it validates it, holding no connection to the database;
3. in one transaction, it replaces the invoice's report (:func:`store.replace_report`) and
   counts the invoice in the job's progress, which names the last invoice done.

The progress tells how far the job has come, and where an attempt that takes the job on again
continues: whatever the attempts, each invoice is counted, and its report replaced, once. An
attempt that was superseded replaces no report, because its transaction fails with its
progress.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, replace
from typing import Any, Final, cast

from sqlalchemy import ColumnElement, func, select

from sef_api.invoices import store
from sef_api.invoices.validation import ProfileName, Validation
from sef_api.invoices.validator import (
    TooManyElementsError,
    ValidationRefusedError,
    ValidationTimeoutError,
    ValidatorFailedError,
    ValidatorUnavailableError,
)
from sef_api.jobs.runs import Claimed, JobContext, JobError, Progress
from sef_api.models import StoredInvoice

__all__ = ["PAGE", "UNAVAILABLE", "Tally", "revalidate"]

#: How many invoices are looked up at a time; their documents are read one by one.
PAGE: Final = 100
#: Why a revalidation failed when the validator cannot run.
UNAVAILABLE: Final = "the validator cannot run on this server"

#: What a validation that failed for one document raises: the job counts it and goes on.
_FAILURES = (
    TooManyElementsError,
    ValidationTimeoutError,
    ValidationRefusedError,
    ValidatorFailedError,
)


@dataclass(frozen=True)
class Tally:
    """How far a revalidation has come: the invoices it takes on, how many of them are done,
    what became of those, and the last one done.

    An invoice done is ``valid`` or ``invalid`` under its new report; ``kept`` its report
    because the new one would have taken the organization past its quota; ``failed`` to be
    validated (too large, too slow, or refused by the rule sets); or was ``deleted`` before
    the job was done with it.
    """

    total: int
    done: int = 0
    valid: int = 0
    invalid: int = 0
    kept: int = 0
    failed: int = 0
    deleted: int = 0
    last: str | None = None

    def counted(self, invoice_id: uuid.UUID, outcome: str) -> Tally:
        """The tally with one more invoice done, and what became of it."""
        done = self.done + 1
        return replace(
            self,
            # An invoice stored the moment the job was started may be found after it counted.
            total=max(self.total, done),
            done=done,
            last=str(invoice_id),
            **{outcome: getattr(self, outcome) + 1},
        )

    def finished(self) -> dict[str, int]:
        """What the job came to. The invoices it never reached were deleted before it did."""
        counts = asdict(self)
        del counts["last"]
        counts["deleted"] += self.total - self.done
        counts["done"] = self.total
        return counts


async def revalidate(context: JobContext, job: Claimed, progress: Progress) -> dict[str, Any]:
    """Validate again, one by one, the invoices the job takes on; what it came to."""
    taken_on = _taken_on(job)
    tally = Tally(**job.progress) if job.progress else await _begin(context, taken_on, progress)
    while page := await _next_page(context, taken_on, tally.last):
        for invoice_id, profile in page:
            tally = await _validate_again(
                context, job, progress, tally, invoice_id=invoice_id, profile=profile
            )
    return tally.finished()


def _taken_on(job: Claimed) -> ColumnElement[bool]:
    """The invoices the job takes on: those its scope holds, stored by the time it was
    started. A later one was validated with the rules there are now when it was stored."""
    submitted_by = job.parameters.get("submitted_by")
    scope = store.Scope(
        job.organization_id,
        submitted_by=None if submitted_by is None else uuid.UUID(submitted_by),
    )
    return scope.holds() & (StoredInvoice.created_at <= job.created_at)


async def _begin(context: JobContext, taken_on: ColumnElement[bool], progress: Progress) -> Tally:
    async with context.database.sessions() as session:
        total = await session.scalar(
            select(func.count()).select_from(StoredInvoice).where(taken_on)
        )
    tally = Tally(total=total or 0)
    await progress.report(asdict(tally))
    return tally


async def _next_page(
    context: JobContext, taken_on: ColumnElement[bool], last: str | None
) -> list[tuple[uuid.UUID, str]]:
    """The next invoices to validate again, after the ``last`` one done."""
    query = select(StoredInvoice.id, StoredInvoice.profile).where(taken_on)
    if last is not None:
        query = query.where(StoredInvoice.id > uuid.UUID(last))
    async with context.database.sessions() as session:
        rows = await session.execute(query.order_by(StoredInvoice.id).limit(PAGE))
        return [(row.id, row.profile) for row in rows]


async def _validate_again(
    context: JobContext,
    job: Claimed,
    progress: Progress,
    tally: Tally,
    *,
    invoice_id: uuid.UUID,
    profile: str,
) -> Tally:
    """Validate the invoice again and, in one transaction, replace its report and count it."""
    async with context.database.sessions() as session:
        content = await session.scalar(
            select(StoredInvoice.content).where(
                StoredInvoice.organization_id == job.organization_id,
                StoredInvoice.id == invoice_id,
            )
        )
    validation = None if content is None else await _validated(context, content, profile)
    async with context.database.sessions() as session:
        if content is None:
            outcome = "deleted"
        elif validation is None:
            outcome = "failed"
        else:
            replaced = await store.replace_report(
                session,
                organization_id=job.organization_id,
                invoice_id=invoice_id,
                validation=validation,
                quota=context.settings.max_stored_bytes,
            )
            verdict = "valid" if validation.report.valid else "invalid"
            outcome = {"replaced": verdict, "kept": "kept", "gone": "deleted"}[replaced]
        tally = tally.counted(invoice_id, outcome)
        await progress.report(asdict(tally), session=session)
        await session.commit()
    return tally


async def _validated(context: JobContext, content: bytes, profile: str) -> Validation | None:
    """The validator's report on the document, or None when it could not be validated."""
    try:
        return await context.validator.validate(content, cast(ProfileName, profile))
    except ValidatorUnavailableError:
        raise JobError(UNAVAILABLE) from None
    except _FAILURES:
        return None
