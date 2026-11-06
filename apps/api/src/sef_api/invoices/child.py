"""The validator's child process: warm up, then validate what the API sends, one at a time.

It is started with ``multiprocessing``'s *spawn* method (the only one on Windows), so it
imports only what validating needs. Its standard output and error go to the null device
before anything else runs: a traceback or a native library may quote a document, and nothing
a document makes this process say may reach a log. The API learns what happened from the
outcome it sends back (:mod:`sef_api.invoices.validation`) and from its exit code.

Messages on the connection: the child first sends ``("ready", "")`` or
``("unavailable", why)``; then, for each ``(number, profile, content, max_elements, patches,
fields)`` it receives, the number and an :data:`~sef_api.invoices.validation.Outcome`:
``(number, kind, detail)``. ``patches`` is None to validate the document, or a list of patches
as JSON to apply first; ``fields`` asks, with patches, for the fields around the violations
that remain. The number lets the API check that an answer is to the message it has just sent.
The child stops when the connection closes.
"""

from __future__ import annotations

import os
from multiprocessing.connection import Connection

from sef_api.invoices.validation import PATCHES, Outcome, outcome, patched_outcome, warm_up

__all__ = ["serve"]


def _silence() -> None:
    null = os.open(os.devnull, os.O_WRONLY)
    os.dup2(null, 1)
    os.dup2(null, 2)
    os.close(null)


def serve(connection: Connection) -> None:
    """The child's main loop."""
    _silence()
    problem = warm_up()
    connection.send(("ready", "") if problem is None else ("unavailable", problem))
    if problem is not None:
        return
    while True:
        try:
            number, profile, content, max_elements, patches, fields = connection.recv()
        except EOFError:
            return
        answer: Outcome
        if patches is None:
            answer = outcome(content, profile, max_elements=max_elements)
        else:
            listed = PATCHES.validate_json(patches)
            answer = patched_outcome(
                content, profile, listed, max_elements=max_elements, fields=fields
            )
        connection.send((number, *answer))
