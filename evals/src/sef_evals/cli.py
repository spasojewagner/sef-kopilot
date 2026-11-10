"""``sef-evals``: run the evaluations, write their report, or check it (ADR-0054, ADR-0055).

    sef-evals               # measure, print the table, write evals/reports/latest.{json,md}
    sef-evals --check       # measure, and fail if a threshold is not met or the report is stale
    sef-evals --record      # ask the real model what the cassette lacks, then measure and write
    sef-evals --unlabelled  # list the passages retrieval finds that no label names

Run from the repository or below it: the root is the nearest directory up that holds
``evals/thresholds.yaml``. The validator needs the fetched rule sets (``make rulesets``); the
explanations, a PostgreSQL server for a database of their own (``SEF_TEST_DATABASE_URL``,
``make up``). They are explained with the answers recorded in
``evals/cassettes/explanations.json``, offline; ``--record`` asks the model the settings name
(``LLM_PROVIDER=groq``, ``GROQ_API_KEY``) only what the cassette does not hold.

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
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final, Literal, TextIO

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from einvoice_core.rulesets import RulesetNotFoundError
from sef_api.llm import GroqClient, LLMClient
from sef_evals import __version__, explanations, verdicts
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
from sef_evals.report import JSON_NAME, MARKDOWN_NAME, as_json, as_markdown, versions
from sef_evals.thresholds import ThresholdError, judge, load_thresholds

__all__ = ["EXIT_ERROR", "EXIT_MET", "EXIT_NOT_MET", "main"]

EXIT_MET: Final = 0
EXIT_NOT_MET: Final = 1
EXIT_ERROR: Final = 2

THRESHOLDS: Final = Path("evals/thresholds.yaml")
DOCUMENTS: Final = Path("evals/golden/documents.yaml")
EXPLANATIONS: Final = Path("evals/golden/explanations.yaml")
CASSETTE: Final = Path("evals/cassettes/explanations.json")
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
    developer's ``.env`` is read for these three names only."""

    model_config = SettingsConfigDict(extra="ignore")

    llm_provider: Literal["none", "groq"] = Field(default="none", alias="LLM_PROVIDER")
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    llm_model: str | None = Field(default=None, alias="SEF_LLM_MODEL")


def model_named_in(env_file: Path) -> LLMClient | None:
    """The model ``LLM_PROVIDER``, ``GROQ_API_KEY`` and ``SEF_LLM_MODEL`` name, from the
    environment or ``env_file``, as the API would ask it; None when they name none."""
    named = _ModelSettings(_env_file=env_file)  # type: ignore[call-arg]
    if named.llm_provider != "groq" or named.groq_api_key is None:
        return None
    return GroqClient(named.groq_api_key, model=named.llm_model or GroqClient.MODEL)


async def _explained(
    root: Path,
    golden: explanations.ExplanationGolden,
    server: str,
    llm: LLMClient,
    progress: Callable[[str], None] | None,
) -> list[Measure]:
    try:
        async with corpus_database(server, root / CORPUS) as database:
            asked = await explanations.explain(root, golden, database, llm, progress=progress)
            return await explanations.measure(golden, database, asked)
    finally:
        await llm.aclose()


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


def _model_to_use(
    record: bool, cassette: Cassette | None, model: Callable[[], LLMClient | None]
) -> tuple[LLMClient, Recording | None]:
    """The model the explanations are asked of: the cassette's, or, recording, the settings'
    one behind the cassette."""
    if not record:
        # A replayed explanation that has no answer is a measure, not a warning to print.
        logging.getLogger("sef_api").setLevel(logging.ERROR)
        return Replaying(cassette or Cassette(NOT_RECORDED)), None
    recorded_with = model()
    if recorded_with is None:
        raise _UsageError("set LLM_PROVIDER=groq and GROQ_API_KEY to record")
    recording = Recording(recorded_with, cassette, pause=PAUSE, patience=PATIENCE)
    return recording, recording


def _tell(asking: str) -> None:
    sys.stderr.write(f"sef-evals: explaining {asking}\n")
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
    golden = explanations.load_golden(root / EXPLANATIONS)
    server = server_url(root / ".env")
    if args.unlabelled:
        asyncio.run(_list_unlabelled(root, golden, server, out))
        return EXIT_MET
    cassette = Cassette.load(root / CASSETTE) if (root / CASSETTE).is_file() else None
    measures = verdicts.measure(root, load_cases(root, root / DOCUMENTS))
    llm, recording = _model_to_use(args.record, cassette, model)
    try:
        measures += asyncio.run(
            _explained(root, golden, server, llm, _tell if recording is not None else None)
        )
    except RecordingStoppedError as error:
        if recording is None:  # pragma: no cover - only a recording stops
            raise
        recording.cassette(finished=False).save(root / CASSETTE)
        print(f"sef-evals: {error}; what was recorded is kept in {CASSETTE.as_posix()}", file=out)
        return EXIT_NOT_MET
    if recording is not None:
        recording.cassette(finished=True).save(root / CASSETTE)
        print(f"sef-evals: {recording.asked} requests to {recording.model}\n", file=out)
        return _report(root, measures, recording.model, args.check, out)
    return _report(root, measures, cassette.model if cassette else None, args.check, out)


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
