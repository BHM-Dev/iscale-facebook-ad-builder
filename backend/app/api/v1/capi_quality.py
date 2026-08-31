"""CAPI (Conversions API) match-quality monitoring.

Backs the Dashboard's "CAPI Match Quality" card. Pulls Meta's Dataset Quality
API (Event Match Quality) once a day per pixel and stores it, so the app can
show EMQ / ACR / match-key coverage side by side across pixels — the question
this exists to answer: is RHO 4's advertiser-run CAPI pixel actually matching
better than the original pixel on RHO's own account?

Meta returns EMQ per event_name with no aggregate/all-events row, so each
pixel can have more than one event's worth of data on a given day. `/latest`
groups by PIXEL, not by account — confirmed live 2026-08-28 that grouping by
account instead was actively misleading: RHO's own account has ad sets on
the exact same pixel RHO 4 uses, so an account-grouped view showed that one
pixel's identical data twice, under two different account names, which read
as "two accounts happen to match" rather than "this is one dataset." Each
pixel now lists every account that sends to it, so it's structurally
impossible to mistake one pixel counted twice for a real two-pixel
comparison.
"""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal
from sqlalchemy.orm import Session

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models import CapiQualitySnapshot, User, normalize_account_id
from app.services.capi_quality_service import get_pixel_performance, sync_capi_quality

router = APIRouter()


def _serialize_event(row: CapiQualitySnapshot) -> dict:
    return {
        "event_name": row.event_name,
        "event_match_quality": float(row.event_match_quality) if row.event_match_quality is not None else None,
        "acr": float(row.acr) if row.acr is not None else None,
        "event_coverage": float(row.event_coverage) if row.event_coverage is not None else None,
        "data_freshness": row.data_freshness,
        "match_key_feedback": row.match_key_feedback,
        "fetch_error": row.fetch_error,
    }


def _allowed_filter(query, current_user: User):
    """Same account-scoping convention as facebook.py/pnl.py: allowed_account_ids()
    returns None for unrestricted users (superuser or unassigned); otherwise
    restrict to that user's assigned ad accounts. Without this, a scoped user
    (e.g. Abel, Joel) would see every other advertiser's CAPI match data.
    """
    allowed = current_user.allowed_account_ids()
    if allowed is None:
        return query
    normalized = {normalize_account_id(a) for a in allowed}
    return query.filter(CapiQualitySnapshot.fb_account_id.in_(normalized))


# Postgres' plain `IS` only works against boolean/NULL literals, not another
# column — fb_account_id (and event_name) can be NULL on either side of a
# self-join, so compare via COALESCE to a sentinel rather than reaching for
# IS NOT DISTINCT FROM.
_NULL_SENTINEL = "__none__"


