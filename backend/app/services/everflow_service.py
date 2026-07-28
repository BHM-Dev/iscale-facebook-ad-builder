"""Switchboard Everflow affiliate-realm revenue service."""

from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.eflow.team"
DEFAULT_TIMEZONE_ID = 90  # Pacific, aligned with the Meta ad account billing day.
USD_CURRENCY_ID = "USD"
CENT = Decimal("0.01")
META_ID_RE = re.compile(r"^\d{10,}$")
CONVERSION_DATE_FIELDS = (
    "conversion_date",
    "conversion_time",
    "conversion_unix_timestamp",
    "event_date",
    "event_time",
    "event_timestamp",
    "date",
    "created_at",
    "unix_timestamp",
)


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
        offer_names: set[str] | None = None,
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
        report = self._aggregate_rows(rows, offer_names=offer_names)
        report["timezone_id"] = timezone_id
        return report

    def get_revenue_by_adset_by_month(
        self,
        date_from: str | date,
        date_to: str | date,
        timezone_id: int = DEFAULT_TIMEZONE_ID,
        offer_names: set[str] | None = None,
    ) -> dict[str, dict]:
        """Fetch once, then bucket billable revenue by conversion month."""
        if not self.is_configured():
            raise RuntimeError("SWITCHBOARD_EVERFLOW_API_KEY not configured")

        start = date_from.isoformat() if isinstance(date_from, date) else str(date_from)
        end = date_to.isoformat() if isinstance(date_to, date) else str(date_to)
        rows = self._fetch_conversion_rows(start, end, timezone_id)
        rows_by_month: dict[str, list[dict]] = {}
        for row in rows:
            month = self._conversion_month(row)
            rows_by_month.setdefault(month, []).append(row)
        return {
            month: {**self._aggregate_rows(month_rows, offer_names=offer_names), "timezone_id": timezone_id}
            for month, month_rows in rows_by_month.items()
        }

    def _aggregate_rows(self, rows: list[dict], offer_names: set[str] | None = None) -> dict:
        allowed_offers = {name.casefold() for name in offer_names or set() if name}

        by_adset: dict[str, dict] = {}
        unattributed_revenue = Decimal("0")
        unattributed_events = 0

        for row in rows:
            if allowed_offers and self._offer_name(row).casefold() not in allowed_offers:
                continue
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
                    # Reserved for service-layer diagnostics. P&L deliberately
                    # does not surface lead/paywall/call splits.
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
        }

    @staticmethod
    def _offer_name(row: dict) -> str:
        for key in ("offer", "offer_name"):
            if row.get(key):
                value = row.get(key)
                if isinstance(value, dict):
                    return str(value.get("name") or value.get("offer_name") or "").strip()
                return str(value).strip()
        offer = row.get("relationship", {}).get("offer") if isinstance(row.get("relationship"), dict) else None
        if isinstance(offer, dict):
            return str(offer.get("name") or "").strip()
        return ""

    @staticmethod
    def _conversion_month(row: dict) -> str:
        for field in CONVERSION_DATE_FIELDS:
            raw = row.get(field)
            if not raw:
                continue
            value = str(raw)
            if value.isdigit():
                return datetime.fromtimestamp(int(value)).date().replace(day=1).isoformat()
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date().replace(day=1).isoformat()
            except ValueError:
                match = re.match(r"^\d{4}-\d{2}-\d{2}", value)
                if match:
                    return datetime.strptime(match.group(0), "%Y-%m-%d").date().replace(day=1).isoformat()
        raise RuntimeError("Everflow conversion row is missing a recognised conversion date field")

    # This endpoint cannot be paged. Verified against the live API 2026-07-28:
    # `page`/`page_size` in the body are ignored in both the flat and the nested
    # form — every request returns page 1 — while the response hard-caps at 2000
    # rows and reports the true size in `paging.total_count`. A paging loop
    # therefore re-fetches identical rows: with page_size=1000 against
    # total_count=2334 the old loop ran three times and accumulated 6000 rows for
    # 2334 real conversions, overstating revenue ~2.5x with no error raised.
    #
    # So: request narrow date windows, split any window that still overflows the
    # cap, and dedupe on conversion_id as a backstop.
    MAX_ROWS_PER_RESPONSE = 2000
    INITIAL_WINDOW_DAYS = 7

    def _fetch_conversion_rows(self, date_from: str, date_to: str, timezone_id: int) -> list[dict]:
        start = datetime.strptime(date_from, "%Y-%m-%d").date()
        end = datetime.strptime(date_to, "%Y-%m-%d").date()
        if end < start:
            raise RuntimeError(f"Everflow window end {end} precedes start {start}")

        pending: list[tuple[date, date]] = []
        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=self.INITIAL_WINDOW_DAYS - 1), end)
            pending.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)

        by_id: dict[str, dict] = {}
        unkeyed: list[dict] = []

        while pending:
            window_start, window_end = pending.pop(0)
            rows, total_count = self._fetch_window(window_start, window_end, timezone_id)

            if total_count is not None and total_count > len(rows):
                if window_start == window_end:
                    # A single day exceeds the cap and there is no way to page it.
                    # Raise so the P&L reports data_incomplete instead of a number
                    # that is quietly short.
                    raise RuntimeError(
                        f"Everflow returned {len(rows)} of {total_count} conversions for "
                        f"{window_start} and the endpoint cannot be paged further"
                    )
                midpoint = window_start + (window_end - window_start) // 2
                pending.insert(0, (midpoint + timedelta(days=1), window_end))
                pending.insert(0, (window_start, midpoint))
                continue

            for row in rows:
                conversion_id = str(row.get("conversion_id") or "").strip()
                if conversion_id:
                    by_id[conversion_id] = row
                else:
                    unkeyed.append(row)

        rows = list(by_id.values()) + unkeyed
        logger.info(
            "Switchboard Everflow: %d unique conversions (%s -> %s), %d without conversion_id",
            len(rows), date_from, date_to, len(unkeyed),
        )
        return rows

    def _fetch_window(self, window_start: date, window_end: date, timezone_id: int) -> tuple[list[dict], int | None]:
        resp = httpx.post(
            f"{BASE_URL}/v1/affiliates/reporting/conversions",
            headers=self._headers(),
            json={
                "from": window_start.isoformat(),
                "to": window_end.isoformat(),
                "timezone_id": timezone_id,
                "currency_id": USD_CURRENCY_ID,
                "show_events": True,
                "query": {"filters": []},
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        rows = self._rows_from_response(data)
        paging = data.get("paging") if isinstance(data, dict) else None
        total_count = None
        if isinstance(paging, dict) and paging.get("total_count") is not None:
            total_count = int(paging["total_count"])
        return rows, total_count

    @staticmethod
    def _rows_from_response(data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("conversions", "data", "table"):
                value = data.get(key)
                if isinstance(value, list):
                    return value
        # Never fall back to [] — an unrecognised envelope is indistinguishable
        # from "no conversions" and would report $0 revenue as fact.
        raise RuntimeError(f"Unrecognised Everflow conversions response shape: {type(data).__name__}")
