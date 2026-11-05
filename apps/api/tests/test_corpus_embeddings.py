"""Embeddings: Jina's API as the corpus's embedder, what it is sent, how its failures end, and
the settings that choose it."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pydantic import SecretStr, ValidationError

import sef_api.rag.embeddings as embedding_module
from sef_api.rag.embeddings import DIMENSIONS, EmbeddingError, JinaEmbedder, embedder_for

from .conftest import settings_for

KEY = SecretStr("jina_test_key")
NANS = b",".join([b"NaN"] * DIMENSIONS)


def vector(seed: float) -> list[float]:
    return [seed] * DIMENSIONS


def answering(
    handler: Callable[[dict[str, Any]], httpx.Response], requests: list[httpx.Request]
) -> JinaEmbedder:
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(json.loads(request.content))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return JinaEmbedder(KEY, client=client, backoff_seconds=0)


def embeddings(body: dict[str, Any]) -> httpx.Response:
    """Jina's answer: an embedding for each text, listed in reverse to show the order is kept."""
    data = [{"index": index, "embedding": vector(index)} for index in range(len(body["input"]))]
    return httpx.Response(200, json={"model": body["model"], "data": data[::-1]})


async def test_passages_are_sent_in_batches_and_come_back_in_their_order() -> None:
    requests: list[httpx.Request] = []
    embedder = answering(embeddings, requests)

    vectors = await embedder.passages([f"passage {n}" for n in range(35)])

    assert [vector[0] for vector in vectors] == [*range(32), 0, 1, 2]  # 32 to a request
    first = json.loads(requests[0].content)
    assert len(requests) == 2
    assert requests[0].url == JinaEmbedder.URL
    assert requests[0].headers["Authorization"] == "Bearer jina_test_key"
    assert first == {
        "model": "jina-embeddings-v5-text-small",
        "input": [f"passage {n}" for n in range(32)],
        "task": "retrieval.passage",
        "dimensions": DIMENSIONS,
        "normalized": True,
        "embedding_type": "float",
    }
    assert embedder.model == "jina/jina-embeddings-v5-text-small/1024"
    await embedder.aclose()


async def test_a_question_is_embedded_as_a_query() -> None:
    requests: list[httpx.Request] = []
    embedder = answering(embeddings, requests)

    assert await embedder.query("шифра врсте фактуре") == vector(0)
    assert json.loads(requests[0].content)["task"] == "retrieval.query"


async def test_a_busy_or_failing_service_is_asked_again_then_given_up() -> None:
    requests: list[httpx.Request] = []
    answers = iter([httpx.Response(429, headers={"Retry-After": "0"}), httpx.Response(503)])

    def busy_then_well(body: dict[str, Any]) -> httpx.Response:
        return next(answers, None) or embeddings(body)

    assert await answering(busy_then_well, requests).passages(["a"]) == [vector(0)]
    assert len(requests) == 3

    requests.clear()
    with pytest.raises(EmbeddingError, match="Jina answered 502, 4 times"):
        await answering(lambda _body: httpx.Response(502), requests).passages(["a"])
    assert len(requests) == JinaEmbedder.ATTEMPTS


async def test_the_service_is_asked_again_after_the_wait_it_names_or_a_growing_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    waits: list[float] = []

    class Clock:
        @staticmethod
        async def sleep(seconds: float) -> None:
            waits.append(seconds)

    monkeypatch.setattr(embedding_module, "asyncio", Clock)
    answers = iter(
        [
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(429, headers={"Retry-After": "3600"}),
            httpx.Response(503),
        ]
    )

    def handle(request: httpx.Request) -> httpx.Response:
        return next(answers, None) or embeddings(json.loads(request.content))

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    embedder = JinaEmbedder(KEY, client=client, backoff_seconds=0.5)

    assert await embedder.passages(["a"]) == [vector(0)]
    assert waits == [7.0, 60.0, 2.0]  # as asked, at most a minute, then 0.5 s doubled twice


async def test_a_request_that_fails_on_the_way_is_tried_again() -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("no route to host", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    with pytest.raises(EmbeddingError, match=r"the request failed \(ConnectError\), 4 times"):
        await JinaEmbedder(KEY, client=client, backoff_seconds=0).passages(["a"])
    assert attempts == JinaEmbedder.ATTEMPTS


@pytest.mark.parametrize(
    ("answer", "problem"),
    [
        (httpx.Response(401, json={"detail": "Invalid API key"}), "Jina answered 401"),
        (httpx.Response(200, text="not json"), "not a list of embeddings"),
        (httpx.Response(200, json={"data": [{"index": 0}]}), "not a list of embeddings"),
        (httpx.Response(200, json={"data": []}), "0 embeddings for 1 texts"),
        (
            httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.5] * 3}]}),
            "not 1024 numbers",
        ),
        (
            # Python's JSON reads NaN, which no embedding may hold
            httpx.Response(200, content=b'{"data": [{"index": 0, "embedding": [%s]}]}' % NANS),
            "not 1024 numbers",
        ),
    ],
)
async def test_an_answer_that_is_not_the_embeddings_asked_for_is_an_error(
    answer: httpx.Response, problem: str
) -> None:
    with pytest.raises(EmbeddingError, match=problem) as raised:
        await answering(lambda _body: answer, []).passages(["тајни текст"])
    assert "тајни" not in str(raised.value)  # what was sent is never repeated


def test_the_settings_choose_the_embedder() -> None:
    assert embedder_for(settings_for()) is None
    assert embedder_for(settings_for(JINA_API_KEY="jina_key")) is None  # a key alone sends nothing
    jina = embedder_for(settings_for(EMBEDDINGS_PROVIDER="jina", JINA_API_KEY="jina_key"))
    assert isinstance(jina, JinaEmbedder)
    with pytest.raises(ValidationError, match="JINA_API_KEY must be set"):
        settings_for(EMBEDDINGS_PROVIDER="jina")
    with pytest.raises(ValidationError):
        settings_for(EMBEDDINGS_PROVIDER="openai")
