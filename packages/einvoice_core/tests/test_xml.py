"""Hardened loading and canonical XPath addressing."""

from __future__ import annotations

import errno
import io
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from lxml import etree

from einvoice_core.xml import (
    CAC,
    NAMESPACES,
    SRBDT_EXT,
    UBL,
    ParseError,
    canonical_xpath,
    load_document,
    qualified_name,
)

MINIMAL = f'<Invoice xmlns="{UBL}" xmlns:cbc="{NAMESPACES["cbc"]}"><cbc:ID>1</cbc:ID></Invoice>'


# --- loading ------------------------------------------------------------------------------


def test_loads_from_bytes_path_and_stream(tmp_path: Path) -> None:
    path = tmp_path / "invoice.xml"
    path.write_text(MINIMAL, encoding="utf-8")

    for source in (MINIMAL.encode(), path, str(path), io.BytesIO(MINIMAL.encode())):
        tree = load_document(source)
        assert tree.getroot().tag == f"{{{UBL}}}Invoice"


def test_a_str_is_a_path_not_xml_text() -> None:
    """Passing XML text as ``str`` must not silently parse it (it would bypass the path branch)."""
    with pytest.raises(OSError, match="<Invoice xmlns=") as raised:
        load_document(MINIMAL)

    # No such file on POSIX; on Windows `<`, `>`, `:` and `"` make the name invalid.
    assert raised.value.errno in {errno.ENOENT, errno.EINVAL}


def test_rejects_documents_over_the_byte_limit() -> None:
    with pytest.raises(ParseError, match="size limit of 16 bytes"):
        load_document(MINIMAL.encode(), max_bytes=16)
    with pytest.raises(ParseError, match="size limit"):
        load_document(io.BytesIO(MINIMAL.encode()), max_bytes=16)


def test_rejects_malformed_xml() -> None:
    with pytest.raises(ParseError, match="malformed XML"):
        load_document(b"<Invoice><cbc:ID>1</Invoice>")


@pytest.mark.parametrize(
    "prolog",
    [
        "<!DOCTYPE Invoice>",
        '<!DOCTYPE Invoice SYSTEM "http://attacker.invalid/x.dtd">',
        '<!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>',
        '<!DOCTYPE lol [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>',
    ],
)
def test_rejects_any_doctype(prolog: str) -> None:
    with pytest.raises(ParseError, match="DOCTYPE"):
        load_document((prolog + MINIMAL).encode())


def test_parse_error_message_includes_xpath_when_known() -> None:
    assert str(ParseError("boom")) == "boom"
    assert str(ParseError("boom", xpath="/ubl:Invoice/cbc:ID")) == "boom (at /ubl:Invoice/cbc:ID)"


# --- canonical xpath -------------------------------------------------------------------


def test_predicates_only_where_siblings_share_a_name() -> None:
    root = etree.fromstring(
        f'<Invoice xmlns="{UBL}" xmlns:cac="{CAC}" xmlns:cbc="{NAMESPACES["cbc"]}">'
        "<cbc:ID>1</cbc:ID>"
        "<cac:InvoiceLine><cbc:ID>a</cbc:ID></cac:InvoiceLine>"
        "<cac:InvoiceLine><cbc:ID>b</cbc:ID></cac:InvoiceLine>"
        "</Invoice>"
    )
    document_id, first_line, second_line = list(root)
    (second_line_id,) = list(second_line)

    assert canonical_xpath(root) == "/ubl:Invoice"
    assert canonical_xpath(document_id) == "/ubl:Invoice/cbc:ID"
    assert canonical_xpath(first_line) == "/ubl:Invoice/cac:InvoiceLine[1]"
    assert canonical_xpath(second_line) == "/ubl:Invoice/cac:InvoiceLine[2]"
    assert canonical_xpath(second_line_id) == "/ubl:Invoice/cac:InvoiceLine[2]/cbc:ID"


def test_the_serbian_extension_has_a_canonical_prefix() -> None:
    root = etree.fromstring(
        f'<Invoice xmlns="{UBL}" xmlns:ext="{NAMESPACES["ext"]}" xmlns:srb="{SRBDT_EXT}">'
        "<ext:UBLExtensions><ext:UBLExtension><ext:ExtensionContent>"
        "<srb:SrbDtExt><srb:ReducedTotals/></srb:SrbDtExt>"
        "</ext:ExtensionContent></ext:UBLExtension></ext:UBLExtensions></Invoice>"
    )
    (reduced,) = root.iter(f"{{{SRBDT_EXT}}}ReducedTotals")
    xpath = canonical_xpath(reduced)

    assert xpath == (
        "/ubl:Invoice/ext:UBLExtensions/ext:UBLExtension/ext:ExtensionContent"
        "/sbt:SrbDtExt/sbt:ReducedTotals"
    )
    assert root.xpath(xpath, namespaces=NAMESPACES) == [reduced]


def test_unknown_namespaces_use_the_document_prefix_or_clark_notation() -> None:
    root = etree.fromstring(
        f'<Invoice xmlns="{UBL}" xmlns:x="urn:example:x"><x:Extra/><Plain xmlns=""/></Invoice>'
    )
    extra, plain = list(root)

    assert canonical_xpath(extra) == "/ubl:Invoice/x:Extra"
    assert qualified_name(plain) == "Plain"
    assert canonical_xpath(plain) == "/ubl:Invoice/Plain"


def test_default_namespace_without_prefix_falls_back_to_clark_notation() -> None:
    root = etree.fromstring('<Doc xmlns="urn:example:nodefault"><Child/></Doc>')

    assert canonical_xpath(root[0]) == "/{urn:example:nodefault}Doc/{urn:example:nodefault}Child"


_TAGS = ("A", "B", "C")


@st.composite
def _trees(draw: st.DrawFn, depth: int = 0) -> etree._Element:
    element = etree.Element(f"{{{CAC}}}{draw(st.sampled_from(_TAGS))}")
    if depth < 3:
        for _ in range(draw(st.integers(min_value=0, max_value=4))):
            element.append(draw(_trees(depth=depth + 1)))
    return element


@given(_trees())
def test_every_canonical_xpath_selects_exactly_its_element(root: etree._Element) -> None:
    """The invariant the rest of the system relies on: an XPath resolves to one node."""
    tree = root.getroottree()
    for element in root.iter():
        selected = tree.xpath(canonical_xpath(element), namespaces=NAMESPACES)
        assert selected == [element]
