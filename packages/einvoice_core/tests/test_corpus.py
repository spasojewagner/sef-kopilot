"""The fixture corpus: the Ministry's SEF examples, kept byte for byte."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from einvoice_core.xml import load_document

from .conftest import REPOSITORY_ROOT

SEF_DIR = REPOSITORY_ROOT / "fixtures" / "invoices" / "official" / "sef"
SEF_MANIFEST: dict[str, Any] = json.loads((SEF_DIR / "manifest.json").read_text(encoding="utf-8"))
SEF_EXAMPLES: list[dict[str, Any]] = SEF_MANIFEST["documents"]


def test_the_manifest_lists_every_sef_example_once_in_order() -> None:
    names = [entry["file"] for entry in SEF_EXAMPLES]

    assert names == sorted(set(names))
    assert names == sorted(path.name for path in SEF_DIR.glob("*.xml"))
    assert len(names) == 17


@pytest.mark.parametrize("entry", SEF_EXAMPLES, ids=lambda entry: entry["file"])
def test_each_sef_example_is_the_published_file(entry: dict[str, Any]) -> None:
    data = (SEF_DIR / entry["file"]).read_bytes()

    assert len(data) == entry["bytes"]
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    assert entry["url"].startswith("https://www.efaktura.gov.rs/extfile/sr/")
    assert load_document(data).getroot() is not None
