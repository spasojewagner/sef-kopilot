"""``sef-evals``: running the evaluations, recording the model, writing the report and
checking it."""

from __future__ import annotations

import io
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from einvoice_core.rulesets import RulesetNotFoundError
from sef_api.llm import LLMClient
from sef_evals import __version__, cli, verdicts
from sef_evals.cassettes import Cassette
from sef_evals.cli import EXIT_ERROR, EXIT_MET, EXIT_NOT_MET, find_root, main, model_named_in
from sef_evals.measures import Measure

from .conftest import REPOSITORY_ROOT, Explaining, needs_database

CASSETTE = Path("evals/cassettes/explanations.json")
REPAIRS = Path("evals/cassettes/repairs.json")
ARTICLE_2 = "pib-rulebook/article-2/2018-10-01"
NOWHERE = "postgresql+asyncpg://nobody@nowhere.invalid/none"


def run(
    root: Path, *argv: str, model: Callable[[], LLMClient | None] = Explaining
) -> tuple[int, str]:
    out = io.StringIO()
    status = main(list(argv), cwd=root, out=out, model=lambda _env_file: model())
    return status, out.getvalue()


def recorded(root: Path) -> Cassette:
    return Cassette.load(root / CASSETTE)


def reject_the_valid_one(root: Path) -> None:
    golden = root / "evals" / "golden" / "documents.yaml"
    golden.write_text(
        golden.read_text(encoding="utf-8").replace("expect: accept", "expect: reject"),
        encoding="utf-8",
    )


def test_finds_the_root_from_below_it(small_root: Path) -> None:
    (small_root / "docs" / "deeper").mkdir()
    assert find_root(small_root / "docs" / "deeper") == small_root
    assert find_root(small_root.parent) is None


def test_says_when_there_is_nothing_to_run(tmp_path: Path) -> None:
    status, out = run(tmp_path)
    assert (status, out) == (EXIT_ERROR, "sef-evals: no evals/thresholds.yaml here or above\n")


