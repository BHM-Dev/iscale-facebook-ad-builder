"""Meta Dataset Quality API (Event Match Quality) — daily CAPI match-quality snapshots.

Built to answer one question: is RHO 4's advertiser-run CAPI actually producing
a higher Event Match Quality score than Everflow's CAPI on the other RHO
accounts? Meta doesn't offer a cross-account comparison itself — this pulls
each account's pixel individually and lets the app do the comparison.

Two real caveats worth reading before trusting the numbers this produces:

1. EMQ is a property of the pixel/dataset, not the ad account. If two ad
   accounts ever share one Meta pixel, Meta will report the identical score
   for both — this comparison only works if RHO 4 sends to a genuinely
   different pixel/dataset than the other RHO accounts. Worth confirming
   directly rather than assuming.
2. Meta has no per-account "Use events dataset" guarantee just because our
   token can manage the ad account — a shared/advertiser-owned pixel may need
   an explicit dataset-sharing grant before `dataset_quality` will return
   anything for it. First real sync should be treated as a permissions test,
   not just a data-quality test — check `fetch_error` on each account.

API reference, response shape confirmed against Meta's live documented example
(https://developers.facebook.com/docs/marketing-api/conversions-api/dataset-quality-api/,
fetched 2026-08-28):
  GET /{api_version}/dataset_quality
    ?dataset_id=<pixel_id>            (dataset_id is Meta's name for our pixel_id)
    &fields=web{event_name,event_match_quality{composite_score,match_key_feedback},acr,event_coverage,data_freshness}
    &agent_name=<optional>            (filters to events sent with a given partner_agent —
                                        relevant if a pixel is ever shared across CAPI senders)
  Response root is "web" (a list), NOT "data" — one row per event_name, no
  aggregate/all-events row. `event_match_quality` is itself an object:
    {"composite_score": 6.2, "match_key_feedback": [{"identifier": "email",
     "coverage": {"percentage": 100}}, ...]}
  `acr` / `event_coverage` / `data_freshness` are documented as separate
  conditional fields (per Meta's Ads Dataset Event Coverage reference) whose
  exact nesting isn't confirmed by a first-party example response — parsed
  defensively below (percentage extracted if present as an object, stored as
  the raw value otherwise, null if the field is absent).
  EMQ is web-events only (no offline/app conversions) — this app's lead events
  are web-sourced, so that's not a gap, but Meta on-platform instant-form leads
  never enter the dataset and will show no EMQ.
  `event_coverage.percentage` is documented as a *trailing 7-day average*, not
  a same-day number — day-over-day deltas in it will look smoother than the
  underlying reality; don't read a single day's move as real movement.
"""
import logging
import os
from datetime import date
from typing import Optional

import requests
from sqlalchemy.orm import Session

from app.models import CapiQualitySnapshot, generate_uuid, normalize_account_id
from app.services.facebook_service import FacebookService

logger = logging.getLogger(__name__)

GRAPH_API_BASE = "https://graph.facebook.com"
REQUEST_TIMEOUT_SECONDS = 30
DATASET_QUALITY_FIELDS = (
    "web{event_name,event_match_quality{composite_score,match_key_feedback},"
    "acr,event_coverage,data_freshness}"
)


def _api_version() -> str:
    return os.getenv("FACEBOOK_API_VERSION") or os.getenv("VITE_FACEBOOK_API_VERSION") or "v25.0"


