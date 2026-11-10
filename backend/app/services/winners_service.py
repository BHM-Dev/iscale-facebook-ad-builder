"""Pure aggregation and ranking for the Winning ads performance view."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
import logging
import threading
import time
from typing import Any, Iterable

from sqlalchemy import or_

from app.models import DriveAsset, FacebookAd, FacebookAdSet, FacebookCampaign, normalize_account_id
from app.services.facebook_service import FacebookService
from app.services.max_cpl_service import compute_max_cpl
from app.services.naming_presets import concept_from_filename, parse_adset_prefix
from app.services.redtrack_service import RedTrackService

logger = logging.getLogger(__name__)
CACHE_TTL_SECONDS = 15 * 60
_CACHE: dict[tuple, tuple[float, dict]] = {}
_LOCKS: dict[tuple, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                item = item.get("text") or item.get("headline") or item.get("value")
            if str(item or "").strip():
                return str(item).strip()
    if isinstance(value, str):
        return value.strip()
    return ""


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def group_winner_rows(
    ads: Iterable[dict],
    insights_by_adset: dict,
    max_cpl_by_adset: dict,
    redtrack_by_ad: dict,
    drive_by_filename: dict,
    group_by: str,
    known_niche_codes: set | None = None,
) -> list[dict]:
    """Join ad-grain inputs and return unranked aggregate rows.

    Insights is the period inventory: local ads with no delivery are not added as
    empty winners. Meta rows without a local FacebookAd remain visible so spend
    is never silently omitted from the rollup.
    """
    if group_by not in {"creative", "concept", "headline"}:
        raise ValueError("group_by must be creative, concept, or headline")

    local_by_id = {str(ad.get("ad_id")): ad for ad in ads if ad.get("ad_id")}
    groups: dict[str, dict] = {}

    for insight_adset_id, insight_rows in (insights_by_adset or {}).items():
        for insight in insight_rows or []:
            ad_id = str(insight.get("ad_id") or "").strip()
            if not ad_id:
                continue
            local = local_by_id.get(ad_id, {})
            adset_id = str(local.get("adset_id") or insight_adset_id or "").strip()
            creative_name = str(local.get("creative_name") or local.get("ad_name") or insight.get("ad_name") or ad_id).strip()
            concept = concept_from_filename(creative_name) or creative_name
            headline = _first_text(local.get("headlines")) or "No headline"
            if group_by == "creative":
                key, label = creative_name, creative_name
            elif group_by == "concept":
                key, label = concept.casefold(), concept
            else:
                key, label = " ".join(headline.split()).casefold(), headline

            if key not in groups:
                groups[key] = {
                    "key": key,
                    "label": label,
                    "group_by": group_by,
                    "concept": concept,
                    "image_url": local.get("thumbnail_url") or local.get("image_url"),
                    "drive_file_id": None,
                    "drive_file_name": None,
                    "drive_file_ids": [],
                    "drive_file_names": [],
                    "niches": [],
                    "niche_codes": [],
                    "adset_count": 0,
                    "ad_ids": [],
                    "active_ad_count": 0,
                    "spend": 0.0,
                    "leads": 0,
                    "cpl": None,
                    "max_cpl": None,
                    "est_revenue": None,
                    "est_profit": None,
                    "est_partial": False,
                    "rt_revenue": 0.0,
                    "rt_coverage": "none",
                    "first_seen": _iso(local.get("created_at")),
                    "top_spend_ad_id": ad_id,
                    "details": [],
                    "_adsets": set(),
                    "_active_ids": set(),
                    "_rt_ids": set(),
                    "_known_rpl_ads": 0,
                    "_missing_rpl_ads": 0,
                    "_known_spend": 0.0,
                    "_weighted_max_cpl": 0.0,
                    "_max_cpls": [],
                    "_top_spend": -1.0,
                    "_est_revenue": 0.0,
                    "_rpl_spend": 0.0,
                }
            row = groups[key]
            spend = _number(insight.get("spend"))
            leads = int(_number(insight.get("leads")))
            cpl = spend / leads if leads else None
            max_entry = max_cpl_by_adset.get(adset_id) or {}
            rpl_raw = max_entry.get("rpl")
            max_cpl_raw = max_entry.get("max_cpl")
            has_rpl = rpl_raw is not None
            niche = str(max_entry.get("niche") or local.get("niche") or "").strip()
            prefix = parse_adset_prefix(local.get("adset_name"))
            # Ads with no local launch record (duplicated in Ads Manager) still carry the convention in the
            # file/ad name (`VW-PLOW-02-PlowLabel-IMG-1x1.jpg`): use it for the niche code and the Drive match.
            name_prefix = re.match(r"^([A-Z0-9]{1,8})-([A-Z0-9]{2,8})-\d{1,3}-", creative_name, re.I)
            # Only trust a code read off the file name when the account's naming setup knows it: older names
            # like `CR-ITER-01-...` / `TRUCK-RB-05-...` would otherwise yield ITER / RB as fake niches.
            name_code = name_prefix.group(2).upper() if name_prefix else None
            niche_code = prefix.get("niche_code") or (name_code if name_code and known_niche_codes and name_code in known_niche_codes else None)
            drive = drive_by_filename.get(creative_name) or drive_by_filename.get(str(insight.get("ad_name") or "").strip())

            row["spend"] += spend
            row["leads"] += leads
            row["ad_ids"].append(ad_id)
            row["_adsets"].add(adset_id)
            if str(local.get("status") or "").upper() == "ACTIVE":
                row["_active_ids"].add(ad_id)
            if niche and niche not in row["niches"]:
                row["niches"].append(niche)
            if niche_code and niche_code not in row["niche_codes"]:
                row["niche_codes"].append(niche_code)
            if drive:
                drive_id = drive.get("drive_file_id")
                drive_name = drive.get("file_name") or creative_name
                if drive_id and drive_id not in row["drive_file_ids"]:
                    row["drive_file_ids"].append(drive_id)
                    row["drive_file_names"].append(drive_name)
                row["drive_file_id"] = row["drive_file_id"] or drive_id
                row["drive_file_name"] = row["drive_file_name"] or drive_name
                row["image_url"] = drive.get("thumbnail_url") or drive.get("image_url") or row["image_url"]

            if has_rpl:
                rpl = _number(rpl_raw)
                row["_known_rpl_ads"] += 1
                row["_est_revenue"] += leads * rpl
                row["_rpl_spend"] += spend
                if max_cpl_raw is not None:
                    max_cpl = _number(max_cpl_raw)
                    row["_weighted_max_cpl"] += max_cpl * spend
                    row["_known_spend"] += spend
                    row["_max_cpls"].append(max_cpl)
            else:
                row["_missing_rpl_ads"] += 1

            rt = redtrack_by_ad.get(ad_id)
            if rt is not None:
                row["_rt_ids"].add(ad_id)
                row["rt_revenue"] += _number(rt.get("revenue"))
            if spend > row["_top_spend"]:
                row["_top_spend"] = spend
                row["top_spend_ad_id"] = ad_id
                row["image_url"] = (
                    (drive.get("thumbnail_url") or drive.get("image_url")) if drive else None
                ) or local.get("thumbnail_url") or local.get("image_url") or row["image_url"]
            seen = _iso(local.get("created_at"))
            if seen and (not row["first_seen"] or seen < row["first_seen"]):
                row["first_seen"] = seen
            row["details"].append({
                "ad_id": ad_id,
                "ad_name": local.get("ad_name") or insight.get("ad_name") or ad_id,
                "creative_name": creative_name,
                "niche": niche or None,
                "niche_code": niche_code,
                "adset_name": local.get("adset_name"),
                "spend": round(spend, 2),
                "leads": leads,
                "cpl": round(cpl, 2) if cpl is not None else None,
                "max_cpl": round(_number(max_cpl_raw), 2) if max_cpl_raw is not None else None,
                "drive_file_id": drive.get("drive_file_id") if drive else None,
                "drive_file_name": drive.get("file_name") if drive else None,
            })

    result = []
    for row in groups.values():
        ad_count = len(row["ad_ids"])
        row["adset_count"] = len(row.pop("_adsets"))
        row["active_ad_count"] = len(row.pop("_active_ids"))
        rt_count = len(row.pop("_rt_ids"))
        row["rt_coverage"] = "full" if rt_count == ad_count else "partial" if rt_count else "none"
        known = row.pop("_known_rpl_ads")
        missing = row.pop("_missing_rpl_ads")
        known_spend = row.pop("_known_spend")
        weighted = row.pop("_weighted_max_cpl")
        max_cpls = row.pop("_max_cpls")
        est_revenue = row.pop("_est_revenue")
        rpl_spend = row.pop("_rpl_spend")
        row.pop("_top_spend")
        row["cpl"] = round(row["spend"] / row["leads"], 2) if row["leads"] else None
        row["max_cpl"] = round(weighted / known_spend, 2) if known_spend else (round(sum(max_cpls) / len(max_cpls), 2) if max_cpls else None)
        if known:
            row["est_revenue"] = round(est_revenue, 2)
            # Spend of ads whose niche has no revenue-per-lead is excluded rather than counted as $0-revenue cost.
            row["est_profit"] = round(est_revenue - rpl_spend, 2)
        row["est_partial"] = bool(missing)
        row["spend"] = round(row["spend"], 2)
        row["rt_revenue"] = round(row["rt_revenue"], 2)
        row["niches"].sort()
        row["niche_codes"].sort()
        row["details"].sort(key=lambda detail: (-detail["spend"], detail["ad_name"]))
        result.append(row)
    return result


def rank_winner_rows(rows: Iterable[dict], min_leads: int = 10, max_cpl_available: bool = True) -> list[dict]:
    """Apply the evidence floor and deterministic profit/lead ordering."""
    ranked = deepcopy(list(rows))
    for row in ranked:
        row["enough_data"] = int(row.get("leads") or 0) >= min_leads

    def key(row: dict):
        enough = row["enough_data"]
        profit = row.get("est_profit")
        if max_cpl_available and profit is not None:
            primary = float(profit)
            has_estimate = 1
        else:
            primary = float(row.get("leads") or 0)
            has_estimate = 0
        return (0 if enough else 1, -has_estimate, -primary, -float(row.get("leads") or 0), -float(row.get("spend") or 0), str(row.get("label") or ""))

    ranked.sort(key=key)
    return ranked


def _lock_for(key: tuple) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _cached(key: tuple) -> dict | None:
    item = _CACHE.get(key)
    if item and time.monotonic() - item[0] < CACHE_TTL_SECONDS:
        return deepcopy(item[1])
    if item:
        _CACHE.pop(key, None)
    return None


def _local_ads(db, account_id: str) -> list[dict]:
    normalized = normalize_account_id(account_id)
    numeric = normalized.removeprefix("act_") if normalized else normalized
    rows = (
        db.query(FacebookAd, FacebookAdSet, FacebookCampaign)
        .join(FacebookAdSet, FacebookAd.adset_id == FacebookAdSet.id)
        .join(FacebookCampaign, FacebookAdSet.campaign_id == FacebookCampaign.id)
        .filter(or_(FacebookAdSet.fb_account_id == normalized, FacebookAdSet.fb_account_id == numeric))
        .all()
    )
    return [{
        "ad_id": ad.fb_ad_id,
        "ad_name": ad.name,
        "creative_name": ad.creative_name,
        "image_url": ad.image_url,
        "thumbnail_url": ad.thumbnail_url,
        "headlines": ad.headlines,
        "status": ad.status,
        "created_at": ad.created_at,
        "adset_id": adset.fb_adset_id,
        "adset_name": adset.name,
        "campaign_name": campaign.name,
    } for ad, adset, campaign in rows]


def _known_niche_codes(db, account_id: str) -> set:
    from app.models import NamingPreset
    row = db.query(NamingPreset).filter(NamingPreset.ad_account_id == normalize_account_id(account_id)).first()
    return {str(r.get("code") or "").upper() for r in (row.niche_codes if row else []) or [] if r.get("code")}


def _drive_assets(db, creative_names: set[str]) -> dict[str, dict]:
    if not creative_names:
        return {}
    rows = (
        db.query(DriveAsset)
        .filter(DriveAsset.archived.is_(False), DriveAsset.file_name.in_(creative_names))
        .order_by(DriveAsset.drive_modified_time.desc())
        .all()
    )
    result = {}
    for asset in rows:
        # A duplicate filename is ambiguous; deterministic newest-first behavior
        # matches what Joel sees at the top of the Drive picker.
        result.setdefault(asset.file_name, {
            "drive_file_id": asset.drive_file_id,
            "file_name": asset.file_name,
            "image_url": asset.r2_key,
            "thumbnail_url": asset.thumbnail_r2_key,
        })
    # Meta ad names sometimes drop the size/extension (`RB-LIMO-03-BlackSuvCosts` for the Drive file
    # `RB-LIMO-03-BlackSuvCosts-IMG-1x1.jpg`). Only convention names (CODE-CODE-NN-...) get this prefix
    # match, and a 1x1 feed file is preferred so Relaunch picks the same asset the picker shows first.
    stems = [n for n in creative_names if n not in result and "." not in n[-5:] and re.match(r"^[A-Z0-9]{1,8}-[A-Z0-9]{2,8}-\d{1,3}-\S+$", n, re.I)]
    for stem in stems:
        candidates = (
            db.query(DriveAsset)
            .filter(DriveAsset.archived.is_(False), DriveAsset.file_name.ilike(f"{stem}-%"))
            .order_by(DriveAsset.drive_modified_time.desc())
            .limit(6)
            .all()
        )
        if not candidates:
            continue
        asset = next((c for c in candidates if "-1x1" in (c.file_name or "")), candidates[0])
        result[stem] = {
            "drive_file_id": asset.drive_file_id,
            "file_name": asset.file_name,
            "image_url": asset.r2_key,
            "thumbnail_url": asset.thumbnail_r2_key,
        }
    return result


def get_winner_base_rows(
    db,
    account_id: str,
    date_preset: str,
    date_from: str | None,
    date_to: str | None,
    group_by: str,
) -> tuple[dict, bool]:
    """Fetch/join sources once per 15-minute account/range/group cache key."""
    key = (normalize_account_id(account_id), date_preset, date_from, date_to, group_by)
    cached = _cached(key)
    if cached is not None:
        return cached, True
    with _lock_for(key):
        cached = _cached(key)
        if cached is not None:
            return cached, True

        # Import here to reuse the exact ads-bulk cache without coupling module
        # imports during application startup.
        from app.api.v1.auto_pause import _read_insights_bulk_cache, _write_insights_bulk_cache

        meta_key = ("ads-bulk", account_id, date_preset, date_from, date_to)
        started = time.monotonic()
        insights = _read_insights_bulk_cache(meta_key, False)
        if insights is None:
            insights = FacebookService().get_account_ads_insights_bulk(
                ad_account_id=account_id,
                date_preset=date_preset,
                date_from=date_from,
                date_to=date_to,
            )
            _write_insights_bulk_cache(meta_key, insights, started)

        ads = _local_ads(db, account_id)
        names = {str(ad.get("creative_name")) for ad in ads if ad.get("creative_name")}
        # Meta ad names too: ads duplicated in Ads Manager have no local record but keep the Drive file name.
        names |= {str(row.get("ad_name")).strip() for rows in (insights or {}).values() for row in (rows or []) if row.get("ad_name")}
        drive = _drive_assets(db, names)
        max_cpl = compute_max_cpl(db, normalize_account_id(account_id))
        max_cpl_available = bool(max_cpl.get("available"))
        if date_from and date_to:
            rt_from, rt_to = date_from, date_to
        else:
            rt_from, rt_to = RedTrackService.preset_to_dates(date_preset)
        try:
            redtrack = RedTrackService().get_report_by_sub(rt_from, rt_to, "sub1")
        except Exception:
            logger.exception("Winning ads RedTrack read failed for %s", account_id)
            redtrack = None

        rows = group_winner_rows(
            ads,
            insights,
            max_cpl.get("adsets") or {},
            redtrack or {},
            drive,
            group_by,
            _known_niche_codes(db, account_id),
        )
        payload = {
            "rows": rows,
            "group_by": group_by,
            "date_preset": date_preset,
            "date_from": rt_from,
            "date_to": rt_to,
            "max_cpl_available": max_cpl_available,
            "max_cpl_reason": None if max_cpl_available else max_cpl.get("reason", "Max CPL unavailable"),
            "rt_available": redtrack is not None,
        }
        if redtrack is None:
            for row in rows:
                row["rt_revenue"] = None
                row["rt_coverage"] = "none"
        # Never cache a degraded result (Max CPL or RedTrack down): the next load should retry, not
        # serve "unavailable" / missing revenue for 15 minutes.
        if redtrack is not None and max_cpl_available:
            _CACHE[key] = (time.monotonic(), deepcopy(payload))
        if len(_CACHE) > 64:
            for stale_key, _ in sorted(_CACHE.items(), key=lambda item: item[1][0])[:len(_CACHE) - 64]:
                _CACHE.pop(stale_key, None)
        return payload, False
