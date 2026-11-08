"""Naming presets: code observation over real RHO name shapes (2026-11-07 sample)."""
from app.services.naming_presets import (
    strip_unresolved_tokens,
    DEFAULT_TEMPLATES,
    campaign_niche_segment,
    default_preset,
    observe_codes,
    split_wave,
)

REAL = [
    ("WW8-FUN | FLEET AND CREW", "RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 10.19.2026"),
    ("WW8-FUN | HEARSE LABEL", "RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 10.19.2026"),
    ("VW-SEPT | SEPTIC AND PORTABLE TOILETS", "RHO v1 | ABO | VEHICLE W2 SEPTIC AND PORTABLE TOILETS | CAPI | 10.19.2026"),
    ("BW1-BAKE | BAKERIES", "RHO v1 | ABO | BREADTH W1 BAKERIES | CAPI | 10.21.2026"),
    ("BW2T-HAUL | HEAVY HAUL", "RHO v1 | ABO | BREADTH W2T HEAVY HAUL | CAPI | 10.28.2026"),
    ("POP-LIMO | WINNERS NEW IMAGES", "RHO v1 | ABO | LEADS | LIMO | CAPI | 10.06.2026"),
    # Legacy / free-form names must be ignored, not guessed at.
    ("BREAKOUT | WW3-LIMO-SUV-02 SUVLabel | $100/day | Oct 22", "RHO v1 | ABO | LEADS | LIMO | CAPI | 10.06.2026"),
    ("Tow Owners Broad", "RHO v1 | ABO | TOWING | CAPI | 10.21.2026"),
]


def test_niche_segment_skips_brand_budget_objective_tracking_and_date():
    assert campaign_niche_segment("RHO v1 | ABO | LEADS | AUTOBODY WINNERS | CAPI | 10.06.2026") == "AUTOBODY WINNERS"
    assert campaign_niche_segment("RHO v1 | CBO | LEADS | NICHE FINDER SHOPS | CAPI | 11.05.2026") == "NICHE FINDER SHOPS"


def test_wave_is_split_from_niche():
    assert split_wave("VEHICLE W2 FUNERAL HOMES") == ("VEHICLE W2", "FUNERAL HOMES")
    assert split_wave("BREADTH W2T HEAVY HAUL") == ("BREADTH W2T", "HEAVY HAUL")
    assert split_wave("WAVE 8 TOWING") == ("WAVE 8", "TOWING")
    assert split_wave("LIMO") == (None, "LIMO")


def test_observe_codes_uses_only_conforming_adsets_and_counts_them():
    out = observe_codes(REAL)
    codes = {r["code"]: r for r in out["niche_codes"]}
    assert codes["FUN"] == {"niche": "FUNERAL HOMES", "code": "FUN", "seen": 2}
    assert codes["SEPT"]["niche"] == "SEPTIC AND PORTABLE TOILETS"
    assert codes["HAUL"]["niche"] == "HEAVY HAUL"
    assert codes["LIMO"]["niche"] == "LIMO"
    assert "BREAKOUT" not in codes and len(codes) == 5
    assert out["niche_codes"][0]["code"] == "FUN"  # most-seen first
    waves = {r["code"]: r["wave"] for r in out["waves"]}
    assert waves["BW1"] == "BREADTH W1" and waves["BW2T"] == "BREADTH W2T"
    assert waves["POP"] == "POP"  # no wave words in the campaign: labelled by code


def test_default_preset_is_templates_only_and_unsaved():
    preset = default_preset("act_1")
    assert preset["templates"] == DEFAULT_TEMPLATES
    assert preset["saved"] is False
    assert preset["waves"] == [] and preset["niche_codes"] == [] and preset["brand_code"] == ""


def test_angle_text_is_never_recorded_as_a_niche():
    out = observe_codes([("XX-LIMO | NEW IMAGES", "RHO v1 | ABO | LEADS | CAPI | 10.06.2026")])
    assert out["niche_codes"] == []
    assert out["waves"][0]["code"] == "XX"


def test_junk_codes_skipped_and_brand_tracking_guessed():
    out = observe_codes(REAL + [("BW1-TEST | RESTAURANTS", "RHO v1 | ABO | BREADTH W1 RESTAURANTS | CAPI | 10.21.2026")])
    assert "TEST" not in {r["code"] for r in out["niche_codes"]}
    assert out["brand_code"] == "RHO v1" and out["tracking_tag"] == "CAPI"


def test_unresolved_tokens_never_reach_meta():
    assert strip_unresolved_tokens("{brand_code} | ABO | {wave} FUNERAL HOMES | {tracking} | 11.09.2026") == "ABO | FUNERAL HOMES | 11.09.2026"
    assert strip_unresolved_tokens("{wave_code}-FUN | {angle}") == "FUN"
    assert strip_unresolved_tokens("{wave_code}-{niche_code}-01-HearseAndStaff-IMG-1x1") == "01-HearseAndStaff-IMG-1x1"
    assert strip_unresolved_tokens("WW8-FUN | FLEET AND CREW") == "WW8-FUN | FLEET AND CREW"
    assert strip_unresolved_tokens("{angle}") == "Untitled"
    assert strip_unresolved_tokens(None) is None
