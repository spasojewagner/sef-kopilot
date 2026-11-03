"""Liveness, readiness and the OpenAPI contract of the health endpoints."""

from importlib.metadata import version

from httpx import AsyncClient

import sef_api


def test_version_matches_package_metadata() -> None:
    assert sef_api.__version__ == version("sef-kopilot-api")


async def test_health_reports_ok_with_service_and_version(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "sef-kopilot-api",
        "version": sef_api.__version__,
    }


async def test_ready_reports_ready_when_no_check_fails(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert all(result == "ok" for result in body["checks"].values())


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
