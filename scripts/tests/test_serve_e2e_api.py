"""The API of the browser's end-to-end test: the scripted model repairs the golden path's invoice
through the repairer the API uses, the settings are the launcher's whatever the environment, and
the database is made anew each time. Patches are applied as the validator's process applies them,
so the rule sets must have been fetched; the database tests need ``SEF_TEST_DATABASE_URL``."""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

import serve_e2e_api
from einvoice_core.patches import Patch
from sef_api.invoices.validation import Patched, patched_outcome, warm_up
from sef_api.llm import Language, LLMError, Message
from sef_api.migrations import alembic_config
from sef_api.repairs.repairer import Apply, NoPatchError, Repairer, Suggestion

MUTATIONS = serve_e2e_api.REPOSITORY_ROOT / "fixtures" / "invoices" / "synthetic" / "mutations"
#: The golden path's invoice: its type code, 393, is not one SEF accepts (SRB-001).
TYPE_CODE = (MUTATIONS / "srb-001-invoice-type-code.xml").read_bytes()
#: An invoice whose buyer has no city (SRB-015), which the scripted model does not repair.
CITY = (MUTATIONS / "srb-015-city.xml").read_bytes()
SERVER = serve_e2e_api.server_url(serve_e2e_api.REPOSITORY_ROOT / ".env")
DATABASE_URL = "postgresql+asyncpg://sef:sef@127.0.0.1:1/sef_e2e"


@pytest.fixture(scope="module")
def _warm() -> None:
    """Rule sets compiled before any test counts its seconds."""
    assert warm_up() is None


def applying(content: bytes) -> Apply:
    """Applies patches to ``content`` as the validator's process does."""

    async def apply(patches: Sequence[Patch]) -> Patched:
        kind, detail = patched_outcome(content, "srb", patches, max_elements=20_000, fields=True)
        assert kind == "patched", detail
        return Patched.model_validate_json(detail)

    return apply


async def suggested(content: bytes, language: Language = "sr") -> Suggestion:
    repairer = Repairer(serve_e2e_api.ScriptedModel())
    return await repairer.suggest(applying(content), language=language, seconds=60.0)


@pytest.mark.usefixtures("_warm")
async def test_the_scripted_model_repairs_the_type_code_as_the_repairer_asks() -> None:
    suggestion = await suggested(TYPE_CODE)

    assert [(outcome.patch, outcome.status) for outcome in suggestion.patched.outcomes] == [
        (
            Patch(
                xpath="/ubl:Invoice/cbc:InvoiceTypeCode",
                op="replace",
                value="380",
                reason="380 je kod komercijalne fakture, jedan od onih koje SEF prima.",
            ),
            "applied",
        )
    ]
    assert suggestion.patched.validation.report.valid
    # The repairer took its first answer: the model wrote no value it was not given.
    assert (suggestion.rounds, suggestion.answers) == (1, 1)


@pytest.mark.usefixtures("_warm")
async def test_its_reasons_are_in_the_language_asked_for() -> None:
    suggestion = await suggested(TYPE_CODE, language="en")

    assert [outcome.patch.reason for outcome in suggestion.patched.outcomes] == [
        "380 is the code of a commercial invoice, one of those SEF accepts."
    ]


@pytest.mark.usefixtures("_warm")
async def test_it_proposes_nothing_for_another_rule() -> None:
    with pytest.raises(NoPatchError, match="proposes no patch for these violations"):
        await suggested(CITY)


async def test_it_writes_nothing_but_repairs() -> None:
    model = serve_e2e_api.ScriptedModel()

    with pytest.raises(LLMError, match="proposes repairs, and writes nothing else"):
        await model.answer(
            [Message("system", "Explain."), Message("user", "SRB-001")],
            name="explanation",
            schema={},
        )


