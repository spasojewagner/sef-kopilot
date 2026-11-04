"""Configuration, read from the environment and from a local ``.env`` file.

Variable names are the ones in ``.env.example``. Values that carry credentials are
:class:`~pydantic.SecretStr`, so they never appear in a ``repr``, a log line or a traceback.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

Environment = Literal["development", "test", "production"]

#: The database of ``infra/docker-compose.yml``, so that a fresh clone runs without a ``.env``.
LOCAL_DATABASE_URL = "postgresql+asyncpg://sef:sef@localhost:5432/sef_kopilot"
DRIVER = "postgresql+asyncpg"


class Settings(BaseSettings):
    """Everything the API reads from its environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        # Validation errors must not echo a value: DATABASE_URL carries a password.
        hide_input_in_errors=True,
    )

    environment: Environment = Field(
        default="development",
        validation_alias="SEF_ENVIRONMENT",
        description="`development`, `test` or `production`.",
    )
    database_url: SecretStr = Field(
        default=SecretStr(LOCAL_DATABASE_URL),
        validation_alias="DATABASE_URL",
        description=f"SQLAlchemy URL of the PostgreSQL database; the driver is `{DRIVER}`.",
    )

    @model_validator(mode="after")
    def _check_database_url(self) -> Self:
        if self.environment == "production" and "database_url" not in self.model_fields_set:
            raise ValueError("DATABASE_URL must be set in production")
        try:
            driver = make_url(self.database_url.get_secret_value()).drivername
        except ArgumentError:
            raise ValueError("DATABASE_URL is not a database URL") from None
        if driver != DRIVER:
            raise ValueError(
                f"DATABASE_URL must use the {DRIVER}:// scheme, for example {LOCAL_DATABASE_URL}"
            )
        return self
