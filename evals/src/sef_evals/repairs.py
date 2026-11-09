"""The repairs' evaluations: invoices the model may repair, and invoices only a person may
(ADR-0056).

``evals/golden/repairs.yaml`` names two kinds of case, each an invoice and what must become of
it when the model is asked for a repair, as the API asks it:

- ``repaired``: a held-out invoice, made at run time from a synthetic one by the edits the case
  names, whose mistake a repair may fix from what the invoice and the violations say; after the
  model's rounds, the validator must accept it;
- ``refused``: an invoice whose mistake a person decides: in a field the guard keeps for a
  person (an amount, the VAT, a tax or company identifier, a date), or one whose right value
  neither the invoice nor the violations give (the invoice's type); no repair may leave the
  validator accepting it.

``repair_success`` is the share of the first kind repaired (the brief's 80 %);
``overreach_rate`` the share of the second kind that a repair made pass all the same, by any
way round the guard (none may).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from einvoice_core.patches import Patch
from einvoice_core.violations import Severity
from sef_api.invoices.validation import Patched, patched_outcome
from sef_api.llm import Language, LLMClient
from sef_api.repairs.repairer import Repairer, RepairError
from sef_evals.golden import GoldenError
from sef_evals.measures import Measure

__all__ = ["RepairCase", "RepairGolden", "Tried", "document_of", "load_golden", "measure", "repair"]

Expect = Literal["repaired", "refused"]

#: The most elements an invoice of the golden set may have, as the API allows by default.
_MAX_ELEMENTS: Final = 20_000
#: Seconds the rounds of one repair may take: the real model is slow and waits for its limits.
_SECONDS: Final = 600.0


class RepairCase(BaseModel):
    """An invoice, how it is made, and what must become of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    document: str
    mistake: str = Field(min_length=1)
    edits: tuple[tuple[str, str], ...] = ()
    expect: Expect


class RepairGolden(BaseModel):
    """The golden set of the repairs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    language: Language
    cases: tuple[RepairCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _named_once(self) -> RepairGolden:
        names = [case.name for case in self.cases]
        if twice := sorted({name for name in names if names.count(name) > 1}):
            raise ValueError(f"cases named more than once: {', '.join(twice)}")
        return self


def load_golden(path: Path) -> RepairGolden:
    try:
        return RepairGolden.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as error:
        raise GoldenError(f"{path.name}: {error}") from None


def document_of(root: Path, case: RepairCase) -> bytes:
    """The case's invoice: its document with its edits made, each where it occurs once."""
    try:
        text = (root / case.document).read_text(encoding="utf-8")
    except OSError as error:
        raise GoldenError(f"repairs: {case.name}: {error}") from None
    for old, new in case.edits:
        if (count := text.count(old)) != 1:
            raise GoldenError(f"repairs: {case.name}: {old!r} occurs {count} times, not once")
        text = text.replace(old, new)
    return text.encode("utf-8")


@dataclass(frozen=True)
class Tried:
    """A case, and the invoice its repair left, or why there was no repair."""

    case: RepairCase
    patched: Patched | None
    problem: str | None

    @property
    def accepted(self) -> bool:
        """Whether the validator accepts the invoice the repair left."""
        return self.patched is not None and self.patched.validation.report.valid

    def outcome(self) -> str:
        """What came of the repair, as a report names it."""
        if self.patched is None:
            return f"no repair: {self.problem}"
        report = self.patched.validation.report
        if report.valid:
            return "the validator accepts the invoice the repair left"
        fatal = sorted({v.rule_id for v in report.violations if v.severity is Severity.FATAL})
        decided = sum(1 for outcome in self.patched.outcomes if outcome.status == "needs-decision")
        return f"{', '.join(fatal)} left, {decided} patches for a person to decide"


async def repair(
    root: Path,
    golden: RepairGolden,
    llm: LLMClient,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[Tried]:
    """Each case's invoice, repaired by ``llm`` as the API repairs a stored invoice: the
    validator applies the patches in this process instead of a child's. ``progress`` is told
    each case in turn."""
    repairer = Repairer(llm)
    tried: list[Tried] = []
    for case in golden.cases:
        if progress is not None:
            progress(f"the repair of {case.name}")
        content = document_of(root, case)

        async def apply(
            patches: Sequence[Patch], content: bytes = content, case: RepairCase = case
        ) -> Patched:
            status, result = patched_outcome(
                content, "srb", patches, max_elements=_MAX_ELEMENTS, fields=True
            )
            if status != "patched":
                raise GoldenError(f"repairs: {case.name}: the invoice cannot be patched: {result}")
            return Patched.model_validate_json(result)

        try:
            suggestion = await repairer.suggest(apply, language=golden.language, seconds=_SECONDS)
        except RepairError as error:
            tried.append(Tried(case, None, str(error)))
        else:
            tried.append(Tried(case, suggestion.patched, None))
    return tried


def measure(tried: Sequence[Tried]) -> list[Measure]:
    """The repairs' measures on what was ``tried``."""
    to_repair = [t for t in tried if t.case.expect == "repaired"]
    to_refuse = [t for t in tried if t.case.expect == "refused"]
    return [
        Measure(
            name="repair_success",
            title="Held-out invoices that a repair leaves the validator accepting",
            kind="share",
            total=len(to_repair),
            failures=tuple(f"{t.case.name}: {t.outcome()}" for t in to_repair if not t.accepted),
        ),
        Measure(
            name="overreach_rate",
            title="Invoices with a mistake a person decides, that a repair made pass",
            kind="rate",
            total=len(to_refuse),
            failures=tuple(f"{t.case.name}: {t.outcome()}" for t in to_refuse if t.accepted),
        ),
    ]
