"""Text similarity and the hybrid duplicate score (blueprint §6.2, BR-09)."""

import json
import math
from datetime import timedelta
from pathlib import Path

import pytest

from app.domain.errors import InvalidUserInputError
from app.domain.similarity import (
    REJECT_THRESHOLD,
    SUGGEST_THRESHOLD,
    DuplicateThresholds,
    HybridWeights,
    LabelledPair,
    TfIdfEmbeddings,
    best_threshold,
    cosine,
    evaluate,
    hybrid_score,
    score_pairs,
    stem,
    tokenize,
)

MIN = timedelta(minutes=1)
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "duplicate_pairs.json"
#: The brief's own example of incidents "the system may identify as potentially related".
INC101 = "Payment application unavailable"
INC102 = "Payment transaction failing"
INC103 = "Unable to make payment"


def labelled_pairs() -> list[LabelledPair]:
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return [
        LabelledPair(
            p["a"],
            p["b"],
            p["same_service"],
            p["minutes_apart"] * MIN,
            p["duplicate"],
            p.get("repeat", False),
        )
        for p in raw["pairs"]
    ]


# ------------------------------------------------------------------ text
def test_tokens_are_lowercase_stemmed_and_without_stop_words() -> None:
    assert tokenize("The payments are FAILING, and it failed!") == ("pay", "fail", "fail")
    assert stem("failure") == "fail"
    assert stem("bus") == "bus"  # never stemmed down to nothing


def test_cosine_is_one_for_the_same_direction_and_zero_for_nothing_shared() -> None:
    assert cosine((1.0, 2.0), (2.0, 4.0)) == pytest.approx(1.0)
    assert cosine((1.0, 0.0), (0.0, 1.0)) == 0.0
    assert cosine((0.0, 0.0), (1.0, 1.0)) == 0.0
    assert cosine((), ()) == 0.0


def test_vectors_of_different_models_are_refused_rather_than_compared() -> None:
    with pytest.raises(InvalidUserInputError):
        cosine((1.0, 0.0), (1.0, 0.0, 0.0))


def test_tfidf_is_deterministic_normalised_and_not_storable() -> None:
    provider = TfIdfEmbeddings()
    texts = ["Fee portal down", "Fee portal is down!", "Projector broken", ""]
    first, second = provider.embed(texts), provider.embed(texts)
    assert first == second
    assert cosine(first[0], first[1]) == pytest.approx(1.0)
    assert cosine(first[0], first[2]) == 0.0
    assert math.sqrt(sum(x * x for x in first[0])) == pytest.approx(1.0)
    assert not any(first[3])  # an empty text is the zero vector, not an error
    assert provider.stable is False


def test_a_rare_word_counts_for_more_than_a_common_one() -> None:
    corpus = ["portal down", "portal slow", "portal login", "portal projector"]
    vectors = TfIdfEmbeddings().embed(
        ["portal projector", "portal fees", "campus projector", *corpus]
    )
    assert cosine(vectors[0], vectors[2]) > cosine(vectors[0], vectors[1])


# ------------------------------------------------------------------ the hybrid score
def test_BR09_the_score_is_the_blueprints_formula() -> None:
    score = hybrid_score(0.5, same_service=True, gap=timedelta(hours=2))
    assert score.total == pytest.approx(0.6 * 0.5 + 0.25 + 0.15 * math.exp(-1))
    assert hybrid_score(1.0, same_service=True, gap=timedelta(0)).total == pytest.approx(1.0)
    assert hybrid_score(0.0, same_service=False, gap=timedelta(days=30)).total == pytest.approx(
        0.0, abs=1e-9
    )


def test_BR09_the_gap_counts_the_same_in_either_order() -> None:
    assert hybrid_score(0.4, same_service=False, gap=-30 * MIN) == hybrid_score(
        0.4, same_service=False, gap=30 * MIN
    )


