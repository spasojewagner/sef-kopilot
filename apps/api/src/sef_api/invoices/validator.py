"""Where invoices are validated: a child process, one document at a time, within a time limit.

Validating in a thread of the API's process is not enough, for three measured reasons:

* Saxon holds Python's global interpreter lock while it applies a rule set: a two-second run
  stalled the main thread for 1.7 s. One large document would stall every other request.
* The published rule sets cost more than linearly in the elements that fail them, and they are
  executed as published (ADR-0005), so their worst case cannot be fixed, only bounded.
* A thread cannot be stopped; a process can.

:class:`ProcessValidator` therefore keeps one child process (:mod:`sef_api.invoices.child`),
warmed up with every rule set, and sends it one document at a time. A validation that takes
longer than the time limit is stopped by killing the child, which is replaced at once; so is
a child that dies. Each turn, once its document is sent, ends with the child ready for the
next one even if its request is cancelled, and every answer names the message it answers: an
answer read for the wrong document would be one organization's report handed to another.
:class:`ThreadValidator` does the same work in a thread of this process,
without a time limit, for tests and tools. :class:`Admission` bounds the validations waiting
or running, so that a burst is turned away quickly instead of queueing without end.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import multiprocessing
import time
from collections.abc import Callable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from typing import Final, Literal, NoReturn, Protocol

from einvoice_core.patches import Patch
from sef_api.invoices.child import serve
from sef_api.invoices.validation import (
    PATCHES,
    Outcome,
    Patched,
    ProfileName,
    Validation,
    outcome,
    patched_outcome,
    rule_sets_missing,
    warm_up,
)
from sef_api.settings import Settings

__all__ = [
    "Admission",
    "ProcessValidator",
    "ThreadValidator",
    "TooManyElementsError",
    "UnreadableInvoiceError",
    "ValidationRefusedError",
    "ValidationTimeoutError",
    "Validator",
    "ValidatorBusyError",
    "ValidatorFailedError",
    "ValidatorUnavailableError",
    "validator_for",
]

logger = logging.getLogger(__name__)

#: How long a child may take to compile the rule sets: seconds normally, more on a small host.
START_SECONDS: Final = 120.0
#: How long after a child failed to start the next request tries again.
RETRY_SECONDS: Final = 30.0
#: How long a child that waits for an invoice has to end once its connection is closed.
_GRACE_SECONDS: Final = 5.0

#: What the child is sent: a number for the message, the profile, the invoice, the budget, the
#: patches to apply first as JSON, or None, and whether to list the fields around what remains.
_Message = tuple[int, ProfileName, bytes, int, str | None, bool]
#: How a turn ends: the child's outcome, or the time limit, which stopped the child.
_Ending = Outcome | tuple[Literal["timeout"], str]


class ValidatorUnavailableError(Exception):
    """This server cannot validate: its rule sets are missing or broken, or the child failed."""


class ValidatorBusyError(Exception):
    """As many validations as allowed are already waiting or running."""


class TooManyElementsError(Exception):
    """The invoice has more elements than the budget allows."""


class ValidationTimeoutError(Exception):
    """The validation took longer than the time limit and was stopped."""


class ValidationRefusedError(Exception):
    """The rule sets could not be applied to this invoice."""


class UnreadableInvoiceError(Exception):
    """The invoice is not well-formed XML, so no patch applies to it."""


class ValidatorFailedError(Exception):
    """The validator failed; the message is the type of the error, never document content."""


class _OutOfStepError(Exception):
    """The child's answer is not to the message just sent."""


class Validator(Protocol):
    """What the API needs from a validator."""

    @property
    def problem(self) -> str | None:
        """Why this validator cannot validate now, or None."""
        ...

    async def start(self) -> None: ...

    async def validate(self, content: bytes, profile: ProfileName) -> Validation: ...

    async def patch(
        self,
        content: bytes,
        profile: ProfileName,
        patches: Sequence[Patch],
        *,
        fields: bool = False,
    ) -> Patched:
        """What ``patches`` do to ``content``; with ``fields``, with the fields around the
        violations to repair that remain."""
        ...

    async def stop(self) -> None: ...


def _raise_for(kind: str, detail: str) -> NoReturn:
    if kind == "too-many-elements":
        raise TooManyElementsError(detail)
    if kind == "unreadable":
        raise UnreadableInvoiceError(detail)
    if kind == "unavailable":
        raise ValidatorUnavailableError(detail)
    if kind == "refused":
        raise ValidationRefusedError(detail)
    if kind == "timeout":
        raise ValidationTimeoutError(detail)
    if kind == "failed":
        raise ValidatorFailedError(detail)
    # A report or a patched document out of turn: its detail quotes the document, so not it.
    raise ValidatorFailedError(f"the validator answered {kind} out of turn")


