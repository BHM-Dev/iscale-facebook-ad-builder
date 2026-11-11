"""Wave words must not split one niche into several (Dashboard niche table, Intelligence, Copy Library)."""
from app.services.niche_extraction import _extract_niche


def test_wave_prefix_is_stripped_from_campaign_niche():
    assert _extract_niche("WW8-FUN | FLEET AND CREW", "RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 10.19.2026") == "FUNERAL HOMES"
    assert _extract_niche("BW2T-HAUL | HEAVY HAUL", "RHO v1 | ABO | BREADTH W2T HEAVY HAUL | CAPI | 10.28.2026") == "HEAVY HAUL"
    assert _extract_niche("EXP-AR | AUTO REPAIR", "RHO v1 | ABO | EXPLORE W1 AUTO REPAIR | CAPI | 10.15.2026") == "AUTO REPAIR"


def test_names_without_a_wave_are_unchanged():
    assert _extract_niche("POP-LIMO | WINNERS", "RHO v1 | ABO | LEADS | LIMO | CAPI | 10.06.2026") == "LIMO"
