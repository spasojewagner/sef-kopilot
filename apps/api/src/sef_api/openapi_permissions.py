"""The permission each endpoint requires, named in the OpenAPI schema (ASVS V4).

A guarded route depends on :func:`sef_api.auth.dependencies.require`, one dependency per
permission (and per variant that changes the members), so its dependencies tell what it requires.
The schema names that permission in each such operation's ``x-required-permission``. An operation
without the extension is public by name, which the route audit (``test_access_control.py``) holds
every other route to.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, Final

from fastapi import FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from sef_api.auth.dependencies import require
from sef_api.auth.permissions import Permission

__all__ = ["EXTENSION", "name_permissions", "required_permissions"]

#: The extension of an operation that names the permission it requires.
EXTENSION: Final = "x-required-permission"


def _calls(dependant: Dependant) -> Iterator[Callable[..., Any]]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _calls(dependency)


def required_permissions(route: APIRoute) -> list[Permission]:
    """The permissions ``route`` requires, by their order in :class:`Permission`."""
    used = set(_calls(route.dependant))
    return [
        permission
        for permission in Permission
        if any(require(permission, changes_members=changes) in used for changes in (False, True))
    ]


def _routes(routes: Iterable[BaseRoute]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif (included := getattr(route, "original_router", None)) is not None:
            # FastAPI keeps an included router as one route that holds it.
            yield from _routes(included.routes)


def name_permissions(app: FastAPI) -> None:
    """Have ``app``'s OpenAPI schema name, in each guarded operation, the permission it requires;
    the schema is made once, as FastAPI makes it, then named."""
    make = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = make()
        paths = schema.get("paths", {})
        for route in _routes(app.routes):
            needed = required_permissions(route)
            if not needed or not route.include_in_schema:
                continue
            for method in route.methods or ():
                operation = paths.get(route.path, {}).get(method.lower())
                if operation is not None:
                    operation[EXTENSION] = (
                        needed[0].value if len(needed) == 1 else [each.value for each in needed]
                    )
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
