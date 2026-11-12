"""Text similarity and the hybrid duplicate score (blueprint §6.2, BR-09).

Text overlap alone misses paraphrases: the brief's own INC101-INC103 share one word between
them. So a duplicate is scored on three signals — how alike the texts are, whether both name
the same service, and how close together they were reported:

    sim(a, b) = β1·cos(e_a, e_b) + β2·[s_a = s_b] + β3·exp(-|t_a - t_b| / τ)

Everything here is pure Python and deterministic. ``TfIdfEmbeddings`` is the offline
``EmbeddingProvider``: the fallback when Gemini is unreachable and the test double.
"""

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.errors import InvalidUserInputError
from app.domain.ports import EmbeddingProvider

# --- §6.2 tunables, defined once ------------------------------------------------------------
#: β1: the weight of text similarity (§6.2).
TEXT_WEIGHT = 0.6
#: β2: the weight of both incidents naming the same service (§6.2).
SERVICE_WEIGHT = 0.25
#: β3: the weight of the two reports being close in time (§6.2).
TIME_WEIGHT = 0.15
#: τ: how fast closeness in time fades (§6.2).
TIME_DECAY = timedelta(hours=2)
#: θ: at or above this the form and the technician are shown a possible duplicate (§6.2).
#: Tuned on tests/fixtures/duplicate_pairs.json by scripts/tune_duplicates.py; the precision,
#: recall and F1 it gives are in docs/testing/duplicates.md.
SUGGEST_THRESHOLD = 0.49
#: θ-high: at or above this the same reporter's repeat is refused with 409 (§6.2). Tuned alike.
REJECT_THRESHOLD = 0.89
#: The same reporter's near-identical ticket is refused only within this long (§6.2).
REPEAT_WINDOW = timedelta(minutes=30)

