"""``sef-evals``: run the evaluations, write their report, or check it (ADR-0054 to ADR-0056).

    sef-evals               # measure, print the table, write evals/reports/latest.{json,md}
    sef-evals --check       # measure, and fail if a threshold is not met or the report is stale
    sef-evals --record      # ask the real model what the cassettes lack, then measure and write
    sef-evals --unlabelled  # list the passages retrieval finds that no label names

Run from the repository or below it: the root is the nearest directory up that holds
``evals/thresholds.yaml``. The validator needs the fetched rule sets (``make rulesets``); the
explanations, a PostgreSQL server for a database of their own (``SEF_TEST_DATABASE_URL``,
``make up``). The explanations and the repairs are written with the model's answers recorded
in ``evals/cassettes/``, offline; ``--record`` asks the model the settings name
(``LLM_PROVIDER`` and its key, Groq's free tier for the committed cassettes) only what the
cassettes do not hold.

Exit status: 0 when every threshold is met (and, with ``--check``, the committed report is what
the run gives); 1 when one is not, the report is stale, or a recording stopped at the
provider's limit; 2 for a file that cannot be read, rule sets that have not been fetched, no
database server, or no model to record with.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TextIO

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from einvoice_core.rulesets import RulesetNotFoundError
from sef_api.llm import LLMClient, client_for
from sef_evals import __version__, explanations, repairs, verdicts
from sef_evals.cassettes import (
    Cassette,
    CassetteError,
    Recording,
    RecordingStoppedError,
    Replaying,
)
from sef_evals.database import DatabaseError, corpus_database, server_url
from sef_evals.golden import GoldenError, load_cases
from sef_evals.measures import Measure
from sef_evals.report import (
    BADGE_NAME,
    JSON_NAME,
    MARKDOWN_NAME,
    as_badge,
    as_json,
    as_markdown,
    versions,
)
from sef_evals.thresholds import ThresholdError, judge, load_thresholds

__all__ = ["EXIT_ERROR", "EXIT_MET", "EXIT_NOT_MET", "main"]

EXIT_MET: Final = 0
EXIT_NOT_MET: Final = 1
EXIT_ERROR: Final = 2

THRESHOLDS: Final = Path("evals/thresholds.yaml")
DOCUMENTS: Final = Path("evals/golden/documents.yaml")
EXPLANATIONS: Final = Path("evals/golden/explanations.yaml")
REPAIRS: Final = Path("evals/golden/repairs.yaml")
#: The model's recorded answers, by what they answer: one cassette each, reviewed apart.
CASSETTES: Final = {
    "explanations": Path("evals/cassettes/explanations.json"),
    "repairs": Path("evals/cassettes/repairs.json"),
}
REPORTS: Final = Path("evals/reports")
CORPUS: Final = Path("corpus")
#: The model named by a run with no cassette: no answer is recorded.
NOT_RECORDED: Final = "none recorded"
#: Seconds between two requests to the real model while recording, under a free tier's limits,
#: and how long an answer of 429 is waited for before the request is sent again.
PAUSE = 2.0
PATIENCE = 60.0


def find_root(start: Path) -> Path | None:
    """The nearest directory from ``start`` up that holds ``evals/thresholds.yaml``."""
    for directory in (start, *start.parents):
        if (directory / THRESHOLDS).is_file():
            return directory
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sef-evals",
        description="Measure SEF Kopilot on its golden sets and judge the measures against "
        "evals/thresholds.yaml.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="write nothing; fail if a threshold is not met or evals/reports is stale",
    )
    mode.add_argument(
        "--record",
        action="store_true",
        help="ask the model of the settings what the cassette does not hold, and keep it",
    )
    mode.add_argument(
        "--unlabelled",
        action="store_true",
        help="list the passages retrieval finds for the golden documents that no label names",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _stale(root: Path, written: dict[str, str]) -> list[str]:
    """The report's files that are not what the run gives."""
    return [
        (REPORTS / name).as_posix()
        for name, text in written.items()
        if not (root / REPORTS / name).is_file()
        or (root / REPORTS / name).read_text(encoding="utf-8") != text
    ]


