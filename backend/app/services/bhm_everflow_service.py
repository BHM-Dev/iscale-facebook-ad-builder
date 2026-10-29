"""BHM's own Everflow (network realm) — billable revenue for accounts whose offers run on our network.

Splitero (offer 4626) and LoanDepot (offer 4566) are offers on BHM's own Everflow, not Switchboard's. BHM is the
NETWORK there, so this uses /v1/networks/... with a network key (BHM_EVERFLOW_API_KEY). Unlike Switchboard's affiliate
realm, these offers also carry OUTSIDE affiliates' traffic (LoanDepot had 119 conversions from affiliates 985/814 before
we ran anything), so revenue is only ever counted for our internal affiliates (232 "Bright Horizons Internal - Media
Buys", 125 "Bright Horizons Media - Internal"; Steve 2026-10-29) — never offer-wide.

Verified against the live API 2026-10-29:
  * this endpoint DOES page, via the query string (`?page=N&page_size=M`; paging in the body is ignored);
  * filters of different resource types are ANDed. Whether two filters of the SAME type are ORed is not certain, so we
    filter by offer server-side (one call per offer) and by affiliate client-side;
  * `revenue` is what the advertiser pays BHM, which is the P&L's billable revenue.

Rows have the same shape as Switchboard's (sub3, revenue, event, relationship.offer.name, conversion_unix_timestamp),
so the P&L reuses EverflowService's aggregation and ad-set attribution unchanged.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import date

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.eflow.team/v1"
DEFAULT_TIMEZONE_ID = 80   # Eastern — matches Switchboard's buckets so both sources share day/month boundaries
PAGE_SIZE = 500
MAX_PAGES = 50
# The network reporting endpoint rate-limits hard (a 429 after a handful of back-to-back calls, seen live 2026-10-29),
# and one P&L load asks for the same offer several times (per account, the all-accounts extras, the months table).
# So rows are cached per (offer, range) for a few minutes and a 429 is retried with a short backoff.
CACHE_TTL_SECONDS = 300
MAX_RETRIES = 3
_cache: dict[tuple, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


class BhmEverflowService:
    def __init__(self):
        self.api_key = os.getenv("BHM_EVERFLOW_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def get_internal_conversions(
        self,
        date_from: date,
        date_to: date,
        offer_ids: set[str],
        affiliate_ids: set[str],
        timezone_id: int = DEFAULT_TIMEZONE_ID,
    ) -> list[dict]:
        """Conversions (and events) on these offers from our internal affiliates only. Raises on any failure or an
        incomplete page set, so the P&L marks the period incomplete instead of reporting a short number."""
        if not self.is_configured():
            raise RuntimeError("BHM_EVERFLOW_API_KEY not configured")
        if not affiliate_ids:
            raise RuntimeError("No internal affiliate ids configured for BHM Everflow")
        rows: dict[str, dict] = {}
        for offer_id in sorted(offer_ids):
            offer_rows = self._offer_rows(date_from, date_to, offer_id, timezone_id)
            ids = [
                str(((row.get("relationship") or {}).get("affiliate") or {}).get("network_affiliate_id") or row.get("network_affiliate_id") or "")
                for row in offer_rows
            ]
            if offer_rows and not any(ids):
                # Every row lost its affiliate id: a response-shape change. Filtering would silently report $0.
                raise RuntimeError("BHM Everflow rows carry no affiliate id; cannot separate internal traffic")
            for row, affiliate_id in zip(offer_rows, ids):
                if affiliate_id not in affiliate_ids:
                    continue
                key = str(row.get("conversion_id") or "") or f"_{len(rows)}"
                rows[key] = row
        logger.info("BHM Everflow: %d internal conversions on offers %s (%s -> %s)",
                    len(rows), ",".join(sorted(offer_ids)), date_from, date_to)
        return list(rows.values())

    def _offer_rows(self, date_from: date, date_to: date, offer_id: str, timezone_id: int) -> list[dict]:
        key = (str(offer_id), date_from.isoformat(), date_to.isoformat(), timezone_id)
        with _cache_lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
                return hit[1]
        rows = self._fetch_offer_rows(date_from, date_to, offer_id, timezone_id)
        with _cache_lock:
            if len(_cache) >= 64:
                _cache.pop(min(_cache, key=lambda k: _cache[k][0]), None)
            _cache[key] = (time.time(), rows)
        return rows

    def _post(self, page: int, body: dict) -> httpx.Response:
        for attempt in range(MAX_RETRIES + 1):
            resp = httpx.post(
                f"{BASE_URL}/networks/reporting/conversions",
                params={"page": page, "page_size": PAGE_SIZE},
                headers={"Content-Type": "application/json", "x-eflow-api-key": self.api_key},
                json=body,
                timeout=30,
            )
            if resp.status_code != 429 or attempt == MAX_RETRIES:
                return resp
            try:
                wait = float(resp.headers.get("Retry-After") or 0)
            except ValueError:
                wait = 0
            time.sleep(min(max(wait, 2 * (attempt + 1)), 10))
        return resp

    def _fetch_offer_rows(self, date_from: date, date_to: date, offer_id: str, timezone_id: int) -> list[dict]:
        out: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            resp = self._post(page, {
                    "from": date_from.isoformat(),
                    "to": date_to.isoformat(),
                    "timezone_id": timezone_id,
                    "currency_id": "USD",
                    "show_conversions": True,
                    "show_events": True,
                    "query": {"filters": [{"resource_type": "offer", "filter_id_value": str(offer_id)}]},
            })
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("conversions") if isinstance(data, dict) else None
            if not isinstance(batch, list):
                # Never treat an unrecognised envelope as "no conversions".
                raise RuntimeError("Unrecognised BHM Everflow conversions response shape")
            out.extend(batch)
            total = (data.get("paging") or {}).get("total_count")
            if total is None:
                raise RuntimeError("BHM Everflow response omitted paging.total_count; revenue would be incomplete")
            if len(out) >= int(total) or not batch:
                if len(out) < int(total):
                    raise RuntimeError(f"BHM Everflow returned {len(out)} of {total} conversions for offer {offer_id}")
                return out
        raise RuntimeError(f"BHM Everflow offer {offer_id} exceeded {MAX_PAGES} pages; revenue would be incomplete")
