"""Cassettes: requests named by what is sent, answers replayed, and recorded only once."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from sef_api.llm import LLMError, Message, Picture
from sef_evals.cassettes import (
    Cassette,
    CassetteError,
    Recording,
    RecordingStoppedError,
    Replaying,
    picture_digest,
    request_key,
)

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}
ASKED = [Message("system", "Explain."), Message("user", "SRB-009 in BT-31")]


class Model:
    """A stand-in for the real model: it answers each request with its number, or fails as
    ``failures`` say, in turn."""

    model = "test/model"

    def __init__(self, *failures: str) -> None:
        self.failures = list(failures)
        self.asked: list[list[str]] = []
        self.closed = False

    async def answer(
        self,
        messages: Sequence[Message],
        *,
        name: str,
        schema: Mapping[str, Any],  # noqa: ARG002
        max_tokens: int | None = None,  # noqa: ARG002
    ) -> str:
        self.asked.append([message.content for message in messages])
        if self.failures:
            raise LLMError(self.failures.pop(0))
        return json.dumps({"answer": f"answer {len(self.asked)}", "name": name})

    async def aclose(self) -> None:
        self.closed = True


def key(*messages: Message, name: str = "explanation", tokens: int | None = None) -> str:
    return request_key(messages or ASKED, name=name, schema=SCHEMA, max_tokens=tokens)


def test_a_request_is_named_by_everything_sent_and_only_that() -> None:
    assert key() == key()
    assert len(key()) == 64
    assert key(Message("system", "Explain."), Message("user", "SRB-009 in BT-48")) != key()
    assert key(Message("user", "SRB-009 in BT-31"), Message("system", "Explain.")) != key()
    assert key(name="repair") != key()
    assert key(tokens=2048) != key()
    reordered = {"properties": SCHEMA["properties"], "type": "object"}
    assert request_key(ASKED, name="explanation", schema=reordered, max_tokens=None) == key()


def test_a_request_without_pictures_keeps_the_name_it_had_before_pictures() -> None:
    sent = {
        "name": "explanation",
        "schema": SCHEMA,
        "max_tokens": None,
        "messages": [[message.role, message.content] for message in ASKED],
    }
    canonical = json.dumps(sent, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    # The cassettes recorded before a model could be shown pictures still answer.
    assert key() == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


DRAWN = Picture("image/jpeg", b"\xff\xd8 drawn here")
DRAWN_ELSEWHERE = Picture("image/jpeg", b"\xff\xd8 drawn on another machine")


def shown(picture: Picture) -> Message:
    return Message("user", "Read the invoice's fields.", pictures=(picture,))


def test_a_picture_is_named_by_its_digest_or_by_the_name_given_to_it() -> None:
    assert picture_digest(DRAWN) == hashlib.sha256(DRAWN.data).hexdigest()
    assert picture_digest(DRAWN.data) == picture_digest(DRAWN)
    assert key(shown(DRAWN)) != key(shown(DRAWN_ELSEWHERE))
    assert key(shown(DRAWN)) != key(Message("user", "Read the invoice's fields."))
    names = {
        picture_digest(DRAWN): "racun.jpg page 1",
        picture_digest(DRAWN_ELSEWHERE): "racun.jpg page 1",
    }
    named = [
        request_key(
            [shown(picture)], name="explanation", schema=SCHEMA, max_tokens=None, names=names
        )
        for picture in (DRAWN, DRAWN_ELSEWHERE)
    ]
    # The same page drawn on two machines is the same request.
    assert named[0] == named[1]
    assert named[0] != key(shown(DRAWN))


async def test_a_recording_answers_the_same_page_drawn_on_another_machine() -> None:
    names: dict[str, str] = {}
    recording = Recording(Model(), names=names)
    names[picture_digest(DRAWN)] = "racun.jpg page 1"
    answer = await recording.answer([shown(DRAWN)], name="invoice_fields", schema=SCHEMA)
    elsewhere: dict[str, str] = {}
    replaying = Replaying(recording.cassette(finished=True), names=elsewhere)
    elsewhere[picture_digest(DRAWN_ELSEWHERE)] = "racun.jpg page 1"
    assert (
        await replaying.answer([shown(DRAWN_ELSEWHERE)], name="invoice_fields", schema=SCHEMA)
        == answer
    )
    with pytest.raises(LLMError):
        await Replaying(recording.cassette(finished=True)).answer(
            [shown(DRAWN_ELSEWHERE)], name="invoice_fields", schema=SCHEMA
        )


def test_a_cassette_is_saved_and_loaded_sorted(tmp_path: Path) -> None:
    path = tmp_path / "cassettes" / "explanations.json"
    Cassette("groq/openai/gpt-oss-120b", {"b" * 64: "Druga.", "a" * 64: "Prva."}).save(path)
    text = path.read_text(encoding="utf-8")
    assert text.index("a" * 64) < text.index("b" * 64)
    assert "\r" not in text
    assert json.loads(text)["$comment"].startswith("The language model's answers")
    assert Cassette.load(path) == Cassette(
        "groq/openai/gpt-oss-120b", {"a" * 64: "Prva.", "b" * 64: "Druga."}
    )


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("{", "explanations.json: "),
        ('{"model": "m"}', "explanations.json: 'answers'"),
        ('{"model": 1, "answers": {}}', "a model's name and its answers by request"),
        ('{"model": "m", "answers": []}', "a model's name and its answers by request"),
        ('{"model": "m", "answers": {"k": 1}}', "each answer is text"),
        ("[]", "explanations.json: "),
    ],
)
def test_refuses_a_cassette_it_cannot_read(tmp_path: Path, text: str, problem: str) -> None:
    path = tmp_path / "explanations.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(CassetteError, match=problem):
        Cassette.load(path)


async def test_replays_what_is_recorded_and_nothing_else() -> None:
    model = Replaying(Cassette("test/model", {key(): "Zapisan odgovor."}))
    assert model.model == "test/model"
    answer = await model.answer(ASKED, name="explanation", schema=SCHEMA)
    assert answer == "Zapisan odgovor."
    with pytest.raises(LLMError, match="no answer is recorded for this request"):
        await model.answer(ASKED, name="explanation", schema=SCHEMA, max_tokens=10)
    await model.aclose()


async def test_records_only_what_the_cassette_lacks_and_keeps_what_the_run_used() -> None:
    model = Model()
    other = Message("user", "SRB-001 in BT-3")
    held = Cassette("test/model", {key(): "Zapisan odgovor.", "f" * 64: "Zastareo."})
    recording = Recording(model, held)
    assert recording.model == "test/model"

    assert await recording.answer(ASKED, name="explanation", schema=SCHEMA) == "Zapisan odgovor."
    new = await recording.answer([other], name="explanation", schema=SCHEMA)
    again = await recording.answer([other], name="explanation", schema=SCHEMA)

    assert new == again == json.dumps({"answer": "answer 1", "name": "explanation"})
    assert model.asked == [["SRB-001 in BT-3"]]
    assert recording.asked == 1
    # Finished: the answers the run used, and not the one it no longer asks for.
    assert recording.cassette(finished=True).answers == {key(): "Zapisan odgovor.", key(other): new}
    # Stopped before the end: everything held, for the next recording to continue from.
    assert set(recording.cassette(finished=False).answers) == {key(), key(other), "f" * 64}
    assert held.answers == {key(): "Zapisan odgovor.", "f" * 64: "Zastareo."}
    await recording.aclose()
    assert not model.closed  # its owner closes it


async def test_waits_out_a_limit_and_asks_again() -> None:
    model = Model("Groq answered 429, 3 times", "Groq answered 429, 3 times")
    recording = Recording(model, pause=0, patience=0, tries=3)
    answer = await recording.answer(ASKED, name="explanation", schema=SCHEMA)
    assert json.loads(answer)["answer"] == "answer 3"
    assert recording.asked == 3


async def test_stops_at_a_limit_that_does_not_lift_and_keeps_what_it_has() -> None:
    model = Model(*["Groq answered 429, 3 times"] * 3)
    recording = Recording(model, Cassette("test/model", {"a" * 64: "Prva."}), patience=0, tries=3)
    with pytest.raises(RecordingStoppedError, match="429 3 times: its provider's limit"):
        await recording.answer(ASKED, name="explanation", schema=SCHEMA)
    assert recording.asked == 3
    assert recording.cassette(finished=False).answers == {"a" * 64: "Prva."}


async def test_another_failure_of_the_model_is_its_answer_now() -> None:
    model = Model("Groq answered 400 (json_validate_failed)")
    recording = Recording(model, patience=0)
    with pytest.raises(LLMError, match="400"):
        await recording.answer(ASKED, name="explanation", schema=SCHEMA)
    # Nothing is kept for it, so that the next recording asks again.
    assert recording.cassette(finished=False).answers == {}
    assert json.loads(await recording.answer(ASKED, name="explanation", schema=SCHEMA))