def _safe_float(value) -> Optional[float]:
    """Meta can return a bare number, a numeric string, or omit the field
    entirely depending on which conditional fields actually populated for a
    given event — never let a surprise shape crash the whole sync.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_percentage(value) -> Optional[float]:
    """acr/event_coverage are documented as objects carrying a `percentage`
    field, but that's not confirmed by a first-party example response —
    handle both "it's an object with percentage" and "it's just a number".
    """
    if isinstance(value, dict):
        return _safe_float(value.get("percentage"))
    return _safe_float(value)


def _extract_freshness(value) -> Optional[str]:
    if isinstance(value, dict):
        return value.get("upload_frequency") or value.get("description")
    if isinstance(value, str):
        return value
    return None


def get_tracked_pixels(svc: FacebookService) -> list[dict]:
    """Distinct (pixel_id, fb_account_id) pairs currently in use, read LIVE from
    Meta's `promoted_object.pixel_id` on every ad set in every visible account —
    NOT from the local FacebookAdSet.pixel_id column.

    That local column is only populated for ad sets created through our own
    wizard (AdSetStep.jsx writes it at creation time); it's confirmed empty for
    every RHO ad set (checked live 2026-08-28 — RHO's ad sets were created
    directly in Ads Manager, not through this app), which would make the whole
    feature see zero RHO pixels on day one if it relied on that cache. Querying
    Meta directly is also just more correct — it's the actual live-in-use pixel,
    not whatever we last happened to cache.
    """
    seen: dict[tuple, dict] = {}
    try:
        accounts = svc.get_ad_accounts() or []
    except Exception as exc:
        logger.warning("capi_quality: could not list ad accounts: %s", exc)
        return []

    for acc in accounts:
        aid = normalize_account_id(acc.get("id") or acc.get("account_id"))
        if not aid:
            continue
        try:
            adsets = svc.get_adsets(ad_account_id=aid) or []
        except Exception as exc:
            logger.warning("capi_quality: could not list ad sets for %s: %s", aid, exc)
            continue
        for adset in adsets:
            promoted_object = adset.get("promoted_object") or {}
            pixel_id = promoted_object.get("pixel_id")
            if not pixel_id:
                continue
            key = (pixel_id, aid)
            if key not in seen:
                seen[key] = {"pixel_id": pixel_id, "fb_account_id": aid}
    return list(seen.values())


def _account_name_map(svc: FacebookService) -> dict[str, str]:
    names: dict[str, str] = {}
    try:
        for acc in svc.get_ad_accounts() or []:
            aid = normalize_account_id(acc.get("id") or acc.get("account_id"))
            if aid:
                names[aid] = acc.get("name") or aid
    except Exception as exc:
        logger.warning("capi_quality: could not resolve account names: %s", exc)
    return names


def fetch_pixel_name(pixel_id: str, access_token: str) -> Optional[str]:
    """Best-effort — a pixel name lookup failing shouldn't block the actual
    quality sync, just leave pixel_name null for that row.
    """
    try:
        url = f"{GRAPH_API_BASE}/{_api_version()}/{pixel_id}"
        response = requests.get(
            url, params={"access_token": access_token, "fields": "name"}, timeout=REQUEST_TIMEOUT_SECONDS
        )
        if response.ok:
            return response.json().get("name")
    except Exception as exc:
        logger.warning("capi_quality: could not resolve pixel name for %s: %s", pixel_id, exc)
    return None


def fetch_dataset_quality(pixel_id: str, access_token: str, agent_name: Optional[str] = None) -> dict:
    """One raw Graph API call. Raises on transport/HTTP failure — caller decides
    whether to store a fetch_error row or skip.
    """
    url = f"{GRAPH_API_BASE}/{_api_version()}/dataset_quality"
    params = {
        "dataset_id": pixel_id,
        "access_token": access_token,
        "fields": DATASET_QUALITY_FIELDS,
    }
    if agent_name:
        params["agent_name"] = agent_name
    response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    if not response.ok:
        raise RuntimeError(f"Dataset Quality API HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def _parse_dataset_quality(raw: dict) -> list[dict]:
    """Returns one parsed dict per event_name — Meta gives no aggregate/
    all-events row, so we store every event rather than guessing which one
    matters (an earlier version of this code picked data[0] arbitrarily,
    which made two accounts' "EMQ" incomparable — this fixes that).
    """
    rows = raw.get("web") or []
    if not rows:
        return [{
            "event_name": None,
            "event_match_quality": None,
            "match_key_feedback": None,
            "acr": None,
            "event_coverage": None,
            "data_freshness": None,
            "diagnostics": {"raw": raw, "note": "no 'web' rows returned"},
        }]

    parsed = []
    for row in rows:
        emq_obj = row.get("event_match_quality") or {}
        raw_match_keys = emq_obj.get("match_key_feedback") or []
        # Normalize Meta's array-of-objects shape to a flat {identifier: pct}
        # dict — easier for the frontend to render generically.
        match_key_feedback = {}
        for item in raw_match_keys:
            identifier = item.get("identifier")
            coverage = item.get("coverage") or {}
            if identifier:
                match_key_feedback[identifier] = _safe_float(coverage.get("percentage"))

        parsed.append({
            "event_name": row.get("event_name"),
            "event_match_quality": _safe_float(emq_obj.get("composite_score")),
            "match_key_feedback": match_key_feedback or None,
            "acr": _extract_percentage(row.get("acr")),
            "event_coverage": _extract_percentage(row.get("event_coverage")),
            "data_freshness": _extract_freshness(row.get("data_freshness")),
            "diagnostics": {"raw_row": row},
        })
    return parsed


def sync_capi_quality(db: Session, snapshot_date: Optional[date] = None) -> dict:
    """Pull today's Dataset Quality snapshot for every pixel we have on file.

    One row per (pixel_id, fb_account_id, event_name, snapshot_date) —
    idempotent, safe to call more than once a day (e.g. the scheduled job plus
    a manual "Sync now"); re-running overwrites the same day's rows rather
    than duplicating them.
    """
    snapshot_date = snapshot_date or date.today()
    svc = FacebookService()
    if not svc.access_token:
        return {"synced": 0, "failed": 0, "skipped_reason": "FACEBOOK_ACCESS_TOKEN not configured"}

    account_names = _account_name_map(svc)
    tracked = get_tracked_pixels(svc)
    pixel_names: dict[str, Optional[str]] = {}
    synced = 0
    failed = 0
    for entry in tracked:
        pixel_id = entry["pixel_id"]
        fb_account_id = entry["fb_account_id"]
        account_name = account_names.get(normalize_account_id(fb_account_id)) if fb_account_id else None
        if pixel_id not in pixel_names:
            pixel_names[pixel_id] = fetch_pixel_name(pixel_id, svc.access_token)
        pixel_name = pixel_names[pixel_id]

        try:
            raw = fetch_dataset_quality(pixel_id, svc.access_token)
            parsed_rows = _parse_dataset_quality(raw)
        except Exception as exc:
            # Fetch/parse failed before we know any per-event breakdown — store
            # one error row for this pixel/account/day rather than silently
            # skipping it, and null out any stale metrics from a prior success
            # so a failed re-sync can't leave old numbers looking current.
            db.rollback()
            existing = (
                db.query(CapiQualitySnapshot)
                .filter(
                    CapiQualitySnapshot.pixel_id == pixel_id,
                    CapiQualitySnapshot.fb_account_id == fb_account_id,
                    CapiQualitySnapshot.snapshot_date == snapshot_date,
                    CapiQualitySnapshot.event_name.is_(None),
                )
                .first()
            )
            row = existing or CapiQualitySnapshot(
                id=generate_uuid(), pixel_id=pixel_id, snapshot_date=snapshot_date, event_name=None,
            )
            row.fb_account_id = fb_account_id
            row.account_name = account_name
            row.pixel_name = pixel_name
            row.event_match_quality = None
            row.acr = None
            row.event_coverage = None
            row.data_freshness = None
            row.match_key_feedback = None
            row.fetch_error = str(exc)[:2000]
            try:
                if not existing:
                    db.add(row)
                db.commit()
            except Exception as write_exc:
                db.rollback()
                logger.error("capi_quality: could not even record fetch_error for pixel %s: %s", pixel_id, write_exc)
            failed += 1
            logger.warning("capi_quality: fetch failed for pixel %s: %s", pixel_id, exc)
            continue

        for parsed in parsed_rows:
            existing = (
                db.query(CapiQualitySnapshot)
                .filter(
                    CapiQualitySnapshot.pixel_id == pixel_id,
                    CapiQualitySnapshot.fb_account_id == fb_account_id,
                    CapiQualitySnapshot.snapshot_date == snapshot_date,
                    CapiQualitySnapshot.event_name == parsed["event_name"],
                )
                .first()
            )
            row = existing or CapiQualitySnapshot(
                id=generate_uuid(),
                pixel_id=pixel_id,
                snapshot_date=snapshot_date,
                event_name=parsed["event_name"],
            )
            row.fb_account_id = fb_account_id
            row.account_name = account_name
            row.pixel_name = pixel_name
            row.event_match_quality = parsed["event_match_quality"]
            row.acr = parsed["acr"]
            row.event_coverage = parsed["event_coverage"]
            row.data_freshness = parsed["data_freshness"]
            row.match_key_feedback = parsed["match_key_feedback"]
            row.diagnostics = parsed["diagnostics"]
            row.fetch_error = None

            try:
                if not existing:
                    db.add(row)
                db.commit()
                synced += 1
            except Exception as write_exc:
                # A single bad row (e.g. a constraint violation) can't be
                # allowed to poison the session and abort every remaining
                # pixel — roll back just this row and keep going.
                db.rollback()
                failed += 1
                logger.error(
                    "capi_quality: failed to store snapshot for pixel %s event %s: %s",
                    pixel_id, parsed["event_name"], write_exc,
                )

    return {"synced": synced, "failed": failed, "tracked_pixels": len(tracked)}