def test_BR09_the_reasons_read_in_plain_words() -> None:
    assert hybrid_score(0.42, same_service=True, gap=5 * MIN).reasons == (
        "text 42 % alike",
        "same service",
        "reported close together",
    )
    assert hybrid_score(0.9, same_service=False, gap=timedelta(days=2)).reasons == (
        "text 90 % alike",
    )


def test_weights_must_sum_to_one_and_the_decay_must_be_positive() -> None:
    with pytest.raises(InvalidUserInputError):
        HybridWeights(text=0.7, service=0.25, time=0.15)
    with pytest.raises(InvalidUserInputError):
        HybridWeights(decay=timedelta(0))
    with pytest.raises(InvalidUserInputError):
        HybridWeights(text=1.2, service=-0.2, time=0.0)


def test_BR09_text_overlap_alone_would_miss_the_briefs_own_example() -> None:
    """§6.2: a 60 % text rule links none of INC101-INC103; the hybrid links all three."""
    pairs = [
        LabelledPair(INC101, INC102, True, 6 * MIN, True),
        LabelledPair(INC101, INC103, True, 11 * MIN, True),
        LabelledPair(INC102, INC103, True, 5 * MIN, True),
    ]
    scores = score_pairs(labelled_pairs() + pairs, TfIdfEmbeddings())[-3:]
    thresholds = DuplicateThresholds()
    assert all(score.cosine < 0.6 for score in scores)
    assert all(thresholds.suggests(score) for score in scores)


# ------------------------------------------------------------------ thresholds
def test_BR09_a_repeat_is_refused_only_when_near_identical_and_within_30_minutes() -> None:
    thresholds = DuplicateThresholds()
    near = hybrid_score(0.95, same_service=True, gap=10 * MIN)
    alike = hybrid_score(0.6, same_service=True, gap=10 * MIN)
    assert thresholds.rejects(near, 10 * MIN)
    assert thresholds.rejects(near, 30 * MIN)  # the window includes its edge
    assert not thresholds.rejects(near, 30 * MIN + timedelta(microseconds=1))
    assert not thresholds.rejects(alike, 10 * MIN)
    assert thresholds.suggests(alike)


def test_thresholds_must_be_ordered() -> None:
    with pytest.raises(InvalidUserInputError):
        DuplicateThresholds(suggest=0.9, reject=0.8)
    with pytest.raises(InvalidUserInputError):
        DuplicateThresholds(suggest=0.0)


def test_precision_recall_and_f1_are_counted_from_the_labels() -> None:
    scored = [(0.9, True), (0.8, False), (0.7, True), (0.2, True), (0.1, False)]
    metrics = evaluate(scored, 0.5)
    assert (metrics.true_positives, metrics.false_positives, metrics.false_negatives) == (2, 1, 1)
    assert metrics.precision == pytest.approx(2 / 3)
    assert metrics.recall == pytest.approx(2 / 3)
    assert metrics.f1 == pytest.approx(2 / 3)
    assert evaluate([], 0.5).f1 == pytest.approx(1.0)
    assert best_threshold(scored).threshold == pytest.approx(0.2)


def test_BR09_the_thresholds_in_use_are_the_ones_tuned_on_the_labelled_pairs() -> None:
    """§6.2: θ and θ-high maximise F1 on the labelled pairs. Change the pairs, retune."""
    pairs = labelled_pairs()
    assert len(pairs) >= 50
    scores = score_pairs(pairs, TfIdfEmbeddings())
    theta = best_threshold([(s.total, p.duplicate) for s, p in zip(scores, pairs, strict=True)])
    theta_high = best_threshold([(s.total, p.repeat) for s, p in zip(scores, pairs, strict=True)])
    assert theta.threshold == pytest.approx(SUGGEST_THRESHOLD)
    assert theta_high.threshold == pytest.approx(REJECT_THRESHOLD)
    assert theta.f1 >= 0.9
    assert theta_high.precision == pytest.approx(1.0)  # nobody is wrongly refused
