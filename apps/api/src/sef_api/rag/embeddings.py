"""Embeddings: the vectors by which a passage is found by what it means (ADR-0020).

An :class:`Embedder` turns passages, and later the questions asked of them, into vectors of
:data:`DIMENSIONS` numbers. The corpus is embedded when it is ingested, with the provider the
settings name:

- ``EMBEDDINGS_PROVIDER=none``, the default, embeds nothing: passages are then found by their
  keywords and by the rules that cite them, and nothing leaves the server;
- ``EMBEDDINGS_PROVIDER=jina`` calls Jina's embeddings API with ``JINA_API_KEY``.

What is sent is the text of official documents, never an organization's data, and an error says
what went wrong without the text it was about.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Final, Protocol

import httpx

if TYPE_CHECKING:
    from pydantic import SecretStr

    from sef_api.settings import Settings

__all__ = ["DIMENSIONS", "Embedder", "EmbeddingError", "JinaEmbedder", "embedder_for"]

#: How many numbers a vector has: what Jina's v5 small model gives at full size, and BGE-M3, a
#: multilingual model that a server could run itself, gives too.
DIMENSIONS: Final = 1024


class EmbeddingError(Exception):
    """The provider could not embed the texts; the message says why, never what they were."""


class Embedder(Protocol):
    """Something that turns texts into vectors of :data:`DIMENSIONS` numbers."""

    @property
    def model(self) -> str:
        """The provider, the model and the size, stored with every vector it makes: a vector
        is only compared with vectors of the same model."""
        ...

    async def passages(self, texts: Sequence[str]) -> list[list[float]]:
        """The vectors of passages to be searched, in the order of ``texts``."""
        ...

    async def query(self, text: str) -> list[float]:
        """The vector of a question asked of the passages."""
        ...

    async def aclose(self) -> None: ...


class JinaEmbedder:
    """Jina's embeddings API, with its multilingual v5 small model.

    Passages go in batches of :attr:`BATCH`. An answer of 429 or 5xx, or a request that fails
    on the way, is tried again up to :attr:`ATTEMPTS` times, waiting longer each time (or as
    long as ``Retry-After`` asks); any other answer is an :class:`EmbeddingError`.
    """

    URL: Final = "https://api.jina.ai/v1/embeddings"
    NAME: Final = "jina-embeddings-v5-text-small"
    BATCH: Final = 32
    ATTEMPTS: Final = 4
    TIMEOUT_SECONDS: Final = 60.0

    def __init__(
        self,
        api_key: SecretStr,
        *,
        client: httpx.AsyncClient | None = None,
        backoff_seconds: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=self.TIMEOUT_SECONDS)
        self._backoff = backoff_seconds

    @property
    def model(self) -> str:
        return f"jina/{self.NAME}/{DIMENSIONS}"

    async def passages(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.BATCH):
            vectors += await self._embed(texts[start : start + self.BATCH], "retrieval.passage")
        return vectors

    async def query(self, text: str) -> list[float]:
        return (await self._embed([text], "retrieval.query"))[0]

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _embed(self, texts: Sequence[str], task: str) -> list[list[float]]:
        body = {
            "model": self.NAME,
            "input": list(texts),
            "task": task,
            "dimensions": DIMENSIONS,
            "normalized": True,
            "embedding_type": "float",
        }
        headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
        problem = "no answer"
        retry_after: str | None = None
        for attempt in range(self.ATTEMPTS):
            if attempt:
                await asyncio.sleep(self._wait(attempt, retry_after))
                retry_after = None
            try:
                response = await self._client.post(self.URL, json=body, headers=headers)
            except httpx.HTTPError as error:
                problem = f"the request failed ({type(error).__name__})"
                continue
            if response.status_code == httpx.codes.TOO_MANY_REQUESTS or response.is_server_error:
                problem = f"Jina answered {response.status_code}"
                retry_after = response.headers.get("Retry-After")
                continue
            if response.status_code != httpx.codes.OK:
                raise EmbeddingError(f"Jina answered {response.status_code}")
            return _vectors(response, len(texts))
        raise EmbeddingError(f"{problem}, {self.ATTEMPTS} times")

    def _wait(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None and retry_after.isdigit():
            return min(float(retry_after), 60.0)
        return float(self._backoff * 2 ** (attempt - 1))


def _vectors(response: httpx.Response, expected: int) -> list[list[float]]:
    """The vectors of Jina's answer, in the order of the texts, each checked."""
    try:
        data: list[dict[str, Any]] = response.json()["data"]
        ordered = sorted(data, key=lambda item: int(item["index"]))
        vectors = [[float(number) for number in item["embedding"]] for item in ordered]
    except (ValueError, KeyError, TypeError) as error:
        raise EmbeddingError(f"Jina's answer is not a list of embeddings ({error!r})") from None
    if [int(item["index"]) for item in ordered] != list(range(expected)):
        raise EmbeddingError(f"Jina answered {len(vectors)} embeddings for {expected} texts")
    for vector in vectors:
        if len(vector) != DIMENSIONS or not all(math.isfinite(number) for number in vector):
            raise EmbeddingError(f"Jina answered an embedding that is not {DIMENSIONS} numbers")
    return vectors


def embedder_for(settings: Settings) -> Embedder | None:
    """The embedder the settings name, or None when the corpus is not to be embedded."""
    if settings.embeddings_provider == "jina" and settings.jina_api_key is not None:
        return JinaEmbedder(settings.jina_api_key)
    return None
