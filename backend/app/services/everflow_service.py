"""Switchboard Everflow affiliate-realm revenue service."""

from __future__ import annotations

import logging
import os
import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.eflow.team"
DEFAULT_TIMEZONE_ID = 90  # Pacific, aligned with the Meta ad account billing day.
USD_CURRENCY_ID = "USD"
CENT = Decimal("0.01")
META_ID_RE = re.compile(r"^\d{10,}$")


def _money(value: Any) -> Decimal:
    return Decimal(str(value or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


class EverflowService:
    """Pull billable revenue from Switchboard's affiliate Everflow realm.

    This key is an affiliate key, so use /v1/affiliates/... endpoints. Network
    and advertiser realm endpoints return 403 for this integration.
    """

    def __init__(self):
        self.api_key = os.getenv("SWITCHBOARD_EVERFLOW_API_KEY")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "x-eflow-api-key": self.api_key,
        }

    def get_revenue_by_adset(
        self,
        date_from: str | date,
        date_to: str | date,
        timezone_id: int = DEFAULT_TIMEZONE_ID,
    ) -> dict:
        """Return billable revenue grouped by Meta ad set id from sub3.

        Raises on missing config or HTTP failures so callers can mark P&L data
        incomplete instead of treating source downtime as true $0 revenue.
        """
        if not self.is_configured():
            raise RuntimeError("SWITCHBOARD_EVERFLOW_API_KEY not configured")

        start = date_from.isoformat() if isinstance(date_from, date) else str(date_from)
        end = date_to.isoformat() if isinstance(date_to, date) else str(date_to)
        rows = self._fetch_conversion_rows(start, end, timezone_id)

        by_adset: dict[str, dict] = {}
        unattributed_revenue = Decimal("0")
        unattributed_events = 0

        for row in rows:
            revenue = _money(row.get("revenue"))
            events = 1
            adset_id = str(row.get("sub3") or "").strip()
            if not META_ID_RE.fullmatch(adset_id):
                unattributed_revenue += revenue
                unattributed_events += events
                continue

            metrics = by_adset.setdefault(
                adset_id,
                {
                    "revenue": Decimal("0"),
                    "events": 0,
                    "clicks": 0,
                    "event_breakdown": {},
                    "adset_name": str(row.get("sub8") or "").strip() or None,
                },
            )
            metrics["revenue"] += revenue
            metrics["events"] += events
            event_name = str(row.get("event") or "unknown").strip() or "unknown"
            bucket = metrics["event_breakdown"].setdefault(event_name, {"events": 0, "revenue": Decimal("0")})
            bucket["events"] += events
            bucket["revenue"] += revenue
            if row.get("sub8") and not metrics.get("adset_name"):
                metrics["adset_name"] = str(row.get("sub8")).strip()

        return {
            "adsets": {
                adset_id: {
                    **metrics,
                    "revenue": metrics["revenue"].quantize(CENT, rounding=ROUND_HALF_UP),
                    "event_breakdown": {
                        name: {
                            "events": bucket["events"],
                            "revenue": bucket["revenue"].quantize(CENT, rounding=ROUND_HALF_UP),
                        }
                        for name, bucket in metrics["event_breakdown"].items()
                    },
                }
                for adset_id, metrics in by_adset.items()
            },
            "unattributed_revenue": unattributed_revenue.quantize(CENT, rounding=ROUND_HALF_UP),
            "unattributed_events": unattributed_events,
            "timezone_id": timezone_id,
        }

    def _fetch_conversion_rows(self, date_from: str, date_to: str, timezone_id: int) -> list[dict]:
        rows: list[dict] = []
        page = 1
        page_size = 1000

        while True:
            payload = {
                "from": date_from,
                "to": date_to,
                "timezone_id": timezone_id,
                "currency_id": USD_CURRENCY_ID,
                "show_events": True,
                "query": {"filters": []},
                "page": page,
                "page_size": page_size,
            }
            resp = httpx.post(
                f"{BASE_URL}/v1/affiliates/reporting/conversions",
                headers=self._headers(),
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            page_rows = self._rows_from_response(data)
            rows.extend(page_rows)

            paging = data.get("paging") if isinstance(data, dict) else None
            if not self._has_next_page(paging, page, page_size, len(page_rows)):
                break
            page += 1

        logger.info("Switchboard Everflow: fetched %d conversion rows (%s -> %s)", len(rows), date_from, date_to)
        return rows

    @staticmethod
    def _rows_from_response(data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if not isinstance(data, dict):
            return []
        for key in ("conversions", "data", "table"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _has_next_page(paging: Any, page: int, page_size: int, row_count: int) -> bool:
        if not isinstance(paging, dict):
            return row_count >= page_size

        for key in ("next", "next_page"):
            if paging.get(key):
                return True

        total_pages = paging.get("total_pages") or paging.get("pages")
        if total_pages is not None:
            return page < int(total_pages)

        total = paging.get("total") or paging.get("total_count")
        if total is not None:
            return page * page_size < int(total)

        return row_count >= page_size
