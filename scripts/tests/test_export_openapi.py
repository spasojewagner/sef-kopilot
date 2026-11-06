"""The OpenAPI document in the repository is the API's own."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import export_openapi


def test_the_document_in_the_repository_is_the_apis() -> None:
    kept = (export_openapi.REPOSITORY_ROOT / export_openapi.DOCUMENT).read_text(encoding="utf-8")

    assert kept == export_openapi.render(export_openapi.openapi_document()), (
        "docs/api/openapi.json is out of date: run `uv run python scripts/export_openapi.py`, "
        "then `pnpm --filter @sef-kopilot/web api:types`"
    )


def test_the_document_is_the_same_whatever_the_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("SEF_MAX_INVOICE_BYTES=1024\n", encoding="utf-8")
    monkeypatch.setenv("SEF_ENVIRONMENT", "production")
    monkeypatch.setenv("LLM_PROVIDER", "groq")

    assert export_openapi.openapi_document() == json.loads(
        (export_openapi.REPOSITORY_ROOT / export_openapi.DOCUMENT).read_text(encoding="utf-8")
    )


def test_the_document_names_the_answers_the_web_application_reads() -> None:
    schemas = export_openapi.openapi_document()["components"]["schemas"]

    assert {"HealthResponse", "TokenResponse", "MeResponse", "StoredInvoiceOut"} <= set(schemas)


def test_the_command_writes_the_document(tmp_path: Path) -> None:
    (tmp_path / "docs" / "api").mkdir(parents=True)

    assert export_openapi.main([], root=tmp_path) == 0

    written = json.loads((tmp_path / export_openapi.DOCUMENT).read_text(encoding="utf-8"))
    assert written["info"]["title"] == export_openapi.openapi_document()["info"]["title"]