class _ModelSettings(BaseSettings):
    """The model to record with, as the API's settings name it, and nothing else of them: a
    developer's ``.env`` is read for these names only."""

    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: str = Field(default="none", alias="LLM_PROVIDER")
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    llm_model: str | None = Field(default=None, alias="SEF_LLM_MODEL")


def model_named_in(env_file: Path) -> LLMClient | None:
    """The model ``LLM_PROVIDER``, its key and ``SEF_LLM_MODEL`` name, from the environment or
    ``env_file``, as the API would ask it; None when they name none."""
    named = _ModelSettings(_env_file=env_file)  # type: ignore[call-arg]
    keys = {
        "groq": named.groq_api_key,
        "openai": named.openai_api_key,
        "anthropic": named.anthropic_api_key,
    }
    return client_for(named.llm_provider, keys.get(named.llm_provider), named.llm_model)


@dataclass(frozen=True)
class _Golden:
    explanations: explanations.ExplanationGolden
    repairs: repairs.RepairGolden


async def _measured(
    root: Path,
    golden: _Golden,
    server: str,
    models: Mapping[str, LLMClient],
    progress: Callable[[str], None] | None,
) -> list[Measure]:
    """The model's measures: the explanations, on a database of their own, then the repairs."""
    async with corpus_database(server, root / CORPUS) as database:
        asked = await explanations.explain(
            root, golden.explanations, database, models["explanations"], progress=progress
        )
        measures = await explanations.measure(golden.explanations, database, asked)
    tried = await repairs.repair(root, golden.repairs, models["repairs"], progress=progress)
    return measures + repairs.measure(tried)


async def _list_unlabelled(
    root: Path, golden: explanations.ExplanationGolden, server: str, out: TextIO
) -> None:
    async with corpus_database(server, root / CORPUS) as database:
        found = await explanations.unlabelled(root, golden, database)
    for rule, passages in found.items():
        print(rule, file=out)
        for passage in passages:
            heading = f" {passage.heading}" if passage.heading else ""
            text = " ".join(passage.text.split())[:120]
            print(f"  {passage.id}\n    {passage.label}{heading}: {text}", file=out)
    if not found:
        print("Every passage retrieval finds is labelled.", file=out)


class _UsageError(Exception):
    """What the command cannot do, said to the person who ran it; ends with exit status 2."""


def _replaying(cassettes: dict[str, Cassette | None]) -> dict[str, LLMClient]:
    # A replayed request that has no answer is a measure, not a warning to print.
    logging.getLogger("sef_api").setLevel(logging.ERROR)
    return {
        name: Replaying(cassette or Cassette(NOT_RECORDED)) for name, cassette in cassettes.items()
    }


def _recorded_model(cassettes: dict[str, Cassette | None]) -> str | None:
    """The model whose answers the cassettes hold, as a report names it; None for none."""
    models = sorted({cassette.model for cassette in cassettes.values() if cassette is not None})
    return " and ".join(models) or None


def _tell(asking: str) -> None:
    sys.stderr.write(f"sef-evals: asking about {asking}\n")
    sys.stderr.flush()


def _report(
    root: Path, measures: list[Measure], model: str | None, check: bool, out: TextIO
) -> int:
    """Judge ``measures``, print and write the report, or check the written one."""
    judgements = judge(measures, load_thresholds(root / THRESHOLDS))
    measured = versions(root) | {"model": model}
    written = {
        JSON_NAME: as_json(judgements, measured),
        MARKDOWN_NAME: as_markdown(judgements, measured),
        BADGE_NAME: as_badge(judgements),
    }
    out.write(written[MARKDOWN_NAME])
    met = all(judgement.met is not False for judgement in judgements)
    stale = _stale(root, written) if check else []
    if stale:
        print(f"\nsef-evals: the report is stale, run `make evals`: {', '.join(stale)}", file=out)
    if not check:
        (root / REPORTS).mkdir(parents=True, exist_ok=True)
        for name, text in written.items():
            (root / REPORTS / name).write_text(text, encoding="utf-8", newline="\n")
    if not met:
        print("\nsef-evals: a threshold is not met", file=out)
    return EXIT_MET if met and not stale else EXIT_NOT_MET


