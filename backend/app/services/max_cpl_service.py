"""Read-only account economics used by the Campaign Performance Max CPL column."""
from datetime import timedelta
from time import monotonic

from app.services import proposal_service
from app.services.niche_resolver import resolve
from app.services.facebook_service import FacebookService

_CACHE: dict[tuple[str, float], tuple[float, dict]] = {}
TTL_SECONDS = 3600


def _cached(key):
    item = _CACHE.get(key)
    return item[1] if item and monotonic() - item[0] < TTL_SECONDS else None


def compute_max_cpl(db, account_id: str, days: int = 30, target_roas: float = 1.30) -> dict:
    key = (account_id, float(target_roas))
    cached = _cached(key)
    if cached is not None:
        return cached
    svc = FacebookService()
    svc.initialize()
    account = svc._get_account(account_id)
    until = proposal_service.account_today(account)
    since = until - timedelta(days=days)
    rows = list(account.get_insights(fields=["adset_id", "adset_name", "campaign_name", "spend", "actions"], params={
        "time_range": {"since": since.isoformat(), "until": until.isoformat()}, "level": "adset", "limit": 500,
    }))
    spend = sum(float(row.get("spend") or 0) for row in rows)
    revenue = proposal_service.revenue_by_adset_day(db, account_id, since, until, spend)
    adsets = {}
    niches = {}
    for row in rows:
        aid = str(row.get("adset_id") or "")
        if not aid:
            continue
        leads = sum(int(float(a.get("value") or 0)) for a in (row.get("actions") or []) if a.get("action_type") in proposal_service.LEAD_TYPES)
        rev = sum(revenue.get(aid, {}).values())
        niche = resolve(row.get("campaign_name"), row.get("adset_name"))
        bucket = niches.setdefault(niche, {"rpl": 0.0, "max_cpl": 0.0, "leads": 0, "revenue": 0.0, "spend": 0.0, "source": "niche"})
        bucket["leads"] += leads; bucket["revenue"] += rev; bucket["spend"] += float(row.get("spend") or 0)
        adsets[aid] = {"niche": niche, "leads": leads, "revenue": rev}
    total_leads = sum(v["leads"] for v in niches.values())
    total_revenue = sum(v["revenue"] for v in niches.values())
    account_rpl = total_revenue / total_leads if total_leads else 0.0
    for niche, bucket in niches.items():
        bucket["rpl"] = bucket["revenue"] / bucket["leads"] if bucket["leads"] else 0.0
        bucket["source"] = "acct_avg" if bucket["leads"] < 40 or niche == "Unmapped" else "niche"
        if bucket["source"] == "acct_avg": bucket["rpl"] = account_rpl
        bucket["max_cpl"] = bucket["rpl"] / target_roas if target_roas else 0.0
    for aid, item in adsets.items():
        bucket = niches[item["niche"]]
        adsets[aid].update(max_cpl=bucket["max_cpl"], rpl=bucket["rpl"], source=bucket["source"])
    result = {"available": True, "account_id": account_id, "window": {"since": since.isoformat(), "until": until.isoformat()},
              "target_roas": target_roas, "account": {"rpl": account_rpl, "max_cpl": account_rpl / target_roas if target_roas else 0.0,
              "leads": total_leads, "revenue": total_revenue}, "niches": niches, "adsets": adsets}
    _CACHE[key] = (monotonic(), result)
    return result
