"""Read-only: profile what people's pause/raise/re-activate decisions looked like at decision time.

Caveat: windows include the full decision day (actions happen 00-06 PT, so this slightly overstates what
the buyer could see). Set DAYS via env (default 28)."""
import json, os, statistics as st
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.database import SessionLocal
from app.services import proposal_service as ps
from app.services.facebook_service import FacebookService

DAYS = int(os.environ.get("DAYS", "28"))
db = SessionLocal(); svc = FacebookService(); svc.initialize()
def q(v): 
    v = sorted(v); n = len(v)
    return None if not n else {"n": n, "p25": round(v[n//4],1), "med": round(v[n//2],1), "p75": round(v[(3*n)//4],1)}
out = []
for acct in ["act_521142087204815", "act_737291135429748"]:
    meta, revenue, live, names, until = ps.fetch_inputs(db, acct, days=DAYS + 14)
    tz = ZoneInfo(dict(svc._get_account(acct).api_get(fields=["timezone_name"])).get("timezone_name") or "UTC")
    since = datetime.combine(until - timedelta(days=DAYS), datetime.min.time(), tz).astimezone(timezone.utc)
    acts = ps.human_adset_actions(acct, since)
    def ser(aid):
        s = {d: {**v, "rev": revenue.get(aid, {}).get(d, 0.0)} for d, v in meta.get(aid, {}).items()}
        for d, rv in revenue.get(aid, {}).items(): s.setdefault(d, {"spend": 0.0, "leads": 0, "rev": rv})
        return s
    def win(s, end, n):  # n days ending the day BEFORE `end` plus `end` itself up to decision (full day approx)
        sp = l = r = 0.0
        for i in range(n):
            x = s.get(ps._day(end - timedelta(days=i)), {}); sp += x.get("spend", 0); l += x.get("leads", 0); r += x.get("rev", 0)
        return sp, l, r
    rows = []
    for a in acts:
        d = a["at"].astimezone(tz).date(); s = ser(a["fb_adset_id"])
        spent_days = sorted(k for k, v in s.items() if v.get("spend", 0) > 0 and k <= ps._day(d))
        age = (d - datetime.fromisoformat(spent_days[0]).date()).days + 1 if spent_days else 0
        s3, l3, r3 = win(s, d, 3); s7, l7, r7 = win(s, d, 7); sl, ll, rl = win(s, d, DAYS + 13)
        fs, fl, fr = 0.0, 0, 0.0
        for i in range(1, 4):
            x = s.get(ps._day(d + timedelta(days=i)), {}); fs += x.get("spend", 0); fr += x.get("rev", 0)
        rows.append({"kind": a["kind"], "actor": a["actor"], "hour": a["at"].astimezone(tz).hour, "weekday": d.strftime("%a"),
                     "age_days": age, "s3": s3, "l3": l3, "p3": r3 - s3, "s7": s7, "p7": r7 - s7,
                     "roi7": (r7 - s7) / s7 if s7 else None, "cpl3": s3 / l3 if l3 else None,
                     "rev_per_lead_life": rl / ll if ll else None, "life_profit": rl - sl, "life_spend": sl,
                     "zero_lead_3d": l3 == 0 and s3 > 0, "raise_pct": ((a.get("to_cents", 0) / a["from_cents"]) - 1) * 100 if a["kind"].startswith("budget") and a.get("from_cents") else None,
                     "to_budget": a.get("to_cents", 0) / 100 if a["kind"].startswith("budget") else None,
                     "next3_spend": fs, "next3_profit": fr - fs, "aid": a["fb_adset_id"], "day": str(d), "name": a["adset_name"]})
    def prof(kind):
        R = [r for r in rows if r["kind"] == kind]
        if not R: return {"n": 0}
        return {"n": len(R), "actors": dict(Counter(r["actor"] for r in R)),
                "age_days": q([r["age_days"] for r in R]), "spend_3d": q([r["s3"] for r in R]),
                "profit_3d": q([r["p3"] for r in R]), "roi_7d_pct": q([r["roi7"] * 100 for r in R if r["roi7"] is not None]),
                "cpl_3d": q([r["cpl3"] for r in R if r["cpl3"]]), "share_zero_leads_3d": round(sum(r["zero_lead_3d"] for r in R) / len(R), 2),
                "share_losing_3d": round(sum(r["p3"] < 0 for r in R) / len(R), 2),
                "share_lifetime_profitable": round(sum(r["life_profit"] > 0 for r in R) / len(R), 2),
                "raise_pct": q([r["raise_pct"] for r in R if r["raise_pct"] is not None]),
                "to_budget": q([r["to_budget"] for r in R if r["to_budget"] is not None]),
                "hour_local": dict(sorted(Counter(r["hour"] for r in R).items())),
                "weekday": dict(Counter(r["weekday"] for r in R))}
    paused_profitable = [r for r in rows if r["kind"] == "pause" and r["p3"] > 0]
    react = [r for r in rows if r["kind"] == "activate"]
    paused_ids = {r["aid"]: r["day"] for r in rows if r["kind"] == "pause"}
    out.append({"account": acct, "window_days": DAYS, "actions": len(rows),
                "pause": prof("pause"), "budget_increase": prof("budget_increase"), "budget_decrease": prof("budget_decrease"), "activate": prof("activate"),
                "paused_while_profitable_3d": {"n": len(paused_profitable),
                    "share_with_zero_leads_today": None,
                    "profile": [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items() if k in ("name","day","age_days","s3","l3","p3","cpl3","life_profit","next3_profit")} for r in paused_profitable][:20]},
                "reactivated_after_pause_in_window": sum(1 for r in react if r["aid"] in paused_ids),
                "account_7d_cpl_median_for_reference": None})
print(json.dumps(out, indent=1, default=str))
