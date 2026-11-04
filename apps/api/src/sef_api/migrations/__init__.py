"""Database migrations (Alembic): the scripts in ``versions/`` and how to run them.

From the repository root::

    uv run alembic -c apps/api/alembic.ini upgrade head        # or: make migrate
    uv run alembic -c apps/api/alembic.ini revision --autogenerate --rev-id 0002 -m "..."

The database URL comes from ``DATABASE_URL``. From code, :func:`alembic_config` gives a
configuration bound to a URL; the tests use it to build and migrate their own databases.
"""

from __future__ import annotations

from typing import TextIO

from alembic.config import Config

__all__ = ["SCRIPT_LOCATION", "alembic_config"]

SCRIPT_LOCATION = "sef_api:migrations"


def alembic_config(database_url: str, *, output: TextIO | None = None) -> Config:
    """An Alembic configuration for ``database_url``; SQL goes to ``output`` in offline mode."""
    config = Config(output_buffer=output)
    config.set_main_option("script_location", SCRIPT_LOCATION)
    config.attributes["database_url"] = database_url
    return config
