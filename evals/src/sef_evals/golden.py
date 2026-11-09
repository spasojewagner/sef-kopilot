"""The golden set of documents: what each document of the corpus must get from the validator.

``evals/golden/documents.yaml`` names the documents in groups, each by globs from the
repository's root, with the profile they are judged by, whether they must be accepted or
rejected, and the rules that must be among those reported. ``reports: header`` takes the rules
from the line ``The srb profile reports: ...`` that ``scripts/make_fixtures.py`` writes at the
top of each mutation, which states the mistake the mutation was made to have.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from einvoice_core.pipeline import PROFILES

__all__ = ["Case", "Expect", "GoldenError", "load_cases", "reported_in_header"]

#: Whether a document must be accepted or rejected.
Expect = Literal["accept", "reject"]

_HEADER = re.compile(r"^\s*The srb profile reports: (?P<rules>.+)\.\s*$", re.MULTILINE)
_REPORTED = re.compile(r"(?P<rule>[A-Z][A-Z0-9-]*)(?: \((?P<count>[1-9][0-9]*)\))?")


class GoldenError(Exception):
    """The golden set is not what its file must be; the message says where and why."""


@dataclass(frozen=True)
class Case:
    """One document, judged under one profile: what it must get."""

    document: str
    group: str
    profile: str
    expect: Expect
    #: The rules that must be among those reported, each as often as it is counted here.
    reports: Counter[str]

    @property
    def id(self) -> str:
        """The case's name in a report: the document, and the profile it is judged by."""
        return f"{self.document} [{self.profile}]"


class _Group(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    title: str = Field(min_length=1)
    documents: tuple[str, ...] = Field(min_length=1)
    exclude: tuple[str, ...] = ()
    profile: str
    expect: Expect
    reports: tuple[str, ...] | Literal["header"] = ()
    why: str | None = None

    @field_validator("documents", "exclude", mode="before")
    @classmethod
    def _listed(cls, value: object) -> object:
        return (value,) if isinstance(value, str) else value

    @field_validator("profile")
    @classmethod
    def _known(cls, value: str) -> str:
        if value not in PROFILES:
            raise ValueError(f"unknown profile {value!r}; choose one of {', '.join(PROFILES)}")
        return value


class _Golden(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    groups: tuple[_Group, ...] = Field(min_length=1)


def reported_in_header(text: str) -> Counter[str]:
    """The rules a mutation's header says the srb profile reports, with how often."""
    match = _HEADER.search(text)
    if match is None:
        raise GoldenError("no line 'The srb profile reports: ...' in the document's header")
    reported: Counter[str] = Counter()
    for item in match["rules"].split(", "):
        named = _REPORTED.fullmatch(item)
        if named is None:
            raise GoldenError(f"cannot read {item!r} as a rule and its count")
        reported[named["rule"]] += int(named["count"] or 1)
    return reported


def _matched(root: Path, patterns: Sequence[str], group: str) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        paths = sorted(root.glob(pattern))
        if not paths:
            raise GoldenError(f"group {group}: {pattern!r} names no document")
        found += [path.relative_to(root).as_posix() for path in paths if path.is_file()]
    return found


def _cases(root: Path, group: _Group) -> list[Case]:
    excluded = set(_matched(root, group.exclude, group.name))
    cases = []
    for document in dict.fromkeys(_matched(root, group.documents, group.name)):
        if document in excluded:
            continue
        if group.reports == "header":
            text = (root / document).read_text(encoding="utf-8", errors="replace")
            try:
                reports = reported_in_header(text)
            except GoldenError as error:
                raise GoldenError(f"group {group.name}: {document}: {error}") from None
        else:
            reports = Counter(group.reports)
        cases.append(Case(document, group.name, group.profile, group.expect, reports))
    return cases


def load_cases(root: Path, path: Path) -> list[Case]:
    """Every case of the golden set in ``path``, its documents found under ``root``."""
    try:
        golden = _Golden.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as error:
        raise GoldenError(f"{path.name}: {error}") from None
    cases: list[Case] = []
    seen: set[str] = set()
    for group in golden.groups:
        for case in _cases(root, group):
            if case.id in seen:
                raise GoldenError(f"group {group.name}: {case.id} is already in another group")
            seen.add(case.id)
            cases.append(case)
    return cases