def _validation(result: _Ending) -> Validation:
    kind, detail = result
    if kind == "report":
        return Validation.model_validate_json(detail)
    _raise_for(kind, detail)


def _patched(result: _Ending) -> Patched:
    kind, detail = result
    if kind == "patched":
        return Patched.model_validate_json(detail)
    _raise_for(kind, detail)


class Admission:
    """At most ``capacity`` validations waiting or running; the next one is turned away."""

    def __init__(self, capacity: int) -> None:
        self.capacity = capacity
        self._inside = 0

    @property
    def full(self) -> bool:
        return self._inside >= self.capacity

    @contextmanager
    def admit(self) -> Iterator[None]:
        if self.full:
            raise ValidatorBusyError(f"{self.capacity} validations are already waiting or running")
        self._inside += 1
        try:
            yield
        finally:
            self._inside -= 1


class ThreadValidator:
    """Validates in a thread of this process, for tests and tools.

    The work runs in an executor of its own, so it never waits behind password hashing in the
    default one. There is no time limit, since a thread cannot be stopped, and a large
    document can stall the event loop while Saxon runs; the API uses :class:`ProcessValidator`.
    """

    def __init__(self, *, max_elements: int) -> None:
        self._max_elements = max_elements
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sef-validation")
        self._warmed = False
        self._problem: str | None = None

    @property
    def problem(self) -> str | None:
        return self._problem if self._warmed else rule_sets_missing()

    async def start(self) -> None:
        await self._warm()

    async def _warm(self) -> None:
        if not self._warmed:
            self._problem = await asyncio.get_running_loop().run_in_executor(
                self._executor, warm_up
            )
            self._warmed = True

    async def validate(self, content: bytes, profile: ProfileName) -> Validation:
        await self._warm()
        if self._problem is not None:
            raise ValidatorUnavailableError(self._problem)
        work = functools.partial(outcome, content, profile, max_elements=self._max_elements)
        return _validation(await asyncio.get_running_loop().run_in_executor(self._executor, work))

    async def patch(
        self,
        content: bytes,
        profile: ProfileName,
        patches: Sequence[Patch],
        *,
        fields: bool = False,
    ) -> Patched:
        await self._warm()
        if self._problem is not None:
            raise ValidatorUnavailableError(self._problem)
        work = functools.partial(
            patched_outcome,
            content,
            profile,
            patches,
            max_elements=self._max_elements,
            fields=fields,
        )
        return _patched(await asyncio.get_running_loop().run_in_executor(self._executor, work))

    async def stop(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


class _Child:
    """One child process and the connection to it. Every method blocks."""

    def __init__(self, process: BaseProcess, connection: Connection) -> None:
        self.process = process
        self.connection = connection

    @classmethod
    def spawn(
        cls, start_seconds: float, target: Callable[[Connection], object] = serve
    ) -> tuple[_Child | None, str | None]:
        """A warmed-up child running ``target``, or None and why there is none."""
        context = multiprocessing.get_context("spawn")
        ours, theirs = context.Pipe()
        process = context.Process(
            target=target, args=(theirs,), name="sef-kopilot-validator", daemon=True
        )
        process.start()
        theirs.close()
        child = cls(process, ours)
        try:
            if not ours.poll(start_seconds):
                child.stop(at_once=True)
                return None, f"the validator did not start within {start_seconds:g} s"
            kind, detail = ours.recv()
        except (EOFError, OSError):
            child.stop()  # it is ending: wait for its exit code
            return None, f"the validator stopped while starting (exit code {process.exitcode})"
        if kind != "ready":
            child.stop()
            return None, str(detail)
        return child, None

    def exchange(self, message: _Message, seconds: float) -> Outcome | None:
        """The child's outcome for ``message``, or None if it takes longer than ``seconds``.

        Raises :class:`EOFError` or :class:`OSError` if the child has gone, and
        :class:`_OutOfStepError` if its answer names another message.
        """
        self.connection.send(message)
        if not self.connection.poll(seconds):
            return None
        number, kind, detail = self.connection.recv()
        if number != message[0]:
            raise _OutOfStepError(f"the answer to message {number} came for message {message[0]}")
        return kind, detail

    def stop(self, *, at_once: bool = False) -> None:
        """End the child: closing the connection ends one that waits for an invoice; one that
        is busy, or does not end within a few seconds, is killed."""
        self.connection.close()
        if not at_once:
            self.process.join(timeout=_GRACE_SECONDS)
        if self.process.is_alive():
            self.process.kill()
        self.process.join(timeout=30)


class ProcessValidator:
    """Validates in a child process, one document at a time, stopping any that runs too long.

    The child is started by :meth:`start` and replaced, before the next document, whenever it
    is stopped for taking too long, has died or has answered out of step. A child that cannot
    start is tried again by the first request after :data:`RETRY_SECONDS`, so that a server
    heals once, say, its rule sets are fetched. Requests wait their turn; :class:`Admission`
    keeps that queue short.
    """

    def __init__(
        self, *, max_elements: int, seconds: float, start_seconds: float = START_SECONDS
    ) -> None:
        self._max_elements = max_elements
        self._seconds = seconds
        self._start_seconds = start_seconds
        self._turn = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sef-validator")
        self._child: _Child | None = None
        self._problem: str | None = "the validator has not started"
        self._started = False
        self._retry_at = 0.0
        self._sent = 0

    @property
    def problem(self) -> str | None:
        return self._problem

    async def _run[T](self, work: functools.partial[T]) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._executor, work)

    async def _replace(self) -> None:
        if self._child is not None:
            await self._run(functools.partial(self._child.stop, at_once=True))
            self._child = None
        self._child, self._problem = await self._run(
            functools.partial(_Child.spawn, self._start_seconds)
        )
        if self._problem is not None:
            self._retry_at = time.monotonic() + RETRY_SECONDS
            if self._started:  # at start, the application reports it
                logger.warning("the validator could not be replaced: %s", self._problem)
        self._started = True

    async def start(self) -> None:
        async with self._turn:
            await self._replace()

    async def validate(self, content: bytes, profile: ProfileName) -> Validation:
        return _validation(await self._answer(content, profile, None, fields=False))

    async def patch(
        self,
        content: bytes,
        profile: ProfileName,
        patches: Sequence[Patch],
        *,
        fields: bool = False,
    ) -> Patched:
        listed = PATCHES.dump_json(list(patches)).decode()
        return _patched(await self._answer(content, profile, listed, fields=fields))

    async def _answer(
        self, content: bytes, profile: ProfileName, patches: str | None, *, fields: bool
    ) -> _Ending:
        entered = asyncio.Event()
        message = (profile, content, patches, fields)
        turn = asyncio.ensure_future(self._take_turn(*message, entered))
        try:
            return await asyncio.shield(turn)
        except asyncio.CancelledError:
            if not entered.is_set():
                turn.cancel()  # still waiting for its turn: it has nothing to settle
            raise

    async def _take_turn(
        self,
        profile: ProfileName,
        content: bytes,
        patches: str | None,
        fields: bool,
        entered: asyncio.Event,
    ) -> _Ending:
        """One validation, after which the child is ready for the next document.

        It runs as a task of its own, which the request awaits through a shield: once the turn
        has begun, a cancelled request does not cut it short. The turn still waits for the
        child's answer, or stops a child that overruns, before the next document is sent. Cut
        short, it would leave the answer in the pipe, to be read as the next document's.
        """
        async with self._turn:
            entered.set()
            failed_lately = self._child is None and time.monotonic() < self._retry_at
            if not failed_lately and (self._child is None or not self._child.process.is_alive()):
                await self._replace()
            child = self._child
            if child is None:
                return "unavailable", self._problem or "the validator is not available"
            self._sent += 1
            message = (self._sent, profile, content, self._max_elements, patches, fields)
            try:
                result = await self._run(functools.partial(child.exchange, message, self._seconds))
            except (EOFError, OSError):
                exit_code = child.process.exitcode
                await self._replace()
                logger.error("the validator stopped while validating (exit code %s)", exit_code)
                return "failed", "the validator stopped"
            except _OutOfStepError:
                await self._replace()
                logger.error("the validator answered out of step and was replaced")
                return "failed", "the validator answered out of step"
            if result is None:
                logger.warning("a validation was stopped after %g s", self._seconds)
                await self._replace()
                return "timeout", f"the invoice could not be validated within {self._seconds:g} s"
            return result

    async def stop(self) -> None:
        async with self._turn:
            if self._child is not None:
                await self._run(functools.partial(self._child.stop))
                self._child = None
            self._problem = "the validator has stopped"
        self._executor.shutdown(wait=False)


def validator_for(settings: Settings) -> Validator:
    """The validator ``settings`` choose: a child process, or a thread for tests and tools."""
    if settings.validator == "thread":
        return ThreadValidator(max_elements=settings.max_invoice_elements)
    return ProcessValidator(
        max_elements=settings.max_invoice_elements, seconds=settings.validation_seconds
    )
