"""The explanations of a stored invoice's report, kept with the invoice (ADR-0040).

One set is kept a language, with the digest of the report it explains and the day whose law it
cites. A set that explains another report, or cites another day, is not the invoice's any more:
it is not read, and the next explanation in that language replaces it. Only a whole set is kept,
one in which every rule asked about was explained, so that a rule the model could not explain is
asked about again.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.pipeline import ValidationReport
from sef_api.llm import Language
from sef_api.models import KeptExplanations, StoredInvoice
from sef_api.rag.explainer import Explanation

__all__ = ["Kept", "keep", "kept", "report_digest"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Kept:
    """A set of explanations as it was written, and when."""

    model: str
    explanations: list[Explanation]
    unexplained: list[str]
    written_at: datetime


def report_digest(report: ValidationReport) -> str:
    """The SHA-256 of ``report`` as the API writes it."""
    return hashlib.sha256(report.model_dump_json().encode()).hexdigest()


async def kept(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    language: Language,
    *,
    report_sha256: str,
    day: date,
) -> Kept | None:
    """The explanations kept for the invoice in ``language``, when they explain the report whose
    digest is ``report_sha256`` and cite the law of ``day``; None otherwise."""
    row = await session.scalar(
        select(KeptExplanations).where(
            KeptExplanations.invoice_id == invoice_id, KeptExplanations.language == language
        )
    )
    if row is None or (row.report_sha256, row.day) != (report_sha256, day):
        return None
    try:
        explanations = [Explanation.model_validate(item) for item in row.explanations]
    except ValidationError as error:
        # Written by an earlier version whose explanations had another form: written again.
        logger.warning("kept explanations not read: %s", type(error).__name__)
        return None
    return Kept(row.model, explanations, list(row.unexplained), row.written_at)


async def keep(
    session: AsyncSession,
    invoice_id: uuid.UUID,
    language: Language,
    *,
    report_sha256: str,
    day: date,
    model: str,
    explanations: list[Explanation],
    unexplained: list[str],
) -> datetime | None:
    """Keep a whole set of explanations of the invoice in ``language``, in place of the set kept
    before, and commit; when they were kept. None, keeping nothing, when the invoice was deleted
    meanwhile: its row is locked first, so that it cannot go between the check and the insert."""
    organization_id = await session.scalar(
        select(StoredInvoice.organization_id)
        .where(StoredInvoice.id == invoice_id)
        .with_for_update(key_share=True)
    )
    if organization_id is None:
        await session.commit()
        return None
    values = {
        "report_sha256": report_sha256,
        "day": day,
        "model": model,
        "explanations": [explanation.model_dump(mode="json") for explanation in explanations],
        "unexplained": unexplained,
    }
    statement = (
        insert(KeptExplanations)
        .values(invoice_id=invoice_id, language=language, organization_id=organization_id, **values)
        .on_conflict_do_update(
            index_elements=[KeptExplanations.invoice_id, KeptExplanations.language],
            set_={**values, "written_at": func.now()},
        )
        .returning(KeptExplanations.written_at)
    )
    written_at = cast(datetime, await session.scalar(statement))
    await session.commit()
    return written_at
