"""Rule-based classification: the deterministic fallback and test double for AIAdvisor (§6.1)."""

import logging
import re
from collections.abc import Sequence

from app.domain.errors import InfrastructureError
from app.domain.ports import AIAdvisor, CategoryInfo, Classification

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]+")
FULL_CONFIDENCE_HITS = 3  # three keyword hits give confidence 1.0


class RuleBasedAdvisor(AIAdvisor):
    """Picks the category whose keywords appear most often; ties go to the lower ID."""

    def classify(self, text: str, categories: Sequence[CategoryInfo]) -> Classification:
        words = _WORD.findall(text.lower())
        joined = " ".join(words)
        best: tuple[int, int] | None = None  # (hits, -category_id)
        for category in categories:
            hits = sum(1 for keyword in category.keywords if keyword.lower() in joined)
            if hits and (best is None or (hits, -category.category_id) > best):
                best = (hits, -category.category_id)
        if best is None:
            return Classification(None, 0.0, "rules")
        hits, negative_id = best
        return Classification(-negative_id, min(1.0, hits / FULL_CONFIDENCE_HITS), "rules")


class FallbackAdvisor(AIAdvisor):
    """Asks the primary advisor and falls back to another when it cannot answer (§6.1).

    Pattern: Proxy. Problem solved: the demo and the campus must keep classifying when Gemini
    is unreachable, slow or answers nonsense; callers keep one advisor and never see the
    outage, only the ``source`` of the answer they got.
    """

    def __init__(self, primary: AIAdvisor, fallback: AIAdvisor | None = None) -> None:
        self.__primary = primary
        self.__fallback = fallback or RuleBasedAdvisor()

    def classify(self, text: str, categories: Sequence[CategoryInfo]) -> Classification:
        try:
            return self.__primary.classify(text, categories)
        except InfrastructureError as error:
            logger.warning("classifier unavailable (%s); using keyword rules", error.message)
            return self.__fallback.classify(text, categories)
