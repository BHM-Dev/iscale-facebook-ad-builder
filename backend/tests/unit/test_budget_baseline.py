from app.api.v1.facebook import _budget_stats


def test_budget_stats_median_max_and_dedupe():
    rows = [("a", 5000), ("b", 15000), ("c", 3000), ("a", 5000), ("d", 0), ("e", None)]
    stats = _budget_stats(rows)
    assert stats == {"median": 50.0, "max": 150.0, "count": 3, "total": 230.0}


def test_budget_stats_even_count_and_empty():
    assert _budget_stats([("a", 2000), ("b", 4000)])["median"] == 30.0
    assert _budget_stats([]) == {"median": None, "max": None, "count": 0, "total": 0}
