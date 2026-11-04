"""Where invoices are validated: the child process, its time limit and its replacement, the
thread for tests and tools, the admission of validations, and the application's lifecycle."""

from __future__ import annotations

import asyncio
import logging
import multiprocessing
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from einvoice_core.pipeline import validate
from einvoice_core.rulesets import ENV_VAR
from sef_api.invoices import validator
from sef_api.invoices.validation import Validation
from sef_api.invoices.validator import (
    Admission,
    ProcessValidator,
    ThreadValidator,
    TooManyElementsError,
    ValidationRefusedError,
    ValidationTimeoutError,
    ValidatorBusyError,
    ValidatorFailedError,
    ValidatorUnavailableError,
)
from sef_api.main import create_app

from .conftest import REPOSITORY_ROOT, settings_for

FIXTURES = REPOSITORY_ROOT / "fixtures" / "invoices"
INVOICE = (FIXTURES / "synthetic" / "srb-final-invoice.xml").read_bytes()
EXAMPLE = (FIXTURES / "official" / "sef" / "avansna-faktura.xml").read_bytes()
LINE = re.search(rb"<cac:InvoiceLine>.*?</cac:InvoiceLine>", INVOICE, re.DOTALL)
assert LINE is not None
#: An invoice of 1500 lines: about a second of work, far more than a short time limit.
LONG = INVOICE.replace(LINE[0], LINE[0] * 1500, 1)
BUDGET = 20_000


def report_of(content: bytes, profile: str = "srb") -> dict[str, Any]:
    return validate(content, profile).model_dump(mode="json")


# --- admission --------------------------------------------------------------------------------


def test_admission_turns_away_what_is_beyond_its_capacity() -> None:
    admission = Admission(2)

    with admission.admit(), admission.admit():
        assert admission.full
        with pytest.raises(ValidatorBusyError), admission.admit():
            pass

    assert not admission.full


def test_admission_lets_go_of_a_validation_that_fails() -> None:
    admission = Admission(1)

    with pytest.raises(RuntimeError), admission.admit():
        raise RuntimeError

    with admission.admit():
        assert admission.full


# --- outcomes as exceptions -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "error"),
    [
        ("too-many-elements", TooManyElementsError),
        ("unavailable", ValidatorUnavailableError),
        ("refused", ValidationRefusedError),
        ("timeout", ValidationTimeoutError),
        ("failed", ValidatorFailedError),
    ],
)
def test_every_outcome_but_a_report_is_an_exception(kind: Any, error: type[Exception]) -> None:
    with pytest.raises(error, match="the detail"):
        validator._validation((kind, "the detail"))


# --- the thread, for tests and tools ----------------------------------------------------------


async def test_the_thread_validator_warms_up_once_in_a_thread_of_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    threads: list[str] = []

    def warm_up() -> None:
        threads.append(threading.current_thread().name)

    monkeypatch.setattr(validator, "warm_up", warm_up)
    runner = ThreadValidator(max_elements=BUDGET)

    validation = await runner.validate(INVOICE, "srb")
    await runner.validate(INVOICE, "srb")
    await runner.stop()

    assert validation.report.model_dump(mode="json") == report_of(INVOICE)
    assert len(threads) == 1
    assert threads[0].startswith("sef-validation")  # not the event loop's, not the default pool


async def test_the_thread_validator_says_why_it_cannot_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))
    runner = ThreadValidator(max_elements=BUDGET)

    assert runner.problem is not None  # before warming up: the rule sets are checked
    with pytest.raises(ValidatorUnavailableError, match=r"'ubl-2\.1' is not present"):
        await runner.validate(INVOICE, "srb")
    await runner.stop()


# --- the child process ------------------------------------------------------------------------


async def test_the_child_validates_as_the_validator_does_one_invoice_at_a_time(
    capfd: pytest.CaptureFixture[str],
) -> None:
    runner = ProcessValidator(max_elements=1000, seconds=60)
    await runner.start()
    assert runner.problem is None

    for content in (INVOICE, EXAMPLE):
        for profile in ("srb", "en16931", "peppol"):
            validation = await runner.validate(content, profile)
            assert validation.report.model_dump(mode="json") == report_of(content, profile)
    validations = await asyncio.gather(*(runner.validate(INVOICE, "srb") for _ in range(5)))
    with pytest.raises(TooManyElementsError, match="more than 1000 elements"):
        await runner.validate(LONG, "srb")  # counted in the child, never validated
    await runner.stop()

    assert [validation.report.valid for validation in validations] == [True] * 5
    assert capfd.readouterr() == ("", "")  # the child wrote nothing to the API's streams


