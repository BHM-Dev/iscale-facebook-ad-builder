"""Read-only: how long after a pause each ad set gets switched back on (edit toggles vs real kills)."""
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from app.services import proposal_service as ps
from app.services.facebook_service import FacebookService
svc = FacebookService(); svc.initialize()
out = {}
for acct in ["act_521142087204815", "act_737291135429748"]:
    tzn = dict(svc._get_account(acct).api_get(fields=["timezone_name"])).get("timezone_name"); tz = ZoneInfo(tzn or "UTC")
    acts = sorted(ps.human_adset_actions(acct, datetime.now(timezone.utc) - timedelta(days=28)), key=lambda a: a["at"])
    by = {}
    for a in acts: by.setdefault(a["fb_adset_id"], []).append(a)
    gaps, never, dup, cycles = [], 0, 0, Counter()
    for aid, L in by.items():
        for i, a in enumerate(L):
            if a["kind"] != "pause": continue
            if i and L[i-1]["kind"] == "pause" and (a["at"] - L[i-1]["at"]).total_seconds() < 120: dup += 1; continue
            nxt = next((b for b in L[i+1:] if b["kind"] == "activate"), None)
            if nxt is None: never += 1
            else: gaps.append((nxt["at"] - a["at"]).total_seconds() / 3600)
        cycles[sum(1 for a in L if a["kind"] == "pause")] += 1
    gaps.sort(); n = len(gaps)
    b = Counter("<1h" if g < 1 else "1-12h" if g < 12 else "12-24h" if g < 24 else "1-3d" if g < 72 else ">3d" for g in gaps)
    out[acct] = {"tz": tzn, "pauses_dedup": n + never, "dup_pause_events": dup, "never_reactivated": never,
                 "reactivated": n, "hours_to_reactivate_buckets": dict(b), "median_h": round(gaps[n//2],1) if n else None,
                 "adsets_by_pause_count": dict(sorted(cycles.items())),
                 "actors_by_kind": {k: dict(Counter(a["actor"] for a in acts if a["kind"] == k)) for k in ("pause","activate","budget_increase","budget_decrease")}}
print(json.dumps(out, indent=1))
