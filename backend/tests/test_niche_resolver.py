import pytest

from app.services.niche_resolver import resolve


@pytest.mark.parametrize("campaign,adset,expected", [
    ("RHO v1 | ABO | LEADS | LIMO | CAPI | 10.06.2026", "", "Limo"),
    ("EXPLORE W1 Car Rental Rebuild", "", "Car Rental"),
    ("BREADTH W2T Pet Care", "", "Pet Care"),
    ("Tow + Handyman", "", "Tow + Handyman"),
    ("Towing Win Back", "", "Towing"),
    ("RHO | ABO | LEADS | CAPI | 10.06.2026", "", "Unmapped"),
    ("RHO | ABO | Florists", "Ad Set 1", "Florists"),
])
def test_resolve(campaign, adset, expected):
    assert resolve(campaign, adset) == expected
