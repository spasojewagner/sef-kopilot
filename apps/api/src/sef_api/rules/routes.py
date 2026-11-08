"""``/rules``: the rules a profile applies, looked up by id or found by words, with the
passages of the official documents that concern them (ADR-0047).

The rules are the catalogue of the validator's own rule sets, read once per process; the
passages are the corpus's, found as an explanation finds them for a violation of the rule, or
by the words alone, among those that apply on a day. Nothing is counted: no invoice is
validated and no language model is asked.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from einvoice_core.catalogue import CatalogueRule, catalogue, search
from einvoice_core.rulesets import RulesetNotFoundError
from einvoice_core.violations import Violation
from sef_api.auth.dependencies import require
from sef_api.auth.permissions import Permission
from sef_api.auth.routes import Problem
from sef_api.db import get_session
from sef_api.invoices.validation import ProfileName
from sef_api.rag.explainer import Citation
from sef_api.rag.retrieval import Found, Retriever

__all__ = ["Passage", "RuleFound", "RuleOut", "about", "found", "router"]

router = APIRouter(prefix="/rules", tags=["rules"])

Session = Annotated[AsyncSession, Depends(get_session)]
#: Who may look rules up: whoever may have an invoice validated.
_MAY_VALIDATE: Final = Depends(require(Permission.INVOICES_VALIDATE))

#: The most rules a search answers.
MAX_RULES: Final = 50


class Passage(Citation):
    """A stored passage of the corpus, with its text."""

    text: str

    @classmethod
    def found(cls, passage: Found) -> Passage:
        return cls(**Citation.of(passage).model_dump(), text=passage.text)


class RuleFound(BaseModel):
    """What a search found: rules of the profile, and passages that share its words."""

    rules: list[CatalogueRule]
    passages: list[Passage] = Field(
        description="Passages of the official documents that share enough of the words, among "
        "those that apply today."
    )


class RuleOut(BaseModel):
    """A rule, and the passages that concern it on a day."""

    rule: CatalogueRule
    day: date
    passages: list[Passage] = Field(
        description="The passages an explanation of a violation of the rule would cite, most "
        "relevant first: those the rule is authored from, the rows of the business terms it "
        "names, and those that share its words."
    )


_UNAVAILABLE: Final[dict[int | str, dict[str, Any]]] = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": Problem,
        "description": "The rule sets are not available on this server.",
    }
}
_NO_RULE: Final[dict[int | str, dict[str, Any]]] = _UNAVAILABLE | {
    status.HTTP_404_NOT_FOUND: {"model": Problem, "description": "No such rule in the profile."}
}


@router.get(
    "",
    summary="Find rules",
    description=(
        "The rules of a profile that the query names: by id (`BR-CO-15`) or the start of ids "
        "(`BR-CO`), by a business term (`BT-31`), then by the words of their statements, case "
        "and diacritics aside, the Serbian rules first; and the passages of the official "
        "documents that share enough of its words, among those that apply today."
    ),
    responses=_UNAVAILABLE,
    dependencies=[_MAY_VALIDATE],
)
async def find_rules(
    response: Response,
    *,
    session: Session,
    q: Annotated[str, Query(min_length=1, max_length=200, description="An id, a term or words.")],
    profile: ProfileName = "srb",
    limit: Annotated[int, Query(ge=1, le=MAX_RULES)] = 20,
) -> RuleFound:
    response.headers["Cache-Control"] = "no-store"
    return await found(session, q, profile=profile, limit=limit)


@router.get(
    "/{rule_id}",
    summary="Read a rule",
    description=(
        "A rule of the profile, and the passages of the official documents that concern it on "
        "the day (today by default), as an explanation of a violation of it would cite them."
    ),
    responses=_NO_RULE,
    dependencies=[_MAY_VALIDATE],
)
async def read_rule(
    rule_id: str,
    response: Response,
    *,
    session: Session,
    profile: ProfileName = "srb",
    day: date | None = None,
) -> RuleOut:
    response.headers["Cache-Control"] = "no-store"
    return await about(session, rule_id, profile=profile, day=day)


async def found(
    session: AsyncSession, query: str, *, profile: ProfileName, limit: int = 20
) -> RuleFound:
    """The rules ``query`` names and the passages that share its words, the route and the MCP
    tool alike."""
    rules = search(await _catalogue(profile), query, limit=limit)
    passages = await Retriever(session, datetime.now(UTC).date()).by_words(query)
    return RuleFound(rules=rules, passages=[Passage.found(passage) for passage in passages])


async def about(
    session: AsyncSession, rule_id: str, *, profile: ProfileName, day: date | None = None
) -> RuleOut:
    """A rule of ``profile`` and its passages on ``day``, the route and the MCP tool alike; 404
    for a rule the profile does not have."""
    rules = {rule.id: rule for rule in await _catalogue(profile)}
    rule = rules.get(rule_id.strip().upper())
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no such rule in the profile {profile}")
    on = day or datetime.now(UTC).date()
    violation = Violation(
        rule_id=rule.id,
        severity=rule.severity,
        # As a violation of the rule states it: the passages are found for its words.
        message=f"[{rule.id}]-{rule.statement}",
        xpath=None,
        layer=rule.layer,
    )
    passages = await Retriever(session, on).passages(violation)
    return RuleOut(rule=rule, day=on, passages=[Passage.found(passage) for passage in passages])


async def _catalogue(profile: ProfileName) -> tuple[CatalogueRule, ...]:
    """The profile's catalogue, read off the event loop the first time; 503 without the rule
    sets."""
    try:
        return await asyncio.to_thread(catalogue, profile)
    except RulesetNotFoundError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "the rule sets are not available on this server"
        ) from None
