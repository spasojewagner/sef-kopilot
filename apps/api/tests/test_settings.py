"""Settings: variable names, defaults, the checks on DATABASE_URL, secrets kept out of sight."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sef_api.settings import LOCAL_DATABASE_URL, Settings

PASSWORD = "hunter2-not-a-real-one"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No variable from the developer's shell, and no ``.env`` in the working directory."""
    for name in ("SEF_ENVIRONMENT", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_the_defaults_are_development_on_the_local_database() -> None:
    settings = Settings()

    assert settings.environment == "development"
    assert settings.database_url.get_secret_value() == LOCAL_DATABASE_URL


def test_the_values_come_from_the_variables_in_env_example(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://api:secret@db.example:5432/sef")

    settings = Settings()

    assert settings.environment == "production"
    assert settings.database_url.get_secret_value().endswith("@db.example:5432/sef")


def test_a_dot_env_file_in_the_working_directory_is_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SEF_ENVIRONMENT=test\n", encoding="utf-8")

    assert Settings().environment == "test"


def test_production_needs_an_explicit_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")

    with pytest.raises(ValidationError, match="DATABASE_URL must be set in production"):
        Settings()


@pytest.mark.parametrize(
    ("url", "message"),
    [
        (f"postgresql://sef:{PASSWORD}@localhost/sef", r"must use the postgresql\+asyncpg://"),
        ("sqlite+aiosqlite:///sef.db", r"must use the postgresql\+asyncpg://"),
        ("not a url", "is not a database URL"),
    ],
)
def test_the_database_url_names_postgresql_with_asyncpg(url: str, message: str) -> None:
    with pytest.raises(ValidationError, match=message) as error:
        Settings.model_validate({"DATABASE_URL": url})

    assert PASSWORD not in str(error.value)


def test_the_database_password_never_shows() -> None:
    settings = Settings.model_validate(
        {"DATABASE_URL": f"postgresql+asyncpg://sef:{PASSWORD}@h/db"}
    )

    assert PASSWORD not in repr(settings)
    assert PASSWORD not in str(settings.model_dump())


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValidationError, match="SEF_ENVIRONMENT"):
        Settings.model_validate({"SEF_ENVIRONMENT": "staging"})