_WORD = re.compile(r"[a-z0-9]+")
_MIN_STEM = 3
#: Longest first, so "payments" loses "ments" rather than just "s".
_SUFFIXES = (
    "ations",
    "ation",
    "ments",
    "ment",
    "ures",
    "ings",
    "ure",
    "ing",
    "ed",
    "es",
    "s",
)
_STOPWORD_TEXT = (
    "a an and are as at be been but by can cannot could did do does for from had has have "
    "he her his i if in into is it its me my no not of on or our she so that the their "
    "them there they this to too very was we were what when which while who will with "
    "would you your am pm please since still just get got getting keep keeps any some all "
    "also again after before every been being im ive dont doesnt cant isnt wont"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def stem(word: str) -> str:
    """A light suffix stripper: "failing", "failed" and "failure" all become "fail"."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> tuple[str, ...]:
    """Lower-case words, without stop words, stemmed."""
    return tuple(stem(word) for word in _WORD.findall(text.lower()) if word not in _STOPWORDS)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """The cosine of two vectors, 0.0 when either is empty or all zero, clamped to [0, 1].

    Vectors of different lengths come from different models and cannot be compared, which is
    a programming error rather than a zero.
    """
    if len(a) != len(b):
        raise InvalidUserInputError({"vector": "Vectors from different models cannot be compared."})
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return max(0.0, min(1.0, dot / (norm_a * norm_b)))


class TfIdfEmbeddings(EmbeddingProvider):
    """TF-IDF vectors over the texts of one call (D-007: pure Python, no ML dependency).

    Pattern: Strategy (one of the interchangeable ``EmbeddingProvider`` implementations).
    Problem solved: duplicate detection must keep working, deterministically, when Gemini is
    unreachable or no key is configured, and tests need vectors without a network.

    The inverse document frequency depends on the texts being compared, so vectors from two
    calls are not comparable; ``stable`` is False and they are never stored (D-030).
    """

    name = "tfidf"
    model = "tfidf-v1"
    stable = False

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        documents = [Counter(tokenize(text)) for text in texts]
        vocabulary = sorted({term for document in documents for term in document})
        total = len(documents)
        frequency = Counter(term for document in documents for term in document)
        # Smoothed, so a term in every document still counts for something and nothing
        # divides by zero.
        idf = {term: math.log((1 + total) / (1 + frequency[term])) + 1.0 for term in vocabulary}
        vectors: list[tuple[float, ...]] = []
        for document in documents:
            weights = [
                (1.0 + math.log(document[term])) * idf[term] if document[term] else 0.0
                for term in vocabulary
            ]
            norm = math.sqrt(sum(weight * weight for weight in weights))
            vectors.append(tuple(weight / norm for weight in weights) if norm else tuple(weights))
        return vectors


@dataclass(frozen=True, slots=True)
class HybridWeights:
    """β and τ of §6.2. The three weights must sum to 1 so the score stays within 0..1."""

    text: float = TEXT_WEIGHT
    service: float = SERVICE_WEIGHT
    time: float = TIME_WEIGHT
    decay: timedelta = TIME_DECAY

    def __post_init__(self) -> None:
        errors: dict[str, str] = {}
        if min(self.text, self.service, self.time) < 0:
            errors["weights"] = "Weights must not be negative."
        elif not math.isclose(self.text + self.service + self.time, 1.0, abs_tol=1e-9):
            errors["weights"] = "The three weights must sum to 1."
        if self.decay <= timedelta(0):
            errors["decay"] = "The time decay must be positive."
        if errors:
            raise InvalidUserInputError(errors)


@dataclass(frozen=True, slots=True)
class SimilarityScore:
    """One comparison, with the three signals kept so the UI can say why."""

    total: float
    cosine: float
    same_service: bool
    time_closeness: float

    @property
    def reasons(self) -> tuple[str, ...]:
        """Plain words for the "possible duplicate" panel."""
        found = [f"text {round(self.cosine * 100)} % alike"]
        if self.same_service:
            found.append("same service")
        if self.time_closeness >= math.exp(-1):  # within one τ
            found.append("reported close together")
        return tuple(found)


def hybrid_score(
    text_cosine: float,
    *,
    same_service: bool,
    gap: timedelta,
    weights: HybridWeights | None = None,
) -> SimilarityScore:
    """§6.2's sim(a, b). ``gap`` is how far apart the two were reported, in either order."""
    weights = weights or HybridWeights()
    closeness = math.exp(-abs(gap) / weights.decay)
    total = (
        weights.text * text_cosine
        + weights.service * (1.0 if same_service else 0.0)
        + weights.time * closeness
    )
    return SimilarityScore(total, text_cosine, same_service, closeness)


@dataclass(frozen=True, slots=True)
class DuplicateThresholds:
    """θ and θ-high of §6.2, with the window in which a repeat is refused."""

    suggest: float = SUGGEST_THRESHOLD
    reject: float = REJECT_THRESHOLD
    repeat_window: timedelta = REPEAT_WINDOW

    def __post_init__(self) -> None:
        if not 0.0 < self.suggest <= self.reject <= 1.0:
            raise InvalidUserInputError(
                {"thresholds": "Need 0 < suggest <= reject <= 1 (blueprint §6.2)."}
            )

    def suggests(self, score: SimilarityScore) -> bool:
        return score.total >= self.suggest

    def rejects(self, score: SimilarityScore, gap: timedelta) -> bool:
        """True for a near-identical ticket inside the repeat window; the caller checks who."""
        return score.total >= self.reject and abs(gap) <= self.repeat_window


@dataclass(frozen=True, slots=True)
class PairMetrics:
    """Precision, recall and F1 of a threshold over labelled pairs (§6.2, §13)."""

    threshold: float
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else 1.0

    @property
    def recall(self) -> float:
        actual = self.true_positives + self.false_negatives
        return self.true_positives / actual if actual else 1.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0


def evaluate(scored: Sequence[tuple[float, bool]], threshold: float) -> PairMetrics:
    """Count what a threshold gets right over ``(score, is_duplicate)`` pairs."""
    tp = sum(1 for score, label in scored if score >= threshold and label)
    fp = sum(1 for score, label in scored if score >= threshold and not label)
    fn = sum(1 for score, label in scored if score < threshold and label)
    return PairMetrics(threshold, tp, fp, fn)


def best_threshold(scored: Sequence[tuple[float, bool]], *, step: float = 0.01) -> PairMetrics:
    """The threshold with the highest F1; ties go to the higher one (fewer false alarms)."""
    steps = round(1 / step)
    candidates = [evaluate(scored, round(i * step, 4)) for i in range(1, steps + 1)]
    return max(candidates, key=lambda metrics: (round(metrics.f1, 9), metrics.threshold))


@dataclass(frozen=True, slots=True)
class LabelledPair:
    """Two reports and what a person says about them, for tuning θ and θ-high (§6.2)."""

    a: str
    b: str
    same_service: bool
    gap: timedelta
    duplicate: bool
    repeat: bool = False


def score_pairs(
    pairs: Sequence[LabelledPair],
    provider: EmbeddingProvider,
    weights: HybridWeights | None = None,
) -> list[SimilarityScore]:
    """The hybrid score of every pair, embedding all their texts as one corpus."""
    vectors = provider.embed([text for pair in pairs for text in (pair.a, pair.b)])
    return [
        hybrid_score(
            cosine(vectors[2 * index], vectors[2 * index + 1]),
            same_service=pair.same_service,
            gap=pair.gap,
            weights=weights,
        )
        for index, pair in enumerate(pairs)
    ]


@dataclass(frozen=True, slots=True)
class StoredEmbedding:
    """One incident's vector, tagged with the provider and model that made it (§6.2, §9)."""

    incident_id: str
    provider: str
    model: str
    vector: tuple[float, ...]
    created_at: datetime
