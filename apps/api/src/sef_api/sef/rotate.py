"""``python -m sef_api.sef.rotate`` (``make rotate-sef-keys``): every stored key, to SEF and to a
model's provider, sealed again under the first key of ``SEF_FERNET_KEY`` (ADR-0050, ADR-0058).

To replace the secret: put the new key first in ``SEF_FERNET_KEY``, the old one after it, and
deploy; run this; then remove the old key. The keys are sealed again in one transaction, and a
token that the keys do not open, or that was sealed for another organization, stops the command
before anything is changed.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

from sqlalchemy import select

from sef_api.db import Database
from sef_api.models import ModelKey, SefKey
from sef_api.sef.keys import Keyring, Purpose, UnreadableKeyError, keyring_for
from sef_api.settings import Settings

__all__ = ["main", "reseal_every_key"]


async def reseal_every_key(database: Database, keyring: Keyring) -> int:
    """Seal every stored key again under the first key, and commit; how many there were.
    :class:`UnreadableKeyError`, and nothing changed, when one cannot be opened."""
    async with database.sessions() as session:
        stored: list[tuple[SefKey | ModelKey, Purpose]] = [
            *((key, "sef") for key in await session.scalars(select(SefKey).with_for_update())),
            *((key, "model") for key in await session.scalars(select(ModelKey).with_for_update())),
        ]
        unreadable = 0
        for key, purpose in stored:
            try:
                keyring.open(key.organization_id, key.token, purpose)
                key.token = keyring.reseal(key.token)
            except UnreadableKeyError:
                unreadable += 1
        if unreadable:
            raise UnreadableKeyError(
                f"{unreadable} of {len(stored)} stored keys cannot be opened with "
                "SEF_FERNET_KEY; nothing was changed"
            )
        await session.commit()
        return len(stored)


async def _run(settings: Settings, keyring: Keyring) -> int:
    database = Database.connect(settings.database_url.get_secret_value(), pooled=False)
    try:
        return await reseal_every_key(database, keyring)
    finally:
        await database.engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # no arguments; the settings say everything
    settings = Settings()
    keyring = keyring_for(settings)
    if keyring is None:
        sys.stderr.write("error: SEF_FERNET_KEY is not set\n")
        return 1
    try:
        count = asyncio.run(_run(settings, keyring))
    except UnreadableKeyError as error:
        sys.stderr.write(f"error: {error}\n")
        return 1
    sys.stdout.write(f"sealed {count} keys again under the first key of SEF_FERNET_KEY\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
