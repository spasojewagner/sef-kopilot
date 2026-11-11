"""Documents for the tests of reading invoices from PDFs and pictures, made here, in memory: a
PDF with a text layer, written by hand as the PDF reference describes one, and pictures and
scanned PDFs drawn with Pillow."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw

__all__ = ["picture", "scanned_pdf", "text_pdf"]


def _escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf(*pages: list[str]) -> bytes:
    """A PDF of A4 pages, each with its lines of text in Helvetica, in a text layer."""
    objects: list[str] = []
    kids = []
    font = 3 + 2 * len(pages)
    for number, lines in enumerate(pages):
        page, content = 3 + 2 * number, 4 + 2 * number
        kids.append(f"{page} 0 R")
        stream = (
            "BT /F1 12 Tf 72 770 Td 16 TL "
            + " ".join(f"({_escaped(line)}) '" for line in lines)
            + " ET"
        )
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {content} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.insert(0, f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(pages)} >>")
    objects.insert(0, "<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    written = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(written))
        written += f"{number} 0 obj\n{body}\nendobj\n".encode("latin-1")
    table = len(written)
    written += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        written += f"{offset:010d} 00000 n \n".encode()
    written += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{table}\n%%EOF\n"
    ).encode()
    return bytes(written)


def _drawn(size: tuple[int, int], words: str) -> Image.Image:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((40, 40), words, fill="black")
    return image


def picture(
    image_format: str = "JPEG",
    *,
    size: tuple[int, int] = (1200, 1700),
    words: str = "RACUN RF-2026-000123",
    exif: Image.Exif | None = None,
) -> bytes:
    """A picture of a page with ``words`` on it, as ``image_format``."""
    encoded = io.BytesIO()
    options = {"exif": exif.tobytes()} if exif is not None else {}
    _drawn(size, words).save(encoded, image_format, **options)
    return encoded.getvalue()


def scanned_pdf(pages: int = 1) -> bytes:
    """A PDF of ``pages`` pages that are pictures only, as a scanner makes it."""
    drawn = [_drawn((1240, 1754), f"STRANA {number}") for number in range(1, pages + 1)]
    encoded = io.BytesIO()
    drawn[0].save(encoded, "PDF", save_all=True, append_images=drawn[1:], resolution=150.0)
    return encoded.getvalue()
