"""Account-economics niche labels for Max CPL."""
import re

DROP = {"RHO V1", "RHO", "ABO", "CBO", "LEADS", "CAPI", "BREAKOUT"}
MERGE = [
    (r"DEALERSHIP|DEALER", "Auto Dealers"), (r"CAR RENTAL", "Car Rental"), (r"\bLIMO", "Limo"),
    (r"TRUCKING|BOX TRUCK|FREIGHT", "Trucking"), (r"COURIER", "Couriers / Cargo Vans"),
    (r"PAINTING", "Painting Contractors"), (r"TOW \+ HANDYMAN", "Tow + Handyman"), (r"TOWING", "Towing"),
    (r"NEMT", "NEMT"), (r"LLC RATE", "LLC Rate Check"), (r"ELECTRICIAN", "Electricians"),
    (r"HORSE", "Horse & Stable"), (r"BROAD|PRICE ANCHOR|CALLOUT|CA PROVEN|VEHICLE OWNERS", "Broad / Multi-niche"),
    (r"RELIGIOUS", "Religious Orgs"), (r"TAXI", "Taxi"), (r"AUTOBODY", "Autobody"), (r"FUNERAL", "Funeral Homes"),
    (r"HVAC|PLUMBING", "HVAC & Plumbing"), (r"PET CARE", "Pet Care"), (r"LOCKSMITH", "Locksmiths"),
    (r"FLORIST", "Florists"), (r"JANITORIAL", "Janitorial"), (r"RESTAURANT", "Restaurants"),
    (r"SALON|BARBER|DRY CLEAN", "Salon / Barber / Dry Clean"), (r"WELDER", "Welders"), (r"JUNK|SCRAP", "Junk & Scrap Haulers"),
    (r"LANDSCAP", "Landscaping"), (r"CABLE", "Cable Installers"), (r"LAUNDROMAT", "Laundromat"), (r"ROOFING", "Roofing"),
    (r"BUILDING CONTR|CONTRACTOR", "Contractors"),
]


def resolve(campaign_name: str | None, adset_name: str | None) -> str:
    for source in (campaign_name or "", adset_name or ""):
        upper = source.upper()
        for pattern, niche in MERGE:
            if re.search(pattern, upper):
                return niche
    for segment in (campaign_name or "").split("|"):
        segment = segment.strip()
        if not segment or segment.upper() in DROP or re.fullmatch(r"[\d.]+", segment):
            continue
        segment = re.sub(r"^(EXPLORE|VEHICLE|BREADTH)\s+W\d+\w*\s+|^NEW NICHES\s*", "", segment, flags=re.I).strip()
        if segment:
            return segment.title()
    return "Unmapped"