async def test_a_validation_over_the_time_limit_is_stopped_and_the_child_replaced() -> None:
    runner = ProcessValidator(max_elements=BUDGET, seconds=0.2)
    await runner.start()
    assert runner._child is not None
    first = runner._child.process

    with pytest.raises(ValidationTimeoutError, match=r"within 0\.2 s"):
        await runner.validate(LONG, "srb")

    assert not first.is_alive()
    assert runner._child is not None
    assert runner._child.process.pid != first.pid
    assert (await runner.validate(INVOICE, "srb")).report.valid
    await runner.stop()


async def test_a_cancelled_validation_leaves_the_child_ready_for_the_next_invoice() -> None:
    """Cut short, the turn would leave the child's answer in the pipe, and the next request,
    perhaps another organization's, would receive the report on this invoice."""
    runner = ProcessValidator(max_elements=BUDGET, seconds=0.2)
    await runner.start()
    assert runner._child is not None
    first = runner._child.process
    cancelled = asyncio.create_task(runner.validate(LONG, "srb"))
    while runner._sent == 0:  # the long invoice is on its way to the child
        await asyncio.sleep(0.01)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled

    validation = await runner.validate(EXAMPLE, "srb")

    assert validation.report.model_dump(mode="json") == report_of(EXAMPLE)
    assert not first.is_alive()  # stopped at the time limit, as if its request had waited
    await runner.stop()


async def test_a_validation_cancelled_before_its_turn_is_never_sent() -> None:
    runner = ProcessValidator(max_elements=BUDGET, seconds=60)
    await runner.start()
    async with runner._turn:  # another validation is running
        waiting = asyncio.create_task(runner.validate(INVOICE, "srb"))
        await asyncio.sleep(0.05)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

    assert (await runner.validate(INVOICE, "srb")).report.valid
    assert runner._sent == 1
    await runner.stop()


def test_an_answer_to_another_message_is_refused() -> None:
    ours, theirs = multiprocessing.Pipe()
    child = validator._Child(multiprocessing.Process(), ours)
    theirs.send((6, "report", "{}"))  # left over from an earlier message

    with pytest.raises(validator._OutOfStepError, match="answer to message 6 came for message 7"):
        child.exchange((7, "srb", INVOICE, BUDGET), 5)

    assert theirs.recv() == (7, "srb", INVOICE, BUDGET)


async def test_a_child_that_answers_out_of_step_is_replaced(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    runner = ProcessValidator(max_elements=BUDGET, seconds=60)
    await runner.start()
    assert runner._child is not None
    before = runner._child.process

    def out_of_step(*_: Any) -> None:
        raise validator._OutOfStepError

    monkeypatch.setattr(validator._Child, "exchange", out_of_step)
    with (
        caplog.at_level(logging.ERROR, logger="sef_api.invoices.validator"),
        pytest.raises(ValidatorFailedError, match="answered out of step"),
    ):
        await runner.validate(INVOICE, "srb")
    monkeypatch.undo()

    assert "the validator answered out of step and was replaced" in caplog.text
    assert not before.is_alive()
    assert (await runner.validate(INVOICE, "srb")).report.valid
    await runner.stop()


async def test_a_child_that_dies_is_replaced(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    runner = ProcessValidator(max_elements=BUDGET, seconds=60)
    await runner.start()
    assert runner._child is not None
    between = runner._child.process
    between.kill()  # between two invoices: replaced before the next one
    between.join()

    assert (await runner.validate(INVOICE, "srb")).report.valid
    assert runner._child.process.pid != between.pid
    during = runner._child.process

    def dies(*_: Any) -> None:
        during.kill()
        raise EOFError

    monkeypatch.setattr(validator._Child, "exchange", dies)  # while it validates: a failure
    with (
        caplog.at_level(logging.ERROR, logger="sef_api.invoices.validator"),
        pytest.raises(ValidatorFailedError, match="the validator stopped"),
    ):
        await runner.validate(INVOICE, "srb")
    monkeypatch.undo()

    assert "the validator stopped while validating (exit code" in caplog.text
    assert runner._child.process.pid != during.pid
    assert (await runner.validate(INVOICE, "srb")).report.valid
    await runner.stop()


async def test_without_rule_sets_the_child_says_why_and_is_tried_again_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path))  # inherited by the child
    runner = ProcessValidator(max_elements=BUDGET, seconds=60)

    await runner.start()

    problem = runner.problem
    assert problem is not None
    assert "'ubl-2.1' is not present" in problem
    with pytest.raises(ValidatorUnavailableError, match=r"'ubl-2\.1' is not present"):
        await runner.validate(INVOICE, "srb")  # within RETRY_SECONDS: not tried again
    runner._retry_at = 0  # RETRY_SECONDS have passed, and the rule sets are still missing
    with (
        caplog.at_level(logging.WARNING, logger="sef_api.invoices.validator"),
        pytest.raises(ValidatorUnavailableError),
    ):
        await runner.validate(INVOICE, "srb")
    assert "the validator could not be replaced: rule set 'ubl-2.1'" in caplog.text
    monkeypatch.delenv(ENV_VAR)  # now they are there
    runner._retry_at = 0

    assert (await runner.validate(INVOICE, "srb")).report.valid
    healed = runner.problem
    await runner.stop()

    assert healed is None
    assert runner.problem == "the validator has stopped"


