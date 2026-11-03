from app.domain.ports import AIAdvisor, CategoryInfo
from app.domain.rule_advisor import RuleBasedAdvisor

CATEGORIES = [
    CategoryInfo(1, "Network", ("wifi", "wi-fi", "lan", "signal")),
    CategoryInfo(2, "Application", ("portal", "payment", "error", "lms")),
]


def test_rule_advisor_is_an_ai_advisor_and_picks_the_best_keyword_match() -> None:
    advisor: AIAdvisor = RuleBasedAdvisor()
    result = advisor.classify("Fee payment portal shows error 502", CATEGORIES)
    assert (result.category_id, result.confidence, result.source) == (2, 1.0, "rules")


def test_new_categories_work_immediately_and_unknown_text_gives_no_suggestion() -> None:
    advisor = RuleBasedAdvisor()
    printers = [*CATEGORIES, CategoryInfo(3, "Hardware", ("printer", "toner"))]
    assert advisor.classify("The printer is jammed", printers).category_id == 3
    none = advisor.classify("Something odd happened", CATEGORIES)
    assert (none.category_id, none.confidence) == (None, 0.0)
