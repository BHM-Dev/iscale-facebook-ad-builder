from types import SimpleNamespace

from app.services.morning_digest import close_lines, raise_lines


def _p(name, action, profit, frm=6000, to=7200):
    return SimpleNamespace(action=action, adset_name=name, fb_account_id="act_1", fb_adset_id="9",
                           action_params={"from_cents": frm, "to_cents": to},
                           evidence={"why": f"why {name}", "totals_7d": {"profit": profit}})


def test_raises_ranked_by_7d_profit_and_capped_at_three():
    rows = [_p("A", "budget_increase", 50), _p("B", "budget_increase", 400), _p("C", "pause", 999),
            _p("D", "budget_increase", 200), _p("E", "budget_increase", 100)]
    lines = raise_lines(rows)
    assert lines[0].startswith("*Budget raises worth making (4 open, top 3)")
    assert lines[1].endswith("why B") and "|B>" in lines[1] and "|D>" in lines[2] and "|E>" in lines[3]
    assert "$60 → $72/day" in lines[1]
    assert lines[-1].startswith("…and 1 more")
    assert not any("|C>" in line for line in lines)            # pauses are never listed as raises


def test_close_lines_handles_unavailable_and_available():
    assert "revenue not in yet" in close_lines({"combined": {"day": "2026-11-10", "available": False}}, {})[0]
    close = {"combined": {"day": "2026-11-10", "available": True, "profit": -125.4, "spend": 6007, "roas": 0.98,
                          "leads": 157, "mtd": {"profit": 5153, "pace": 25767, "last_month_profit": 20000}},
             "accounts": [{"account_id": "act_a", "available": True, "profit": 100},
                          {"account_id": "act_b", "available": True, "profit": -225}]}
    lines = close_lines(close, {"act_a": "RHO Commercial", "act_b": "RHO 4"})
    assert lines[0] == "*Tue Nov 10 closed −$125* · $6,007 spend · 0.98x · 157 leads"
    assert lines[2] == "RHO Commercial +$100 · RHO 4 −$225"


def test_pipe_in_adset_name_does_not_break_the_link():
    line = raise_lines([_p("VW-PLOW | SNOW PLOWING", "budget_increase", 10)])[1]
    link = line[line.index("<") + 1:line.index(">")]
    assert link.endswith("|VW-PLOW · SNOW PLOWING") and link.count("|") == 1


def test_reasons_cannot_inject_slack_mentions():
    row = _p("X", "budget_increase", 10)
    row.evidence["why"] = "<!channel> ping"
    assert "&lt;!channel&gt;" in raise_lines([row])[1]