def _run(
    root: Path, args: argparse.Namespace, out: TextIO, model: Callable[[], LLMClient | None]
) -> int:
    load_thresholds(root / THRESHOLDS)  # a file that cannot be read stops the run first
    golden = _Golden(
        explanations.load_golden(root / EXPLANATIONS), repairs.load_golden(root / REPAIRS)
    )
    server = server_url(root / ".env")
    if args.unlabelled:
        asyncio.run(_list_unlabelled(root, golden.explanations, server, out))
        return EXIT_MET
    cassettes = {
        name: Cassette.load(root / path) if (root / path).is_file() else None
        for name, path in CASSETTES.items()
    }
    measures = verdicts.measure(root, load_cases(root, root / DOCUMENTS))
    if not args.record:
        measures += asyncio.run(_measured(root, golden, server, _replaying(cassettes), None))
        return _report(root, measures, _recorded_model(cassettes), args.check, out)
    return _record(
        root,
        args,
        out,
        golden=golden,
        server=server,
        cassettes=cassettes,
        measures=measures,
        model=model,
    )


def _record(
    root: Path,
    args: argparse.Namespace,
    out: TextIO,
    *,
    golden: _Golden,
    server: str,
    cassettes: dict[str, Cassette | None],
    measures: list[Measure],
    model: Callable[[], LLMClient | None],
) -> int:
    """Ask the real model what the cassettes lack, keep its answers, then report."""
    real = model()
    if real is None:
        raise _UsageError("set LLM_PROVIDER and its key (GROQ_API_KEY, say) to record")
    recordings = {
        name: Recording(real, cassette, pause=PAUSE, patience=PATIENCE)
        for name, cassette in cassettes.items()
    }

    async def measured() -> list[Measure]:
        try:
            return await _measured(root, golden, server, recordings, _tell)
        finally:
            await real.aclose()

    try:
        measures += asyncio.run(measured())
    except RecordingStoppedError as error:
        for name, recording in recordings.items():
            recording.cassette(finished=False).save(root / CASSETTES[name])
        print(f"sef-evals: {error}; what was recorded is kept in evals/cassettes/", file=out)
        return EXIT_NOT_MET
    for name, recording in recordings.items():
        recording.cassette(finished=True).save(root / CASSETTES[name])
    asked = sum(recording.asked for recording in recordings.values())
    print(f"sef-evals: {asked} requests to {real.model}\n", file=out)
    return _report(root, measures, real.model, args.check, out)


def main(
    argv: Sequence[str] | None = None,
    *,
    cwd: Path | None = None,
    out: TextIO | None = None,
    model: Callable[[Path], LLMClient | None] = model_named_in,
) -> int:
    """Run the command line; returns the exit status. ``model`` gives the model to record
    with, named in the environment or the ``.env`` file it is given."""
    args = _parser().parse_args(argv)
    out = out or sys.stdout
    root = find_root((cwd or Path.cwd()).resolve())
    if root is None:
        print(f"sef-evals: no {THRESHOLDS.as_posix()} here or above", file=out)
        return EXIT_ERROR
    try:
        return _run(root, args, out, lambda: model(root / ".env"))
    except (GoldenError, ThresholdError, DatabaseError, CassetteError, _UsageError) as error:
        print(f"sef-evals: {error}", file=out)
    except RulesetNotFoundError as error:
        print(f"sef-evals: {error} (run `make rulesets`)", file=out)
    return EXIT_ERROR


def console() -> None:
    """The ``sef-evals`` entry point."""
    raise SystemExit(main())
