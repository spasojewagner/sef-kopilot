"""Render the documents the reading of invoices is measured on (ADR-0063): each case of
``evals/golden/extraction.yaml`` printed as a Serbian invoice is printed, three ways.

The fields of a case are what its documents print, and so what reading them must give. Each
case's page is drawn from HTML in one of two layouts, by Chromium, then kept as ``<name>.pdf``,
a PDF with its text layer, as a business program prints one; ``<name>.scan.pdf``, the page as a
scanner gives it, a grey picture in a PDF without text; and ``<name>.jpg``, the paper
photographed on a desk, turned a little, lit unevenly and saved as a phone saves it. The
pictures are made with fixed seeds, so the same cases always give the same pictures. The
documents are committed: the evaluations replay the model's answers to them offline
(ADR-0055), and a document drawn again must be recorded again.

It needs Playwright for Python and its Chromium, which the workspace does not install::

    pip install playwright pyyaml pillow && playwright install chromium
    python scripts/render_documents.py                  # writes evals/golden/documents/
    python scripts/render_documents.py --only <name>    # one case
"""

from __future__ import annotations

import argparse
import html
import io
import random
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import yaml
from PIL import Image, ImageChops, ImageFilter, ImageOps

REPOSITORY_ROOT: Final = Path(__file__).resolve().parents[1]
GOLDEN: Final = REPOSITORY_ROOT / "evals" / "golden" / "extraction.yaml"
DOCUMENTS: Final = REPOSITORY_ROOT / "evals" / "golden" / "documents"
#: A4 at 150 dots an inch: the page a scanner and a photograph start from.
PAGE: Final = (1240, 1754)
#: The longest side of a photograph: what the API reads a picture at.
PHOTO_SIDE: Final = 1600

TITLES: Final = {
    "380": "RAČUN",
    "386": "AVANSNI RAČUN",
    "381": "KNJIŽNO ODOBRENJE",
    "383": "KNJIŽNO ZADUŽENJE",
}
#: The units as an invoice prints them; C62, one, prints none.
UNITS: Final = {
    "H87": "kom",
    "HUR": "sat",
    "DAY": "dan",
    "KGM": "kg",
    "LTR": "l",
    "MTR": "m",
    "KMT": "km",
    "C62": "",
}


