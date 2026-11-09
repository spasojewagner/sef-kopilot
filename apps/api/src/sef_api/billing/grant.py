"""``python -m sef_api.billing.grant ORGANIZATION_ID COUNT`` (``make grant-credits``): give an
organization more credits, where billing is on (ADR-0059).

The operator's way to give credits, on a server whose organizations do not buy them: a
self-hosted deployment, a trial, a correction. The grant is written to the ledger beside the
balance, in one transaction; an organization that does not exist, or a server with billing off,
stops the command before anything is changed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence
from typing import Final

from sef_api.billing.ledger import CreditTerms, grant, terms_for
from sef_api.db import Database
from sef_api.models import Organization
from sef_api.settings import Settings

__all__ = ["MOST_GRANTED", "grant_credits", "main"]

#: The most credits one grant gives: a typing mistake should not make an organization rich.
MOST_GRANTED: Final = 100_000


class _NoSuchOrganizationError(Exception):
    pass


async def grant_credits(
    database: Database, terms: CreditTerms, organization_id: uuid.UUID, count: int
) -> int:
    """Give the organization ``count`` credits and commit; how many it then holds."""
    async with database.sessions() as session:
        if await session.get(Organization, organization_id) is None:
            raise _NoSuchOrganizationError
        held = await grant(session, organization_id, terms, count=count)
        await session.commit()
        return held


def _count(text: str) -> int:
    count = int(text)
    if not 1 <= count <= MOST_GRANTED:
        raise argparse.ArgumentTypeError(f"give from 1 to {MOST_GRANTED} credits")
    return count


async def _run(
    settings: Settings, terms: CreditTerms, organization_id: uuid.UUID, count: int
) -> int:
    database = Database.connect(settings.database_url.get_secret_value(), pooled=False)
    try:
        return await grant_credits(database, terms, organization_id, count)
    finally:
        await database.engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m sef_api.billing.grant", description="Give an organization credits."
    )
    parser.add_argument("organization", type=uuid.UUID, help="the organization's id")
    parser.add_argument("count", type=_count, help="how many credits to give")
    args = parser.parse_args(argv)
    settings = Settings()
    terms = terms_for(settings)
    if terms is None:
        sys.stderr.write("error: billing is off (SEF_BILLING): storing costs nothing\n")
        return 1
    try:
        held = asyncio.run(_run(settings, terms, args.organization, args.count))
    except _NoSuchOrganizationError:
        sys.stderr.write(f"error: no organization has the id {args.organization}\n")
        return 1
    sys.stdout.write(f"gave {args.count} credits; the organization now holds {held}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
