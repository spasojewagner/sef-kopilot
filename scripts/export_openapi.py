"""Write the API's OpenAPI document to ``docs/api/openapi.json``.

The document is the contract between the API and its clients: the web application's types are
generated from it (``pnpm --filter @sef-kopilot/web api:types``). It is generated, never edited
by hand, and a test fails when it is out of date, so a change to the API shows in its diff.
Usage::

    uv run python scripts/export_openapi.py

The document does not depend on the environment: the API is built with fixed settings, and
nothing is connected to.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from sef_api.main import create_app
from sef_api.settings import Settings

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
DOCUMENT: Final = "docs/api/openapi.json"

#: Settings that build the API without reading the environment; it is never started.
_SETTINGS: Final = {
    "SEF_ENVIRONMENT": "development",
    "DATABASE_URL": "postgresql+asyncpg://unused:unused@127.0.0.1:1/unused",
    "SEF_JWT_SECRET": "only-to-build-the-openapi-document-0123456789",
    "SEF_VALIDATOR": "thread",
}


class _Fixed(Settings):
    """Settings read from :data:`_SETTINGS` alone: never from the environment or ``.env``."""

    # pydantic-settings passes every source by name; only the values given are kept.
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],  # noqa: ARG003
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        dotenv_settings: PydanticBaseSettingsSource,  # noqa: ARG003
        file_secret_settings: PydanticBaseSettingsSource,  # noqa: ARG003
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document of the API."""
    return create_app(_Fixed.model_validate(_SETTINGS)).openapi()


def render(document: dict[str, Any]) -> str:
    """The document as it is kept: indented JSON in the API's own order, ending in a newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None, *, root: Path = REPOSITORY_ROOT) -> int:
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args(argv)
    target = root / DOCUMENT
    target.write_text(render(openapi_document()), encoding="utf-8")
    print(f"wrote {DOCUMENT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
