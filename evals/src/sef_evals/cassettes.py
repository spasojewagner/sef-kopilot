"""The language model's answers, recorded once and replayed offline (cassettes, ADR-0055).

A cassette maps each request the evaluations make of the model to the answer the model gave.
A request is named by the SHA-256 of what is sent: the schema's name, the schema, the messages
and the token limit, in canonical JSON, never by the provider or the key. A picture shown to
the model is named by the name its run gives it, the document it was drawn from (ADR-0063),
or else by its digest: drawing a page may differ in its last bits from one machine to another,
and a cassette recorded on one must answer on the others. Replayed, the same
request gets the same answer, without network or key; a request the cassette does not hold is
an :class:`LLMError`, as a model that does not answer, so that a changed prompt, passage or
document shows up as a measure that drops, and is recorded again on purpose.

Recording asks the real model only what the cassette does not hold yet, and keeps only the
answers the run used: an interrupted recording, by a provider's daily limit say, continues
where it stopped.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from sef_api.llm import LLMClient, LLMError, Message, Picture

__all__ = [
    "Cassette",
    "CassetteError",
    "Recording",
    "RecordingStoppedError",
    "Replaying",
    "picture_digest",
    "request_key",
]

_COMMENT: Final = (
    "The language model's answers to the evaluations' requests, by the SHA-256 of each request "
    "(ADR-0055). Written by `make evals-record`; do not edit."
)


class CassetteError(Exception):
    """A cassette's file is not what it must be; the message says where and why."""


def picture_digest(picture: Picture | bytes) -> str:
    """The SHA-256 of a picture's bytes."""
    data = picture.data if isinstance(picture, Picture) else picture
    return hashlib.sha256(data).hexdigest()


def _sent(message: Message, names: Mapping[str, str]) -> list[Any]:
    if not message.pictures:
        # As before pictures could be shown: the keys of the cassettes recorded then still hold.
        return [message.role, message.content]
    pictures = [
        [picture.media_type, names.get(digest := picture_digest(picture), digest)]
        for picture in message.pictures
    ]
    return [message.role, message.content, pictures]


def request_key(
    messages: Sequence[Message],
    *,
    name: str,
    schema: Mapping[str, Any],
    max_tokens: int | None,
    names: Mapping[str, str] | None = None,
) -> str:
    """The name of a request: the SHA-256 of what is sent, in canonical JSON, each picture by
    the name ``names`` gives its digest, or by its digest."""
    sent = {
        "name": name,
        "schema": schema,
        "max_tokens": max_tokens,
        "messages": [_sent(message, names or {}) for message in messages],
    }
    canonical = json.dumps(sent, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class Cassette:
    """The model that answered, and its answers by request."""

    model: str
    answers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Cassette:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            model, answers = data["model"], data["answers"]
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise CassetteError(f"{path.name}: {error}") from None
        if not isinstance(model, str) or not isinstance(answers, dict):
            raise CassetteError(f"{path.name}: a model's name and its answers by request")
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in answers.items()):
            raise CassetteError(f"{path.name}: each answer is text, by its request's key")
        return cls(model, dict(answers))

    def save(self, path: Path) -> None:
        data = {
            "$comment": _COMMENT,
            "model": self.model,
            "answers": dict(sorted(self.answers.items())),
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")


class Replaying:
    """A model that answers from a cassette, and only from it; ``names`` names the pictures
    of the requests, as :func:`request_key` does, and may be filled in as they are made."""

    def __init__(self, cassette: Cassette, *, names: Mapping[str, str] | None = None) -> None:
        self._cassette = cassette
        self._names = names

    @property
    def model(self) -> str:
        return self._cassette.model

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        key = request_key(
            messages, name=name, schema=schema, max_tokens=max_tokens, names=self._names
        )
        try:
            return self._cassette.answers[key]
        except KeyError:
            raise LLMError("no answer is recorded for this request") from None

    async def aclose(self) -> None:
        pass


class RecordingStoppedError(Exception):
    """The provider refuses more requests for now (its limit, or a server that stays busy); what
    was recorded is kept."""


#: What a model's error says when its provider refuses for now, which a wait may lift: its limit
#: (429), or a server that is busy or down (5xx: Gemini answers 503 when it is overloaded).
_BUSY: Final = re.compile(r"answered (429|5[0-9]{2})\b")


class Recording:
    """A model that answers from a cassette what it holds, and asks ``llm`` the rest.

    ``pause`` seconds pass before each request to the real model, so that a provider's limit
    per minute is not reached; an answer of 429, or of 5xx from a server that is busy, is waited
    for ``patience`` seconds and asked again, up to ``tries`` times, after which the recording
    stops (:class:`RecordingStoppedError`): a provider's daily limit is not waited out. Any other
    failure is the model's answer to that request, for now. ``names`` names the pictures of the
    requests, as :func:`request_key` does.
    """

    def __init__(
        self,
        llm: LLMClient,
        cassette: Cassette | None = None,
        *,
        pause: float = 0.0,
        patience: float = 60.0,
        tries: int = 5,
        names: Mapping[str, str] | None = None,
    ) -> None:
        self._llm = llm
        self._names = names
        self._held = dict(cassette.answers) if cassette is not None else {}
        self._used: dict[str, str] = {}
        #: How many requests the real model was sent.
        self.asked = 0
        self._pause = pause
        self._patience = patience
        self._tries = tries

    @property
    def model(self) -> str:
        return self._llm.model

    def cassette(self, *, finished: bool) -> Cassette:
        """The answers to keep: those the run used, once it finished; every answer held, when
        it stopped before, so that the next recording continues from them."""
        return Cassette(self.model, dict(self._used if finished else self._held))

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None = None,
    ) -> str:
        key = request_key(
            messages, name=name, schema=schema, max_tokens=max_tokens, names=self._names
        )
        if key not in self._held:
            self._held[key] = await self._ask(messages, name, schema, max_tokens)
        self._used[key] = self._held[key]
        return self._held[key]

    async def _ask(
        self,
        messages: Sequence[Message],
        name: str,
        schema: Mapping[str, Any],
        max_tokens: int | None,
    ) -> str:
        status = "429"
        for attempt in range(1, self._tries + 1):
            if attempt > 1:
                await asyncio.sleep(self._patience)
            await asyncio.sleep(self._pause)
            self.asked += 1
            try:
                return await self._llm.answer(
                    messages, name=name, schema=schema, max_tokens=max_tokens
                )
            except LLMError as error:
                busy = _BUSY.search(str(error))
                if busy is None:
                    raise
                status = busy.group(1)
        why = "its provider's limit is reached" if status == "429" else "its provider is busy"
        raise RecordingStoppedError(
            f"the model answered {status} {self._tries} times: {why}; record again later to "
            "continue"
        )

    async def aclose(self) -> None:
        """Nothing: the model recorded from is its owner's to close, and may record for more
        than one cassette."""
