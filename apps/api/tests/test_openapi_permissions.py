"""The OpenAPI schema names the permission each guarded endpoint requires, and none for a public
one (ASVS V4)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from sef_api.main import create_app
from sef_api.openapi_permissions import EXTENSION

from .conftest import settings_for
from .test_access_control import GUARDED, PUBLIC


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    app: FastAPI = create_app(settings_for())
    return app.openapi()


def test_every_guarded_operation_names_the_permission_the_route_audit_pins(
    schema: dict[str, Any],
) -> None:
    named = {
        (method.upper(), path): operation[EXTENSION]
        for path, operations in schema["paths"].items()
        for method, operation in operations.items()
        if EXTENSION in operation
    }

    assert named == {
        endpoint: guarded.permission.value
        for endpoint, guarded in GUARDED.items()
        if endpoint[1] in schema["paths"]
    }


def test_a_public_operation_names_none(schema: dict[str, Any]) -> None:
    for method, path in PUBLIC:
        operation = schema["paths"].get(path, {}).get(method.lower())
        if operation is not None:
            assert EXTENSION not in operation, (method, path)


def test_the_schema_is_named_once_and_kept(schema: dict[str, Any]) -> None:
    validate = schema["paths"]["/invoices/validate"]["post"]

    assert validate[EXTENSION] == "invoices:validate"