def test_the_settings_are_the_launchers_whatever_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://other:other@db.example:5432/other\n"
        "SEF_WEB_ORIGINS=https://elsewhere.example\n"
        "SEF_PUBLIC_URL=https://api.elsewhere.example\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "unused")
    monkeypatch.setenv("SEF_JOBS", "arq")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SEF_VALIDATOR", "thread")

    settings = serve_e2e_api.settings_for(
        DATABASE_URL, "http://localhost:3100", "http://127.0.0.1:8100"
    )

    assert settings.database_url.get_secret_value() == DATABASE_URL
    assert settings.web_origins == ("http://localhost:3100",)
    assert (settings.public_url, settings.web_url) == (
        "http://127.0.0.1:8100",
        "http://localhost:3100",
    )
    assert (settings.environment, settings.validator, settings.jobs) == (
        "test",
        "process",
        "inline",
    )
    assert (settings.llm_provider, settings.embeddings_provider) == ("none", "none")
    assert settings.groq_api_key is None


def test_it_serves_the_api_with_the_scripted_model_on_a_fresh_database(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("SEF_TEST_DATABASE_URL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SEF_TEST_DATABASE_URL=postgresql+asyncpg://sef:sef@localhost:5432/postgres\n",
        encoding="utf-8",
    )
    made: list[str] = []
    served: dict[str, Any] = {}

    def fresh_database(server_url: str) -> str:
        made.append(server_url)
        return DATABASE_URL

    def run(app: Any, **options: Any) -> None:
        served.update(app=app, **options)

    monkeypatch.setattr(serve_e2e_api, "fresh_database", fresh_database)
    monkeypatch.setattr(uvicorn, "run", run)

    assert serve_e2e_api.main(["--web-origin", "http://localhost:3123"], env_file=env_file) == 0

    app = served.pop("app")
    assert made == ["postgresql+asyncpg://sef:sef@localhost:5432/postgres"]
    assert served == {"host": "127.0.0.1", "port": 8100, "log_level": "warning"}
    assert app.state.settings.database_url.get_secret_value() == DATABASE_URL
    assert app.state.settings.web_origins == ("http://localhost:3123",)
    assert (app.state.settings.public_url, app.state.settings.web_url) == (
        "http://127.0.0.1:8100",
        "http://localhost:3123",
    )
    assert app.state.repairer.model == "e2e/scripted"
    assert app.state.explainer is None
    asyncio.run(app.state.database.engine.dispose())


def test_it_does_not_start_without_the_tests_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("SEF_TEST_DATABASE_URL", raising=False)

    assert serve_e2e_api.main([], env_file=tmp_path / ".env") == 2

    assert "SEF_TEST_DATABASE_URL is not set" in capsys.readouterr().err


async def _rows(url: str, query: str) -> list[Any]:
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return list((await connection.execute(text(query))).scalars())
    finally:
        await engine.dispose()


async def _execute(url: str, statement: str) -> None:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture
def database_name() -> Iterator[str]:
    """A name for the test's database on the tests' server, which is dropped afterwards."""
    if not SERVER:
        pytest.skip("set SEF_TEST_DATABASE_URL to a PostgreSQL server to run database tests")
    name = f"sef_e2e_test_{secrets.token_hex(6)}"
    yield name
    asyncio.run(_execute(SERVER, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def test_the_database_is_made_anew_and_migrated_each_time(database_name: str) -> None:
    assert SERVER is not None
    url = serve_e2e_api.fresh_database(SERVER, database_name)
    asyncio.run(_execute(url, "CREATE TABLE left_by_a_run_before (id integer)"))

    assert serve_e2e_api.fresh_database(SERVER, database_name) == url

    assert make_url(url).database == database_name
    tables = asyncio.run(_rows(url, "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
    assert "left_by_a_run_before" not in tables
    assert "organizations" in tables
    head = ScriptDirectory.from_config(alembic_config(url)).get_current_head()
    assert asyncio.run(_rows(url, "SELECT version_num FROM alembic_version")) == [head]
