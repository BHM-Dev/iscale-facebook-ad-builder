"""Read-only: replay approvals-queue triggers for the last 7 full days and compare with people's Meta actions.

Caveat: replays use today's budgets (or $100/day when unknown), so raise proposals are approximate."""
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.database import SessionLocal
from app.models import AutoPauseRuleLog
from app.services import proposal_service as ps
from app.services.facebook_service import FacebookService

db = SessionLocal()
svc = FacebookService(); svc.initialize()
report = []
for acct in ["act_521142087204815", "act_737291135429748"]:
    meta, revenue, live, names, until = ps.fetch_inputs(db, acct, days=17)
    tz = ZoneInfo(dict(svc._get_account(acct).api_get(fields=["timezone_name"])).get("timezone_name") or "UTC")
    days = [until - timedelta(days=i) for i in range(7, 0, -1)]
    def series(aid):
        s = {d: {**v, "rev": revenue.get(aid, {}).get(d, 0.0)} for d, v in meta.get(aid, {}).items()}
        for d, rv in revenue.get(aid, {}).items():
            s.setdefault(d, {"spend": 0.0, "leads": 0, "rev": rv})
        return s
    def fwd(aid, d, n=3):
        s = series(aid); sp = rv = 0.0
        for i in range(1, n + 1):
            x = s.get(ps._day(d + timedelta(days=i)), {}); sp += x.get("spend", 0.0); rv += x.get("rev", 0.0)
        return round(rv - sp, 2), round(sp, 2)
    def back(aid, d, n=3):
        s = series(aid); sp = rv = 0.0
        for i in range(n):
            x = s.get(ps._day(d - timedelta(days=i)), {}); sp += x.get("spend", 0.0); rv += x.get("rev", 0.0)
        return round(rv - sp, 2), round(sp, 2)
    # proposals the queue would have made (end-of-day data), 3-day dedupe per ad set
    props, last = [], {}
    for d in days:
        live_d = {}
        for aid, s in meta.items():
            if s.get(ps._day(d), {}).get("spend", 0) > 0:
                live_d[aid] = {"name": names.get(aid), "status": "ACTIVE",
                               "daily_budget_cents": (live.get(aid) or {}).get("daily_budget_cents") or 10000}
        for c in ps.evaluate(meta, revenue, live_d, d, 10**9):
            a = c["fb_adset_id"]
            if a in last and (d - last[a]).days < 3:
                continue
            last[a] = d
            props.append({"aid": a, "name": c["adset_name"], "day": d, "action": c["action"], "trigger": (c.get("trigger_keys") or [None])[0]})
    # what people did
    since = datetime.combine(days[0], datetime.min.time(), tz).astimezone(timezone.utc)
    end = datetime.combine(until, datetime.min.time(), tz).astimezone(timezone.utc)
    acts = ps.human_adset_actions(acct, since, end)
    rules = db.query(AutoPauseRuleLog.fb_adset_id, AutoPauseRuleLog.created_at).filter(
        AutoPauseRuleLog.created_at >= since.replace(tzinfo=None), AutoPauseRuleLog.result == "success").all()
    def by_rule(a):
        return any(str(r[0]) == a["fb_adset_id"] and abs((a["at"] - ps._aware(r[1])).total_seconds()) <= 600 for r in rules)
    rule_n = sum(1 for a in acts if by_rule(a))
    acts = [dict(a, day=a["at"].astimezone(tz).date()) for a in acts if not by_rule(a) and a["kind"] in ("pause", "budget_increase")]
    used = set()
    for p in props:
        want = p["action"]
        hit = next((i for i, a in enumerate(acts) if i not in used and a["fb_adset_id"] == p["aid"] and a["kind"] == want
                    and 0 <= (a["day"] - p["day"]).days <= 1), None)
        # also: did a person already do it earlier the same day (proposal would have been moot)?
        p["matched"] = hit is not None
        p["by"] = acts[hit]["actor"] if hit is not None else None
        if hit is not None: used.add(hit)
        p["next3_profit"], p["next3_spend"] = fwd(p["aid"], p["day"])
    missed = [a for i, a in enumerate(acts) if i not in used]
    for a in missed:
        a["prior3_profit"], a["prior3_spend"] = back(a["fb_adset_id"], a["day"])
        a["next3_profit"], a["next3_spend"] = fwd(a["fb_adset_id"], a["day"])
    def summ(kind):
        P = [p for p in props if p["action"] == kind]; M = [a for a in missed if a["kind"] == kind]
        H = [a for a in acts if a["kind"] == kind]
        um = [p for p in P if not p["matched"]]
        return {"queue_proposals": len(P), "people_also_did_within_1d": sum(p["matched"] for p in P),
                "people_actions": len(H), "people_actions_queue_missed": len(M),
                "unmatched_proposals_next3d_profit": round(sum(p["next3_profit"] for p in um), 2),
                "unmatched_proposals_that_kept_losing" if kind == "pause" else "unmatched_raises_next3d_profitable":
                    sum(1 for p in um if (p["next3_profit"] < 0) == (kind == "pause")),
                "missed_actions_prior3d_profit_losing": sum(1 for a in M if a["prior3_profit"] < 0),
                "missed_actions_prior3d_profit_positive": sum(1 for a in M if a["prior3_profit"] >= 0),
                "missed_actions_prior3d_spend_under_150": sum(1 for a in M if a["prior3_spend"] < 150)}
    report.append({
        "account": acct, "window": f"{days[0]}..{days[-1]}", "rule_actions_excluded": rule_n,
        "by_actor": {k: sum(1 for a in acts if a["actor"] == k) for k in sorted({a["actor"] for a in acts})},
        "pause": summ("pause"), "budget_increase": summ("budget_increase"),
        "unmatched_proposals": [{k: (str(v) if isinstance(v, date) else v) for k, v in p.items() if k != "aid"} for p in props if not p["matched"]][:25],
        "matched_proposals": [{"name": p["name"], "day": str(p["day"]), "action": p["action"], "by": p["by"]} for p in props if p["matched"]],
    })
print(json.dumps(report, indent=1, default=str))
