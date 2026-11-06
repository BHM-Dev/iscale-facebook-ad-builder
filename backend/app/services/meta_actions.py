"""Helpers for reading Meta insights `actions` lists. No app imports, so any module can use it."""

LEAD_TYPES = {"lead", "onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead"}


def count_leads(actions) -> int:
    """Leads from a Meta insights `actions` list.

    Meta reports `lead` as the aggregate of the pixel and on-Facebook variants, so summing every
    lead type double-counts: RHO on 2026-11-04 returned lead=167 AND fb_pixel_lead=167 on 51 of 71
    ad sets (real total 167, summed 334). Prefer `lead`; fall back to the largest single variant.

    A `lead` of 0 next to a non-zero variant also falls back, so the result is 0 only when every lead
    type is 0 — the same as the old sum. Auto-pause's zero-lead kill keys on `leads == 0`.
    """
    by_type: dict[str, int] = {}
    for a in actions or []:
        t = a.get("action_type")
        if t in LEAD_TYPES:
            by_type[t] = by_type.get(t, 0) + int(float(a.get("value") or 0))
    if not by_type:
        return 0
    lead = by_type.get("lead")
    return lead if lead else max(by_type.values())
