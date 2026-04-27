"""RedTrack API service.

Pulls conversion and revenue data from RedTrack, grouped by sub2
(= Meta fb_adset_id), providing ground-truth ROAS and quality rate
alongside Meta Insights data.

Requires env var:
  REDTRACK_API_KEY — from RedTrack → Settings → Tools → Integrations

Silently returns empty data if key is not configured.
"""

import logging
import os
from datetime import date, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.redtrack.io"


class RedTrackService:

    def __init__(self):
        self.api_key = os.getenv("REDTRACK_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        # RedTrack requires api_key as a query param — x-api-key header returns 401
        return {"Accept": "application/json"}

    def _auth_params(self) -> dict:
        return {"api_key": self.api_key}

    # ── Date helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def preset_to_dates(date_preset: str) -> tuple[str, str]:
        """Convert a Meta-style date preset to (date_from, date_to) strings."""
        today = date.today()
        if date_preset == "today":
            return str(today), str(today)
        if date_preset == "yesterday":
            d = today - timedelta(days=1)
            return str(d), str(d)
        if date_preset == "last_7d":
            return str(today - timedelta(days=6)), str(today)
        if date_preset == "last_14d":
            return str(today - timedelta(days=13)), str(today)
        if date_preset == "last_30d":
            return str(today - timedelta(days=29)), str(today)
        if date_preset == "this_month":
            return str(today.replace(day=1)), str(today)
        # default — last 7 days
        return str(today - timedelta(days=6)), str(today)

    # ── Core report ───────────────────────────────────────────────────────────

    def get_report_by_adset(
        self,
        date_from: str,
        date_to: str,
    ) -> dict:
        """Pull conversions + revenue grouped by sub2 (= Meta fb_adset_id).

        Returns a dict keyed by fb_adset_id:
        {
          "23850123456789": {
            "conversions": 31,
            "revenue": 2170.00,
            "cost": 940.00,
            "profit": 1230.00,
            "roas": 2.31,
            "cpl": 30.32,
            "clicks": 412,
          },
          ...
        }
        Returns empty dict if API key not configured or call fails.
        """
        if not self.is_configured():
            logger.debug("REDTRACK_API_KEY not set — skipping report fetch")
            return {}

        try:
            resp = httpx.get(
                f"{BASE_URL}/report",
                headers=self._headers(),
                params={
                    **self._auth_params(),
                    "date_from": date_from,
                    "date_to": date_to,
                    "group": "sub2",   # correct param — group_by is ignored by the API
                },
                timeout=15,
            )
            resp.raise_for_status()
            rows = resp.json()

            # Normalise to dict keyed by sub2 (= fb_adset_id)
            # Note: API returns `total_revenue` and `total_conversions` (not `revenue`/`conversions`)
            # `cpa` = cost per acquisition (= our cpl), `roas` uses total_revenue internally
            result = {}
            for row in (rows if isinstance(rows, list) else rows.get("data", [])):
                adset_id = str(row.get("sub2") or "").strip()
                if not adset_id or adset_id == "0":
                    continue
                result[adset_id] = {
                    "conversions": int(row.get("total_conversions") or 0),
                    "revenue":     round(float(row.get("total_revenue") or 0), 2),
                    "cost":        round(float(row.get("cost")          or 0), 2),
                    "profit":      round(float(row.get("profit")        or 0), 2),
                    "roas":        round(float(row.get("roas")          or 0), 2),
                    "cpl":         round(float(row.get("cpa")           or 0), 2),
                    "clicks":      int(row.get("clicks") or 0),
                }
            logger.info("RedTrack: fetched %d ad set rows (%s → %s)", len(result), date_from, date_to)
            return result

        except httpx.HTTPStatusError as e:
            logger.error("RedTrack HTTP error: %s %s", e.response.status_code, e.response.text)
            return {}
        except Exception as e:
            logger.error("RedTrack fetch error: %s", e)
            return {}

    def get_report_by_sub(
        self,
        date_from: str,
        date_to: str,
        group_field: str = "sub2",
    ) -> dict:
        """Generic report grouped by any sub parameter (sub2, sub3, etc.).

        group_field: 'sub2' (adset ID) or 'sub3' (ad ID)
        Returns dict keyed by the sub field value → metrics.
        """
        if not self.is_configured():
            return {}
        try:
            resp = httpx.get(
                f"{BASE_URL}/report",
                headers=self._headers(),
                params={
                    **self._auth_params(),
                    "date_from": date_from,
                    "date_to": date_to,
                    "group": group_field,
                },
                timeout=15,
            )
            resp.raise_for_status()
            rows = resp.json()
            result = {}
            for row in (rows if isinstance(rows, list) else rows.get("data", [])):
                key = str(row.get(group_field) or "").strip()
                if not key or key == "0":
                    continue
                result[key] = {
                    "conversions": int(row.get("total_conversions") or 0),
                    "revenue":     round(float(row.get("total_revenue") or 0), 2),
                    "cost":        round(float(row.get("cost")          or 0), 2),
                    "profit":      round(float(row.get("profit")        or 0), 2),
                    "roas":        round(float(row.get("roas")          or 0), 2),
                    "cpl":         round(float(row.get("cpa")           or 0), 2),
                    "clicks":      int(row.get("clicks") or 0),
                }
            logger.info("RedTrack %s: fetched %d rows (%s → %s)", group_field, len(result), date_from, date_to)
            return result
        except httpx.HTTPStatusError as e:
            logger.error("RedTrack HTTP error: %s %s", e.response.status_code, e.response.text)
            return {}
        except Exception as e:
            logger.error("RedTrack fetch error: %s", e)
            return {}

    def get_report_by_adset_preset(self, date_preset: str = "last_7d") -> dict:
        """Convenience wrapper — accepts Meta-style date presets."""
        date_from, date_to = self.preset_to_dates(date_preset)
        return self.get_report_by_adset(date_from, date_to)

    def get_adset_data(self, fb_adset_id: str, date_preset: str = "last_7d") -> Optional[dict]:
        """Get RedTrack data for a single ad set. Returns None if not found."""
        report = self.get_report_by_adset_preset(date_preset)
        return report.get(str(fb_adset_id))

    # ── Campaign list ─────────────────────────────────────────────────────────

    def get_campaigns(self) -> list:
        """List all RedTrack campaigns — used for connection validation."""
        if not self.is_configured():
            return []
        try:
            resp = httpx.get(
                f"{BASE_URL}/campaigns",
                headers=self._headers(),
                params=self._auth_params(),
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("data", [])
        except Exception as e:
            logger.error("RedTrack campaigns fetch error: %s", e)
            return []

    # ── Quality rate helper ───────────────────────────────────────────────────

    @staticmethod
    def quality_rate(rt_conversions: int, meta_leads: int) -> Optional[float]:
        """RT conversions ÷ Meta leads. Returns None if denominator is 0."""
        if not meta_leads:
            return None
        return round(rt_conversions / meta_leads, 3)
