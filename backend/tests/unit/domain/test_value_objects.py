import dataclasses

import pytest

from app.domain.errors import InvalidUserInputError
from app.domain.value_objects import EmailAddress, SkillSet


def test_email_is_normalised_and_exposes_its_domain() -> None:
    email = EmailAddress("  Asha.R@Hyderabad.BITS-Pilani.ac.in ")
    assert email.value == "asha.r@hyderabad.bits-pilani.ac.in"
    assert email.domain == "hyderabad.bits-pilani.ac.in"
    assert str(email) == email.value


@pytest.mark.parametrize("bad", ["", "no-at-sign", "a@", "@b.com", "a b@c.com", "a@b"])
def test_invalid_email_is_rejected(bad: str) -> None:
    with pytest.raises(InvalidUserInputError) as caught:
        EmailAddress(bad)
    assert "email" in caught.value.field_errors


def test_value_objects_are_immutable_and_compare_by_value() -> None:
    email = EmailAddress("x@y.org")
    with pytest.raises(dataclasses.FrozenInstanceError):
        email.value = "other@y.org"  # type: ignore[misc]
    assert EmailAddress("X@y.org") == email
    assert SkillSet({"Networking"}) == SkillSet({"networking"})


def test_skill_set_normalises_names_and_reports_coverage() -> None:
    skills = SkillSet({" Networking ", "Payments", "payments"})
    assert skills.names == ("networking", "payments")
    assert "NETWORKING" in skills
    assert len(skills) == 2
    assert skills.coverage(SkillSet({"payments", "app-support"})) == (1, 2)
    assert skills.coverage(SkillSet()) == (0, 0)


def test_skill_set_rejects_blank_names() -> None:
    with pytest.raises(InvalidUserInputError):
        SkillSet({"  "})
