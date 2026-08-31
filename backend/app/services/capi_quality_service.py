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
from app.services.niche_extraction import _extract_niche
from app.services.redtrack_service import RedTrackService

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
    """acr/event_coverage/coverage are variously documented (or not confirmed
    at all) as an object carrying a `percentage` field, a bare number, or a
    numeric string — handle all three, and anything else (list, bool, garbage
    dict with no `percentage` key) resolves to None rather than raising.
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


CAPI_QUALITY_ACCOUNT_IDS_ENV = "CAPI_QUALITY_ACCOUNT_IDS"


def _tracked_account_allowlist() -> Optional[set]:
    """Optional comma-separated allowlist of ad_account_ids (same pattern as
    SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS elsewhere in this app). Unset = track
    every visible account (the original behavior). Steve scoped this down
    2026-08-28 — the unscoped version pulled ~26 pixels across all 12 visible
    accounts (most of them years-old ResourceHelpOnline test pixels with no
    real data), which both bloated the daily sync's Meta API calls and buried
    the one actual comparison (RHO vs RHO 4) under noise.
    """
    raw = os.getenv(CAPI_QUALITY_ACCOUNT_IDS_ENV, "").strip()
    if not raw:
        return None
    return {normalize_account_id(x.strip()) for x in raw.split(",") if x.strip()}


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

    Scoped to CAPI_QUALITY_ACCOUNT_IDS when that env var is set (see
    _tracked_account_allowlist) — skips get_adsets() entirely for accounts
    outside the allowlist, so scoping down also cuts the actual Meta API call
    volume, not just what gets displayed.
    """
    allowlist = _tracked_account_allowlist()
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
        if allowlist is not None and aid not in allowlist:
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


def _parse_match_key_feedback(emq_obj: dict) -> Optional[dict]:
    """Normalize Meta's `[{identifier, coverage: {percentage}}, ...]` array into
    a flat `{identifier: percentage}` dict. Every layer here is guarded: Meta
    (or a mock/future response) could send `match_key_feedback` as something
    other than a list, an item as something other than a dict, `identifier` as
    a non-string, or `coverage` as an object, a bare number, a numeric string,
    or missing entirely — none of those should raise, they just drop that one
    identifier (or all of them) rather than aborting the whole pixel's sync.
    """
    raw_match_keys = emq_obj.get("match_key_feedback")
    if not isinstance(raw_match_keys, list):
        return None

    match_key_feedback = {}
    for item in raw_match_keys:
        if not isinstance(item, dict):
            continue
        identifier = item.get("identifier")
        if not identifier or not isinstance(identifier, str):
            continue
        # coverage can be {"percentage": N}, a bare number/numeric string, or
        # absent — _extract_percentage already handles all three shapes.
        match_key_feedback[identifier] = _extract_percentage(item.get("coverage"))
    return match_key_feedback or None


def _parse_dataset_quality(raw) -> list[dict]:
    """Returns one parsed dict per event_name — Meta gives no aggregate/
    all-events row, so we store every event rather than guessing which one
    matters (an earlier version of this code picked data[0] arbitrarily,
    which made two accounts' "EMQ" incomparable — this fixes that).

    Every field extraction here is defensive: a malformed or unexpected shape
    for any single value resolves to None for that field, it never raises and
    aborts the pixel's whole sync. `raw` itself might not even be a dict if
    something upstream ever changes (defensive, not expected in practice since
    fetch_dataset_quality already calls response.json() on a 2xx response).
    """
    if not isinstance(raw, dict):
        return [{
            "event_name": None,
            "event_match_quality": None,
            "match_key_feedback": None,
            "acr": None,
            "event_coverage": None,
            "data_freshness": None,
            "diagnostics": {"raw": raw, "note": "response was not a JSON object"},
        }]

    rows = raw.get("web")
    if not isinstance(rows, list) or not rows:
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
        if not isinstance(row, dict):
            # A malformed individual row shouldn't drop the rest of the
            # pixel's events — skip just this one and keep going.
            logger.warning("capi_quality: skipping non-dict row in 'web' list: %r", row)
            continue

        emq_raw = row.get("event_match_quality")
        emq_obj = emq_raw if isinstance(emq_raw, dict) else {}

        parsed.append({
            "event_name": row.get("event_name"),
            "event_match_quality": _safe_float(emq_obj.get("composite_score")),
            "match_key_feedback": _parse_match_key_feedback(emq_obj),
            "acr": _extract_percentage(row.get("acr")),
            "event_coverage": _extract_percentage(row.get("event_coverage")),
            "data_freshness": _extract_freshness(row.get("data_freshness")),
            "diagnostics": {"raw_row": row},
        })

    if not parsed:
        # Every row in 'web' was malformed — still return something so the
        # caller records a visible (empty-but-not-crashed) result for the day
        # instead of silently storing zero events for this pixel.
        return [{
            "event_name": None,
            "event_match_quality": None,
            "match_key_feedback": None,
            "acr": None,
            "event_coverage": None,
            "data_freshness": None,
            "diagnostics": {"raw": raw, "note": "'web' rows were present but all malformed"},
        }]
    return parsed


