"""Opening a PDF or a picture into the pages a model reads: the text a PDF holds, pictures made
anew within the size limits and without their metadata, and documents refused for what they
are, never for what they contain."""

from __future__ import annotations

import asyncio
import io

import pytest
from PIL import ExifTags, Image

from sef_api.extraction.documents import (
    LONGEST_SIDE,
    MAX_PAGES,
    DocumentTooLargeError,
    UnreadableDocumentError,
    open_document,
    read_document,
)

from .documents import picture, scanned_pdf, text_pdf

INVOICE_TEXT = [
    "RACUN broj RF-2026-000123",
    "Prodavac: Primer Softver d.o.o., PIB 100000024",
    "Ukupno za uplatu: 14.400,00 RSD",
]


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def test_a_pdf_with_a_text_layer_gives_its_text_and_a_picture_of_each_page() -> None:
    document = read_document(
        text_pdf(INVOICE_TEXT, ["Strana 2: napomena o placanju racuna"]), "application/pdf"
    )

    assert document.kind == "pdf"
    assert document.has_text
    first, second = document.pages
    assert first.text is not None
    assert first.text.splitlines() == INVOICE_TEXT
    assert second.text == "Strana 2: napomena o placanju racuna"
    for page in document.pages:
        assert page.picture.media_type == "image/jpeg"
        shown = opened(page.picture.data)
        assert shown.format == "JPEG"
        assert max(shown.size) == LONGEST_SIDE
        assert shown.size == (1131, LONGEST_SIDE)  # A4, upright


def test_a_scanned_pdf_has_pictures_and_no_text() -> None:
    document = read_document(scanned_pdf(2), "application/pdf")

    assert document.kind == "pdf"
    assert not document.has_text
    assert [page.text for page in document.pages] == [None, None]
    assert all(max(opened(page.picture.data).size) == LONGEST_SIDE for page in document.pages)


def test_a_page_with_a_stray_word_counts_as_one_without_text() -> None:
    document = read_document(text_pdf(["Strana 1"]), "application/pdf")

    assert document.pages[0].text is None
    assert not document.has_text


def test_a_pdf_of_more_pages_than_are_read_is_refused() -> None:
    with pytest.raises(DocumentTooLargeError, match=f"the PDF has 4 pages; at most {MAX_PAGES}"):
        read_document(scanned_pdf(MAX_PAGES + 1), "application/pdf")


@pytest.mark.parametrize(
    ("image_format", "media_type"),
    [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")],
)
def test_a_picture_is_made_anew_as_jpeg_no_larger_than_a_page_is_shown(
    image_format: str, media_type: str
) -> None:
    document = read_document(picture(image_format, size=(3000, 4000)), media_type)

    assert document.kind == "picture"
    (page,) = document.pages
    assert page.text is None
    shown = opened(page.picture.data)
    assert shown.format == "JPEG"
    assert shown.size == (1200, LONGEST_SIDE)


def test_a_small_picture_keeps_its_size() -> None:
    document = read_document(picture("PNG", size=(800, 600)), "image/png")

    assert opened(document.pages[0].picture.data).size == (800, 600)


def test_a_photograph_is_turned_upright_and_loses_where_it_was_taken() -> None:
    exif = Image.Exif()
    exif[ExifTags.Base.Orientation] = 6  # taken on its side: turn 90 degrees clockwise
    exif[ExifTags.Base.Make] = "Primer Phone"
    gps = exif.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSLatitudeRef] = "N"
    gps[ExifTags.GPS.GPSLatitude] = (44.0, 49.0, 0.0)
    taken = picture(size=(1600, 1200), exif=exif)
    assert opened(taken).getexif()[ExifTags.Base.Make] == "Primer Phone"

    document = read_document(taken, "image/jpeg")

    shown = opened(document.pages[0].picture.data)
    assert shown.size == (1200, 1600)
    assert dict(shown.getexif()) == {}
    assert b"Primer Phone" not in document.pages[0].picture.data


def test_a_picture_of_too_many_pixels_is_refused_before_it_is_decoded() -> None:
    encoded = io.BytesIO()
    Image.new("1", (10_000, 4_100)).save(encoded, "PNG")

    with pytest.raises(DocumentTooLargeError, match="10000 by 4100 pixels; at most 40 million"):
        read_document(encoded.getvalue(), "image/png")


@pytest.mark.parametrize(
    ("data", "media_type", "message"),
    [
        (b"<Invoice/>", "application/pdf", "is not a PDF, a JPEG, a PNG or a WebP picture"),
        (picture("PNG"), "image/jpeg", "sent as image/jpeg, but it is image/png"),
        (text_pdf(INVOICE_TEXT), "image/png", "sent as image/png, but it is application/pdf"),
        (b"%PDF-1.7\nnot a PDF at all", "application/pdf", "the PDF cannot be opened"),
        (b"\x89PNG\r\n\x1a\nbroken", "image/png", "the picture cannot be opened"),
        (picture("JPEG")[:200], "image/jpeg", "the picture cannot be opened"),
    ],
)
def test_a_document_that_cannot_be_read_is_refused_for_what_it_is(
    data: bytes, media_type: str, message: str
) -> None:
    with pytest.raises(UnreadableDocumentError, match=message) as refused:
        read_document(data, media_type)
    assert "RF-2026" not in str(refused.value)


def test_a_pdf_without_pages_is_refused() -> None:
    with pytest.raises(UnreadableDocumentError, match="the PDF cannot be opened"):
        read_document(text_pdf(), "application/pdf")


async def test_pdfs_opened_at_once_are_opened_one_at_a_time_and_all_read() -> None:
    documents = await asyncio.gather(
        *(
            open_document(text_pdf([*INVOICE_TEXT, f"Kopija {n}"]), "application/pdf")
            for n in range(6)
        )
    )

    for number, document in enumerate(documents):
        assert document.pages[0].text is not None
        assert document.pages[0].text.endswith(f"Kopija {number}")
