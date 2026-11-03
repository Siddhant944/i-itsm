"""Rule-based classification: the deterministic fallback and test double for AIAdvisor (§6.1)."""

import re
from collections.abc import Sequence

from app.domain.ports import AIAdvisor, CategoryInfo, Classification

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