_UPSERT_CONSTRAINT_NAME = "uq_capi_quality_pixel_account_event_date"
_UPSERT_UPDATE_COLUMNS = (
    "account_name",
    "pixel_name",
    "event_match_quality",
    "acr",
    "event_coverage",
    "data_freshness",
    "match_key_feedback",
    "diagnostics",
    "fetch_error",
)


def _upsert_snapshot(db: Session, values: dict) -> None:
    """Single atomic INSERT ... ON CONFLICT DO UPDATE, not a select-then-write.

    The prior version did `query(...).first()` to decide insert vs. update as
    two separate round trips — two concurrent syncs (the daily scheduler job
    landing at the same moment as a manual "Sync now" click, say) could both
    see "no existing row" and both try to INSERT, racing on the unique
    constraint. This does it in one statement Postgres itself serializes.

    Known limitation, not fixed here: Postgres treats each NULL as distinct in
    a unique constraint, so two concurrent syncs writing a NULL fb_account_id
    (an untagged ad set) or NULL event_name (a fetch-error placeholder row)
    for the same pixel/day could still each successfully INSERT without
    conflicting — this closes the race for the normal case (real account +
    real event, which is the vast majority of rows) but not that edge case.
    Fixing it fully would need a functional unique index over COALESCE'd
    sentinel values, which is a schema change beyond this fix's scope.

    Raises on failure — caller decides how to handle/log/rollback per row so
    one bad row can't abort the rest of the sync.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = pg_insert(CapiQualitySnapshot).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint=_UPSERT_CONSTRAINT_NAME,
        set_={col: stmt.excluded[col] for col in _UPSERT_UPDATE_COLUMNS},
    )
    db.execute(stmt)
    db.commit()


def _prune_out_of_scope_snapshots(db: Session) -> int:
    """Delete stored rows for accounts outside CAPI_QUALITY_ACCOUNT_IDS.

    Runs every sync when an allowlist is configured, not just once — so if
    the allowlist ever gets tightened further, or a new out-of-scope account
    starts a fresh CAPI experiment, this keeps cleaning up on its own instead
    of needing a one-off manual wipe every time. Rows with a NULL
    fb_account_id (shouldn't normally happen, but defensively) are treated as
    out of scope too when an allowlist is active — there's no way to know
    they're in scope.
    """
    allowlist = _tracked_account_allowlist()
    if allowlist is None:
        return 0
    deleted = (
        db.query(CapiQualitySnapshot)
        .filter(
            (CapiQualitySnapshot.fb_account_id.is_(None))
            | (~CapiQualitySnapshot.fb_account_id.in_(allowlist))
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def sync_capi_quality(db: Session, snapshot_date: Optional[date] = None) -> dict:
    """Pull today's Dataset Quality snapshot for every pixel we have on file.

    One row per (pixel_id, fb_account_id, event_name, snapshot_date) —
    idempotent, safe to call more than once a day (e.g. the scheduled job plus
    a manual "Sync now"); re-running overwrites the same day's rows rather
    than duplicating them. Each row is written via a single atomic upsert
    (see _upsert_snapshot) rather than a separate select-then-insert/update,
    so two syncs landing at the same moment can't race each other into a
    duplicate-key error.

    When CAPI_QUALITY_ACCOUNT_IDS is set, also prunes any stored snapshot
    rows outside that allowlist before syncing — keeps the Dashboard card
    (and the daily API call volume) scoped down permanently, not just for
    this one cleanup.
    """
    snapshot_date = snapshot_date or date.today()
    svc = FacebookService()
    if not svc.access_token:
        return {"synced": 0, "failed": 0, "skipped_reason": "FACEBOOK_ACCESS_TOKEN not configured"}

    pruned = _prune_out_of_scope_snapshots(db)
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
            try:
                _upsert_snapshot(db, {
                    "id": generate_uuid(),
                    "pixel_id": pixel_id,
                    "fb_account_id": fb_account_id,
                    "account_name": account_name,
                    "pixel_name": pixel_name,
                    "event_name": None,
                    "snapshot_date": snapshot_date,
                    "event_match_quality": None,
                    "acr": None,
                    "event_coverage": None,
                    "data_freshness": None,
                    "match_key_feedback": None,
                    "diagnostics": None,
                    "fetch_error": str(exc)[:2000],
                })
            except Exception as write_exc:
                db.rollback()
                logger.error("capi_quality: could not even record fetch_error for pixel %s: %s", pixel_id, write_exc)
            failed += 1
            logger.warning("capi_quality: fetch failed for pixel %s: %s", pixel_id, exc)
            continue

        # Reaching here means THIS call succeeded — clear any leftover
        # event_name=NULL placeholder row from an earlier attempt the same
        # day for this exact (pixel, account, day), whether that placeholder
        # came from an exception (fetch_error set) or from a prior call that
        # succeeded but got an empty/malformed 'web' list back (fetch_error
        # NULL — see _parse_dataset_quality's own "no data"/"all malformed"
        # fallback). Both are stale the moment a later call succeeds with
        # real data: confirmed live 2026-08-29 in two forms — (1) a "Couldn't
        # fetch" banner persisting on /latest even after a retried sync
        # fetched real Lead/CompleteRegistration/etc. scores, and (2) a bogus
        # phantom event_name=None row sitting in the events list alongside
        # otherwise-complete real data. If this call's own parse also lands
        # on the "no data" fallback, the loop below writes a fresh copy of
        # that same placeholder immediately after — no gap, just no stale
        # leftovers from a different day's attempt.
        try:
            db.query(CapiQualitySnapshot).filter(
                CapiQualitySnapshot.pixel_id == pixel_id,
                CapiQualitySnapshot.fb_account_id == fb_account_id,
                CapiQualitySnapshot.snapshot_date == snapshot_date,
                CapiQualitySnapshot.event_name.is_(None),
            ).delete(synchronize_session=False)
            db.commit()
        except Exception as clear_exc:
            db.rollback()
            logger.warning("capi_quality: could not clear stale error row for pixel %s: %s", pixel_id, clear_exc)

        for parsed in parsed_rows:
            try:
                _upsert_snapshot(db, {
                    "id": generate_uuid(),
                    "pixel_id": pixel_id,
                    "fb_account_id": fb_account_id,
                    "account_name": account_name,
                    "pixel_name": pixel_name,
                    "event_name": parsed["event_name"],
                    "snapshot_date": snapshot_date,
                    "event_match_quality": parsed["event_match_quality"],
                    "acr": parsed["acr"],
                    "event_coverage": parsed["event_coverage"],
                    "data_freshness": parsed["data_freshness"],
                    "match_key_feedback": parsed["match_key_feedback"],
                    "diagnostics": parsed["diagnostics"],
                    "fetch_error": None,
                })
                synced += 1
            except Exception as write_exc:
                # A single bad row (e.g. an unexpected constraint violation)
                # can't be allowed to poison the session and abort every
                # remaining pixel — roll back just this row and keep going.
                db.rollback()
                failed += 1
                logger.error(
                    "capi_quality: failed to store snapshot for pixel %s event %s: %s",
                    pixel_id, parsed["event_name"], write_exc,
                )

    return {"synced": synced, "failed": failed, "tracked_pixels": len(tracked), "pruned": pruned}


_PERFORMANCE_PRESETS = {"today", "yesterday", "last_7d", "last_14d", "last_30d", "this_month"}


def get_pixel_performance(
    date_preset: str = "last_30d",
    restrict_to_account_ids: Optional[set] = None,
    known_pixels: Optional[list[dict]] = None,
) -> dict:
    """Real Meta spend/leads + RedTrack revenue/cost, bucketed by PIXEL for an
    explicit date range — the actual "is the better EMQ pixel translating
    into lower cost / higher ROAS" answer, not just the match-quality score.

    Important mismatch, unavoidable given Meta's own API: the EMQ score shown
    elsewhere on this card has NO selectable date range (see the module
    docstring) — it's Meta's own rolling default of unknown exact length.
    This function's numbers DO have an explicit, real date_preset. The two
    are never perfectly time-aligned; treat them as two separate views, not
    one apples-to-apples pairing. Surfaced in the API response's date_from/
    date_to specifically so the frontend can label this honestly rather than
    implying it's the same window as the EMQ score.

    Ad-set-to-pixel mapping is read live from Meta (promoted_object.pixel_id)
    same as get_tracked_pixels, for the same reason: the local FacebookAdSet
    cache doesn't have it for these accounts.
    """
    if date_preset not in _PERFORMANCE_PRESETS:
        date_preset = "last_30d"

    svc = FacebookService()
    if not svc.access_token:
        return {"pixels": [], "date_preset": date_preset, "skipped_reason": "FACEBOOK_ACCESS_TOKEN not configured"}

    allowlist = _tracked_account_allowlist()
    try:
        accounts = svc.get_ad_accounts() or []
    except Exception as exc:
        logger.warning("capi_quality: could not list ad accounts for performance: %s", exc)
        return {"pixels": [], "date_preset": date_preset, "skipped_reason": str(exc)}

    account_names = _account_name_map(svc)
    full_account_ids = []  # allowlist-scoped only, ignoring the caller's own restriction
    account_ids = []       # also filtered by restrict_to_account_ids — what we actually query
    for acc in accounts:
        aid = normalize_account_id(acc.get("id") or acc.get("account_id"))
        if not aid:
            continue
        if allowlist is not None and aid not in allowlist:
            continue
        full_account_ids.append(aid)
        if restrict_to_account_ids is not None and aid not in restrict_to_account_ids:
            continue
        account_ids.append(aid)

    # A pixel can be shared across accounts (confirmed real for RHO/RHO4) — if
    # a restricted user (e.g. Abel/Joel) can see only SOME of the accounts
    # feeding a shared pixel, their bucket for it is a partial slice of real
    # spend/leads, not the complete number, and would look identical to a
    # complete one without a flag. Only pay for this extra pass when a
    # restriction is actually excluding something (the common case —
    # superusers, no restriction — skips it entirely).
    restricted_out_accounts = set(full_account_ids) - set(account_ids)
    pixel_all_accounts: dict[str, set] = {}
    if restricted_out_accounts:
        for aid in full_account_ids:
            try:
                for a in svc.get_adsets(ad_account_id=aid) or []:
                    pid = (a.get("promoted_object") or {}).get("pixel_id")
                    if pid:
                        pixel_all_accounts.setdefault(pid, set()).add(aid)
            except Exception as exc:
                logger.warning("capi_quality: could not check full account coverage for %s: %s", aid, exc)

    rt_svc = RedTrackService()
    date_from, date_to = RedTrackService.preset_to_dates(date_preset)
    try:
        rt_report = rt_svc.get_report_by_adset_preset(date_preset) if rt_svc.is_configured() else {}
    except Exception as exc:
        # RedTrack is supplementary here too — a failure shouldn't blank out
        # the real Meta spend/lead numbers, just leave revenue/ROAS null.
        logger.warning("capi_quality: RedTrack fetch failed for performance: %s", exc)
        rt_report = {}

    buckets: dict[str, dict] = {}

    def ensure_pixel_bucket(pixel_id: str) -> dict:
        return buckets.setdefault(pixel_id, {
            "spend": 0.0, "leads": 0, "adset_count": 0,
            "rt_conversions": 0, "rt_revenue": 0.0, "rt_cost": 0.0,
            "breakdown": {},
            "breakdown_by_campaign": {},
        })

    known_pixel_names = {}
    for pixel in known_pixels or []:
        pixel_id = pixel.get("pixel_id")
        if not pixel_id:
            continue
        ensure_pixel_bucket(pixel_id)
        if pixel.get("pixel_name"):
            known_pixel_names[pixel_id] = pixel["pixel_name"]

    for aid in account_ids:
        try:
            adsets = svc.get_adsets(ad_account_id=aid) or []
        except Exception as exc:
            logger.warning("capi_quality: could not list ad sets for performance on %s: %s", aid, exc)
            continue
        adset_pixel = {}
        adset_name_map = {}
        adset_campaign_map = {}
        for a in adsets:
            raw_adset_id = a.get("id")
            adset_id = str(raw_adset_id) if raw_adset_id else ""
            if adset_id:
                adset_name_map[adset_id] = a.get("name") or ""
                campaign = a.get("campaign") or {}
                adset_campaign_map[adset_id] = {
                    "campaign_id": a.get("campaign_id"),
                    "campaign_name": campaign.get("name") or "Unnamed Campaign",
                }
            promoted_object = a.get("promoted_object") or {}
            pixel_id = promoted_object.get("pixel_id")
            if pixel_id and adset_id:
                adset_pixel[adset_id] = pixel_id
                # Keep tracked pixels visible even when Meta returns no
                # insights rows for the selected date preset. Without this,
                # inactive-but-relevant pixels disappear from the comparison.
                ensure_pixel_bucket(pixel_id)

        try:
            insights = svc.get_account_insights_bulk(ad_account_id=aid, date_preset=date_preset)
        except Exception as exc:
            logger.warning("capi_quality: insights fetch failed for performance on %s: %s", aid, exc)
            continue

        for fb_adset_id, metrics in (insights or {}).items():
            pixel_id = adset_pixel.get(str(fb_adset_id))
            if not pixel_id:
                # An ad set with no pixel attached (or one Meta didn't return
                # promoted_object for) has its spend dropped from every
                # pixel's bucket — sum(pixel.spend) across the response can
                # legitimately be less than the account's true total spend
                # for the period. Fine for a per-pixel comparison view, just
                # not a full account reconciliation.
                continue
            b = ensure_pixel_bucket(pixel_id)
            niche = _extract_niche(
                adset_name_map.get(str(fb_adset_id)) or metrics.get("adset_name") or "",
                require_separator=True,
            )
            breakdown_key = (aid, niche or "General")
            nb = b["breakdown"].setdefault(breakdown_key, {
                "fb_account_id": aid,
                "account_name": account_names.get(aid),
                "niche": niche or "General",
                "spend": 0.0,
                "leads": 0,
                "adset_count": 0,
                "rt_conversions": 0,
                "rt_revenue": 0.0,
                "rt_cost": 0.0,
            })
            camp = adset_campaign_map.get(str(fb_adset_id)) or {}
            campaign_key = (aid, camp.get("campaign_id") or "unknown")
            cb = b["breakdown_by_campaign"].setdefault(campaign_key, {
                "fb_account_id": aid,
                "account_name": account_names.get(aid),
                "campaign_id": camp.get("campaign_id"),
                "campaign_name": camp.get("campaign_name") or "Unnamed Campaign",
                "spend": 0.0,
                "leads": 0,
                "adset_count": 0,
                "rt_conversions": 0,
                "rt_revenue": 0.0,
                "rt_cost": 0.0,
            })
            spend = _safe_float(metrics.get("spend")) or 0.0
            b["spend"] += spend
            nb["spend"] += spend
            cb["spend"] += spend
            # Route through _safe_float first, same as every other field here —
            # a bare int() on a decimal-formatted string (e.g. "12.0", which
            # Meta/RedTrack can plausibly send) raises ValueError with no
            # per-row guard around this line, which would 500 the whole
            # endpoint over one malformed value instead of just zeroing it.
            leads = int(_safe_float(metrics.get("leads")) or 0)
            b["leads"] += leads
            nb["leads"] += leads
            cb["leads"] += leads
            b["adset_count"] += 1
            nb["adset_count"] += 1
            cb["adset_count"] += 1
            rt = rt_report.get(str(fb_adset_id)) or {}
            rt_conversions = int(_safe_float(rt.get("conversions")) or 0)
            rt_revenue = _safe_float(rt.get("revenue")) or 0.0
            rt_cost = _safe_float(rt.get("cost")) or 0.0
            b["rt_conversions"] += rt_conversions
            b["rt_revenue"] += rt_revenue
            b["rt_cost"] += rt_cost
            nb["rt_conversions"] += rt_conversions
            nb["rt_revenue"] += rt_revenue
            nb["rt_cost"] += rt_cost
            cb["rt_conversions"] += rt_conversions
            cb["rt_revenue"] += rt_revenue
            cb["rt_cost"] += rt_cost

    # One serial Graph API call per distinct pixel — fine at the current
    # allowlist-scoped pixel count (2), would need batching (Meta's `?ids=`
    # multi-get) if this list ever grows large enough for it to matter.
    # known_pixel_names (from the snapshot table) is the fallback, not the
    # winner — a live Meta name should always take priority when the fetch
    # succeeds; the snapshot name only matters for a pixel with no currently
    # live ad set (fetch_pixel_name still tries, but has nothing to resolve
    # against). Merge order below reflects that: seed with known names,
    # then let any truthy live result overwrite it.
    live_pixel_names = {pid: fetch_pixel_name(pid, svc.access_token) for pid in buckets}
    pixel_names = dict(known_pixel_names)
    pixel_names.update({pid: name for pid, name in live_pixel_names.items() if name})

    pixels = []
    for pid, b in buckets.items():
        cpl = b["spend"] / b["leads"] if b["leads"] else None
        rt_cpl = b["rt_cost"] / b["rt_conversions"] if b["rt_conversions"] else None
        rt_roas = b["rt_revenue"] / b["rt_cost"] if b["rt_cost"] else None
        # True only when this pixel is ALSO fed by an account the caller
        # can't see — i.e. the numbers below are a real but incomplete slice,
        # not the full picture for this pixel.
        partial = bool(pixel_all_accounts.get(pid, set()) - set(account_ids))
        pixels.append({
            "pixel_id": pid,
            "pixel_name": pixel_names.get(pid),
            "adset_count": b["adset_count"],
            "spend": round(b["spend"], 2),
            "leads": b["leads"],
            "cpl": round(cpl, 2) if cpl is not None else None,
            "rt_conversions": b["rt_conversions"],
            "rt_revenue": round(b["rt_revenue"], 2),
            "rt_cost": round(b["rt_cost"], 2),
            "rt_cpl": round(rt_cpl, 2) if rt_cpl is not None else None,
            "rt_roas": round(rt_roas, 4) if rt_roas is not None else None,
            "partial": partial,
            "breakdown": sorted(
                [
                    {
                        **{k: v for k, v in nb.items() if k not in ("spend", "rt_revenue", "rt_cost")},
                        "spend": round(nb["spend"], 2),
                        "cpl": round(nb["spend"] / nb["leads"], 2) if nb["leads"] else None,
                        "rt_revenue": round(nb["rt_revenue"], 2),
                        "rt_cost": round(nb["rt_cost"], 2),
                        "rt_cpl": round(nb["rt_cost"] / nb["rt_conversions"], 2) if nb["rt_conversions"] else None,
                        "rt_roas": round(nb["rt_revenue"] / nb["rt_cost"], 4) if nb["rt_cost"] else None,
                    }
                    for nb in b["breakdown"].values()
                ],
                key=lambda row: row["spend"],
                reverse=True,
            ),
            "breakdown_by_campaign": sorted(
                [
                    {
                        **{k: v for k, v in cb.items() if k not in ("spend", "rt_revenue", "rt_cost")},
                        "spend": round(cb["spend"], 2),
                        "cpl": round(cb["spend"] / cb["leads"], 2) if cb["leads"] else None,
                        "rt_revenue": round(cb["rt_revenue"], 2),
                        "rt_cost": round(cb["rt_cost"], 2),
                        "rt_cpl": round(cb["rt_cost"] / cb["rt_conversions"], 2) if cb["rt_conversions"] else None,
                        "rt_roas": round(cb["rt_revenue"] / cb["rt_cost"], 4) if cb["rt_cost"] else None,
                    }
                    for cb in b["breakdown_by_campaign"].values()
                ],
                key=lambda row: row["spend"],
                reverse=True,
            ),
        })

    return {"pixels": pixels, "date_preset": date_preset, "date_from": date_from, "date_to": date_to}
