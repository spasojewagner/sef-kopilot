"""The official documents the SRB-CIUS rules are authored from.

Every rule cites one or more passages of these documents (:class:`~einvoice_core.srb.rule.
Reference`), so that an explanation can quote the text a requirement comes from and a reader
can check it. The versions are the ones the rules were written against; a newer version of a
document means reviewing every rule that cites it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = ["SOURCES", "Source"]


@dataclass(frozen=True)
class Source:
    """An official document, as published."""

    title: str
    version: str
    publisher: str
    url: str | None


SOURCES: Final[dict[str, Source]] = {
    "srb-cius": Source(
        title=(
            "Specifikacija prilagođene primene standarda EN 16931-1 za elektronske fakture u "
            "unutrašnjem prometu u Republici Srbiji"
        ),
        version="06.06.2025",
        publisher="Ministarstvo finansija Republike Srbije",
        url=(
            "https://www.efaktura.gov.rs/tekst/en/5370/updated-specification-for-the-adapted-"
            "implementation-of-the-en-16931-1-standard-for-electronic-invoices-in-domestic-"
            "trade-in-the-republic-of-serbia.php"
        ),
    ),
    "tax-categories": Source(
        title="Poreske kategorije i šifre od 1. septembra 2024.",
        version="01.09.2024",
        publisher="Ministarstvo finansija Republike Srbije",
        url="https://efaktura.gov.rs/tekst/1382/poreske-kategorije-za-elektronske-fakture.php",
    ),
    "pib-rulebook": Source(
        title="Pravilnik o poreskom identifikacionom broju",
        version="Službeni glasnik RS, br. 57/2003, 68/2003, 32/2009, 48/2010 i 44/2018",
        publisher="Ministarstvo finansija Republike Srbije",
        url=None,
    ),
}