def money(value: str | None) -> str:
    """An amount as a Serbian invoice prints it: 14.400,00."""
    if value is None:
        return ""
    whole, _, cents = f"{Decimal(value):.2f}".partition(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    grouped = ".".join(reversed([digits[max(i - 3, 0) : i] for i in range(len(digits), 0, -3)]))
    return f"{sign}{grouped},{cents}"


def quantity(value: str | None) -> str:
    return "" if value is None else value.replace(".", ",")


def day(value: str | None) -> str:
    """A date as printed: 05.10.2026."""
    if value is None:
        return ""
    year, month, date = value.split("-")
    return f"{date}.{month}.{year}."


def e(value: Any) -> str:
    return "" if value is None else html.escape(str(value))


def party_block(party: dict[str, Any], *, label: str, vat: bool | None = None) -> str:
    lines = [f"<div class='label'>{label}</div>", f"<div class='name'>{e(party.get('name'))}</div>"]
    address = ", ".join(
        part
        for part in (
            party.get("street"),
            " ".join(p for p in (party.get("postal_code"), party.get("city")) if p),
        )
        if part
    )
    # The country is not printed: a Serbian invoice names none, and the reading writes RS.
    if address:
        lines.append(f"<div>{e(address)}</div>")
    if party.get("tax_id"):
        lines.append(f"<div>PIB: {e(party['tax_id'])}</div>")
    if party.get("company_id"):
        lines.append(f"<div>Matični broj: {e(party['company_id'])}</div>")
    if party.get("email"):
        lines.append(f"<div>E-pošta: {e(party['email'])}</div>")
    if vat is True:
        lines.append("<div class='note'>Obveznik PDV-a</div>")
    elif vat is False:
        lines.append("<div class='note'>Nije u sistemu PDV-a</div>")
    return "\n".join(lines)


STYLES: Final = {
    "classic": """
      body { font-family: 'DejaVu Serif', serif; font-size: 12.5px; color: #111; margin: 0; }
      .page { padding: 48px 56px; }
      header { display: flex; justify-content: space-between; border-bottom: 2px solid #111;
               padding-bottom: 14px; }
      .title { font-size: 26px; letter-spacing: 1px; font-weight: bold; }
      .label { font-size: 10px; text-transform: uppercase; color: #555; margin-bottom: 2px; }
      .name { font-weight: bold; font-size: 14px; }
      .parties { display: flex; gap: 40px; margin: 22px 0; }
      .parties > div { flex: 1; border: 1px solid #999; padding: 10px 12px; }
      table { width: 100%; border-collapse: collapse; margin-top: 10px; }
      th, td { border: 1px solid #999; padding: 5px 7px; }
      th { background: #eee; font-size: 11px; }
      td.n { text-align: right; white-space: nowrap; }
      .meta td { border: none; padding: 2px 8px 2px 0; }
      .totals { width: 48%; margin-left: auto; }
      .totals td { border: none; border-bottom: 1px solid #ccc; }
      .due td { font-weight: bold; font-size: 15px; border-bottom: 2px solid #111; }
      .note { font-style: italic; color: #333; }
      footer { margin-top: 28px; font-size: 11px; color: #333; }
    """,
    "modern": """
      body { font-family: 'DejaVu Sans', sans-serif; font-size: 12px; color: #222; margin: 0; }
      .page { padding: 40px 48px; }
      header { display: flex; justify-content: space-between; align-items: flex-start; }
      .title { font-size: 22px; font-weight: bold; color: #0b4f6c; }
      .label { font-size: 9.5px; color: #0b4f6c; font-weight: bold; margin-bottom: 3px; }
      .name { font-weight: bold; font-size: 13px; }
      .parties { display: flex; gap: 24px; margin: 26px 0 18px; }
      .parties > div { flex: 1; background: #f2f6f8; padding: 12px 14px; border-radius: 6px; }
      table { width: 100%; border-collapse: collapse; margin-top: 8px; }
      th { text-align: left; font-size: 10px; color: #0b4f6c; border-bottom: 2px solid #0b4f6c;
           padding: 6px 6px; }
      td { border-bottom: 1px solid #dde5e9; padding: 6px 6px; }
      td.n, th.n { text-align: right; white-space: nowrap; }
      .meta td { border: none; padding: 1px 10px 1px 0; }
      .totals { width: 45%; margin-left: auto; }
      .totals td { border-bottom: 1px solid #dde5e9; }
      .due td { font-weight: bold; font-size: 14px; color: #0b4f6c; border-bottom: none; }
      .note { color: #555; }
      footer { margin-top: 30px; font-size: 10.5px; color: #555; border-top: 1px solid #dde5e9;
               padding-top: 10px; }
    """,
}


def page_html(fields: dict[str, Any], layout: str) -> str:
    """The invoice that ``fields`` describe, as a page of ``layout``."""
    seller, buyer = fields.get("seller") or {}, fields.get("buyer") or {}
    totals, payment = fields.get("totals") or {}, fields.get("payment") or {}
    currency = fields.get("currency") or "RSD"
    meta = [
        ("Broj", fields.get("number")),
        ("Datum izdavanja", day(fields.get("issue_date"))),
        ("Datum prometa", day(fields.get("delivery_date"))),
        ("Rok plaćanja", day(fields.get("due_date"))),
        ("Valuta", currency),
        ("Broj narudžbenice", fields.get("buyer_reference")),
    ]
    meta_rows = "".join(
        f"<tr><td>{label}:</td><td><b>{e(value)}</b></td></tr>" for label, value in meta if value
    )
    rows = "".join(
        "<tr>"
        f"<td>{number}</td><td>{e(line.get('name'))}</td>"
        f"<td>{e(UNITS.get(line.get('unit') or '', line.get('unit')))}</td>"
        f"<td class='n'>{quantity(line.get('quantity'))}</td>"
        f"<td class='n'>{money(line.get('unit_price'))}</td>"
        f"<td class='n'>{e(line.get('vat_rate'))}%</td>"
        f"<td class='n'>{money(line.get('net_amount'))}</td>"
        "</tr>"
        for number, line in enumerate(fields.get("lines") or [], start=1)
    )
    recap = "".join(
        "<tr>"
        f"<td>{e(row.get('vat_category'))}</td><td class='n'>{e(row.get('vat_rate'))}%</td>"
        f"<td class='n'>{money(row.get('taxable_amount'))}</td>"
        f"<td class='n'>{money(row.get('tax_amount'))}</td>"
        "</tr>"
        for row in fields.get("vat_breakdown") or []
    )
    total_rows = [
        ("Zbir stavki", totals.get("line_total")),
        ("Ukupna osnovica", totals.get("tax_exclusive")),
        ("Ukupan PDV", totals.get("tax")),
        ("Ukupno sa PDV-om", totals.get("tax_inclusive")),
        ("Plaćeno avansom", totals.get("prepaid")),
    ]
    totals_html = "".join(
        f"<tr><td>{label}</td><td class='n'>{money(value)} {currency}</td></tr>"
        for label, value in total_rows
        if value is not None
    )
    totals_html += (
        f"<tr class='due'><td>Za uplatu</td><td class='n'>{money(totals.get('payable'))} "
        f"{currency}</td></tr>"
    )
    paying = []
    if payment.get("account"):
        paying.append(f"Tekući račun: <b>{e(payment['account'])}</b>")
    if payment.get("model"):
        paying.append(f"Model: <b>{e(payment['model'])}</b>")
    if payment.get("reference"):
        paying.append(f"Poziv na broj: <b>{e(payment['reference'])}</b>")
    issuer = party_block(seller, label="Izdavalac računa", vat=fields.get("seller_in_vat_register"))
    return f"""<!doctype html><html lang="sr"><head><meta charset="utf-8">
<style>{STYLES[layout]}</style></head><body><div class="page">
<header>
  <div>{issuer}</div>
  <div style="text-align:right">
    <div class="title">{TITLES.get(fields.get("type_code") or "380", "RAČUN")}</div>
    <table class="meta" style="width:auto;margin-left:auto">{meta_rows}</table>
  </div>
</header>
<div class="parties">
  <div>{party_block(buyer, label="Kupac")}</div>
  <div><div class="label">Plaćanje</div>{"<br>".join(paying)}</div>
</div>
<table>
  <thead><tr><th>R.br.</th><th>Naziv</th><th>Jed. mere</th><th class="n">Količina</th>
  <th class="n">Cena bez PDV-a</th><th class="n">PDV</th>
  <th class="n">Iznos bez PDV-a</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
<div style="display:flex;gap:32px;margin-top:22px;align-items:flex-start">
  <div style="flex:1"><div class="label">Rekapitulacija PDV-a</div>
    <table><thead><tr><th>Kategorija</th><th class="n">Stopa</th><th class="n">Osnovica</th>
    <th class="n">PDV</th></tr></thead><tbody>{recap}</tbody></table></div>
  <table class="totals">{totals_html}</table>
</div>
<footer>Račun je izdat elektronski i punovažan je bez pečata i potpisa.
Sintetički dokument za proveru čitanja: firme i brojevi su izmišljeni.</footer>
</div></body></html>"""


def scanned(picture: Image.Image, seed: int) -> Image.Image:
    """The page as a scanner gives it: grey, a little soft, a little noisy."""
    rng = random.Random(seed)
    grey = ImageOps.grayscale(picture).filter(ImageFilter.GaussianBlur(0.6))
    noise = Image.effect_noise(grey.size, 10).point(lambda value: value // 8)
    grey = Image.blend(grey, ImageOps.grayscale(noise.convert("RGB")), 0.06)
    return grey.rotate(rng.uniform(-0.6, 0.6), expand=False, fillcolor=255)


def photographed(picture: Image.Image, seed: int) -> Image.Image:
    """The page as a phone photographs it on a desk: turned, lit unevenly, a little soft, no
    larger than the API reads it."""
    rng = random.Random(seed)
    width, height = picture.size
    desk_colour = (88, 76, 64)
    desk = Image.new("RGB", (int(width * 1.12), int(height * 1.1)), desk_colour)
    turned = picture.convert("RGB").rotate(
        rng.uniform(-3.0, 3.0), expand=True, fillcolor=desk_colour
    )
    desk.paste(turned, ((desk.width - turned.width) // 2, (desk.height - turned.height) // 2))
    # The light falls from one side: darker by a fifth at the far edge.
    light = Image.linear_gradient("L").rotate(rng.choice((0, 90, 180, 270))).resize(desk.size)
    light = light.point(lambda value: 205 + value // 5).convert("RGB")
    lit = ImageChops.multiply(desk, light).filter(ImageFilter.GaussianBlur(0.7))
    lit.thumbnail((PHOTO_SIDE, PHOTO_SIDE), Image.Resampling.LANCZOS)
    return lit


def render(cases: list[tuple[int, dict[str, Any]]], out: Path) -> None:
    """Each case's three documents in ``out``; a case's seed is its place in the golden set."""
    # Installed apart, for this script only: the workspace does not need a browser.
    from playwright.sync_api import sync_playwright  # noqa: PLC0415

    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        # A4 is 794 by 1123 CSS pixels; drawn at 150 dots an inch.
        page = browser.new_page(
            viewport={"width": 794, "height": 1123}, device_scale_factor=PAGE[0] / 794
        )
        for seed, case in cases:
            name = case["name"]
            page.set_content(page_html(case["fields"], case["layout"]))
            page.pdf(path=str(out / f"{name}.pdf"), format="A4", print_background=True)
            shot = Image.open(io.BytesIO(page.screenshot(full_page=False))).resize(PAGE)
            scanned(shot, seed).save(out / f"{name}.scan.pdf", "PDF", resolution=150.0)
            photographed(shot, seed).save(out / f"{name}.jpg", "JPEG", quality=82)
            print(f"rendered {name}")
        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DOCUMENTS)
    parser.add_argument("--only", nargs="*", help="the names of the cases to render")
    arguments = parser.parse_args(argv)
    cases = list(enumerate(yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"]))
    if arguments.only:
        cases = [(seed, case) for seed, case in cases if case["name"] in arguments.only]
    render(cases, arguments.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
