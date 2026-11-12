"""Finding the incidents a report may be a duplicate of (blueprint §6.2, BR-09).

The detector compares a report with the incidents somebody is still dealing with, using the
hybrid score of ``app.domain.similarity``. Vectors come from the configured
``EmbeddingProvider``; when it cannot be reached the TF-IDF fallback answers instead, so the
feature degrades to a weaker comparison rather than to an error.

A stable provider's vectors (Gemini) are stored per incident and reused. TF-IDF vectors are
recomputed over the recent incidents each time, because their weights depend on that corpus
(D-030).
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.core.clock import Clock
from app.domain.errors import NetworkFailureError
from app.domain.incident import Incident
from app.domain.ports import EmbeddingProvider
from app.domain.repositories import UnitOfWork
from app.domain.search import IncidentQuery
from app.domain.similarity import (
    DuplicateThresholds,
    HybridWeights,
    SimilarityScore,
    StoredEmbedding,
    TfIdfEmbeddings,
    cosine,
    hybrid_score,
)
from app.domain.states import IncidentStatus

logger = logging.getLogger(__name__)

#: How far back a report is compared. Past this an open incident is too old for the time
#: signal to matter and the list would only grow (§6.2).
CANDIDATE_WINDOW = timedelta(days=14)
#: The most recent incidents read as the TF-IDF corpus; also bounds the work per request.
CORPUS_LIMIT = 300
#: How many possible duplicates anyone is shown, and so may follow (§6.2: a hint, not a
#: search; BR-01 keeps the rest of other people's incidents out of sight).
MAX_SUGGESTIONS = 3
#: Only an incident somebody is still dealing with can be "followed instead" (§6.2).
COMPARABLE_STATUSES = frozenset(
    {
        IncidentStatus.NEW,
        IncidentStatus.CLASSIFIED,
        IncidentStatus.ASSIGNED,
        IncidentStatus.ACKNOWLEDGED,
        IncidentStatus.IN_PROGRESS,
        IncidentStatus.ON_HOLD,
    }
)


def text_of(title: str, description: str) -> str:
    """What is embedded for an incident: its title and its description."""
    return f"{title}\n{description}".strip()


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """An open incident the report resembles, with the score and how far apart they are."""

    incident: Incident
    score: SimilarityScore
    gap: timedelta


@dataclass(frozen=True, slots=True)
class DuplicateCheck:
    """What one comparison found: candidates at or above θ, best first."""

    candidates: tuple[DuplicateCandidate, ...]
    provider: str
    #: The report's own vector when the provider's vectors are worth storing, else None.
    vector: tuple[float, ...] | None = None
    model: str = ""

    def top(self, count: int = MAX_SUGGESTIONS) -> "DuplicateCheck":
        """The same check, keeping only the ``count`` best candidates."""
        return replace(self, candidates=self.candidates[:count])

    @property
    def best(self) -> DuplicateCandidate | None:
        return self.candidates[0] if self.candidates else None


class DuplicateDetector:
    """Scores a report against the open incidents and keeps the ones worth showing."""

    def __init__(
        self,
        uow: UnitOfWork,
        clock: Clock,
        provider: EmbeddingProvider | None = None,
        *,
        fallback: EmbeddingProvider | None = None,
        thresholds: DuplicateThresholds | None = None,
        weights: HybridWeights | None = None,
    ) -> None:
        self.__uow = uow
        self.__clock = clock
        self.__fallback = fallback or TfIdfEmbeddings()
        self.__provider = provider or self.__fallback
        self.__thresholds = thresholds or DuplicateThresholds()
        self.__weights = weights or HybridWeights()

    @property
    def thresholds(self) -> DuplicateThresholds:
        return self.__thresholds

    def check(
        self,
        *,
        title: str,
        description: str,
        service_id: int | None,
        reported_at: datetime,
        exclude_id: str | None = None,
    ) -> DuplicateCheck:
        """The open incidents this text resembles at or above θ, best first.

        ``exclude_id`` is the incident the text belongs to, when it already exists.
        """
        recent = self.__recent(reported_at, exclude_id)
        comparable = [i for i in recent if i.status in COMPARABLE_STATUSES]
        text = text_of(title, description)
        if not comparable or not text:
            return DuplicateCheck((), self.__provider.name)

        try:
            provider = self.__provider
            query, vectors, storable = self.__embed(provider, text, comparable, recent)
        except NetworkFailureError:
            if self.__provider is self.__fallback:
                raise
            logger.warning(
                "embedding provider %s unreachable; using %s",
                self.__provider.name,
                self.__fallback.name,
            )
            provider = self.__fallback
            query, vectors, storable = self.__embed(provider, text, comparable, recent)

        found: list[DuplicateCandidate] = []
        for incident, vector in zip(comparable, vectors, strict=True):
            gap = abs(reported_at - incident.created_at)
            score = hybrid_score(
                cosine(query, vector),
                same_service=incident.service_id == service_id,
                gap=gap,
                weights=self.__weights,
            )
            if self.__thresholds.suggests(score):
                found.append(DuplicateCandidate(incident, score, gap))
        found.sort(key=lambda c: (-c.score.total, c.incident.created_at, c.incident.id))
        return DuplicateCheck(
            tuple(found), provider.name, query if storable else None, provider.model
        )

    def remember(self, incident_id: str, check: DuplicateCheck) -> None:
        """Store the report's vector for later comparisons, when it is worth storing (§9)."""
        if check.vector is None:
            return
        self.__uow.embeddings.put(
            StoredEmbedding(
                incident_id, check.provider, check.model, check.vector, self.__clock.now()
            )
        )

    # ------------------------------------------------------------ internals
    def __recent(self, reported_at: datetime, exclude_id: str | None) -> list[Incident]:
        page = self.__uow.incidents.search(
            IncidentQuery(created_from=reported_at - CANDIDATE_WINDOW, limit=CORPUS_LIMIT),
            self.__clock.now(),
        )
        return [incident for incident in page.items if incident.id != exclude_id]

    def __embed(
        self,
        provider: EmbeddingProvider,
        text: str,
        comparable: Sequence[Incident],
        recent: Sequence[Incident],
    ) -> tuple[tuple[float, ...], list[tuple[float, ...]], bool]:
        """The report's vector and one per comparable incident, in order."""
        if not provider.stable:
            # The corpus is every recent incident, so common words are weighed down even
            # when only a few incidents are open.
            others = [i for i in recent if i.status not in COMPARABLE_STATUSES]
            texts = [text, *(text_of(i.title, i.description) for i in (*comparable, *others))]
            vectors = provider.embed(texts)
            return vectors[0], vectors[1 : 1 + len(comparable)], False

        stored = dict(
            self.__uow.embeddings.get_many(
                [i.id for i in comparable], provider=provider.name, model=provider.model
            )
        )
        missing = [i for i in comparable if i.id not in stored]
        fresh = provider.embed([text, *(text_of(i.title, i.description) for i in missing)])
        for incident, vector in zip(missing, fresh[1:], strict=True):
            stored[incident.id] = vector
            self.__uow.embeddings.put(
                StoredEmbedding(
                    incident.id, provider.name, provider.model, vector, self.__clock.now()
                )
            )
        return fresh[0], [stored[i.id] for i in comparable], True
