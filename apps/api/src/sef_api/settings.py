"""Configuration, read from the environment and from a local ``.env`` file.

Variable names are the ones in ``.env.example``. Values that carry credentials are
:class:`~pydantic.SecretStr`, so they never appear in a ``repr``, a log line or a traceback.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from einvoice_core.xml import DEFAULT_MAX_BYTES

Environment = Literal["development", "test", "production"]

#: The database of ``infra/docker-compose.yml``, so that a fresh clone runs without a ``.env``.
LOCAL_DATABASE_URL = "postgresql+asyncpg://sef:sef@localhost:5432/sef_kopilot"
DRIVER = "postgresql+asyncpg"
#: The shortest signing key accepted: 32 characters, 256 bits for a random one.
MINIMUM_JWT_SECRET_LENGTH = 32
#: The default size limit of an invoice the API accepts: 5 MiB leaves room for the attachments
#: an invoice may embed and stays below the validator's own ceiling.
DEFAULT_MAX_INVOICE_BYTES = 5 * 1024 * 1024
#: The default budget of elements. Validating costs memory and time per element, not per byte
#: (an embedded PDF is one text node): 20 000 elements, some 1 500 invoice lines, keep the
#: validator's process within a few hundred MiB even when every line breaks a rule.
DEFAULT_MAX_INVOICE_ELEMENTS = 20_000
#: What an organization may store by default, its invoices and their reports together: some
#: hundreds of large invoices, or thousands of ordinary ones, on a free database of 512 MB.
DEFAULT_MAX_STORED_BYTES = 100 * 1024 * 1024


class Settings(BaseSettings):
    """Everything the API reads from its environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # `.env.example` lists optional variables empty; an empty one means "not set".
        env_ignore_empty=True,
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
    jwt_secret: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(48)),
        validation_alias="SEF_JWT_SECRET",
        description=(
            "Key that signs access tokens. Outside production a random one is made for each "
            "process, so tokens do not survive a restart."
        ),
    )
    access_token_minutes: int = Field(
        default=15, ge=1, le=60, validation_alias="SEF_ACCESS_TOKEN_MINUTES"
    )
    refresh_token_days: int = Field(
        default=30, ge=1, le=90, validation_alias="SEF_REFRESH_TOKEN_DAYS"
    )
    max_invoice_bytes: int = Field(
        default=DEFAULT_MAX_INVOICE_BYTES,
        ge=1024,
        le=DEFAULT_MAX_BYTES,
        validation_alias="SEF_MAX_INVOICE_BYTES",
        description="The largest invoice the API accepts, in bytes; larger ones answer 413.",
    )
    max_invoice_elements: int = Field(
        default=DEFAULT_MAX_INVOICE_ELEMENTS,
        ge=100,
        le=1_000_000,
        validation_alias="SEF_MAX_INVOICE_ELEMENTS",
        description="The most elements an invoice may have; more answer 413.",
    )
    upload_seconds: float = Field(
        default=30.0,
        gt=0,
        le=600,
        validation_alias="SEF_UPLOAD_SECONDS",
        description="How long a client has to send an invoice; a slower one answers 408.",
    )
    validation_seconds: float = Field(
        default=15.0,
        gt=0,
        le=600,
        validation_alias="SEF_VALIDATION_SECONDS",
        description="How long one validation may take before it is stopped (422).",
    )
    max_validations_in_flight: int = Field(
        default=8,
        ge=1,
        le=1000,
        validation_alias="SEF_MAX_VALIDATIONS_IN_FLIGHT",
        description="Validations that may wait or run at once; the next answers 503.",
    )
    max_stored_bytes: int = Field(
        default=DEFAULT_MAX_STORED_BYTES,
        ge=1024 * 1024,
        le=1024**4,
        validation_alias="SEF_MAX_STORED_BYTES",
        description="What one organization may store, invoices and reports together (507).",
    )
    validator: Literal["process", "thread"] = Field(
        default="process",
        validation_alias="SEF_VALIDATOR",
        description=(
            "`process`: a child process with a time limit, for the API. `thread`: a thread of "
            "the API's process, without one, for tests and tools."
        ),
    )

    @property
    def access_token_lifetime(self) -> timedelta:
        return timedelta(minutes=self.access_token_minutes)

    @property
    def refresh_token_lifetime(self) -> timedelta:
        return timedelta(days=self.refresh_token_days)

    @model_validator(mode="after")
    def _check_jwt_secret(self) -> Self:
        if self.environment == "production" and "jwt_secret" not in self.model_fields_set:
            raise ValueError("SEF_JWT_SECRET must be set in production")
        if len(self.jwt_secret.get_secret_value()) < MINIMUM_JWT_SECRET_LENGTH:
            raise ValueError(
                f"SEF_JWT_SECRET must have at least {MINIMUM_JWT_SECRET_LENGTH} characters"
            )
        return self

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
