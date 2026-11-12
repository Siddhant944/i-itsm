"""Gemini embeddings behind the ``EmbeddingProvider`` port (blueprint §6.2, D-013).

Pattern: Adapter. Problem solved: duplicate detection wants "texts in, vectors out" and must
not know the Google Gen AI SDK, its response shapes or its exceptions. This class is the only
place that does; every failure leaves as ``NetworkFailureError``, which is the detector's cue
to fall back to TF-IDF.

Gemini's vectors do not depend on what else is in the call, so they are ``stable`` and are
stored per incident, tagged with the model that made them.
"""

import logging
from collections.abc import Callable, Sequence

from app.domain.errors import NetworkFailureError
from app.domain.ports import EmbeddingProvider

logger = logging.getLogger(__name__)

#: Texts per request; the embedding endpoint takes a bounded batch.
BATCH_SIZE = 50
#: One request may take this long before it counts as a failure (§6.1: a timeout, one retry).
TIMEOUT_SECONDS = 8.0
ATTEMPTS = 2
#: Tells the model the vectors will be compared with each other, not used for retrieval.
TASK_TYPE = "SEMANTIC_SIMILARITY"

#: Embeds one batch of texts. The real one calls the SDK; tests pass a fake.
EmbedCall = Callable[[Sequence[str]], Sequence[Sequence[float]]]


class GeminiEmbeddings(EmbeddingProvider):
    """Embeds texts with a Gemini embedding model, in batches, retrying once."""

    name = "gemini"
    stable = True

    def __init__(self, model: str, call: EmbedCall) -> None:
        self.model = model
        self.__call = call

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            vectors.extend(self.__embed_batch(batch))
        return vectors

    def __embed_batch(self, batch: Sequence[str]) -> list[tuple[float, ...]]:
        last: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            try:
                found = [tuple(float(x) for x in vector) for vector in self.__call(batch)]
            except Exception as error:
                last = error
                logger.warning(
                    "Gemini embedding attempt %s failed: %s", attempt, type(error).__name__
                )
                continue
            if len(found) != len(batch) or any(not vector for vector in found):
                # Not worth a retry: the service answered, just not with what was asked.
                raise NetworkFailureError("The embedding service returned an unusable answer.")
            return found
        raise NetworkFailureError("The embedding service could not be reached.") from last


def sdk_call(api_key: str, model: str, timeout_seconds: float = TIMEOUT_SECONDS) -> EmbedCall:
    """The real ``EmbedCall``: one ``embed_content`` request through the Google Gen AI SDK.

    The client is built on first use, so starting the application never needs the network.
    """
    from google import genai
    from google.genai import types

    client: genai.Client | None = None

    def call(texts: Sequence[str]) -> Sequence[Sequence[float]]:
        nonlocal client
        if client is None:
            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
            )
        response = client.models.embed_content(
            model=model,
            contents=list(texts),
            config=types.EmbedContentConfig(task_type=TASK_TYPE),
        )
        return [embedding.values or [] for embedding in response.embeddings or []]

    return call


def gemini_embeddings(api_key: str, model: str) -> GeminiEmbeddings:
    """The provider the composition root wires when a key and a model are configured."""
    return GeminiEmbeddings(model, sdk_call(api_key, model))
