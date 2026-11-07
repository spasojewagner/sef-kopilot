"""Serve the API for the web application's end-to-end test (ADR-0033).

The application is the one ``make api`` serves: every route, the validator in its child process,
PostgreSQL, and the jobs in the API's own process. Two things differ, so that a browser walks the
golden path, upload, report, repair and approval, the same way every time:

- its database, ``sef_e2e`` on the tests' PostgreSQL server (``SEF_TEST_DATABASE_URL``, from the
  environment or the repository's ``.env``), is dropped, made anew and migrated whenever it starts;
- no language model is called: :class:`ScriptedModel` proposes the repairs, given to the
  repairer as the API's own tests give it a model.

Nothing else is read from the environment, so that a developer's ``.env`` can neither point the
test at another database nor send an invoice to a model's provider. From the repository's root::

    uv run python scripts/serve_e2e_api.py --port 8100 --web-origin http://localhost:3100

The web application's Playwright configuration (``apps/web/playwright.config.ts``) starts it,
and stops it after the test.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import uvicorn
from alembic import command
from pydantic import SecretStr
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from sef_api.llm import LANGUAGES, LLMError, Message
from sef_api.main import create_app
from sef_api.migrations import alembic_config
from sef_api.repairs.repairer import Repairer
from sef_api.settings import Settings

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
#: The database the API starts on, made anew on the tests' server each time.
DATABASE: Final = "sef_e2e"
#: Where the API answers, and the origin of the pages that call it, unless the command says.
HOST: Final = "127.0.0.1"
PORT: Final = 8100
WEB_ORIGIN: Final = "http://localhost:3100"

#: The rule whose violations the scripted model repairs: the invoice type code (BT-3).
TYPE_CODE_RULE: Final = "SRB-001"
#: The type code it writes, a commercial invoice's, one of those the rule's message names.
COMMERCIAL_INVOICE: Final = "380"
#: Its reason, in each language the repairer may ask for.
REASONS: Final = {
    "sr": "380 je kod komercijalne fakture, jedan od onih koje SEF prima.",
    "en": "380 is the code of a commercial invoice, one of those SEF accepts.",
}
#: A violation as the repairer's question names it: its rule, its layer, then its place.
_VIOLATION: Final = re.compile(
    r"<violation>\nrule: (?P<rule>\S+)\nlayer: \S+\nplace: (?P<place>.+)"
)


class ScriptedModel:
    """A stand-in for the language model: it repairs an invoice's type code, and nothing else,
    the same way every time.

    Of each violation of SRB-001 it is sent, it proposes to write 380 at the violation's place,
    the code of a commercial invoice, which the rule's message names among the codes SEF
    accepts. Of any other violation it proposes nothing, as a model that sees no repair would.
    Its reasons are in the language the repairer asks for. The repairer checks its answers as
    it checks a real model's.
    """

    model = "e2e/scripted"

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        if name != "repair":
            raise LLMError("the scripted model proposes repairs, and writes nothing else")
        english = messages[0].content.endswith(f"in {LANGUAGES['en']}.")
        reason = REASONS["en" if english else "sr"]
        patches = [
            {
                "xpath": found["place"],
                "op": "replace",
                "value": COMMERCIAL_INVOICE,
                "reason": reason,
            }
            for found in _VIOLATION.finditer(messages[-1].content)
            if found["rule"] == TYPE_CODE_RULE
        ]
        return json.dumps({"patches": patches})

    async def aclose(self) -> None:
        pass


class _Given(Settings):
    """The API's settings read from the values given alone: never from the environment or
    ``.env``."""

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


def settings_for(database_url: str, web_origin: str) -> Settings:
    """The API's settings for the test: its database, the origin of the web application's pages,
    and the rest as a deployment of one process has them by default, with neither a language
    model nor embeddings. The key that signs tokens is made anew for the process."""
    return _Given.model_validate(
        {
            "SEF_ENVIRONMENT": "test",
            "DATABASE_URL": database_url,
            "SEF_WEB_ORIGINS": web_origin,
            "SEF_VALIDATOR": "process",
            "SEF_JOBS": "inline",
            "LLM_PROVIDER": "none",
            "EMBEDDINGS_PROVIDER": "none",
        }
    )


async def _execute(server: URL, *statements: str) -> None:
    engine = create_async_engine(server, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


def fresh_database(server_url: str, name: str = DATABASE) -> str:
    """The database ``name`` on the PostgreSQL server of ``server_url``, dropped if it is there,
    made anew and migrated to the latest revision: its URL."""
    server = make_url(server_url)
    asyncio.run(
        _execute(
            server, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)', f'CREATE DATABASE "{name}"'
        )
    )
    url = server.set(database=name).render_as_string(hide_password=False)
    command.upgrade(alembic_config(url), "head")
    return url


def server_url(env_file: Path) -> str | None:
    """The URL of the tests' PostgreSQL server, ``SEF_TEST_DATABASE_URL`` from the environment
    or ``env_file``, as the API's tests read it; None when it is not set."""

    class Server(BaseSettings):
        model_config = SettingsConfigDict(env_file=env_file, extra="ignore")

        sef_test_database_url: SecretStr | None = None

    url = Server().sef_test_database_url
    return None if url is None else url.get_secret_value()


def main(argv: Sequence[str] | None = None, *, env_file: Path = REPOSITORY_ROOT / ".env") -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", default=HOST, help=f"the address to answer at ({HOST})")
    parser.add_argument("--port", type=int, default=PORT, help=f"the port to answer at ({PORT})")
    parser.add_argument(
        "--web-origin",
        default=WEB_ORIGIN,
        help=f"the origin of the web application's pages, which may call the API ({WEB_ORIGIN})",
    )
    arguments = parser.parse_args(argv)
    server = server_url(env_file)
    if server is None:
        print(
            "SEF_TEST_DATABASE_URL is not set: name the PostgreSQL server the tests make their "
            "databases on, as .env.example does (`make up` starts one)",
            file=sys.stderr,
        )
        return 2
    app = create_app(settings_for(fresh_database(server), arguments.web_origin))
    app.state.repairer = Repairer(ScriptedModel())
    uvicorn.run(app, host=arguments.host, port=arguments.port, log_level="warning")
    return 0


# The validator's child processes import this module again, as the start method "spawn" does:
# only the process started from the command line serves.
if __name__ == "__main__":
    raise SystemExit(main())