@router.get("/latest")
def get_latest(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Most recent snapshot per (pixel, account, event), grouped into one
    entry per PIXEL — every account that sends to a given pixel is listed
    together under it, rather than one row per (pixel, account) pair.

    Looks back up to 3 days in case yesterday's daily job hasn't run yet or
    failed for a given pixel; doesn't silently fall back further than that so
    a genuinely stale/broken pixel shows up as missing, not as old data.
    """
    cutoff = date.today() - timedelta(days=3)

    latest_dates = (
        db.query(
            CapiQualitySnapshot.pixel_id,
            CapiQualitySnapshot.fb_account_id,
            CapiQualitySnapshot.event_name,
            func.max(CapiQualitySnapshot.snapshot_date).label("max_date"),
        )
        .filter(CapiQualitySnapshot.snapshot_date >= cutoff)
        .group_by(CapiQualitySnapshot.pixel_id, CapiQualitySnapshot.fb_account_id, CapiQualitySnapshot.event_name)
        .subquery()
    )

    left_account = func.coalesce(CapiQualitySnapshot.fb_account_id, literal(_NULL_SENTINEL))
    right_account = func.coalesce(latest_dates.c.fb_account_id, literal(_NULL_SENTINEL))
    left_event = func.coalesce(CapiQualitySnapshot.event_name, literal(_NULL_SENTINEL))
    right_event = func.coalesce(latest_dates.c.event_name, literal(_NULL_SENTINEL))

    query = (
        db.query(CapiQualitySnapshot)
        .join(
            latest_dates,
            (CapiQualitySnapshot.pixel_id == latest_dates.c.pixel_id)
            & (left_account == right_account)
            & (left_event == right_event)
            & (CapiQualitySnapshot.snapshot_date == latest_dates.c.max_date),
        )
    )
    query = _allowed_filter(query, current_user)
    # Order accounts-within-a-pixel deterministically too, so "first account
    # seen" (used below to pick a representative fb_account_id for /history)
    # is stable across reloads rather than depending on row-fetch order.
    rows = query.order_by(
        CapiQualitySnapshot.pixel_name.asc().nullslast(),
        CapiQualitySnapshot.account_name.asc().nullslast(),
    ).all()

    pixels: dict[str, dict] = {}
    order: list[str] = []
    seen_events: dict[str, set] = {}
    for row in rows:
        pixel_key = row.pixel_id
        if pixel_key not in pixels:
            pixels[pixel_key] = {
                "pixel_id": row.pixel_id,
                "pixel_name": row.pixel_name,
                "accounts": [],
                "snapshot_date": row.snapshot_date.isoformat() if row.snapshot_date else None,
                "events": [],
            }
            order.append(pixel_key)
            seen_events[pixel_key] = set()

        account_entry = {"fb_account_id": row.fb_account_id, "account_name": row.account_name}
        if account_entry not in pixels[pixel_key]["accounts"]:
            pixels[pixel_key]["accounts"].append(account_entry)

        # A fetch-error placeholder row (event_name is None) has no events
        # data to show — surface it as a pixel-level error instead of an
        # event. Every account sharing a pixel hits the identical Meta call
        # (dataset_quality only takes the pixel id, not the account), so a
        # failure here applies to the whole pixel, not just one account.
        if row.event_name is None and row.fetch_error:
            pixels[pixel_key]["fetch_error"] = row.fetch_error
        elif row.event_name not in seen_events[pixel_key]:
            # Same pixel + same day + same event is identical data no matter
            # which account's row we're looking at — take the first one seen
            # instead of listing (and rendering) the same event N times for
            # an N-account pixel.
            seen_events[pixel_key].add(row.event_name)
            pixels[pixel_key]["events"].append(_serialize_event(row))

    return {"pixels": [pixels[k] for k in order]}


@router.get("/history")
def get_history(
    pixel_id: str = Query(...),
    fb_account_id: str = Query(...),
    event_name: str = Query(...),
    days: int = Query(default=30, ge=1, le=180),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Trend for one (pixel, account, event) — used by the Dashboard card's
    expanded detail view once an event has been picked to chart.
    """
    cutoff = date.today() - timedelta(days=days)
    query = db.query(CapiQualitySnapshot).filter(
        CapiQualitySnapshot.pixel_id == pixel_id,
        CapiQualitySnapshot.fb_account_id == fb_account_id,
        CapiQualitySnapshot.event_name == event_name,
        CapiQualitySnapshot.snapshot_date >= cutoff,
    )
    query = _allowed_filter(query, current_user)
    rows = query.order_by(CapiQualitySnapshot.snapshot_date.asc()).all()
    return {
        "pixel_id": pixel_id,
        "fb_account_id": fb_account_id,
        "event_name": event_name,
        "history": [
            {"snapshot_date": r.snapshot_date.isoformat() if r.snapshot_date else None, **_serialize_event(r)}
            for r in rows
        ],
    }


@router.get("/performance")
def get_performance(
    date_preset: str = Query(default="last_30d"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """Real Meta spend/leads + RedTrack revenue/cost, bucketed by pixel, for
    an explicit date range — separate from the EMQ score's own rolling
    window (see capi_quality_service module docstring for why those two
    numbers can't be perfectly time-aligned).

    Live Meta/RedTrack calls, not the stored snapshot table — not cached,
    since this is meant to be checked occasionally with different date
    ranges, not polled on every Dashboard load. Account-scoped the same way
    as /latest: a restricted user only sees performance for pixels tied to
    their own allowed accounts.
    """
    allowed = current_user.allowed_account_ids()
    restrict_to = {normalize_account_id(a) for a in allowed} if allowed is not None else None
    cutoff = date.today() - timedelta(days=3)
    known_query = (
        db.query(CapiQualitySnapshot.pixel_id, func.max(CapiQualitySnapshot.pixel_name).label("pixel_name"))
        .filter(CapiQualitySnapshot.snapshot_date >= cutoff)
        .filter(CapiQualitySnapshot.pixel_id.isnot(None))
        .group_by(CapiQualitySnapshot.pixel_id)
    )
    known_query = _allowed_filter(known_query, current_user)
    known_pixels = [
        {"pixel_id": row.pixel_id, "pixel_name": row.pixel_name}
        for row in known_query.all()
    ]
    result = get_pixel_performance(
        date_preset=date_preset,
        restrict_to_account_ids=restrict_to,
        known_pixels=known_pixels,
    )
    if result.get("skipped_reason"):
        raise HTTPException(status_code=503, detail=result["skipped_reason"])
    return result


@router.post("/sync")
def sync_now(db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    """Manual trigger — same code path as the daily scheduled job.

    Any authenticated user can run this (read-only against Meta, idempotent
    per day) — matches the existing "Sync now" precedent on Drive assets.
    The sync itself pulls every tracked pixel regardless of caller (it's a
    shared daily job, not a per-user action); scoping is enforced on read
    in get_latest/get_history above, not here.
    """
    try:
        result = sync_capi_quality(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    if result.get("skipped_reason"):
        raise HTTPException(status_code=503, detail=result["skipped_reason"])
    return result
