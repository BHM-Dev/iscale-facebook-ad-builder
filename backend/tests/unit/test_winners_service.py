from app.services.naming_presets import concept_from_filename
from app.services.winners_service import group_winner_rows, rank_winner_rows


def _inputs():
    ads = [
        {
            "ad_id": "ad-fun",
            "ad_name": "FUN FleetMargin",
            "creative_name": "WW8-FUN-01-FleetMargin-IMG-1x1.png",
            "headlines": ["Protect every vehicle"],
            "status": "ACTIVE",
            "adset_id": "set-fun",
            "adset_name": "WW8-FUN | FLEET AND CREW",
            "campaign_name": "RHO | ABO | VEHICLE W2 FUNERAL HOMES | CAPI",
        },
        {
            "ad_id": "ad-tow",
            "ad_name": "TOW FleetMargin",
            "creative_name": "WW8-TOW-02-FleetMargin-IMG-1x1.png",
            "headlines": ["Protect every vehicle"],
            "status": "PAUSED",
            "adset_id": "set-tow",
            "adset_name": "WW8-TOW | FLEET AND CREW",
            "campaign_name": "RHO | ABO | VEHICLE W2 TOWING | CAPI",
        },
        {
            "ad_id": "ad-lock",
            "ad_name": "LOCK FastQuote",
            "creative_name": "WW8-LOCK-03-FastQuote-IMG-1x1.png",
            "headlines": ["Get a fast quote"],
            "status": "ACTIVE",
            "adset_id": "set-lock",
            "adset_name": "WW8-LOCK | QUICK QUOTE",
            "campaign_name": "RHO | ABO | VEHICLE W2 LOCKSMITHS | CAPI",
        },
    ]
    insights = {
        "set-fun": [{"ad_id": "ad-fun", "spend": 100, "leads": 8}],
        "set-tow": [{"ad_id": "ad-tow", "spend": 40, "leads": 4}],
        "set-lock": [{"ad_id": "ad-lock", "spend": 10, "leads": 2}],
    }
    max_cpl = {
        "set-fun": {"niche": "Funeral Homes", "rpl": 50, "max_cpl": 38.46},
        "set-tow": {"niche": "Towing", "rpl": 40, "max_cpl": 30.77},
        # set-lock intentionally has no RPL
    }
    drive = {
        ad["creative_name"]: {
            "drive_file_id": f"drive-{ad['ad_id']}",
            "file_name": ad["creative_name"],
            "image_url": f"https://example.com/{ad['ad_id']}.png",
        }
        for ad in ads
    }
    redtrack = {"ad-fun": {"revenue": 310}, "ad-tow": {"revenue": 120}}
    return ads, insights, max_cpl, redtrack, drive


def test_concept_parser_matches_frontend_contract():
    assert concept_from_filename("folder/WW8-FUN-01-Fleet_Margin-IMG-1x1.png") == "FleetMargin"
    assert concept_from_filename("Fleet Margin-v3.jpg") == "FleetMargin"


def test_concept_group_combines_niches_and_calculates_estimate():
    rows = group_winner_rows(*_inputs(), group_by="concept")
    fleet = next(row for row in rows if row["label"] == "FleetMargin")

    assert fleet["leads"] == 12
    assert fleet["spend"] == 140
    assert fleet["est_revenue"] == 560
    assert fleet["est_profit"] == 420
    assert fleet["est_partial"] is False
    assert fleet["niche_codes"] == ["FUN", "TOW"]
    assert fleet["niches"] == ["Funeral Homes", "Towing"]
    assert fleet["adset_count"] == 2
    assert fleet["active_ad_count"] == 1
    assert fleet["rt_coverage"] == "full"
    assert fleet["top_spend_ad_id"] == "ad-fun"


def test_partial_estimate_and_floor_sort_after_ranked_rows():
    rows = group_winner_rows(*_inputs(), group_by="headline")
    ranked = rank_winner_rows(rows, min_leads=10, max_cpl_available=True)

    assert ranked[0]["label"] == "Protect every vehicle"
    assert ranked[0]["enough_data"] is True
    assert ranked[1]["label"] == "Get a fast quote"
    assert ranked[1]["enough_data"] is False
    assert ranked[1]["est_profit"] is None
    assert ranked[1]["est_partial"] is True
    assert ranked[1]["rt_coverage"] == "none"


def test_no_max_cpl_falls_back_to_lead_ordering():
    rows = [
        {"label": "High profit", "leads": 11, "spend": 50, "est_profit": 500},
        {"label": "More leads", "leads": 20, "spend": 200, "est_profit": -20},
        {"label": "Under floor", "leads": 9, "spend": 10, "est_profit": 1000},
    ]
    ranked = rank_winner_rows(rows, min_leads=10, max_cpl_available=False)
    assert [row["label"] for row in ranked] == ["More leads", "High profit", "Under floor"]


def test_ads_without_local_record_still_match_drive_and_niche_code():
    """Ads duplicated in Ads Manager have no FacebookAd row; the Meta ad name is the Drive file name."""
    from app.services.winners_service import group_winner_rows
    import inspect
    params = list(inspect.signature(group_winner_rows).parameters)
    insights = {"as1": [{"ad_id": "9", "ad_name": "VW-PLOW-02-PlowLabel-IMG-1x1.jpg", "spend": 296, "leads": 35}]}
    kwargs = {
        "insights_by_adset": insights, "ads": [], "max_cpl_by_adset": {},
        "drive_by_filename": {"VW-PLOW-02-PlowLabel-IMG-1x1.jpg": {"drive_file_id": "d1", "file_name": "VW-PLOW-02-PlowLabel-IMG-1x1.jpg"}},
        "group_by": "creative",
        "known_niche_codes": {"PLOW"},
    }
    kwargs["redtrack_by_ad"] = {}
    rows = group_winner_rows(**{k: v for k, v in kwargs.items() if k in params})
    row = rows[0]
    assert row["drive_file_id"] == "d1"
    assert row["niche_codes"] == ["PLOW"]


def test_unknown_name_codes_are_not_invented_as_niches():
    from app.services.winners_service import group_winner_rows
    insights = {"as1": [{"ad_id": "7", "ad_name": "CR-ITER-01-DarkRed-IMG-1x1.jpg", "spend": 100, "leads": 4}]}
    rows = group_winner_rows([], insights, {}, {}, {}, "creative", {"PLOW", "CR"})
    assert rows[0]["niche_codes"] == []


def test_ads_without_rpl_are_not_counted_as_pure_cost():
    from app.services.winners_service import group_winner_rows
    insights = {
        "as1": [{"ad_id": "1", "ad_name": "WW8-FUN-01-A-IMG-1x1.jpg", "spend": 100, "leads": 4}],
        "as2": [{"ad_id": "2", "ad_name": "WW8-FUN-01-A-IMG-1x1.jpg", "spend": 300, "leads": 1}],
    }
    rows = group_winner_rows([], insights, {"as1": {"rpl": 50, "max_cpl": 38}}, {}, {}, "creative", set())
    row = rows[0]
    assert row["est_revenue"] == 200 and row["est_profit"] == 100 and row["est_partial"] is True
