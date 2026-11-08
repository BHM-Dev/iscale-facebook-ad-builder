"""Shared, per-ad-account naming presets.

The defaults below are template *strings* only (no business data). A row is
written only when someone saves; GET on an account with no row returns these.

`observe_codes` reads existing ad-set / campaign names so the niche-code and
wave dictionaries start from the codes the buyers already use
(e.g. ``WW8-FUN | FLEET AND CREW`` under ``RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 10.19.2026``).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable

DEFAULT_TEMPLATES = {
    "campaign": "{brand_code} | {budget_type} | {objective_tag} | {wave} {niche} | {tracking} | {date:MM.DD.YYYY}",
    "adset": "{wave_code}-{niche_code} | {angle}",
    "ad": "{wave_code}-{niche_code}-{seq:02}-{concept}-{media}-{ratio}",
}


def default_preset(ad_account_id: str) -> dict:
    return {
        "ad_account_id": ad_account_id,
        "brand_code": "",
        "tracking_tag": "",
        "uppercase": True,
        "templates": dict(DEFAULT_TEMPLATES),
        "waves": [],
        "niche_codes": [],
        "objective_tags": {},
        "variant": None,
        "soft_tags": None,
        "updated_by": None,
        "updated_at": None,
        "saved": False,
    }


# `WW8-FUN | FLEET AND CREW`, `BW2T-COACH | CHARTER BUSES`
_ADSET_PREFIX = re.compile(r"^\s*([A-Z0-9]{1,8})-([A-Z0-9]{2,8})\s*\|\s*(.+?)\s*$")
# Wave words at the start of the campaign's niche segment: `VEHICLE W2`, `BREADTH W2T`, `WAVE 8`
_WAVE_PREFIX = re.compile(r"^((?:[A-Z]+\s+)?W\d+[A-Z]?|WAVE\s+\d+)\s+(.+)$")
_DATE = re.compile(r"^\d{1,2}\.\d{1,2}(\.\d{2,4})?$")
_NOISE = {"ABO", "CBO", "LEADS", "CAPI", "SALES", "TRAFFIC"}


def campaign_niche_segment(campaign_name: str) -> str | None:
    """The first segment that isn't brand / budget type / objective / tracking / date."""
    parts = [p.strip() for p in (campaign_name or "").split("|")]
    for i, part in enumerate(parts):
        up = part.upper()
        if not part or i == 0 and len(parts) > 2 or up in _NOISE or _DATE.match(part):
            continue
        return up
    return None


def split_wave(segment: str | None) -> tuple[str | None, str | None]:
    """`VEHICLE W2 FUNERAL HOMES` -> ('VEHICLE W2', 'FUNERAL HOMES'); no wave -> (None, segment)."""
    if not segment:
        return None, None
    m = _WAVE_PREFIX.match(segment)
    return (m.group(1), m.group(2)) if m else (None, segment)


def observe_codes(rows: Iterable[tuple[str, str]]) -> dict:
    """rows = (adset_name, campaign_name). Returns code dictionaries with counts.

    Only ad sets that follow the `CODE-CODE | ...` shape contribute; everything
    else is ignored rather than guessed at.
    """
    niche_counts: dict[str, Counter] = defaultdict(Counter)
    wave_counts: dict[str, Counter] = defaultdict(Counter)
    for adset_name, campaign_name in rows:
        m = _ADSET_PREFIX.match((adset_name or "").upper())
        if not m:
            continue
        wave_code, niche_code, _angle = m.groups()
        wave, niche = split_wave(campaign_niche_segment(campaign_name))
        # Only trust the campaign's niche segment. The ad-set text after `|` is an
        # angle ("FLEET AND CREW"), so it must never be recorded as a niche.
        if niche:
            niche_counts[niche_code][niche] += 1
        wave_counts[wave_code][wave or ""] += 1

    def pick(counter: Counter) -> tuple[str, int]:
        name, _ = counter.most_common(1)[0]
        return name, sum(counter.values())

    niche_codes = sorted(
        ({"niche": pick(c)[0], "code": code, "seen": pick(c)[1]} for code, c in niche_counts.items()),
        key=lambda r: (-r["seen"], r["code"]),
    )
    waves = sorted(
        ({"wave": pick(c)[0], "code": code, "seen": pick(c)[1]} for code, c in wave_counts.items()),
        key=lambda r: (-r["seen"], r["code"]),
    )
    return {"niche_codes": niche_codes, "waves": waves}
