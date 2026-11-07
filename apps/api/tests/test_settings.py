"""Settings: variable names, defaults, the checks on DATABASE_URL and REDIS_URL, secrets kept out
of sight."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from sef_api.settings import LOCAL_DATABASE_URL, Settings

from .conftest import REPOSITORY_ROOT, settings_for

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
        "SEF_MAX_STORED_BYTES",
        "SEF_VALIDATIONS_PER_MINUTE",
        "SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE",
        "SEF_JOBS",
        "REDIS_URL",
        "EMBEDDINGS_PROVIDER",
        "JINA_API_KEY",
        "LLM_PROVIDER",
        "GROQ_API_KEY",
        "SEF_LLM_MODEL",
        "SEF_MAX_EXPLANATIONS",
        "SEF_EXPLANATION_SECONDS",
        "SEF_REPAIR_SECONDS",
        "SEF_EXPLANATIONS_PER_MINUTE",
        "SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE",
        "SEF_WEB_ORIGINS",
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


def test_a_caller_validates_60_invoices_a_minute_and_an_organization_300_by_default() -> None:
    settings = Settings()

    assert (settings.validations_per_minute, settings.organization_validations_per_minute) == (
        60,
        300,
    )


def test_an_organization_stores_100_mib_by_default_and_at_least_1_mib() -> None:
    assert Settings().max_stored_bytes == 100 * 1024 * 1024
    with pytest.raises(ValidationError):
        Settings.model_validate({"SEF_MAX_STORED_BYTES": str(1024 * 1024 - 1)})


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("SEF_MAX_INVOICE_ELEMENTS", "99"),
        ("SEF_UPLOAD_SECONDS", "0"),
        ("SEF_VALIDATION_SECONDS", "601"),
        ("SEF_MAX_VALIDATIONS_IN_FLIGHT", "0"),
        ("SEF_VALIDATIONS_PER_MINUTE", "0"),
        ("SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE", "0"),
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


def test_jobs_run_in_the_api_unless_told_otherwise() -> None:
    settings = Settings()

    assert (settings.jobs, settings.redis_url) == ("inline", None)


def test_jobs_on_a_redis_queue_need_its_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_JOBS", "arq")
    with pytest.raises(ValidationError, match="REDIS_URL must be set when SEF_JOBS is arq"):
        Settings()

    monkeypatch.setenv("REDIS_URL", f"rediss://default:{PASSWORD}@queue.example:6379")
    settings = Settings()

    assert settings.jobs == "arq"
    assert PASSWORD not in repr(settings)


@pytest.mark.parametrize("url", ["http://queue.example:6379", "queue.example:6379"])
def test_the_redis_url_names_redis(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("REDIS_URL", url)

    with pytest.raises(ValidationError, match="REDIS_URL must use the redis:// or rediss://"):
        Settings()


def test_no_page_of_another_origin_may_call_the_api_by_default() -> None:
    assert Settings().web_origins == ()


def test_the_web_origins_are_separated_by_commas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_WEB_ORIGINS", "http://localhost:3000, https://sef-kopilot.pages.dev,")

    assert Settings().web_origins == ("http://localhost:3000", "https://sef-kopilot.pages.dev")


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "localhost:3000",
        "http://localhost:3000/",
        "https://sef-kopilot.pages.dev/app",
        "https://sef-kopilot.pages.dev?from=mail",
        "https://ana@sef-kopilot.pages.dev",
        "https://sef-kopilot.pages.dev:port",
        "HTTPS://SEF-KOPILOT.PAGES.DEV",
        "ftp://sef-kopilot.pages.dev",
    ],
)
def test_a_web_origin_is_a_scheme_a_host_and_a_port(
    monkeypatch: pytest.MonkeyPatch, origin: str
) -> None:
    monkeypatch.setenv("SEF_WEB_ORIGINS", origin)

    with pytest.raises(ValidationError, match="which is no origin"):
        Settings()


def test_in_production_a_web_origin_is_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://api:secret@db.example:5432/sef")
    monkeypatch.setenv("SEF_JWT_SECRET", "k" * 48)
    monkeypatch.setenv("SEF_WEB_ORIGINS", "https://sef-kopilot.pages.dev,http://localhost:3000")

    with pytest.raises(
        ValidationError,
        match=r"'http://localhost:3000', which is no origin: a "
        r"scheme \(https\)",
    ):
        Settings()
    monkeypatch.setenv("SEF_WEB_ORIGINS", "https://sef-kopilot.pages.dev")
    assert Settings().web_origins == ("https://sef-kopilot.pages.dev",)


def test_settings_from_given_values_read_neither_the_environment_nor_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("SEF_MAX_EXPLANATIONS=9\nSEF_JOBS=arq\n", encoding="utf-8")
    monkeypatch.setenv("SEF_VALIDATOR", "thread")
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    settings = Settings.from_values({"SEF_ENVIRONMENT": "test", "SEF_MAX_INVOICE_BYTES": "4096"})

    assert (settings.environment, settings.max_invoice_bytes) == ("test", 4096)
    assert (settings.validator, settings.jobs, settings.llm_provider) == (
        "process",
        "inline",
        "none",
    )
    assert settings.max_explanations == 5
    # What is given is checked as ever.
    with pytest.raises(ValidationError, match="SEF_JWT_SECRET must be set in production"):
        Settings.from_values({"SEF_ENVIRONMENT": "production"})


def test_a_test_applications_settings_read_nothing_from_the_machine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("SEF_MAX_EXPLANATIONS=9\n", encoding="utf-8")
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "unused")

    settings = settings_for(SEF_REPAIR_SECONDS="5")

    assert (settings.llm_provider, settings.groq_api_key) == ("none", None)
    assert (settings.max_explanations, settings.repair_seconds) == (5, 5.0)