def test_says_when_there_is_no_database_server(
    small_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SEF_TEST_DATABASE_URL", raising=False)
    status, out = run(small_root)
    assert status == EXIT_ERROR
    assert out.startswith("sef-evals: SEF_TEST_DATABASE_URL is not set")


@needs_database
def test_records_once_then_replays_offline(small_root: Path) -> None:
    status, out = run(small_root, "--record")
    assert status == EXIT_MET, out
    # One explanation; the repair of the type code in one answer; for the PIB, an answer
    # refused for the value it makes up, then none proposed.
    assert out.startswith("sef-evals: 4 requests to test/explaining\n\n# Evaluation report")
    assert "and the answers of test/explaining recorded in evals/cassettes/." in out
    assert "| `explained` | Rules of the golden documents that the model explained | 100.0%" in out
    assert "| Citations of a passage labelled relevant to the rule | 100.0% (1 of 1) |" in out
    cassette = recorded(small_root)
    assert cassette.model == "test/explaining"
    assert ARTICLE_2 in next(iter(cassette.answers.values()))
    assert len(Cassette.load(small_root / REPAIRS).answers) == 3
    assert (
        "| Held-out invoices that a repair leaves the validator accepting | 100.0% (1 of 1)" in out
    )
    # Replayed, without the model: the same answers, the same report, nothing stale.
    status, out = run(small_root, "--check", model=lambda: None)
    assert (status, out) == (
        EXIT_MET,
        (small_root / "evals/reports/latest.md").read_text(encoding="utf-8"),
    )
    report = json.loads((small_root / "evals/reports/latest.json").read_text("utf-8"))
    assert report["measured"]["model"] == "test/explaining"
    assert report["measures"]["citation_resolution"]["value"] == 1.0


@needs_database
def test_records_only_what_the_cassette_lacks(small_root: Path) -> None:
    run(small_root, "--record")
    model = Explaining()
    status, out = run(small_root, "--record", model=lambda: model)
    assert (status, model.asked) == (EXIT_MET, 0)
    assert out.startswith("sef-evals: 0 requests to test/explaining\n")
    assert model.asked == 0


@needs_database
def test_without_recorded_answers_nothing_is_explained(small_root: Path) -> None:
    status, out = run(small_root)
    assert status == EXIT_NOT_MET
    assert ", with no answer of a language model recorded." in out
    assert "| `explained` | Rules of the golden documents that the model explained | 0.0%" in out
    assert (
        "- docs/srb-009-pib-check-digit.xml [sr] SRB-009: the model gave no answer (no answer "
        "is recorded for this request)"
    ) in out
    assert "| not measured | ≥ 100% | **no** |" in out


def test_needs_a_model_to_record_with(small_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEF_TEST_DATABASE_URL", NOWHERE)
    monkeypatch.setattr(verdicts, "measure", lambda *_: [])
    status, out = run(small_root, "--record", model=lambda: None)
    assert (status, out) == (
        EXIT_ERROR,
        "sef-evals: set LLM_PROVIDER and its key (GROQ_API_KEY, say) to record\n",
    )


@needs_database
def test_a_recording_stopped_by_the_limit_keeps_what_it_has(
    small_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "PAUSE", 0.0)
    monkeypatch.setattr(cli, "PATIENCE", 0.0)
    limited = Explaining(*["Groq answered 429, 3 times"] * 5)
    status, out = run(small_root, "--record", model=lambda: limited)
    assert status == EXIT_NOT_MET
    assert out == (
        "sef-evals: the model answered 429 5 times: its provider's limit is reached; record "
        "again later to continue; what was recorded is kept in evals/cassettes/\n"
    )
    assert recorded(small_root) == Cassette("test/explaining", {})
    assert Cassette.load(small_root / REPAIRS) == Cassette("test/explaining", {})
    assert not (small_root / "evals" / "reports").exists()


@needs_database
def test_lists_the_passages_no_label_names(small_root: Path) -> None:
    status, out = run(small_root, "--unlabelled")
    assert status == EXIT_MET
    assert out.startswith("SRB-009\n  srb-cius/1-3-table-1-bt-31/2025-06-06\n    BT-31 Seller VAT")
    assert ARTICLE_2 not in out


@needs_database
def test_says_when_every_passage_is_labelled(small_root: Path) -> None:
    out = run(small_root, "--unlabelled")[1]
    ids = [line.strip() for line in out.splitlines() if line.startswith("  srb-cius/")]
    golden = small_root / "evals" / "golden" / "explanations.yaml"
    golden.write_text(
        golden.read_text("utf-8") + f"    not_relevant: [{', '.join(ids)}]\n", encoding="utf-8"
    )
    assert run(small_root, "--unlabelled") == (
        EXIT_MET,
        "Every passage retrieval finds is labelled.\n",
    )


@needs_database
def test_a_check_fails_on_a_stale_report_and_writes_nothing(small_root: Path) -> None:
    run(small_root, "--record")
    written = small_root / "evals" / "reports" / "latest.json"
    written.write_text("{}\n", encoding="utf-8")
    status, out = run(small_root, "--check")
    assert status == EXIT_NOT_MET
    assert out.endswith(
        "\nsef-evals: the report is stale, run `make evals`: evals/reports/latest.json\n"
    )
    assert written.read_text(encoding="utf-8") == "{}\n"
    (small_root / "evals" / "reports" / "latest.md").unlink()
    assert run(small_root, "--check")[1].endswith(
        "run `make evals`: evals/reports/latest.json, evals/reports/latest.md\n"
    )


@needs_database
def test_a_check_says_both_when_the_report_is_stale_and_a_threshold_not_met(
    small_root: Path,
) -> None:
    run(small_root, "--record")
    reject_the_valid_one(small_root)
    status, out = run(small_root, "--check")
    assert status == EXIT_NOT_MET
    assert out.endswith(
        "\nsef-evals: the report is stale, run `make evals`: evals/reports/latest.json, "
        "evals/reports/latest.md\n\nsef-evals: a threshold is not met\n"
    )


@needs_database
def test_fails_when_a_threshold_is_not_met(small_root: Path) -> None:
    run(small_root, "--record")
    reject_the_valid_one(small_root)
    status, out = run(small_root)
    assert status == EXIT_NOT_MET
    assert "| Documents that must be rejected, accepted | 50.0% (1 of 2) | ≤ 0% | **no** |" in out
    assert "- docs/srb-minimal-invoice.xml [srb]: accepted" in out
    assert out.endswith("\nsef-evals: a threshold is not met\n")
    # The report is written all the same: it says what failed.
    report = json.loads((small_root / "evals" / "reports" / "latest.json").read_text("utf-8"))
    assert report["met"] is False


@pytest.mark.parametrize(
    ("path", "text", "problem"),
    [
        ("evals/thresholds.yaml", "agreement: {least: 1}\n", "sef-evals: thresholds.yaml: "),
        ("evals/golden/documents.yaml", "groups: []\n", "sef-evals: documents.yaml: "),
        ("evals/golden/explanations.yaml", "rules: {}\n", "sef-evals: explanations.yaml: "),
        (CASSETTE.as_posix(), "{}\n", "sef-evals: explanations.json: "),
    ],
)
def test_refuses_files_it_cannot_read(
    small_root: Path, monkeypatch: pytest.MonkeyPatch, path: str, text: str, problem: str
) -> None:
    monkeypatch.setenv("SEF_TEST_DATABASE_URL", NOWHERE)
    (small_root / path).parent.mkdir(parents=True, exist_ok=True)
    (small_root / path).write_text(text, encoding="utf-8")
    status, out = run(small_root)
    assert status == EXIT_ERROR
    assert out.startswith(problem)
    assert not (small_root / "evals" / "reports").exists()


def test_says_when_the_rule_sets_are_missing(
    small_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unfetched(root: Path, cases: object) -> list[Measure]:
        raise RulesetNotFoundError("rule set 'en16931' is not present in /nowhere")

    monkeypatch.setenv("SEF_TEST_DATABASE_URL", NOWHERE)
    monkeypatch.setattr(verdicts, "measure", unfetched)
    status, out = run(small_root)
    assert (status, out) == (
        EXIT_ERROR,
        "sef-evals: rule set 'en16931' is not present in /nowhere (run `make rulesets`)\n",
    )


def test_records_and_checks_are_not_asked_together(small_root: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        run(small_root, "--record", "--check")
    assert exited.value.code == 2


def test_runs_as_a_module() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "sef_evals", "--version"],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPOSITORY_ROOT,
    )
    assert (done.returncode, done.stdout) == (0, f"sef-evals {__version__}\n")


@needs_database
def test_the_committed_report_is_what_the_run_gives_and_meets_every_threshold() -> None:
    """The repository's own evaluations, as CI runs them, with the recorded answers."""
    status, out = run(REPOSITORY_ROOT, "--check", model=lambda: None)
    assert status == EXIT_MET, out


async def test_records_with_the_model_the_settings_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in (
        "LLM_PROVIDER",
        "GROQ_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "SEF_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    assert model_named_in(env_file) is None
    env_file.write_text(
        "DATABASE_URL=postgresql+asyncpg://not@read/at-all\nSEF_ENVIRONMENT=nonsense\n"
        "LLM_PROVIDER=groq\nGROQ_API_KEY=not-a-real-key\n",
        encoding="utf-8",
    )
    model = model_named_in(env_file)
    assert model is not None
    assert model.model == "groq/openai/gpt-oss-120b"
    await model.aclose()
    monkeypatch.setenv("SEF_LLM_MODEL", "llama-3.3-70b-versatile")
    named = model_named_in(env_file)
    assert named is not None
    assert named.model == "groq/llama-3.3-70b-versatile"
    await named.aclose()
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key-either")
    monkeypatch.delenv("SEF_LLM_MODEL")
    anthropic = model_named_in(env_file)
    assert anthropic is not None
    assert anthropic.model == "anthropic/claude-haiku-5-5"
    await anthropic.aclose()
    monkeypatch.setenv("LLM_PROVIDER", "none")
    assert model_named_in(env_file) is None
