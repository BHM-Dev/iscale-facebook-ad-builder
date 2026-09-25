from app.api.v1.research import _copilot_query_suggestions, _plan_research_copilot_question


def test_copilot_plan_extracts_owner_operator_runtime_and_activity():
    plan = _plan_research_copilot_question(
        "Show active commercial auto ads for owner-operators running 30+ days",
        "commercial_insurance",
    )
    assert plan["segments"] == ["owner-operators"]
    assert plan["active_only"] is True
    assert plan["min_running_days"] == 30
    assert plan["captured_within_days"] is None


def test_copilot_plan_keeps_last_days_distinct_from_runtime():
    plan = _plan_research_copilot_question(
        "Find best performing trucker ads from the last 30 days",
        "commercial_insurance",
    )
    assert plan["segments"] == ["truckers"]
    assert plan["captured_within_days"] == 30
    assert plan["min_running_days"] is None


def test_copilot_suggestions_broaden_runtime_without_claiming_performance():
    question = "Show active commercial auto ads for owner-operators running 30+ days"
    plan = _plan_research_copilot_question(question, "commercial_insurance")
    suggestions = _copilot_query_suggestions(question, plan, "Commercial Insurance")
    assert suggestions
    assert any("runtime" in suggestion["reason"] for suggestion in suggestions)
    assert all("best performing" not in suggestion["question"].casefold() for suggestion in suggestions)
