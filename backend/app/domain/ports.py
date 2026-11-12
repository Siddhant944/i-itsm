"""Interfaces for external services (blueprint §6, §8). Adapters in ``app.adapters`` implement
them, each with a deterministic fallback or fake, so the domain never imports an SDK.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    category_id: int
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Classification:
    category_id: int | None
    confidence: float  # 0..1, shown to the user; suggestions are never applied silently
    source: str  # "gemini" or "rules"


class AIAdvisor(ABC):
    """Suggests a category for an incident description."""

    @abstractmethod
    def classify(self, text: str, categories: Sequence[CategoryInfo]) -> Classification: ...


class EmbeddingProvider(ABC):
    """Turns texts into vectors for similarity (Gemini, or TF-IDF offline; §6.2).

    ``name`` and ``model`` tag every stored vector, so one from another model is never
    compared with it. ``stable`` says whether vectors from separate calls are comparable,
    which is what makes them worth storing per incident.
    """

    name: str
    model: str
    stable: bool

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        """One vector per text, in order. Raise NetworkFailureError when unreachable."""


@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    recipient_id: int
    subject: str
    body: str
    incident_id: str | None = None


class EmailSender(ABC):
    """Hands one message to whatever can deliver it: SMTP, or the console fallback (§5.4)."""

    name: str

    @abstractmethod
    def send(self, to: str, subject: str, body: str) -> None:
        """Deliver, or raise NetworkFailureError so the caller can retry."""


class NotificationChannel(ABC):
    """In-app, email or Telegram delivery; a new channel is one class (blueprint §5.4)."""

    name: str

    @abstractmethod
    def send(self, message: OutgoingMessage) -> None:
        """Deliver or raise NetworkFailureError (the caller retries and never rolls back)."""


@dataclass(frozen=True, slots=True)
class VerifiedIdentity:
    email: str
    full_name: str
    hosted_domain: str | None


class IdentityVerifier(ABC):
    """Verifies a Google ID token (the ``hd`` claim is checked by the caller)."""

    @abstractmethod
    def verify(self, token: str) -> VerifiedIdentity: ...
