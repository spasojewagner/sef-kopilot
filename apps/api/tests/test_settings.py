"""Settings: variable names, defaults, the checks on DATABASE_URL, secrets kept out of sight."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sef_api.settings import LOCAL_DATABASE_URL, Settings

from .conftest import REPOSITORY_ROOT

PASSWORD = "hunter2-not-a-real-one"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No variable from the developer's shell, and no ``.env`` in the working directory."""
    for name in (
        "SEF_ENVIRONMENT",
        "DATABASE_URL",
        "SEF_JWT_SECRET",
        "SEF_ACCESS_TOKEN_MINUTES",
        "SEF_REFRESH_TOKEN_DAYS",
        "SEF_MAX_INVOICE_BYTES",
        "SEF_MAX_INVOICE_ELEMENTS",
        "SEF_UPLOAD_SECONDS",
        "SEF_VALIDATION_SECONDS",
        "SEF_MAX_VALIDATIONS_IN_FLIGHT",
        "SEF_VALIDATOR",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)


def test_the_defaults_are_development_on_the_local_database() -> None:
    settings = Settings()

    assert settings.environment == "development"
    assert settings.database_url.get_secret_value() == LOCAL_DATABASE_URL


def test_the_values_come_from_the_variables_in_env_example(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://api:secret@db.example:5432/sef")
    monkeypatch.setenv("SEF_JWT_SECRET", "k" * 48)

    settings = Settings()

    assert settings.environment == "production"
    assert settings.database_url.get_secret_value().endswith("@db.example:5432/sef")
    assert settings.jwt_secret.get_secret_value() == "k" * 48


def test_a_dot_env_file_in_the_working_directory_is_read(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SEF_ENVIRONMENT=test\n", encoding="utf-8")

    assert Settings().environment == "test"


def test_a_copy_of_env_example_starts_the_api_as_it_is() -> None:
    (Path.cwd() / ".env").write_text(
        (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )

    settings = Settings()

    assert settings.environment == "development"
    assert len(settings.jwt_secret.get_secret_value()) >= 32


def test_production_needs_an_explicit_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")
    monkeypatch.setenv("SEF_JWT_SECRET", "k" * 48)

    with pytest.raises(ValidationError, match="DATABASE_URL must be set in production"):
        Settings()


def test_production_needs_an_explicit_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://api:secret@db.example/sef")

    with pytest.raises(ValidationError, match="SEF_JWT_SECRET must be set in production"):
        Settings()


def test_outside_production_each_process_gets_its_own_signing_key() -> None:
    first, second = Settings(), Settings()

    assert len(first.jwt_secret.get_secret_value()) >= 32
    assert first.jwt_secret != second.jwt_secret


def test_a_signing_key_has_at_least_32_characters() -> None:
    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings.model_validate({"SEF_JWT_SECRET": "too short"})


def test_token_lifetimes_default_to_15_minutes_and_30_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert (Settings().access_token_minutes, Settings().refresh_token_days) == (15, 30)

    monkeypatch.setenv("SEF_ACCESS_TOKEN_MINUTES", "5")
    monkeypatch.setenv("SEF_REFRESH_TOKEN_DAYS", "7")

    assert Settings().access_token_lifetime.total_seconds() == 300
    assert Settings().refresh_token_lifetime.days == 7


def test_an_invoice_may_weigh_5_mib_unless_configured_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert Settings().max_invoice_bytes == 5 * 1024 * 1024

    monkeypatch.setenv("SEF_MAX_INVOICE_BYTES", "65536")

    assert Settings().max_invoice_bytes == 65536


@pytest.mark.parametrize("limit", ["1023", str(10 * 1024 * 1024 + 1)])
def test_the_invoice_limit_stays_within_the_validators_own(limit: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"SEF_MAX_INVOICE_BYTES": limit})


def test_the_validator_runs_in_a_child_process_with_limits_by_default() -> None:
    settings = Settings()

    assert settings.validator == "process"
    assert settings.max_invoice_elements == 20_000
    assert (settings.upload_seconds, settings.validation_seconds) == (30, 15)
    assert settings.max_validations_in_flight == 8


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SEF_MAX_INVOICE_ELEMENTS", "99"),
        ("SEF_UPLOAD_SECONDS", "0"),
        ("SEF_VALIDATION_SECONDS", "601"),
        ("SEF_MAX_VALIDATIONS_IN_FLIGHT", "0"),
        ("SEF_VALIDATOR", "fork"),
    ],
)
def test_the_validators_limits_are_bounded(variable: str, value: str) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({variable: value})


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
    assert settings.jwt_secret.get_secret_value() not in repr(settings)


def test_an_unknown_environment_is_refused() -> None:
    with pytest.raises(ValidationError, match="SEF_ENVIRONMENT"):
        Settings.model_validate({"SEF_ENVIRONMENT": "staging"})