async def test_a_validator_that_never_started_stops_quietly() -> None:
    runner = ProcessValidator(max_elements=BUDGET, seconds=60)

    await runner.stop()

    assert runner.problem == "the validator has stopped"


def test_a_child_that_does_not_start_in_time_is_given_up() -> None:
    child, problem = validator._Child.spawn(0.001)

    assert (child, problem) == (None, "the validator did not start within 0.001 s")


def test_a_child_that_ends_while_starting_says_how() -> None:
    child, problem = validator._Child.spawn(30, target=print)  # returns without a word

    assert (child, problem) == (None, "the validator stopped while starting (exit code 0)")


#: The child's main loop in a process of its own, with an outcome as loud as a traceback or a
#: native library could be. Once the loop has run, only the exit code can say how it went.
SERVE_LOUDLY = """
import os
import sys

from sef_api.invoices import child


class Connection:
    def __init__(self):
        self.received = [(7, "srb", b"<Invoice/>", 10)]
        self.sent = []

    def recv(self):
        if not self.received:
            raise EOFError
        return self.received.pop()

    def send(self, message):
        self.sent.append(message)


def loud(*_args, **_kwargs):
    print("quoted-from-the-invoice", flush=True)
    print("quoted-from-the-invoice", file=sys.stderr, flush=True)
    os.write(2, b"quoted-from-the-invoice")
    return "failed", "RuntimeError"


child.warm_up = lambda: None
child.outcome = loud
connection = Connection()
child.serve(connection)
sys.exit(0 if connection.sent == [("ready", ""), (7, "failed", "RuntimeError")] else 3)
"""


def test_the_child_says_nothing_on_its_standard_streams() -> None:
    """Whatever the child would print while it validates is dropped, and its answer names the
    message it answers."""
    finished = subprocess.run(
        [sys.executable, "-c", SERVE_LOUDLY], capture_output=True, check=False, timeout=60
    )

    assert (finished.returncode, finished.stdout, finished.stderr) == (0, b"", b"")


# --- the application's lifecycle --------------------------------------------------------------


class Recording:
    """A validator that records what the application does with it."""

    def __init__(self, problem: str | None = None) -> None:
        self.problem = problem
        self.calls: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def validate(self, _content: bytes, _profile: str) -> Validation:
        raise AssertionError("not validated in these tests")

    async def stop(self) -> None:
        self.calls.append("stop")


async def test_the_application_starts_its_validator_and_stops_it() -> None:
    app = create_app(settings_for())
    recording = Recording()
    app.state.validator = recording

    async with app.router.lifespan_context(app):
        assert recording.calls == ["start"]

    assert recording.calls == ["start", "stop"]
    await app.state.database.engine.dispose()


async def test_without_a_validator_the_application_starts_and_says_why(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = create_app(settings_for())
    app.state.validator = Recording(problem="rule set 'ubl-2.1' is absent")

    with caplog.at_level(logging.WARNING, logger="sef_api.main"):
        async with app.router.lifespan_context(app):
            pass

    assert "the validator cannot run: rule set 'ubl-2.1' is absent" in caplog.text
    await app.state.database.engine.dispose()


def test_the_api_validates_in_a_child_process_unless_told_otherwise() -> None:
    assert isinstance(
        create_app(settings_for(SEF_VALIDATOR="process")).state.validator, ProcessValidator
    )
    assert isinstance(create_app(settings_for()).state.validator, ThreadValidator)
