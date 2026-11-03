"""Immutable value objects shared by the domain (frozen dataclasses compared by value)."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from app.domain.errors import InvalidUserInputError

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True, slots=True)
class EmailAddress:
    """A syntactically valid, lower-cased email address."""

    value: str

    def __post_init__(self) -> None:
        normalised = self.value.strip().lower()
        if not _EMAIL.match(normalised):
            raise InvalidUserInputError({"email": "Enter a valid email address."})
        object.__setattr__(self, "value", normalised)

    @property
    def domain(self) -> str:
        """The part after ``@`` (used for campus-domain checks)."""
        return self.value.split("@", 1)[1]

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True, init=False)
class SkillSet:
    """A set of normalised skill names.

    A frozenset gives O(1) membership and O(min(m, n)) intersection, which the assignment
    strategies use for skill coverage (blueprint §5.3, §10 Collections).
    """

    _skills: frozenset[str] = field(default_factory=frozenset)

    def __init__(self, names: Iterable[str] = ()) -> None:
        cleaned = {name.strip().lower() for name in names}
        if "" in cleaned:
            raise InvalidUserInputError({"skills": "Skill names must not be blank."})
        object.__setattr__(self, "_skills", frozenset(cleaned))

    @property
    def names(self) -> tuple[str, ...]:
        """Skill names, sorted, as a read-only tuple."""
        return tuple(sorted(self._skills))

    def coverage(self, required: "SkillSet") -> tuple[int, int]:
        """How many of ``required``'s skills this set has: (matched, total)."""
        return len(self._skills & required._skills), len(required._skills)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name.strip().lower() in self._skills

    def __iter__(self) -> Iterator[str]:
        return iter(self.names)

    def __len__(self) -> int:
        return len(self._skills)
