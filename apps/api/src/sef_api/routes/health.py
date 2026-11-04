"""Liveness and readiness endpoints.

Two endpoints with two different questions, because orchestrators (Docker, Render, Kubernetes)
treat them differently:

* ``GET /health`` — *liveness*: is the process up and able to answer HTTP? It never touches a
  dependency, so a slow database cannot make the platform restart a healthy process.
* ``GET /ready`` — *readiness*: can this instance serve real traffic right now? It checks the
  database (Redis and the rule sets join the list when the API starts to use them) and answers
  503 as soon as one check fails, so a load balancer stops sending traffic to it.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from sef_api import __version__
from sef_api.db import Database, get_database

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
        "`checks`; as soon as one of them fails the status is `degraded` and the response 503."
    ),
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "A dependency failed; the instance should not receive traffic.",
        }
    },
)
async def ready(
    response: Response, database: Annotated[Database, Depends(get_database)]
) -> ReadinessResponse:
    checks: dict[str, Literal["ok", "failed"]] = {
        "database": "ok" if await database.ping() else "failed",
    }
    if all(result == "ok" for result in checks.values()):
        return ReadinessResponse(status="ready", checks=checks)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="degraded", checks=checks)
