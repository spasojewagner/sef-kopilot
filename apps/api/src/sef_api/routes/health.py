"""Liveness and readiness endpoints.

Two endpoints with two different questions, because orchestrators (Docker, Render, Kubernetes)
treat them differently:

* ``GET /health`` — *liveness*: is the process up and able to answer HTTP? It never touches a
  dependency, so a slow database cannot make the platform restart a healthy process.
* ``GET /ready`` — *readiness*: can this instance serve real traffic right now? It will check
  the database, Redis and the loaded rule sets once those exist; until then the check list is
  empty and the instance is always ready.
"""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from sef_api import __version__

SERVICE_NAME = "sef-kopilot-api"

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Liveness report."""

    status: Literal["ok"] = Field(description="Always `ok` when the process can answer.")
    service: str = Field(description="Service identifier, useful when several APIs share a host.")
    version: str = Field(description="Version of the running API, from the package metadata.")


class ReadinessResponse(BaseModel):
    """Readiness report with one entry per dependency check."""

    status: Literal["ready", "degraded"] = Field(
        description="`ready` when every check passed, `degraded` otherwise."
    )
    checks: dict[str, Literal["ok", "failed"]] = Field(
        default_factory=dict,
        description="Result per dependency (for example `database`, `redis`, `rulesets`).",
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Reports that the process is up. Never touches external dependencies.",
)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME, version=__version__)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description=(
        "Reports whether this instance can serve traffic. Each dependency is listed under "
        "`checks`; the overall status is `degraded` as soon as one of them fails."
    ),
)
async def ready() -> ReadinessResponse:
    checks: dict[str, Literal["ok", "failed"]] = {}
    status: Literal["ready", "degraded"] = (
        "ready" if all(result == "ok" for result in checks.values()) else "degraded"
    )
    return ReadinessResponse(status=status, checks=checks)
