"""The rules a profile applies, as data: each one's id, severity and statement (ADR-0047).

A validation reports the rules an invoice breaks; an assistant, a person writing an invoice or
an explanation also needs the rules it has not broken, to look one up by its id or find those
about a subject. The catalogue lists them, profile by profile, from where the validator gets
them:

- the Schematron rules are read from the published rule sets the profile runs, CEN's compiled
  XSLT and Peppol's Schematron sources alike, so that the catalogue says what the validator
  checks, in the words the rule set reports, and is never a copy to keep up to date;
- the calculation rules (``BR-CO-10`` to ``BR-CO-17``) are the arithmetic layer's, which
  replaces CEN's under the same ids (ADR-0007);
- the SRB-CIUS rules are ours, with the business terms they concern.

A rule the profile sets aside whatever the document holds is listed with why, and with what
checks the matter instead; one set aside only in some places of a document is listed as it is.
"""

from __future__ import annotations

import functools
import re
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Final, Literal

from lxml import etree
from pydantic import BaseModel, ConfigDict, Field

from einvoice_core import srb
from einvoice_core.arithmetic import STATEMENTS
from einvoice_core.pipeline import PROFILES, SetAside
from einvoice_core.rulesets import ruleset_path, rulesets_dir
from einvoice_core.schematron import RULE_SETS, SVRL
from einvoice_core.violations import Severity

__all__ = ["CatalogueRule", "catalogue", "search"]

#: The namespaces a rule set's assertions are written in.
_SCH: Final = "http://purl.oclc.org/dsdl/schematron"
_XSL: Final = "http://www.w3.org/1999/XSL/Transform"
#: An assertion's id as its text begins with it, ``[BR-01]-``.
_PREFIX: Final = re.compile(r"^\s*\[[^\]]+\]\s*-?\s*")
#: A business term or group of EN 16931, as a statement names it.
_TERM: Final = re.compile(r"\b(B[TG]-\d+)\b")
#: A trusted file read as data: no entity, no network, no DTD.
_PARSER: Final = etree.XMLParser(
    resolve_entities=False, no_network=True, load_dtd=False, huge_tree=True
)


class CatalogueRule(BaseModel):
    """One rule a profile applies, or sets aside."""

    model_config = ConfigDict(frozen=True)

    id: str
    layer: Literal["schematron", "srb-cius", "arithmetic"]
    severity: Severity
    statement: str = Field(description="What the rule requires, as its violation states it.")
    source: str = Field(
        description="Where the rule comes from: a Schematron rule set, `srb-cius` or `arithmetic`."
    )
    terms: tuple[str, ...] = Field(
        description="The EN 16931 business terms and groups the rule concerns or names."
    )
    set_aside: str | None = Field(
        default=None, description="Why the profile does not apply the rule, if it does not."
    )
    replaced_by: tuple[str, ...] = Field(
        default=(), description="The rules that check the matter instead, if it is set aside."
    )


