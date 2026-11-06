"""Read-only account economics used by the Campaign Performance Max CPL column."""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from time import monotonic

from app.services import proposal_service
from app.services.facebook_service import FacebookService
from app.services.niche_resolver import resolve

logger = logging.getLogger(__name__)
_CACHE: dict[tuple[str, float, int], tuple[float, float, dict]] = {}   # key -> (stored_at, ttl, result)
_LOCKS: dict[tuple, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()
TTL_SECONDS = 3600
FAILURE_TTL_SECONDS = 120     # a failing account must not re-pull Meta + Everflow on every page load
META_TIMEOUT_SECONDS = 30
MIN_NICHE_LEADS = 40


def _cached(key):
    item = _CACHE.get(key)
    return item[2] if item and monotonic() - item[0] < item[1] else None


def _lock(key):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _unavailable(account_id, reason):
    return {"available": False, "account_id": account_id, "reason": reason}


def _pull_rows(account_id, since, until):
    def pull():
        svc = FacebookService()
        svc.initialize()
        account = svc._get_account(account_id)
        return [dict(r) for r in account.get_insights(
            fields=["adset_id", "adset_name", "campaign_name", "spend", "actions"],
            params={"time_range": {"since": since.isoformat(), "until": until.isoformat()}, "level": "adset", "limit": 500})]
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(pull).result(timeout=META_TIMEOUT_SECONDS)
    finally:
        pool.shutdown(wait=False)   # a timed-out read-only pull is abandoned, never waited on


def compute_max_cpl(db, account_id: str, days: int = 30, target_roas: float = 1.30) -> dict:
    key = (account_id, float(target_roas), days)
    cached = _cached(key)
    if cached is not None:
        return cached
    with _lock(key):                       # concurrent cold loads share one pull
        cached = _cached(key)
        if cached is not None:
            return cached
        try:
            result = _compute(db, account_id, days, target_roas)
            ttl = TTL_SECONDS if result.get("available") else FAILURE_TTL_SECONDS
        except proposal_service.RevenueUnavailable as exc:
            result, ttl = _unavailable(account_id, str(exc)), FAILURE_TTL_SECONDS
        except Exception:
            logger.exception("Max CPL failed for %s", account_id)
            result, ttl = _unavailable(account_id, "Max CPL unavailable right now"), FAILURE_TTL_SECONDS
        _CACHE[key] = (monotonic(), ttl, result)
        return result


def _compute(db, account_id, days, target_roas):
    # Complete days only, ending yesterday in Pacific time: today's leads have no revenue yet and would
    # drag revenue per lead (and so Max CPL) down.
    from app.services.daily_close_service import closed_day
    until = closed_day()
    since = until - timedelta(days=days - 1)
    rows = _pull_rows(account_id, since, until)
    spend = sum(float(row.get("spend") or 0) for row in rows)
    revenue = proposal_service.revenue_by_adset_day(db, account_id, since, until, spend)
    adsets, niches = {}, {}
    for row in rows:
        aid = str(row.get("adset_id") or "")
        if not aid:
            continue
        leads = proposal_service.count_leads(row.get("actions"))
        rev = sum(revenue.get(aid, {}).values())
        niche = resolve(row.get("campaign_name"), row.get("adset_name"))
        bucket = niches.setdefault(niche, {"leads": 0, "revenue": 0.0, "spend": 0.0})
        bucket["leads"] += leads; bucket["revenue"] += rev; bucket["spend"] += float(row.get("spend") or 0)
        adsets[aid] = {"niche": niche}
    total_leads = sum(v["leads"] for v in niches.values())
    total_revenue = sum(v["revenue"] for v in niches.values())
    if total_leads <= 0 or total_revenue <= 0:
        return _unavailable(account_id, "No leads or revenue in the window")
    account_rpl = total_revenue / total_leads
    for niche, bucket in niches.items():
        small = bucket["leads"] < MIN_NICHE_LEADS or niche == "Unmapped"
        rpl = bucket["revenue"] / bucket["leads"] if bucket["leads"] else 0.0
        if small or rpl <= 0:
            # Too few leads (or no attributed revenue yet) to trust: use the account figure, labelled.
            rpl, source = account_rpl, "acct_avg"
        else:
            source = "niche"
        bucket.update(rpl=round(rpl, 2), max_cpl=round(rpl / target_roas, 2), source=source)
    for aid, item in adsets.items():
        b = niches[item["niche"]]
        item.update(max_cpl=b["max_cpl"], rpl=b["rpl"], source=b["source"])
    return {"available": True, "account_id": account_id, "window": {"since": since.isoformat(), "until": until.isoformat()},
            "target_roas": target_roas,
            "account": {"rpl": round(account_rpl, 2), "max_cpl": round(account_rpl / target_roas, 2),
                        "leads": total_leads, "revenue": round(total_revenue, 2)},
            "niches": niches, "adsets": adsets}
