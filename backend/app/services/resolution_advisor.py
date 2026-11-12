"""Suggested resolution: how similar incidents were fixed (blueprint §6.1, P4.7).

The three most similar resolved incidents are retrieved and shown with their resolutions. When
a summariser is configured (Gemini) it adds a short suggestion that may cite those three and
nothing else; when it is not, or it fails, or it cites anything else, the list stands alone.
Retrieval is the offline TF-IDF, so the list itself never depends on a network.
"""

import logging
from dataclasses import dataclass

from app.core.clock import Clock
from app.domain.errors import InfrastructureError
from app.domain.incident import Incident
from app.domain.ports import PastFix, ResolutionSummarizer
from app.domain.repositories import UnitOfWork
from app.domain.search import IncidentQuery
from app.domain.similarity import TfIdfEmbeddings, cosine
from app.domain.states import RESOLVED_STATUSES
from app.services.duplicates import text_of

logger = logging.getLogger(__name__)

#: How many past fixes are shown and given to the summariser (§6.1: "the three most similar").
TOP_FIXES = 3
#: The most recent resolved incidents read as candidates; bounds the work per request.
CANDIDATE_LIMIT = 300
#: Text similarity counts most; the same service is a useful tie-breaker.
TEXT_WEIGHT, SERVICE_WEIGHT = 0.8, 0.2
#: Below this a past incident shares too little with the ticket to be worth showing.
MIN_TEXT_SIMILARITY = 0.1


@dataclass(frozen=True, slots=True)
class SuggestedFix:
    incident: Incident
    score: float

    @property
    def resolution(self) -> str:
        return self.incident.resolution.summary if self.incident.resolution else ""


@dataclass(frozen=True, slots=True)
class ResolutionSuggestion:
    fixes: tuple[SuggestedFix, ...]
    #: The summariser's suggestion, citing only ``fixes``; None without one.
    summary: str | None = None
    source: str | None = None


class ResolutionAdvisor:
    """Finds the past fixes most like an incident and, optionally, summarises them."""

    def __init__(
        self, uow: UnitOfWork, clock: Clock, summarizer: ResolutionSummarizer | None = None
    ) -> None:
        self.__uow = uow
        self.__clock = clock
        self.__summarizer = summarizer
        self.__embeddings = TfIdfEmbeddings()

    def suggest(self, incident: Incident) -> ResolutionSuggestion:
        fixes = self.__retrieve(incident)
        if not fixes or self.__summarizer is None:
            return ResolutionSuggestion(fixes)
        ticket = text_of(incident.title, incident.description)
        try:
            summary = self.__summarizer.summarize(
                ticket,
                [PastFix(f.incident.id, f.incident.title, f.resolution) for f in fixes],
            )
        except InfrastructureError as error:
            logger.warning("no summary for %s: %s", incident.id, error.message)
            return ResolutionSuggestion(fixes)
        return ResolutionSuggestion(fixes, summary, self.__summarizer.name)

    def __retrieve(self, incident: Incident) -> tuple[SuggestedFix, ...]:
        query = IncidentQuery(
            statuses=tuple(sorted(RESOLVED_STATUSES)),
            category_ids=() if incident.category_id is None else (incident.category_id,),
            limit=CANDIDATE_LIMIT,
        )
        past = [
            other
            for other in self.__uow.incidents.search(query, self.__clock.now()).items
            if other.id != incident.id and other.resolution is not None
        ]
        if not past:
            return ()
        vectors = self.__embeddings.embed(
            [
                text_of(incident.title, incident.description),
                *(
                    f"{text_of(p.title, p.description)}\n{p.resolution.summary}"
                    for p in past
                    if p.resolution
                ),
            ]
        )
        scored: list[SuggestedFix] = []
        for other, vector in zip(past, vectors[1:], strict=True):
            text = cosine(vectors[0], vector)
            if text < MIN_TEXT_SIMILARITY:
                continue
            same = 1.0 if other.service_id == incident.service_id else 0.0
            scored.append(SuggestedFix(other, TEXT_WEIGHT * text + SERVICE_WEIGHT * same))
        scored.sort(key=lambda f: (-f.score, f.incident.id))
        return tuple(scored[:TOP_FIXES])
