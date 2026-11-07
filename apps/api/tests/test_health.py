"""Liveness, readiness and the OpenAPI contract of the health endpoints."""

from importlib.metadata import version
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import sef_api
from einvoice_core.rulesets import ENV_VAR
from sef_api.main import create_app

from .conftest import settings_for


def test_version_matches_package_metadata() -> None:
    assert sef_api.__version__ == version("sef-kopilot-api")


async def test_health_reports_ok_with_service_and_version(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sef-kopilot-api",
        "version": sef_api.__version__,
        "public_demo": False,
    }


async def test_health_says_when_the_server_is_a_public_demo() -> None:
    app = create_app(settings_for(SEF_PUBLIC_DEMO="true"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    await app.state.database.engine.dispose()

    assert response.json()["public_demo"] is True


async def test_ready_is_503_while_the_database_does_not_answer(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "checks": {"database": "failed", "validator": "ok"},
    }


async def test_ready_reports_ready_when_the_database_answers(database_url: str) -> None:
    app = create_app(settings_for(database_url))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    await app.state.database.engine.dispose()

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "validator": "ok"}}


async def test_ready_is_503_without_the_validators_rule_sets(
    database_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))  # an empty directory: nothing fetched
    app = create_app(settings_for(database_url))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    await app.state.database.engine.dispose()

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "validator": "failed"}


async def test_ready_is_503_while_the_validator_cannot_run(database_url: str) -> None:
    """For example a child process whose rule sets do not load: it says so when it starts."""

    class Broken:
        problem = "the validator's rule sets cannot be loaded (SchemaLoadError)"

    app = create_app(settings_for(database_url))
    app.state.validator = Broken()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/ready")
    await app.state.database.engine.dispose()

    assert response.status_code == 503
    assert response.json()["checks"] == {"database": "ok", "validator": "failed"}


async def test_shutting_down_disposes_of_the_database_engine() -> None:
    app = create_app(settings_for())
    engine = app.state.database.engine

    async with app.router.lifespan_context(app):
        pass

    assert engine.pool.checkedout() == 0


async def test_openapi_documents_the_health_endpoints(client: AsyncClient) -> None:
    """The public API contract: both probes are documented with summaries and tags."""
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"] == "SEF Kopilot API"
    assert "not a certified validator" in schema["info"]["description"]
    for path in ("/health", "/ready"):
        operation = schema["paths"][path]["get"]
        assert operation["tags"] == ["health"]
        assert operation["summary"]
        assert operation["description"]