def catalogue(profile: str = "srb", *, root: Path | None = None) -> tuple[CatalogueRule, ...]:
    """Every rule ``profile`` applies, or sets aside, in the order of their ids; the rule sets
    are read from ``root`` (the fetched ``third_party/`` by default). :class:`ValueError` for an
    unknown profile, :class:`~einvoice_core.rulesets.RulesetNotFoundError` for a rule set that
    has not been fetched."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; choose one of {', '.join(PROFILES)}")
    return _catalogue(profile, rulesets_dir() if root is None else root)


@functools.cache
def _catalogue(profile: str, root: Path) -> tuple[CatalogueRule, ...]:
    chosen = PROFILES[profile]
    found: dict[str, CatalogueRule] = {}
    for name in chosen.rule_sets:
        rule_set = RULE_SETS[name]
        path = ruleset_path(rule_set.package, root=root) / rule_set.path
        for rule in _assertions(path, name):
            # The first of a rule's assertions states it; the others check it elsewhere.
            found.setdefault(rule.id, rule)
    for rule_id, statement in STATEMENTS.items():
        found[rule_id] = CatalogueRule(
            id=rule_id,
            layer="arithmetic",
            severity=Severity.FATAL,
            statement=statement,
            source="arithmetic",
            terms=_terms(statement),
        )
    if chosen.srb_rules:
        for srb_rule in srb.RULES:
            found[srb_rule.id] = CatalogueRule(
                id=srb_rule.id,
                layer="srb-cius",
                severity=srb_rule.severity,
                statement=srb_rule.title,
                source="srb-cius",
                terms=tuple(dict.fromkeys((*srb_rule.terms, *_terms(srb_rule.title)))),
            )
    for set_aside in chosen.set_aside:
        for rule_id in _always(set_aside):
            published = found.get(rule_id)
            # A calculation rule is recomputed under its own id: the arithmetic layer's stands.
            if published is not None and published.layer == "schematron":
                found[rule_id] = published.model_copy(
                    update={"set_aside": set_aside.reason, "replaced_by": set_aside.replaced_by}
                )
    # The published ids are padded (BR-01, SRB-001): their order as text is their numbers'.
    return tuple(found[rule_id] for rule_id in sorted(found))


def _always(set_aside: SetAside) -> Iterable[str]:
    """The rules ``set_aside`` sets aside whatever the document holds."""
    if set_aside.rule_ids is None or set_aside.when is not None:
        return ()
    return set_aside.rule_ids


def _assertions(path: Path, source: str) -> Iterator[CatalogueRule]:
    """The assertions of a rule set: a Schematron source (``assert``, ``report``, with their id
    and flag as attributes) or the XSLT compiled from one (``svrl:failed-assert``,
    ``svrl:successful-report``, with ``xsl:attribute`` children)."""
    root = etree.parse(str(path), _PARSER).getroot()
    for element in root.iter(
        f"{{{_SCH}}}assert",
        f"{{{_SCH}}}report",
        f"{{{SVRL}}}failed-assert",
        f"{{{SVRL}}}successful-report",
    ):
        rule_id, flag = element.get("id"), element.get("flag")
        for attribute in element.iterchildren(f"{{{_XSL}}}attribute"):
            if attribute.get("name") == "id":
                rule_id = (attribute.text or "").strip()
            elif attribute.get("name") == "flag":
                flag = (attribute.text or "").strip()
        if not rule_id:
            continue
        text = element.find(f"{{{SVRL}}}text")
        written = "".join((element if text is None else text).itertext())
        statement = _PREFIX.sub("", " ".join(written.split()))
        yield CatalogueRule(
            id=rule_id,
            layer="schematron",
            # As the validator reads a report: an assertion without a flag states a requirement.
            severity=Severity.WARNING if flag == "warning" else Severity.FATAL,
            statement=statement,
            source=source,
            terms=_terms(statement),
        )


def _terms(statement: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_TERM.findall(statement)))


def search(rules: Iterable[CatalogueRule], query: str, *, limit: int = 20) -> list[CatalogueRule]:
    """The rules ``query`` names, at most ``limit``: by id first (``BR-CO-15``, or a prefix of
    ids, ``BR-CO``), then those that concern a business term it names (``BT-31``), then those
    whose statement holds every word of it, case and diacritics aside."""
    wanted = query.strip().casefold()
    words = _words(wanted)
    if not words:
        return []
    listed = list(rules)
    by_id = [rule for rule in listed if rule.id.casefold() == wanted]
    by_id += [
        rule
        for rule in listed
        if rule.id.casefold().startswith(wanted) and rule.id.casefold() != wanted
    ]
    terms = {word.upper() for word in words if _TERM.fullmatch(word.upper())}
    by_term = [rule for rule in listed if terms and terms <= set(rule.terms)]
    by_words = [
        rule
        for rule in listed
        if all(word in _words(f"{rule.id} {rule.statement}") for word in words)
        or all(word in _folded(rule.statement) for word in words)
    ]
    # Within each way, the Serbian rules first: where they apply, they are the most specific.
    found = dict.fromkeys(
        _serbian_first(by_id) + _serbian_first(by_term) + _serbian_first(by_words)
    )
    return list(found)[:limit]


def _serbian_first(rules: list[CatalogueRule]) -> list[CatalogueRule]:
    return sorted(rules, key=lambda rule: rule.layer != "srb-cius")


@functools.lru_cache(maxsize=4096)
def _folded(text: str) -> str:
    """``text`` in lower case, with its letters' diacritics taken off (``č`` reads ``c``)."""
    decomposed = unicodedata.normalize("NFKD", text.casefold()).replace("đ", "dj")
    return "".join(character for character in decomposed if not unicodedata.combining(character))


@functools.lru_cache(maxsize=4096)
def _words(text: str) -> tuple[str, ...]:
    """The words of ``text``, folded; a catalogue's statements are folded once."""
    return tuple(re.findall(r"[\w-]+", _folded(text)))
