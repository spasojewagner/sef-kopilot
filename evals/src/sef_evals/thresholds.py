"""The thresholds the measures must meet (``evals/thresholds.yaml``), and the judgement."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, RootModel, ValidationError, model_validator

from sef_evals.measures import Measure

__all__ = ["Judgement", "Threshold", "ThresholdError", "judge", "load_thresholds"]


class ThresholdError(Exception):
    """The thresholds' file is not what it must be; the message says where and why."""


class Threshold(BaseModel):
    """At least ``min``, or at most ``max``, of a measure's value, from 0 to 1."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min: float | None = Field(default=None, ge=0, le=1)
    max: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def _one(self) -> Threshold:
        if (self.min is None) == (self.max is None):
            raise ValueError("a threshold is either min or max")
        return self

    def met_by(self, value: float) -> bool:
        if self.min is not None:
            return value >= self.min
        return self.max is not None and value <= self.max

    def __str__(self) -> str:
        return f"≥ {self.min:.0%}" if self.min is not None else f"≤ {self.max:.0%}"


class _Thresholds(RootModel[dict[str, Threshold]]):
    pass


def load_thresholds(path: Path) -> dict[str, Threshold]:
    """The thresholds in ``path``, by the name of the measure each holds."""
    try:
        loaded = _Thresholds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as error:
        raise ThresholdError(f"{path.name}: {error}") from None
    return loaded.root


@dataclass(frozen=True)
class Judgement:
    """A measure beside its threshold, or a threshold whose measure was not taken."""

    name: str
    measure: Measure | None
    threshold: Threshold | None

    @property
    def met(self) -> bool | None:
        """Whether the threshold is met; None for a measure that has no threshold."""
        if self.threshold is None:
            return None
        if self.measure is None or self.measure.value is None:
            return False
        return self.threshold.met_by(self.measure.value)


def judge(measures: Sequence[Measure], thresholds: Mapping[str, Threshold]) -> list[Judgement]:
    """Each measure with its threshold, in the measures' order, then each threshold whose
    measure was not taken, which is not met."""
    taken = {measure.name for measure in measures}
    return [Judgement(m.name, m, thresholds.get(m.name)) for m in measures] + [
        Judgement(name, None, threshold)
        for name, threshold in thresholds.items()
        if name not in taken
    ]
