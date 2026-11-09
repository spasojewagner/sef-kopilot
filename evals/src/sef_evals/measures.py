"""What an evaluation measures: a count of cases, and the cases that count against it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["Kind", "Measure"]

#: ``share``: the share of cases that have the property, higher is better (agreement).
#: ``rate``: the share of cases that fail it, lower is better (false accepts).
Kind = Literal["share", "rate"]


@dataclass(frozen=True)
class Measure:
    """One metric over ``total`` cases, of which those in ``failures`` lack its property.

    ``failures`` names each such case with what went wrong, so that a report says which
    documents to look at, not only how many.
    """

    name: str
    title: str
    kind: Kind
    total: int
    failures: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 <= len(self.failures) <= self.total:
            raise ValueError(f"{self.name}: {len(self.failures)} failures of {self.total} cases")

    @property
    def passed(self) -> int:
        return self.total - len(self.failures)

    @property
    def value(self) -> float | None:
        """The share (or the rate), from 0 to 1; None when there was no case to count."""
        if not self.total:
            return None
        counted = self.passed if self.kind == "share" else len(self.failures)
        return counted / self.total
