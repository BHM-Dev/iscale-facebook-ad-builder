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
# "No leads or revenue in the window" is an answer, not an error (Everflow failures stay on the short TTL). Caching it for 2 min meant an
# account like that re-ran the ~9s pull on nearly every Campaign Performance load (seen 2026-11-18).
SETTLED_TTL_SECONDS = 3600   # outlives the warm job's 30-min recheck, like TTL_SECONDS
RECENT_WINDOW_SECONDS = 24 * 3600
_RECENT: dict[str, float] = {}   # account_id -> last time someone opened Max CPL for it
META_TIMEOUT_SECONDS = 30
MIN_NICHE_LEADS = 40
# Revenue-per-lead window. 7 days, not 30 (Steve, 2026-11-19): Switchboard lead values fell ~25-40% mid-November
# after a buyer change, and a 30-day window kept pricing Max CPL off early-month values, ~$10/lead too generous.
WINDOW_DAYS = 7


def _cached(key):
    item = _CACHE.get(key)
    return item[2] if item and monotonic() - item[0] < item[1] else None


def _lock(key):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _unavailable(account_id, reason, settled=False):
    out = {"available": False, "account_id": account_id, "reason": reason}
    if settled:
        out["settled"] = True
    return out


def _ttl(result):
    if result.get("available"):
        return TTL_SECONDS
    return SETTLED_TTL_SECONDS if result.get("settled") else FAILURE_TTL_SECONDS


def note_request(account_id: str) -> None:
    """Remember accounts people actually open so the warm job keeps them warm too."""
    _RECENT[account_id] = monotonic()


MAX_RECENT_WARM = 6   # each cold pull is ~9s of Meta + Everflow; keep the extra warm load bounded


def recent_accounts() -> list[str]:
    cutoff = monotonic() - RECENT_WINDOW_SECONDS
    snapshot = list(_RECENT.items())   # copy: request threads add to _RECENT concurrently
    for account_id, t in snapshot:
        if t < cutoff:
            _RECENT.pop(account_id, None)
    fresh = sorted(((t, a) for a, t in snapshot if t >= cutoff), reverse=True)
    return [a for _, a in fresh[:MAX_RECENT_WARM]]


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


def compute_max_cpl(db, account_id: str, days: int = WINDOW_DAYS, target_roas: float = 1.30) -> dict:
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
            ttl = _ttl(result)
        except proposal_service.RevenueUnavailable as exc:
            result = _unavailable(account_id, str(exc))
            ttl = _ttl(result)
        except Exception:
            logger.exception("Max CPL failed for %s", account_id)
            result, ttl = _unavailable(account_id, "Max CPL unavailable right now"), FAILURE_TTL_SECONDS
        _CACHE[key] = (monotonic(), ttl, result)
        return result


def warm(db, account_id: str, refresh_after: int = 1800, days: int = WINDOW_DAYS, target_roas: float = 1.30) -> str:
    """Background refresh for the scheduler. Pulls only when there is no good cached result or it is older
    than `refresh_after` (30 min — two 10-min retry ticks before the 60-min TTL), so page loads don't meet an expired cache. A failed
    pull never replaces a still-valid good result. Returns what it did, for logging. Never raises."""
    key = (account_id, float(target_roas), days)
    item = _CACHE.get(key)
    now = monotonic()
    if item and (item[2].get("available") or item[2].get("settled")) and now - item[0] < refresh_after:
        return "fresh"
    with _lock(key):
        item = _CACHE.get(key)   # a page load may have refreshed it while we waited for the lock
        if item and (item[2].get("available") or item[2].get("settled")) and monotonic() - item[0] < refresh_after:
            return "fresh"
        try:
            result = _compute(db, account_id, days, target_roas)
        except proposal_service.RevenueUnavailable as exc:
            result = _unavailable(account_id, str(exc))
        except Exception as exc:
            logger.warning("Max CPL warm failed for %s: %s", account_id, exc)
            try:
                db.rollback()   # the session is shared across accounts in one tick
            except Exception:
                pass
            result = _unavailable(account_id, "Max CPL unavailable right now")
        current = _CACHE.get(key)
        still_good = current and current[2].get("available") and monotonic() - current[0] < current[1]
        if result.get("available"):
            _CACHE[key] = (monotonic(), TTL_SECONDS, result)
            return "refreshed"
        if not still_good:
            _CACHE[key] = (monotonic(), _ttl(result), result)
        return "settled" if result.get("settled") else "failed"


def has_revenue_mapping(account_id: str) -> bool:
    """True when the account has Switchboard offers mapped, i.e. Max CPL can ever be computed for it."""
    from app.api.v1 import pnl
    try:
        return bool(pnl._everflow_offer_names_for_account(account_id))
    except Exception:  # noqa: BLE001 — unknown: let the normal path try and report
        return True


def _compute(db, account_id, days, target_roas):
    # Complete days only, ending yesterday in Pacific time: today's leads have no revenue yet and would
    # drag revenue per lead (and so Max CPL) down.
    from app.services.daily_close_service import closed_day
    until = closed_day()
    since = until - timedelta(days=days - 1)
    if not has_revenue_mapping(account_id):
        # Check before the Meta pull: without an offer mapping there is no revenue to divide by, so the
        # pull was wasted on every load and every warm tick (act_708.../act_831..., 2026-11-18).
        raise proposal_service.RevenueUnavailable("no Switchboard offer mapping")
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
        return _unavailable(account_id, "No leads or revenue in the window", settled=True)
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
    return {"available": True, "account_id": account_id, "window": {"since": since.isoformat(), "until": until.isoformat(), "days": days},
            "target_roas": target_roas,
            "account": {"rpl": round(account_rpl, 2), "max_cpl": round(account_rpl / target_roas, 2),
                        "leads": total_leads, "revenue": round(total_revenue, 2)},
            "niches": niches, "adsets": adsets}
