"""The Gemini embeddings adapter (blueprint §6.2), against a fake call: no network, no key."""

from collections.abc import Sequence

import pytest
from pydantic import SecretStr

from app.adapters.gemini_embeddings import BATCH_SIZE, GeminiEmbeddings, gemini_embeddings
from app.core.config import Settings
from app.domain.errors import NetworkFailureError
from app.domain.similarity import TfIdfEmbeddings
from app.main import embedding_provider


class FakeCall:
    """Returns ``[len(text), 1.0]`` per text, after failing ``failures`` times."""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.batches: list[list[str]] = []

    def __call__(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        self.batches.append(list(texts))
        if self.failures:
            self.failures -= 1
            raise TimeoutError("slow")
        return [[float(len(text)), 1.0] for text in texts]


def test_vectors_come_back_in_order_as_tuples_and_are_worth_storing() -> None:
    provider = GeminiEmbeddings("embed-x", FakeCall())
    assert provider.embed(["a", "abc"]) == [(1.0, 1.0), (3.0, 1.0)]
    assert (provider.name, provider.model, provider.stable) == ("gemini", "embed-x", True)
    assert provider.embed([]) == []


def test_a_long_list_is_sent_in_batches() -> None:
    call = FakeCall()
    texts = [f"text {n}" for n in range(BATCH_SIZE + 3)]
    assert len(GeminiEmbeddings("m", call).embed(texts)) == BATCH_SIZE + 3
    assert [len(batch) for batch in call.batches] == [BATCH_SIZE, 3]


def test_one_failure_is_retried_and_a_second_is_a_network_failure() -> None:
    once = FakeCall(failures=1)
    assert GeminiEmbeddings("m", once).embed(["a"]) == [(1.0, 1.0)]
    assert len(once.batches) == 2

    twice = FakeCall(failures=2)
    with pytest.raises(NetworkFailureError):
        GeminiEmbeddings("m", twice).embed(["a"])
    assert len(twice.batches) == 2  # one retry, no more (§6.1)


@pytest.mark.parametrize("answer", [[], [[1.0], [2.0]], [[]]])
def test_an_answer_of_the_wrong_shape_is_refused_without_a_retry(
    answer: list[list[float]],
) -> None:
    calls: list[int] = []

    def call(texts: Sequence[str]) -> Sequence[Sequence[float]]:
        calls.append(len(texts))
        return answer

    with pytest.raises(NetworkFailureError):
        GeminiEmbeddings("m", call).embed(["only one"])
    assert calls == [1]


def test_gemini_is_wired_only_when_a_key_and_a_model_are_configured(settings: Settings) -> None:
    """Building the provider needs no network: the SDK client is made on first use."""
    assert isinstance(embedding_provider(settings), TfIdfEmbeddings)
    keyed = settings.model_copy(update={"gemini_api_key": SecretStr("placeholder")})
    assert isinstance(embedding_provider(keyed), TfIdfEmbeddings)  # no model named
    both = keyed.model_copy(update={"gemini_embedding_model": "embed-x"})
    provider = embedding_provider(both)
    assert isinstance(provider, GeminiEmbeddings)
    assert provider.model == "embed-x"
    assert gemini_embeddings("placeholder", "embed-y").model == "embed-y"
