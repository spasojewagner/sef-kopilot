"""Configuration, read from the environment and from a local ``.env`` file.

Variable names are the ones in ``.env.example``. Values that carry credentials are
:class:`~pydantic.SecretStr`, so they never appear in a ``repr``, a log line or a traceback.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from datetime import timedelta
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, PydanticBaseSettingsSource, SettingsConfigDict
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


def _is_origin(text: str, schemes: set[str]) -> bool:
    """Whether ``text`` is an origin as a browser sends it: a scheme of ``schemes``, a host and a
    port if any, in lower case, with nothing after them."""
    parts = urlsplit(text)
    try:
        parts.port  # noqa: B018 - a port that is no number raises
    except ValueError:
        return False
    return (
        parts.scheme in schemes
        and bool(parts.hostname)
        and parts.username is None
        and text == f"{parts.scheme}://{parts.netloc}".lower()
    )


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
    max_body_bytes: int = Field(
        default=1024 * 1024,
        ge=64 * 1024,
        le=16 * 1024 * 1024,
        validation_alias="SEF_MAX_BODY_BYTES",
        description="The longest request body other than an invoice, in bytes: the JSON of a "
        "request, say a list of patches; longer ones answer 413.",
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
    validations_per_minute: int = Field(
        default=60,
        ge=1,
        le=100_000,
        validation_alias="SEF_VALIDATIONS_PER_MINUTE",
        description="Validations one caller, a person or an API key, may ask for a minute; 429 "
        "beyond.",
    )
    organization_validations_per_minute: int = Field(
        default=300,
        ge=1,
        le=1_000_000,
        validation_alias="SEF_ORGANIZATION_VALIDATIONS_PER_MINUTE",
        description="Validations all the callers of one organization may ask for a minute; 429 "
        "beyond.",
    )
    validator: Literal["process", "thread"] = Field(
        default="process",
        validation_alias="SEF_VALIDATOR",
        description=(
            "`process`: a child process with a time limit, for the API. `thread`: a thread of "
            "the API's process, without one, for tests and tools."
        ),
    )
    jobs: Literal["inline", "arq"] = Field(
        default="inline",
        validation_alias="SEF_JOBS",
        description=(
            "Where jobs run. `inline`: in the API's own process, for a deployment of one "
            "process. `arq`: in workers (`python -m sef_api.jobs.worker`) that take them from "
            "a Redis queue, beside any number of API processes."
        ),
    )
    redis_url: SecretStr | None = Field(
        default=None,
        validation_alias="REDIS_URL",
        description="The Redis server of the job queue: required with `SEF_JOBS=arq`.",
    )
    embeddings_provider: Literal["none", "jina"] = Field(
        default="none",
        validation_alias="EMBEDDINGS_PROVIDER",
        description=(
            "Who embeds the corpus when it is ingested. `none`: nobody, and passages are found "
            "by keyword; `jina`: Jina's embeddings API, with `JINA_API_KEY`."
        ),
    )
    jina_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="JINA_API_KEY",
        description="The key to Jina's embeddings API: required with `EMBEDDINGS_PROVIDER=jina`.",
    )
    llm_provider: Literal["none", "groq"] = Field(
        default="none",
        validation_alias="LLM_PROVIDER",
        description=(
            "The language model that writes explanations and proposes repairs. `none`: no "
            "model, and both answer 503; `groq`: Groq's API, with `GROQ_API_KEY`."
        ),
    )
    groq_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GROQ_API_KEY",
        description="The key to Groq's API: required with `LLM_PROVIDER=groq`.",
    )
    llm_model: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        validation_alias="SEF_LLM_MODEL",
        description=(
            "The provider's model, when not its default (`openai/gpt-oss-120b` on Groq); it "
            "must support structured outputs."
        ),
    )
    max_explanations: int = Field(
        default=5,
        ge=1,
        le=20,
        validation_alias="SEF_MAX_EXPLANATIONS",
        description="The most rules of one report explained in one request; the rest are named.",
    )
    explanation_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        validation_alias="SEF_EXPLANATION_SECONDS",
        description="Seconds the explanations of one request may take; a rule not explained "
        "by then says so.",
    )
    repair_seconds: float = Field(
        default=20.0,
        gt=0,
        le=300,
        validation_alias="SEF_REPAIR_SECONDS",
        description="Seconds the language model's rounds of patches for one repair may take; "
        "a round not done by then is not kept.",
    )
    explanations_per_minute: int = Field(
        default=10,
        ge=1,
        le=100_000,
        validation_alias="SEF_EXPLANATIONS_PER_MINUTE",
        description="Requests to the language model, for explanations or a repair, one caller "
        "may make a minute; 429 beyond.",
    )
    organization_explanations_per_minute: int = Field(
        default=30,
        ge=1,
        le=1_000_000,
        validation_alias="SEF_ORGANIZATION_EXPLANATIONS_PER_MINUTE",
        description="Requests to the language model, for explanations or a repair, all the "
        "callers of one organization may make a minute; 429 beyond.",
    )

    web_origins: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(),
        validation_alias="SEF_WEB_ORIGINS",
        description=(
            "The origins of the web application, separated by commas, whose pages may call the "
            "API from a browser (CORS), such as `https://sef-kopilot.pages.dev`. None by "
            "default: no page of another origin may call it."
        ),
    )

    @field_validator("web_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(part.strip() for part in value.split(",") if part.strip())
        return value

    @classmethod
    def from_values(cls, values: Mapping[str, object]) -> Settings:
        """Settings read from ``values`` alone, by the variables' names
        (``{"SEF_ENVIRONMENT": "test"}``), and from neither the environment nor ``.env``: for the
        tools and tests whose settings must not depend on the machine they run on."""
        return _Given.model_validate(dict(values))

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
    def _check_redis_url(self) -> Self:
        if self.redis_url is None:
            if self.jobs == "arq":
                raise ValueError("REDIS_URL must be set when SEF_JOBS is arq")
            return self
        if urlsplit(self.redis_url.get_secret_value()).scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use the redis:// or rediss:// scheme")
        return self

    @model_validator(mode="after")
    def _check_embeddings(self) -> Self:
        if self.embeddings_provider == "jina" and self.jina_api_key is None:
            raise ValueError("JINA_API_KEY must be set when EMBEDDINGS_PROVIDER is jina")
        return self

    @model_validator(mode="after")
    def _check_llm(self) -> Self:
        if self.llm_provider == "groq" and self.groq_api_key is None:
            raise ValueError("GROQ_API_KEY must be set when LLM_PROVIDER is groq")
        return self

    @model_validator(mode="after")
    def _check_web_origins(self) -> Self:
        schemes = {"https"} if self.environment == "production" else {"http", "https"}
        for origin in self.web_origins:
            if not _is_origin(origin, schemes):
                raise ValueError(
                    f"SEF_WEB_ORIGINS holds {origin!r}, which is no origin: a scheme "
                    f"({' or '.join(sorted(schemes))}), a host and a port if any, nothing more"
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


class _Given(Settings):
    """:class:`Settings` read from the values given alone (:meth:`Settings.from_values`)."""

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
