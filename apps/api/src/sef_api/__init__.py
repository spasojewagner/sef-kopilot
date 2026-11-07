"""SEF Kopilot HTTP API.

A FastAPI application that exposes the deterministic validator from ``einvoice_core`` together
with the explanation and repair layers, multi-tenant persistence, background jobs and the SEF
demo integration. The application is built by :func:`sef_api.main.create_app` so that tests and
deployments can construct it with explicit settings.
"""

__all__ = ["__version__"]

# Kept in sync with ``pyproject.toml`` by ``tests/test_health.py``.
__version__ = "0.3.0"
