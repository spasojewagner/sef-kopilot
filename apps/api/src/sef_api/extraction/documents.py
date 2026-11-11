"""A PDF or a picture opened into pages a model can look at (ADR-0062).

A document is a PDF, or a picture of an invoice: a photograph, a scan, a screenshot. Each page is
shown to the reading model as a picture, with the page's own text where a PDF has it, which a
model reads more surely than text it must make out.

- What a document is, is decided by its first bytes, which must agree with the media type it
  came as: a picture sent as a PDF is refused, not guessed at.
- A PDF is opened by PDFium (``pypdfium2``), Chrome's PDF engine, which runs no JavaScript and
  opens nothing outside the file. One protected by a password is refused, and so is one of more
  than :data:`MAX_PAGES` pages. Each page is drawn so that its longer side is
  :data:`LONGEST_SIDE` pixels; its text is taken from its text layer, if it has one worth the
  name (a scan has none).
- A picture is opened by Pillow, as JPEG, PNG or WebP only, and refused above
  :data:`MAX_PIXELS`, before it is decoded. It is turned upright as its EXIF orientation says,
  made smaller to :data:`LONGEST_SIDE`, and encoded anew as JPEG, which leaves its metadata
  behind: a phone's photograph names where it was taken.

PDFium may serve one thread at a time, so every PDF is opened under one lock, in a worker
thread, never in the event loop. Nothing here keeps the document: its pages live as long as
the request that reads them.
"""

from __future__ import annotations

import asyncio
import io
import threading
import warnings
from dataclasses import dataclass
from typing import Final, Literal

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from sef_api.llm import Picture

__all__ = [
    "LONGEST_SIDE",
    "MAX_PAGES",
    "MAX_PIXELS",
    "Document",
    "DocumentTooLargeError",
    "Page",
    "UnreadableDocumentError",
    "open_document",
    "read_document",
]

#: The most pages a document may have: as many pictures as Groq's reading model takes at once.
MAX_PAGES: Final = 3
#: The longer side of a page as the model sees it, in pixels: an A4 page at about 140 dpi,
#: enough for the small print of an invoice, within what a model reads in one picture.
LONGEST_SIDE: Final = 1600
#: The most pixels a picture may have: a photograph of 40 megapixels, which no phone takes yet;
#: more is refused before anything is decoded.
MAX_PIXELS: Final = 40_000_000
#: The quality pages are encoded at, as JPEG.
QUALITY: Final = 85
#: The fewest characters of text that make a PDF's page one with a text layer: a scanned page
#: may carry a stray word.
MIN_TEXT: Final = 20
#: The most characters of a page's text sent to the model, more than a dense page holds.
MAX_TEXT: Final = 20_000

#: Each kind of document by the bytes it begins with.
_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)
_PDFIUM = threading.Lock()


class UnreadableDocumentError(Exception):
    """A document that cannot be opened; the message says why, never what it holds."""


class DocumentTooLargeError(UnreadableDocumentError):
    """A document with more pages or pixels than may be read."""


@dataclass(frozen=True)
class Page:
    """A page as the model sees it: a picture, and the text of a PDF's text layer if any."""

    picture: Picture
    text: str | None


@dataclass(frozen=True)
class Document:
    """A document opened: a PDF, or a picture of one page."""

    kind: Literal["pdf", "picture"]
    pages: tuple[Page, ...]

    @property
    def has_text(self) -> bool:
        """Whether any page has a text layer."""
        return any(page.text is not None for page in self.pages)


def _sniffed(data: bytes) -> str | None:
    """The media type ``data`` begins as, if it is one that is read."""
    for magic, media_type in _MAGIC:
        if data.startswith(magic):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _jpeg(image: Image.Image) -> Picture:
    """``image`` no larger than :data:`LONGEST_SIDE`, as JPEG, without its metadata."""
    image = image.convert("RGB")
    image.thumbnail((LONGEST_SIDE, LONGEST_SIDE), Image.Resampling.LANCZOS)
    encoded = io.BytesIO()
    image.save(encoded, "JPEG", quality=QUALITY, optimize=True)
    return Picture("image/jpeg", encoded.getvalue())


def _text(raw: str) -> str | None:
    text = "\n".join(line.rstrip() for line in raw.replace("\r\n", "\n").split("\n")).strip()
    if len("".join(text.split())) < MIN_TEXT:
        return None
    return text[:MAX_TEXT]


def _pdf(data: bytes) -> Document:
    with _PDFIUM:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError:
            raise UnreadableDocumentError(
                "the PDF cannot be opened: it is damaged, or protected by a password"
            ) from None
        try:
            if len(pdf) == 0:  # pragma: no cover - PDFium refuses to open a PDF without pages
                raise UnreadableDocumentError("the PDF has no pages")
            if len(pdf) > MAX_PAGES:
                raise DocumentTooLargeError(
                    f"the PDF has {len(pdf)} pages; at most {MAX_PAGES} are read"
                )
            pages = []
            for page in pdf:
                try:
                    width, height = page.get_size()
                    scale = min(LONGEST_SIDE / max(width, height, 1.0), 4.0)
                    image = page.render(scale=scale).to_pil()
                    text = _text(page.get_textpage().get_text_bounded())
                finally:
                    page.close()
                pages.append(Page(_jpeg(image), text))
        except pdfium.PdfiumError:
            raise UnreadableDocumentError("a page of the PDF cannot be drawn") from None
        finally:
            pdf.close()
    return Document("pdf", tuple(pages))


def _picture(data: bytes) -> Document:
    try:
        with warnings.catch_warnings():
            # Above Pillow's own limit a picture warns; above twice it raises. Either way it
            # is refused here first, by its size, read from its header.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP"))
            if image.width * image.height > MAX_PIXELS:
                raise DocumentTooLargeError(
                    f"the picture has {image.width} by {image.height} pixels; at most "
                    f"{MAX_PIXELS // 1_000_000} million are read"
                )
            image.seek(0)  # the first frame of an animation
            upright = ImageOps.exif_transpose(image)
            return Document("picture", (Page(_jpeg(upright), None),))
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        OSError,
        ValueError,
        SyntaxError,
    ):
        raise UnreadableDocumentError("the picture cannot be opened: it is damaged") from None


def read_document(data: bytes, media_type: str) -> Document:
    """The document in ``data``, sent as ``media_type``, opened into pages: blocking, and
    best run by :func:`open_document`."""
    sniffed = _sniffed(data)
    if sniffed is None:
        raise UnreadableDocumentError("the document is not a PDF, a JPEG, a PNG or a WebP picture")
    if sniffed != media_type:
        raise UnreadableDocumentError(
            f"the document was sent as {media_type}, but it is {sniffed}: send it as what it is"
        )
    return _pdf(data) if sniffed == "application/pdf" else _picture(data)


async def open_document(data: bytes, media_type: str) -> Document:
    """The document in ``data``, opened in a worker thread."""
    return await asyncio.to_thread(read_document, data, media_type)
