from app.services.drive_sync_service import DriveSyncService, GOOGLE_DOC_MIME


def test_category_copy_doc_matches_category_and_placement():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """1. LANDSCAPING AND FIELD SERVICE
Headline: Landscapers: See What You're Overpaying
Primary text:
Landscaping copy.

4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
"""

    sections = service._parse_category_copy_doc(document)

    assert sections[4]["headline"] == "Cafe Owners: Compare Coverage Free"
    assert service._category_matches("restaurant-1x1.png", sections[4]["category"], 4)
    assert not service._category_matches("restaurant-1x1.png", sections[1]["category"], 1)


def test_category_copy_doc_tolerates_google_export_mark_before_first_heading():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """\ufeff1. LANDSCAPING AND FIELD SERVICE
Headline: Landscapers: See What You're Overpaying
Primary text:
Landscaping copy.
"""
    media = [
        {"id": "feed", "name": "BT-LANDSCAPING-FIELD-SERVICE-01-1x1.png"},
        {"id": "stories", "name": "BT-LANDSCAPING-FIELD-SERVICE-01-9x16.png"},
    ]

    result = service._category_folder_copy_metadata("broad-testing", media, document)

    assert set(result["assets_by_drive_id"]) == {"feed", "stories"}
    assert result["assets_by_drive_id"]["feed"]["copy"]["headline"] == "Landscapers: See What You're Overpaying"
    assert service._copy_document_is_complete(document, "category")


def test_category_copy_doc_extracts_optional_description_without_leaking_into_primary():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Coverage for Restaurant Owners
Primary text:
Restaurant primary text.
Description: Compare options for your food-service business.
Alt headlines:
- A second headline
"""

    section = service._parse_category_copy_doc(document)[4]

    assert section["primary_text"] == "Restaurant primary text."
    assert section["description"] == "Compare options for your food-service business."


def test_category_copy_doc_keeps_description_missing_as_none():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """1. LANDSCAPING AND FIELD SERVICE
Headline: Coverage for Landscapers
Primary text:
Landscaping primary text.
"""

    assert service._parse_category_copy_doc(document)[1]["description"] is None


def test_native_google_doc_is_syncable_text():
    service = DriveSyncService.__new__(DriveSyncService)

    assert service._is_text_file(GOOGLE_DOC_MIME, "Ad Copy")


def test_category_metadata_tags_both_placements_with_same_copy_id():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
Description: Compare options for your restaurant.
"""
    media = [
        {"id": "feed-id", "name": "restaurant.png", "_parent_folder_name": "1x1"},
        {"id": "stories-id", "name": "restaurant-9x16.png", "_parent_folder_name": "9x16"},
    ]

    result = service._category_folder_copy_metadata("package-id", media, document)

    assert result["assets"]["restaurant.png"]["copy_id"] == "CATEGORY-04"
    assert result["assets"]["restaurant-9x16.png"]["aspect"] == "9x16"
    assert result["assets"]["restaurant.png"]["category"] == "RESTAURANT AND FOOD SERVICE"
    assert result["assets"]["restaurant.png"]["copy"]["primary_text"] == "Restaurant copy."
    assert result["assets"]["restaurant.png"]["copy"]["description"] == "Compare options for your restaurant."


def test_category_metadata_keeps_duplicate_basenames_refreshable():
    service = DriveSyncService.__new__(DriveSyncService)
    media = [
        {"id": "restaurant-a", "name": "restaurant.png", "_parent_folder_name": "1x1"},
        {"id": "restaurant-b", "name": "restaurant.png", "_parent_folder_name": "1x1"},
    ]
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
"""

    result = service._category_folder_copy_metadata("package-id", media, document)

    tags = result["assets"]["restaurant.png"]
    assert tags["drive_file_id"] == "restaurant-b"
    assert result["assets_by_drive_id"]["restaurant-a"]["copy_id"] == "CATEGORY-04-EXTRA-1"
    assert result["assets_by_drive_id"]["restaurant-b"]["copy_id"] == "CATEGORY-04-EXTRA-2"


def test_category_metadata_leaves_ambiguous_duplicate_names_unpaired():
    service = DriveSyncService.__new__(DriveSyncService)
    media = [
        {"id": "feed-a", "name": "restaurant.png", "_parent_folder_name": "1x1"},
        {"id": "feed-b", "name": "restaurant.png", "_parent_folder_name": "1x1"},
        {"id": "stories-a", "name": "restaurant.png", "_parent_folder_name": "9x16"},
        {"id": "stories-b", "name": "restaurant.png", "_parent_folder_name": "9x16"},
    ]
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
"""

    result = service._category_folder_copy_metadata("package-id", media, document)

    # The Drive list order is not an identity. A generic duplicate filename
    # must not silently pair feed-a with stories-b and send the wrong vertical
    # visual to Meta; each remains an explicit single until named uniquely.
    copy_ids = {
        result["assets_by_drive_id"]["feed-a"]["copy_id"],
        result["assets_by_drive_id"]["stories-a"]["copy_id"],
        result["assets_by_drive_id"]["feed-b"]["copy_id"],
        result["assets_by_drive_id"]["stories-b"]["copy_id"],
    }
    assert copy_ids == {
        "CATEGORY-04-EXTRA-1",
        "CATEGORY-04-EXTRA-2",
        "CATEGORY-04-EXTRA-3",
        "CATEGORY-04-EXTRA-4",
    }


def test_category_metadata_pairs_unique_matching_filename_identities():
    service = DriveSyncService.__new__(DriveSyncService)
    media = [
        {"id": "feed-a", "name": "restaurant-lunch-rush-1x1.png", "_parent_folder_name": "1x1"},
        {"id": "stories-a", "name": "restaurant-lunch-rush-9x16.png", "_parent_folder_name": "9x16"},
        {"id": "feed-b", "name": "restaurant-kitchen-slip-1x1.png", "_parent_folder_name": "1x1"},
        {"id": "stories-b", "name": "restaurant-kitchen-slip-9x16.png", "_parent_folder_name": "9x16"},
    ]
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
"""

    result = service._category_folder_copy_metadata("package-id", media, document)

    assert result["assets_by_drive_id"]["feed-b"]["copy_id"] == result["assets_by_drive_id"]["stories-b"]["copy_id"]
    assert result["assets_by_drive_id"]["feed-a"]["copy_id"] == result["assets_by_drive_id"]["stories-a"]["copy_id"]
    assert result["assets_by_drive_id"]["feed-a"]["copy_id"] != result["assets_by_drive_id"]["feed-b"]["copy_id"]


def test_category_metadata_does_not_pair_different_export_revisions():
    service = DriveSyncService.__new__(DriveSyncService)
    media = [
        {"id": "feed", "name": "restaurant-lunch-rush-1x1-v1.png", "_parent_folder_name": "1x1"},
        {"id": "stories", "name": "restaurant-lunch-rush-9x16-v2.png", "_parent_folder_name": "9x16"},
    ]
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
"""

    result = service._category_folder_copy_metadata("package-id", media, document)

    assert result["assets_by_drive_id"]["feed"]["copy_id"] == "CATEGORY-04-EXTRA-1"
    assert result["assets_by_drive_id"]["stories"]["copy_id"] == "CATEGORY-04-EXTRA-2"


def test_category_metadata_reads_placement_from_nested_ancestor_folder():
    service = DriveSyncService.__new__(DriveSyncService)
    media = [{
        "id": "restaurant-feed",
        "name": "restaurant.png",
        "_parent_folder_name": "Restaurant",
        "_parent_folder_path": ["1x1 Images", "Restaurant"],
    }]
    document = """4. RESTAURANT AND FOOD SERVICE
Headline: Cafe Owners: Compare Coverage Free
Primary text:
Restaurant copy.
"""

    result = service._category_folder_copy_metadata("package-id", media, document)

    assert result["assets_by_drive_id"]["restaurant-feed"]["aspect"] == "1x1"


def test_category_aliases_cover_live_batch_labels():
    service = DriveSyncService.__new__(DriveSyncService)

    assert service._category_matches("landscaper.png", "LANDSCAPING AND FIELD SERVICE", 1)
    assert service._category_matches("LND-renewal-1x1.png", "LANDSCAPING AND FIELD SERVICE", 1)
    assert service._category_matches("land-loss-9x16.png", "LANDSCAPING AND FIELD SERVICE", 1)
    assert service._category_matches("FLR-delivery-1x1.png", "FLORIST", 1)
    assert service._category_matches("flor-cooler-9x16.png", "FLORIST", 1)
    assert service._category_matches("FLOR-delivery-9x16.png", "FLR", 1)
    assert service._category_matches("florist-delivery-9x16.png", "FLOWER SHOP", 1)
    assert service._category_matches("landscaper-1x1.png", "LANDSCAPE SERVICES", 1)
    assert service._category_matches("landscaper-1x1.png", "LOCAL BUSINESS COVERAGE", 1)
    assert service._category_matches("restaurantowners-1x1.png", "LOCAL BUSINESS COVERAGE", 4)
    assert not service._category_matches("island-1x1.png", "LANDSCAPING AND FIELD SERVICE", 1)
    assert not service._category_matches("land-1x1.png", "FLORIST", 1)
    assert service._category_matches("Protect What You’ve Built.png", "GENERAL, Protect What You’ve Built", 7)


def test_category_pair_key_normalizes_live_vertical_aliases():
    service = DriveSyncService.__new__(DriveSyncService)

    assert (
        service._category_pair_key("FLR-delivery-1x1.png", "FLORIST")
        == service._category_pair_key("FLOR-delivery-9x16.png", "FLORIST")
    )
    assert (
        service._category_pair_key("LAND-renewal-1x1.png", "LND")
        == service._category_pair_key("LND-renewal-9x16.png", "LND")
    )


def test_category_metadata_pairs_cross_alias_placements():
    service = DriveSyncService.__new__(DriveSyncService)
    florist_document = """1. FLORIST
Headline: Compare Florist Coverage
Primary text:
Florist copy.
"""
    florist_media = [
        {"id": "florist-feed", "name": "FLR-delivery-1x1.png", "_parent_folder_name": "1x1"},
        {"id": "florist-stories", "name": "FLOR-delivery-9x16.png", "_parent_folder_name": "9x16"},
    ]
    florist_result = service._category_folder_copy_metadata("florist-package", florist_media, florist_document)

    assert florist_result["assets_by_drive_id"]["florist-feed"]["copy_id"] == "CATEGORY-01"
    assert florist_result["assets_by_drive_id"]["florist-feed"]["copy_id"] == florist_result["assets_by_drive_id"]["florist-stories"]["copy_id"]

    landscaping_document = """1. LND
Headline: Compare Landscaping Coverage
Primary text:
Landscaping copy.
"""
    landscaping_media = [
        {"id": "land-feed", "name": "LAND-renewal-1x1.png", "_parent_folder_name": "1x1"},
        {"id": "land-stories", "name": "LND-renewal-9x16.png", "_parent_folder_name": "9x16"},
    ]
    landscaping_result = service._category_folder_copy_metadata("land-package", landscaping_media, landscaping_document)

    assert landscaping_result["assets_by_drive_id"]["land-feed"]["copy_id"] == "CATEGORY-01"
    assert landscaping_result["assets_by_drive_id"]["land-feed"]["copy_id"] == landscaping_result["assets_by_drive_id"]["land-stories"]["copy_id"]


def test_single_generic_category_section_rejects_cross_family_short_codes():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """1. LOCAL BUSINESS COVERAGE
Headline: Compare Business Coverage
Primary text:
Generic package copy.
"""
    media = [
        {"id": "feed", "name": "FLR-delivery-1x1.png", "_parent_folder_name": "1x1"},
        {"id": "stories", "name": "FLOR-delivery-9x16.png", "_parent_folder_name": "9x16"},
    ]

    result = service._category_folder_copy_metadata("generic-package", media, document)

    # FLR/FLOR identifies the florist family, not the generic local-business
    # section. The old fully-permissive fallback silently attached this copy.
    assert result["assets"] == {}
    assert result["assets_by_drive_id"] == {}
    assert result["_copy_integrity_warnings"]["feed"]["copy_integrity_issue"] is True
    assert result["_copy_integrity_warnings"]["stories"]["copy_integrity_issue"] is True


def test_ad_numbered_copy_doc_parses_established_meta_labels():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """GBC — Electrical Contractors
Lander: https://www.getbusinesscoverage.com/commercial-auto-v2
AD 1 — Identity
META HEADLINE
Commercial Van Insurance for Electricians
PRIMARY TEXT
Electrical primary copy.
CTA: Get My Rate Now
IMAGE: Electrician and van.
────────────────────────────────
AD 2 — Rate hike
META HEADLINE
Compare Electrical Commercial Auto
PRIMARY TEXT
Second primary copy.
CTA: Get My Rate Now
"""

    sections = service._parse_ad_copy_doc(document)

    assert service._looks_like_ad_copy_doc(document)
    assert sections[1]["headline"] == "Commercial Van Insurance for Electricians"
    assert sections[1]["primary_text"] == "Electrical primary copy."
    assert sections[1]["landing_page"] == "https://www.getbusinesscoverage.com/commercial-auto-v2"
    assert sections[1]["cta"] == "GET_QUOTE"


def test_ad_numbered_copy_doc_maps_legacy_cvi_paint_filenames():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """GBC — Painting Contractors
Lander: https://www.getbusinesscoverage.com/commercial-auto-v2
AD 1 — Identity
META HEADLINE
Commercial Van Insurance for Painters
PRIMARY TEXT
Painting primary copy.
CTA: Get My Rate Now
"""
    media = [
        {"id": "feed", "name": "CVI-PAINT-01-IDENTITY-1x1.png"},
        {"id": "stories", "name": "CVI-PAINT-01-IDENTITY-9x16.png"},
    ]

    result = service._ad_numbered_folder_copy_metadata("painting", media, document)

    assert result["assets"]["cvi-paint-01-identity-1x1.png"]["copy"]["headline"] == "Commercial Van Insurance for Painters"
    assert result["assets"]["cvi-paint-01-identity-9x16.png"]["copy"]["primary_text"] == "Painting primary copy."
    assert result["assets_by_drive_id"]["stories"]["copy_id"] == "AD-01"


def test_ad_numbered_copy_doc_maps_compact_general_auto_legacy_set_names():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 01 — Original Set A1
Headline: Is Your Work Van Actually Covered?
Your work van has been running jobs for years.

DESCRIPTION
One accident can change everything.

AD 06 — Original Set B1
Headline: The Van Is How You Eat.
The van is how you pay the mortgage.
"""
    media = [
        {"id": "a1-feed", "name": "A1-Van-Denial-Scenario.png", "_parent_folder_name": "1x1 Images"},
        {"id": "a1-story", "name": "A1-Van-Denial-Scenario-9x16.png", "_parent_folder_name": "9x16 Images"},
        {"id": "b1-feed", "name": "B1-Van-Identity.png", "_parent_folder_name": "1x1 Images"},
        {"id": "b1-story", "name": "B1-Van-Identity-9x16.png", "_parent_folder_name": "9x16 Images"},
        {"id": "c1-feed", "name": "C1-GenAuto-Gap-Education.png", "_parent_folder_name": "1x1 Images"},
        {"id": "d1-feed", "name": "D1-GenAuto-Comparison.png", "_parent_folder_name": "1x1 Images"},
    ]

    result = service._ad_numbered_folder_copy_metadata("general-auto", media, document)

    assert result["assets_by_drive_id"]["a1-feed"]["copy_id"] == "AD-01"
    assert result["assets_by_drive_id"]["b1-story"]["copy_id"] == "AD-06"
    assert result["assets_by_drive_id"]["a1-story"]["copy"]["primary_text"] == "Your work van has been running jobs for years."
    assert service._ad_number_from_file_name("C1-GenAuto-Gap-Education.png") == 10
    assert service._ad_number_from_file_name("D1-GenAuto-Comparison.png") == 14


def test_ad_numbered_copy_doc_does_not_treat_other_cvi_families_as_painting_ads():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1
META HEADLINE
Painting headline
PRIMARY TEXT
Painting primary copy.
"""
    media = [
        {"id": "paint", "name": "CVI-PAINT-01.png"},
        {"id": "other", "name": "CVI-ELECTRICAL-01.png"},
    ]

    result = service._ad_numbered_folder_copy_metadata("painting", media, document)

    assert "cvi-paint-01.png" in result["assets"]
    assert "cvi-electrical-01.png" not in result["assets"]


def test_ad_numbered_copy_doc_detects_colon_label_variants():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1 — Identity
META HEADLINE:
Commercial Van Insurance
PRIMARY TEXT:
Primary copy.
"""

    assert service._looks_like_ad_copy_doc(document)
    assert service._parse_ad_copy_doc(document)[1]["primary_text"] == "Primary copy."


def test_ad_numbered_copy_doc_tolerates_google_export_formatting_marks():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """\ufeffGBC — Painting Contractors
AD\u00a01 — Identity
META HEADLINE:
Commercial Van Insurance for Painters
PRIMARY TEXT:
\u200bPainting primary copy from Joel.
CTA: Get My Rate Now
"""

    sections = service._parse_ad_copy_doc(document)

    assert service._looks_like_ad_copy_doc(document)
    assert sections[1]["headline"] == "Commercial Van Insurance for Painters"
    assert sections[1]["primary_text"] == "Painting primary copy from Joel."


def test_ad_numbered_copy_doc_parses_compact_v2_format():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """NICHE 04 — LANDSCAPING CONTRACTORS | FRESH SET v2
Lander: https://www.getbusinesscoverage.com/commercial-auto-v2
AD 1 — Identity
Headline: Commercial Van Insurance for Landscapers
Description: Coverage for lawn-care businesses.
====================================================
Landscaping primary copy.
====================================================
AD 2 — Quote shock
Headline: Compare Landscaping Rates
Description: See a better rate.
====================================================
Second landscaping primary copy.
====================================================
"""

    sections = service._parse_ad_copy_doc(document)

    assert service._looks_like_ad_copy_doc(document)
    assert sections[1]["headline"] == "Commercial Van Insurance for Landscapers"
    assert sections[1]["primary_text"] == "Landscaping primary copy."
    assert sections[1]["description"] == "Coverage for lawn-care businesses."


def test_ad_numbered_copy_doc_keeps_lander_on_compact_title_line():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """NICHE 04 — PAINTING CONTRACTORS | Lander: getbusinesscoverage.com/commercial-auto-v2
AD 1 — Identity
Headline: Commercial Van Insurance for Painters
====================================================
Primary copy.
====================================================
"""

    sections = service._parse_ad_copy_doc(document)

    assert sections[1]["landing_page"] == "getbusinesscoverage.com/commercial-auto-v2"


def test_cta_normalization_maps_real_drive_phrases_to_meta_enums():
    service = DriveSyncService.__new__(DriveSyncService)

    assert service._normalize_cta("Check My Coverage Now") == "GET_QUOTE"
    assert service._normalize_cta("Get Covered Today") == "GET_QUOTE"
    assert service._normalize_cta("Compare My Rates") == "GET_QUOTE"
    assert service._normalize_cta("[None — organic post, no CTA button]") is None


def test_ad_numbered_copy_metadata_pairs_explicit_ad_numbers_without_vertical_aliases():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """NICHE 03 — ELECTRICAL CONTRACTORS | FRESH SET v2
AD 1 — Identity
Headline: Commercial Van Insurance for Electricians
Description: Service vans covered.
====================================================
Electrical primary copy.
====================================================
"""
    media = [
        {"id": "feed", "name": "03-ELEC-AD1-Identity-1x1.jpg", "_parent_folder_name": "1x1 Images"},
        {"id": "stories", "name": "03-ELEC-AD1-Identity-9x16.jpg", "_parent_folder_name": "9x16 Images"},
        {"id": "unrelated", "name": "03-ELEC-COVER-1x1.jpg", "_parent_folder_name": "1x1 Images"},
    ]

    result = service._ad_numbered_folder_copy_metadata("electrical-package", media, document)

    assert result["assets_by_drive_id"]["feed"]["copy_id"] == "AD-01"
    assert result["assets_by_drive_id"]["feed"]["copy_id"] == result["assets_by_drive_id"]["stories"]["copy_id"]
    assert result["assets_by_drive_id"]["feed"]["copy"]["primary_text"] == "Electrical primary copy."
    assert "unrelated" not in result["assets_by_drive_id"]


def test_ad_numbered_copy_doc_rejects_duplicate_ad_number_even_if_first_is_incomplete():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1 — Draft
META HEADLINE
Incomplete headline only
AD 1 — Final
META HEADLINE
Final headline
PRIMARY TEXT
Final primary copy.
"""

    assert service._parse_ad_copy_doc(document) == {}


def test_ad_numbered_copy_detector_ignores_incomplete_draft_documents():
    service = DriveSyncService.__new__(DriveSyncService)
    draft = """Painting Contractors — ICP + 5 Ads
AD 1 — Identity
Notes for the draft only.
AD 2 — Claim Denied
Potential headline ideas, no final copy yet.
"""

    assert not service._looks_like_ad_copy_doc(draft)


def test_ad_numbered_copy_doc_resolves_a_package_from_sibling_media():
    service = DriveSyncService.__new__(DriveSyncService)
    service._strategy_package_folder_cache = {}
    service._client = lambda: None
    # "package" is a real package (root/brand/package), not a brand root, so the
    # container guard must let the strategy walk keep it.
    service.root_folder_id = "root"
    service._folder_chain_to_root = lambda folder_id: [
        {"id": "package", "name": "package"},
        {"id": "brand", "name": "brand"},
        {"id": "root", "name": "root"},
    ]
    document = """AD 1 — Identity
META HEADLINE
Headline
PRIMARY TEXT
Primary copy.
"""
    service._list_folder_subtree = lambda folder_id: [
        {"id": "copy", "name": "Ad Copy.txt", "mimeType": "text/plain"},
        {"id": "image", "name": "03-ELEC-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"},
    ]
    service._download_text_file = lambda file_id: document

    assert service._find_strategy_package_folder({"parents": ["package"]}) == "package"


def test_ad_numbered_copy_doc_does_not_borrow_sibling_package_copy():
    service = DriveSyncService.__new__(DriveSyncService)
    service._strategy_package_folder_cache = {}
    document = """AD 1 — Identity
META HEADLINE
Headline
PRIMARY TEXT
Primary copy.
"""

    class FakeFiles:
        def get(self, **kwargs):
            class Request:
                def execute(self):
                    return {"id": "placement", "parents": ["package"]}
            return Request()

    class FakeDrive:
        def files(self):
            return FakeFiles()

    service._client = lambda: FakeDrive()
    service._list_folder_subtree = lambda folder_id: [
        {"id": "media", "name": "AD1-1x1.jpg", "mimeType": "image/jpeg"}
    ]
    service._download_text_file = lambda file_id: document

    assert service._find_strategy_package_folder({"parents": ["placement"]}) is None


def test_incremental_sync_marks_failed_ad_copy_package_unverified():
    service = DriveSyncService.__new__(DriveSyncService)
    service._package_folder_cache = {}
    service._strategy_package_folder_cache = {}
    service._folder_metadata_cache = {}
    service._copy_packages_refreshed_in_sync = set()
    service._metadata_folder_for_copy_document = lambda file_meta: "package"
    marked = []
    service._refresh_folder_copy_metadata = lambda file_meta, **kwargs: (_ for _ in ()).throw(RuntimeError("duplicate AD 1"))
    service._mark_package_copy_unverified = lambda file_meta, reason: marked.append((file_meta["id"], reason))
    result = {"updated": 0, "errors": 0, "skipped": 0}

    service._process_file({"id": "copy", "name": "Ad Copy.txt", "mimeType": "text/plain"}, result)

    assert result["errors"] == 1
    assert result["skipped"] == 1
    assert marked == [("copy", "duplicate AD 1")]


def test_ad_numbered_copy_metadata_keeps_duplicate_ad_placements_unpaired():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1 — Identity
META HEADLINE
One
PRIMARY TEXT
Primary.
"""
    media = [
        {"id": "feed-a", "name": "AD1-A-1x1.jpg", "_parent_folder_name": "1x1 Images"},
        {"id": "feed-b", "name": "AD1-B-1x1.jpg", "_parent_folder_name": "1x1 Images"},
        {"id": "stories", "name": "AD1-Story-9x16.jpg", "_parent_folder_name": "9x16 Images"},
    ]

    result = service._ad_numbered_folder_copy_metadata("package", media, document)

    assert result["assets_by_drive_id"]["feed-a"]["copy_id"] == "AD-01-EXTRA-1"
    assert result["assets_by_drive_id"]["feed-b"]["copy_id"] == "AD-01-EXTRA-2"
    assert result["assets_by_drive_id"]["stories"]["copy_id"] == "AD-01-EXTRA-3"
    assert result["assets_by_drive_id"]["feed-a"]["copy_pairing_status"] == "ambiguous"


def test_ad_numbered_copy_metadata_pairs_each_named_visual_under_one_ad_section():
    """Replacement exports can retain an older winner beside the current pair.

    The shared AD number selects the copy, while the rest of the filename
    selects the actual Feed/Stories visual pair.  Both complete pairs must stay
    selectable instead of being marked ambiguous merely because they use the
    same AD copy block.
    """
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1 — Identity
META HEADLINE
Commercial Van Insurance for Painters
PRIMARY TEXT
Painting primary copy.
"""
    media = [
        {"id": "identity-feed", "name": "01-PAINT-AD1-Identity-1x1.jpg", "_parent_folder_name": "1x1 Images"},
        {"id": "identity-story", "name": "01-PAINT-AD1-Identity-9x16.jpg", "_parent_folder_name": "9x16 Images"},
        {"id": "winner-feed", "name": "01-PAINT-AD1-AdjusterQuestion-1x1.jpg", "_parent_folder_name": "1x1 Images"},
        {"id": "winner-story", "name": "01-PAINT-AD1-AdjusterQuestion-9x16.jpg", "_parent_folder_name": "9x16 Images"},
    ]

    result = service._ad_numbered_folder_copy_metadata("painting", media, document)

    identity = result["assets_by_drive_id"]
    assert identity["identity-feed"]["copy_id"] == identity["identity-story"]["copy_id"]
    assert identity["winner-feed"]["copy_id"] == identity["winner-story"]["copy_id"]
    assert identity["identity-feed"]["copy_id"] != identity["winner-feed"]["copy_id"]
    assert all(
        identity[asset_id]["copy_pairing_status"] == "paired"
        for asset_id in ("identity-feed", "identity-story", "winner-feed", "winner-story")
    )
    assert identity["identity-feed"]["copy"]["headline"] == "Commercial Van Insurance for Painters"


def test_ad_numbered_copy_metadata_blocks_unknown_placement_from_auto_duplication():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1 — Identity
META HEADLINE
One
PRIMARY TEXT
Primary.
"""
    media = [{"id": "unknown", "name": "AD1-unknown.jpg", "_parent_folder_name": "Final Creatives"}]

    result = service._ad_numbered_folder_copy_metadata("package", media, document)

    assert result["assets_by_drive_id"]["unknown"]["aspect"] == "unknown"
    assert result["assets_by_drive_id"]["unknown"]["copy_pairing_status"] == "ambiguous"


def test_ad_numbered_copy_metadata_keeps_a_valid_pair_when_an_unknown_extra_exists():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """AD 1 — Identity
META HEADLINE
One
PRIMARY TEXT
Primary.
"""
    media = [
        {"id": "feed", "name": "AD1-identity-1x1.jpg", "_parent_folder_name": "1x1 Images"},
        {"id": "stories", "name": "AD1-identity-9x16.jpg", "_parent_folder_name": "9x16 Images"},
        {"id": "extra", "name": "AD1-identity-final.jpg", "_parent_folder_name": "Final exports"},
    ]

    result = service._ad_numbered_folder_copy_metadata("package", media, document)

    assert result["assets_by_drive_id"]["feed"]["copy_pairing_status"] == "paired"
    assert result["assets_by_drive_id"]["stories"]["copy_pairing_status"] == "paired"
    assert result["assets_by_drive_id"]["feed"]["copy_id"] == result["assets_by_drive_id"]["stories"]["copy_id"]
    assert result["assets_by_drive_id"]["extra"]["copy_pairing_status"] == "ambiguous"


def test_successful_copy_refresh_clears_stale_unverified_mark():
    """refresh_copy_metadata marks every copy asset unverified before its walk,
    and _write_merged_soft_tags merges rather than overwrites. A successful match
    must therefore write the verified status explicitly, or the blanket mark
    becomes a one-way ratchet no clean copy doc can ever clear."""
    service = DriveSyncService.__new__(DriveSyncService)
    writes = {}
    service._resolve_drive_path = lambda file_meta: type("R", (), {"brand_folder": "Brand", "folder_path": "p"})()
    service._match_brand_id = lambda brand_folder: "brand-id"
    # Content matching is tried first for a non-handoff doc; falling through to
    # _find_package_folder is the legacy path and must still work.
    service._find_strategy_package_folder = lambda file_meta: None
    service._find_package_folder = lambda file_meta: "package"
    service._folder_copy_metadata = lambda folder_id, force=False: {
        "assets_by_drive_id": {"media-1": {"file_name": "AD1-1x1.jpg", "drive_file_ids": ["media-1"], "copy_id": "AD-01"}},
        "_copy_source_drive_file_id": "copy-doc",
    }
    service._write_merged_soft_tags = lambda drive_file_id, tags: (writes.__setitem__(drive_file_id, tags), 1)[1]
    service._mark_unmatched_package_assets_unverified = lambda package_folder, matched: None

    updated = service._refresh_folder_copy_metadata(
        {"id": "copy-doc", "name": "Ad Copy.txt", "mimeType": "text/plain", "parents": ["package"]}
    )

    assert updated == 1
    assert writes["media-1"]["copy_refresh_status"] == "verified"
    assert writes["media-1"]["copy_refresh_error"] is None
    # copy_integrity_issue is only ever written True elsewhere, so a fresh match
    # must clear it too or a filename mismatch fixed in Drive stays blocked forever.
    assert writes["media-1"]["copy_integrity_issue"] is False
    assert writes["media-1"]["copy_integrity_reason"] is None


def test_copy_refresh_includes_filename_keyed_strategy_assets_alongside_id_keyed_assets():
    service = DriveSyncService.__new__(DriveSyncService)
    writes = {}
    service._resolve_drive_path = lambda file_meta: type("R", (), {"brand_folder": "Brand", "folder_path": "p"})()
    service._match_brand_id = lambda brand_folder: "brand-id"
    service._find_strategy_package_folder = lambda file_meta: "package"
    service._find_package_folder = lambda file_meta: "package"
    service._folder_copy_metadata = lambda folder_id, force=False: {
        "assets_by_drive_id": {
            "ad-media": {"file_name": "AD1-1x1.jpg", "drive_file_id": "ad-media", "copy_id": "AD-01"},
        },
        "assets": {
            "strategy-1x1.jpg": {"file_name": "strategy-1x1.jpg", "drive_file_id": "strategy-media", "copy_id": "STRATEGY-01"},
        },
        "_copy_source_drive_file_id": "copy-doc",
    }
    service._write_merged_soft_tags = lambda drive_file_id, tags: (writes.__setitem__(drive_file_id, tags), 1)[1]
    service._mark_unmatched_package_assets_unverified = lambda package_folder, matched: None

    updated = service._refresh_folder_copy_metadata(
        {"id": "copy-doc", "name": "Ad Copy.txt", "mimeType": "text/plain", "parents": ["package"]}
    )

    assert updated == 2
    assert set(writes) == {"ad-media", "strategy-media"}


def test_copy_refresh_uses_resolved_package_when_brand_name_is_not_registered():
    """A copy source can be valid even when its Drive brand folder was renamed."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._resolve_drive_path = lambda file_meta: type("R", (), {"brand_folder": "Renamed Brand", "folder_path": "package"})()
    service._match_brand_id = lambda brand_folder: None
    service._find_strategy_package_folder = lambda file_meta: "package"
    service._find_package_folder = lambda file_meta: None
    service._folder_copy_metadata = lambda folder_id, force=False: {
        "assets_by_drive_id": {
            "media-1": {
                "file_name": "CVI-PAINT-01-IDENTITY-1x1.png",
                "drive_file_ids": ["media-1"],
                "copy_id": "AD-01",
            }
        },
        "_copy_source_drive_file_id": "copy-doc",
    }
    writes = {}
    service._write_merged_soft_tags = lambda drive_file_id, tags: (writes.__setitem__(drive_file_id, tags), 1)[1]
    service._mark_unmatched_package_assets_unverified = lambda package_folder, matched: None

    updated = service._refresh_folder_copy_metadata(
        {"id": "copy-doc", "name": "01-Painting-Ad-Copy.txt", "mimeType": "text/plain", "parents": ["ad-copy-folder"]}
    )

    assert updated == 1
    assert writes["media-1"]["copy_refresh_status"] == "verified"


def test_strategy_copy_refresh_keeps_complete_ads_when_another_ad_is_incomplete():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """## AD-CL-01 — Complete
**Meta headline:** Complete headline
**Primary text:** Complete primary text

## AD-CL-02 — Still being edited
**Meta headline:**
**Primary text:**
"""
    media = [
        {"id": "complete", "name": "AD-CL-01-1x1.png"},
        {"id": "incomplete", "name": "AD-CL-02-1x1.png"},
    ]

    result = service._strategy_folder_copy_metadata(
        "package", media, {item["name"].lower(): item for item in media}, document
    )

    assert list(result["assets"]) == ["ad-cl-01-1x1.png"]
    assert result["assets"]["ad-cl-01-1x1.png"]["copy"]["headline"] == "Complete headline"


def test_strategy_doc_in_package_root_does_not_adopt_sibling_handoff_package():
    """_find_package_folder only recognizes a package by a handoff manifest, and its
    depth guard assumes the walk began at a media file one level below the package
    root. A strategy doc living directly in its package root starts at depth 0, so
    that walk climbs too far and returns an unrelated sibling package. Content
    matching resolves it correctly, so a non-handoff doc must prefer that."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._resolve_drive_path = lambda file_meta: type("R", (), {"brand_folder": "Brand", "folder_path": "p"})()
    service._match_brand_id = lambda brand_folder: "brand-id"
    service._find_package_folder = lambda file_meta: "unrelated-sibling-package"
    service._find_strategy_package_folder = lambda file_meta: "correct-package"
    seen = {}
    service._folder_copy_metadata = lambda folder_id, force=False: seen.setdefault("folder", folder_id) and {} or {
        "assets_by_drive_id": {"media-1": {"file_name": "AD-CL-01-1x1.png", "drive_file_ids": ["media-1"]}},
        "_copy_source_drive_file_id": "strategy-doc",
    }
    service._write_merged_soft_tags = lambda drive_file_id, tags: 1
    service._mark_unmatched_package_assets_unverified = lambda package_folder, matched: None

    service._refresh_folder_copy_metadata(
        {"id": "strategy-doc", "name": "Auto-Dealership-Strategy-and-Copy-v2.md",
         "mimeType": "text/markdown", "parents": ["correct-package"]}
    )

    assert seen["folder"] == "correct-package"


def test_handoff_manifest_still_resolves_via_manifest_package_lookup():
    """A handoff manifest names its own package, so it must keep using
    _find_package_folder rather than the content-matching fallback."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._resolve_drive_path = lambda file_meta: type("R", (), {"brand_folder": "Brand", "folder_path": "p"})()
    service._match_brand_id = lambda brand_folder: "brand-id"
    service._find_package_folder = lambda file_meta: "manifest-package"
    service._find_strategy_package_folder = lambda file_meta: (_ for _ in ()).throw(
        AssertionError("handoff manifest must not use the strategy resolver")
    )
    seen = {}
    service._folder_copy_metadata = lambda folder_id, force=False: seen.setdefault("folder", folder_id) and {} or {
        "assets_by_drive_id": {"media-1": {"file_name": "AD1-1x1.jpg", "drive_file_ids": ["media-1"]}},
    }
    service._write_merged_soft_tags = lambda drive_file_id, tags: 1
    service._mark_unmatched_package_assets_unverified = lambda package_folder, matched: None

    service._refresh_folder_copy_metadata(
        {"id": "manifest", "name": "Handoff-Manifest.md", "mimeType": "text/markdown", "parents": ["manifest-package"]}
    )

    assert seen["folder"] == "manifest-package"


# --------------------------------------------------------------------------
# Flat-package copy leak: a package whose media sits directly in the package
# root with no handoff manifest. The walk in _find_package_folder starts at
# depth 0 in that folder, its "has_media and depth >= 1" guard does not fire at
# depth 0, so it climbs into the brand root -- whose subtree DOES contain a
# manifest plus media belonging to a SIBLING package. The by-drive-id lookup
# then misses (different package) but the by-lowercased-filename lookup can hit,
# attaching the sibling's headline/primary_text/landing_page/CTA to a creative
# that launches to Meta with real spend, tagged source=handoff_manifest and
# copy_refresh_status=verified with no integrity flag.
# --------------------------------------------------------------------------

ROOT = "root-folder"
BRAND = "brand-folder"
FLAT_PKG = "flat-package"
SIBLING_PKG = "sibling-package"
PLACEMENT = "placement-1x1"
AD_COPY = "ad-copy-subfolder"

FOLDER_MIME = "application/vnd.google-apps.folder"


class _FakeExecute:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeFiles:
    def __init__(self, parents_by_id, names_by_id):
        self._parents = parents_by_id
        self._names = names_by_id

    def get(self, fileId=None, fields=None, supportsAllDrives=None):
        parents = self._parents.get(fileId)
        payload = {"id": fileId, "name": self._names.get(fileId, fileId)}
        if parents:
            payload["parents"] = [parents]
        return _FakeExecute(payload)


class _FakeDrive:
    def __init__(self, parents_by_id, names_by_id):
        self._files = _FakeFiles(parents_by_id, names_by_id)

    def files(self):
        return self._files


def _service(parents_by_id, subtrees, names_by_id=None):
    """Build a DriveSyncService with the Drive calls stubbed out.

    parents_by_id maps folder/file id -> its single parent id.
    subtrees maps folder id -> the recursive non-folder listing under it.
    """
    service = DriveSyncService.__new__(DriveSyncService)
    service.root_folder_id = ROOT
    service._package_folder_cache = {}
    service._strategy_package_folder_cache = {}
    service._folder_metadata_cache = {}
    service._path_cache = {}
    drive = _FakeDrive(parents_by_id, names_by_id or {})
    service._client = lambda: drive
    service._list_folder_subtree = lambda folder_id, max_files=2000: subtrees.get(folder_id, [])
    return service


def _png(file_id, name):
    return {"id": file_id, "name": name, "mimeType": "image/png"}


def _manifest(file_id="manifest-id", name="SIBLING_HANDOFF_MANIFEST.txt"):
    return {"id": file_id, "name": name, "mimeType": "text/plain"}


def test_flat_package_does_not_borrow_sibling_manifest_from_brand_root():
    """A flat package must not resolve to the brand root."""
    flat_media = _png("flat-media-id", "contractor.png")
    sibling_media = _png("sibling-media-id", "contractor.png")
    parents = {FLAT_PKG: BRAND, SIBLING_PKG: BRAND, BRAND: ROOT}
    subtrees = {
        FLAT_PKG: [flat_media],
        SIBLING_PKG: [sibling_media, _manifest()],
        BRAND: [flat_media, sibling_media, _manifest()],
    }
    service = _service(parents, subtrees)

    resolved = service._find_package_folder({"id": "flat-media-id", "parents": [FLAT_PKG]})

    assert resolved is None, "walk climbed into the brand root and borrowed a sibling's manifest"


def test_flat_package_media_gets_no_copy_instead_of_a_siblings_copy():
    """End to end: the flat package's creative must not inherit sibling copy."""
    flat_media = _png("flat-media-id", "contractor.png")
    sibling_media = _png("sibling-media-id", "contractor.png")
    parents = {FLAT_PKG: BRAND, SIBLING_PKG: BRAND, BRAND: ROOT}
    subtrees = {
        FLAT_PKG: [flat_media],
        SIBLING_PKG: [sibling_media, _manifest()],
        BRAND: [flat_media, sibling_media, _manifest()],
    }
    service = _service(parents, subtrees)
    # Whatever folder is resolved, the sibling's manifest metadata is keyed by the
    # colliding basename and owned by the SIBLING's Drive file id.
    service._folder_copy_metadata = lambda folder_id, force=False: {
        "assets": {
            "contractor.png": {
                "copy_id": "SIB-F01",
                "copy": {"headline": "Sibling headline", "primary_text": "Sibling body"},
                "landing_page": "https://example.com/sibling",
                "cta": "GET_QUOTE",
                "source": "handoff_manifest",
                "drive_file_id": "sibling-media-id",
            }
        },
        "_copy_source_drive_file_id": "manifest-id",
    }
    service._find_strategy_package_folder = lambda file_meta, max_depth=4: None

    metadata = service._metadata_for_media_file(
        {"id": "flat-media-id", "parents": [FLAT_PKG]}, "contractor.png"
    )

    assert metadata.get("copy_id") != "SIB-F01", "creative inherited a sibling package's copy"
    assert not metadata.get("copy"), "creative inherited a sibling package's copy body"
    assert metadata.get("landing_page") is None, "creative inherited a sibling package's landing page"
    assert metadata.get("cta") is None, "creative inherited a sibling package's CTA"


def test_filename_match_owned_by_another_file_is_refused():
    service = DriveSyncService.__new__(DriveSyncService)
    folder_metadata = {
        "assets": {
            "ad1-identity-1x1.png": {
                "copy": {"headline": "Roofing headline"},
                "drive_file_id": "roofing-file-id",
            }
        }
    }

    metadata, refusal = service._filename_keyed_metadata(
        folder_metadata, "ad1-identity-1x1.png", "janitorial-file-id", "some-folder"
    )

    assert metadata == {}
    # The refusal must be visible: the picker reads a missing copy_refresh_status
    # as "verified", so an empty dict would leave the asset silently selectable.
    assert refusal["copy_integrity_issue"] is True
    assert refusal["copy_refresh_status"] == "unverified"
    assert "ad1-identity-1x1.png" in refusal["copy_integrity_reason"]


def test_filename_match_owned_by_this_file_is_accepted():
    service = DriveSyncService.__new__(DriveSyncService)
    entry = {"copy": {"headline": "Roofing headline"}, "drive_file_id": "roofing-file-id"}
    folder_metadata = {"assets": {"ad1-identity-1x1.png": entry}}

    assert service._filename_keyed_metadata(
        folder_metadata, "ad1-identity-1x1.png", "roofing-file-id", "some-folder"
    ) == (entry, {})


def test_filename_match_without_a_resolved_owner_is_still_accepted():
    """A manifest entry whose media has not landed in Drive yet keeps working."""
    service = DriveSyncService.__new__(DriveSyncService)
    entry = {"copy": {"headline": "Pending headline"}, "drive_file_id": None}
    folder_metadata = {"assets": {"pending-1x1.png": entry}}

    assert service._filename_keyed_metadata(
        folder_metadata, "pending-1x1.png", "some-file-id", "some-folder"
    ) == (entry, {})


def test_normal_placement_subfolder_layout_still_resolves_to_its_package():
    """Regression: media in "1x1 Images" under a manifest-bearing package root."""
    media = _png("media-id", "AD-ROOF-01-1x1.png")
    parents = {PLACEMENT: SIBLING_PKG, SIBLING_PKG: BRAND, BRAND: ROOT}
    subtrees = {
        PLACEMENT: [media],
        SIBLING_PKG: [media, _manifest()],
        BRAND: [media, _manifest()],
    }
    service = _service(parents, subtrees)

    resolved = service._find_package_folder({"id": "media-id", "parents": [PLACEMENT]})

    assert resolved == SIBLING_PKG


def test_manifest_in_ad_copy_subfolder_layout_still_resolves_to_its_package():
    """Regression: two live packages keep their manifest in an "Ad Copy" child,
    not in the package root. That layout must keep resolving."""
    media = _png("media-id", "AD-DEALER-CD-01-1x1.jpg")
    manifest = _manifest("dealer-manifest", "AUTO-DEALER-CLAIM-DENIAL-HANDOFF-MANIFEST.txt")
    parents = {
        PLACEMENT: SIBLING_PKG,
        AD_COPY: SIBLING_PKG,
        SIBLING_PKG: BRAND,
        BRAND: ROOT,
    }
    subtrees = {
        PLACEMENT: [media],
        AD_COPY: [manifest],
        SIBLING_PKG: [media, manifest],
        BRAND: [media, manifest],
    }
    service = _service(parents, subtrees)

    resolved = service._find_package_folder({"id": "media-id", "parents": [PLACEMENT]})

    assert resolved == SIBLING_PKG


def test_brand_root_is_a_package_container_but_a_package_is_not():
    service = _service({BRAND: ROOT, SIBLING_PKG: BRAND}, {})

    assert service._is_package_container(ROOT)
    assert service._is_package_container(BRAND)
    assert not service._is_package_container(SIBLING_PKG)


def test_refused_asset_is_flagged_so_the_picker_blocks_it():
    """A refusal must set the two flags the picker blocks selection on.

    frontend/src/components/AdCreativeStep.jsx reads
    `refreshStatus: tags.copy_refresh_status || 'verified'`, so an asset with no
    status key renders as verified and stays selectable -- and its landing page
    would silently fall back to the brand default at the launch step.
    """
    service = DriveSyncService.__new__(DriveSyncService)
    folder_metadata = {
        "assets": {
            "ad1-identity-1x1.png": {
                "copy": {"headline": "Roofing headline"},
                "landing_page": "https://example.com/roofing",
                "cta": "GET_QUOTE",
                "drive_file_id": "roofing-file-id",
            }
        }
    }

    _, refusal = service._filename_keyed_metadata(
        folder_metadata, "ad1-identity-1x1.png", "janitorial-file-id", "pkg"
    )

    assert refusal["copy_integrity_issue"] is True
    assert refusal["copy_refresh_status"] == "unverified"
    # and it must not carry the other package's destination through
    assert "landing_page" not in refusal
    assert "cta" not in refusal
    # package_folder_id is the pairing key in buildDriveAssetGroups and these tags
    # get merged over an existing row; overwriting it would migrate the refused
    # asset out of its real pair group.
    assert "package_folder_id" not in refusal


def test_strategy_resolver_also_refuses_to_adopt_a_brand_root():
    """The strategy walk needs its own container guard.

    _strategy_folder_copy_metadata pairs a doc's blocks against filenames and
    stamps each entry with THAT file's own Drive ID, so an entry built from a
    brand root's doc legitimately owns this file -- the identity check cannot
    catch it. Only refusing to resolve the brand root prevents it.
    """
    media = _png("flat-media-id", "AD-ROOF-01-1x1.png")
    strategy_doc = {"id": "doc-id", "name": "strategy.md", "mimeType": "text/markdown"}
    parents = {FLAT_PKG: BRAND, SIBLING_PKG: BRAND, BRAND: ROOT}
    subtrees = {
        FLAT_PKG: [media],
        SIBLING_PKG: [_png("sib-id", "AD-ROOF-02-1x1.png"), strategy_doc],
        BRAND: [media, _png("sib-id", "AD-ROOF-02-1x1.png"), strategy_doc],
    }
    service = _service(parents, subtrees)
    service._download_text_file = lambda file_id: "## AD-ROOF-01\nMeta headline: x\nPrimary text: y\n"

    resolved = service._find_strategy_package_folder({"id": "flat-media-id", "parents": [FLAT_PKG]})

    assert resolved is None, "strategy walk adopted the brand root's copy doc"


def test_package_container_fails_closed_when_the_chain_cannot_be_resolved():
    """Fail closed: False would mean "real package, adopt it" -- the leak itself."""
    service = DriveSyncService.__new__(DriveSyncService)
    service.root_folder_id = ROOT
    service._folder_chain_to_root = lambda folder_id: None

    assert service._is_package_container("anything")


def test_package_container_fails_closed_when_drive_raises():
    service = DriveSyncService.__new__(DriveSyncService)
    service.root_folder_id = ROOT

    def _boom(folder_id):
        raise TimeoutError("connection reset")

    service._folder_chain_to_root = _boom

    # Must not propagate: this runs inside the sync loop and would kill the run.
    assert service._is_package_container("anything")


def test_ad_numbered_copy_metadata_fails_closed_for_incomplete_document():
    service = DriveSyncService.__new__(DriveSyncService)

    result = service._ad_numbered_folder_copy_metadata(
        "painting-package",
        [{"id": "feed", "name": "CVI-PAINT-01-IDENTITY-1x1.png"}],
        "AD 1 — Draft\nMETA HEADLINE\n\nPRIMARY TEXT\n",
    )

    assert result == {"assets": {}, "assets_by_drive_id": {}}


def test_package_copy_source_prefers_canonical_ad_copy_over_newer_winner_variations():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    primary = {
        "id": "primary-copy",
        "name": "01-Painting-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:42:21Z",
    }
    winner = {
        "id": "winner-copy",
        "name": "01-Painting-Winner-Variations-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:50:16Z",
    }
    media = {
        "id": "paint-ad1-feed",
        "name": "01-PAINT-AD1-Identity-1x1.jpg",
        "mimeType": "image/png",
        "_parent_folder_path": ["01 - Painting Contractors", "1x1 Images"],
    }
    documents = {
        "primary-copy": "AD 1 — Identity\nMETA HEADLINE\nPrimary headline\nPRIMARY TEXT\nPrimary body\nCTA: Get My Rate Now\n",
        "winner-copy": "AD 1 — Winner\nHeadline: Winner headline\n==========\nWinner body\n==========\n",
    }
    service._list_folder_subtree = lambda folder_id: [primary, winner, media]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("painting-package")

    assert result["_copy_source_drive_file_id"] == "primary-copy"
    assert result["_copy_source_drive_modified_time"] == "2026-09-22T10:42:21Z"
    assert result["assets_by_drive_id"]["paint-ad1-feed"]["copy"]["headline"] == "Primary headline"


def test_package_copy_sources_merge_disjoint_launch_batches_with_per_asset_provenance():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    canonical = {
        "id": "canonical-copy",
        "name": "General-Auto-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:54:48Z",
    }
    winner = {
        "id": "winner-copy",
        "name": "General-Auto-Winner-Variations-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:55:00Z",
    }
    legacy_feed = {"id": "legacy-feed", "name": "A1-Van-Denial-Scenario-1x1.png", "mimeType": "image/png"}
    legacy_story = {"id": "legacy-story", "name": "A1-Van-Denial-Scenario-9x16.png", "mimeType": "image/png"}
    winner_feed = {"id": "winner-feed", "name": "GCA-AD2-Winner-1x1.jpg", "mimeType": "image/jpeg"}
    winner_story = {"id": "winner-story", "name": "GCA-AD2-Winner-9x16.jpg", "mimeType": "image/jpeg"}
    documents = {
        "canonical-copy": """AD 01 — Original Set A1
Headline: Legacy headline
Legacy primary text.
""",
        "winner-copy": """AD 2 — Winner
META HEADLINE
Winner headline
PRIMARY TEXT
Winner primary text.
""",
    }
    service._list_folder_subtree = lambda folder_id: [canonical, winner, legacy_feed, legacy_story, winner_feed, winner_story]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("general-auto")

    assert set(result["assets_by_drive_id"]) == {"legacy-feed", "legacy-story", "winner-feed", "winner-story"}
    assert result["assets_by_drive_id"]["legacy-feed"]["copy_source_drive_file_id"] == "canonical-copy"
    assert result["assets_by_drive_id"]["winner-feed"]["copy_source_drive_file_id"] == "winner-copy"
    assert result["assets_by_drive_id"]["winner-story"]["copy"]["headline"] == "Winner headline"


def test_package_copy_sources_apply_priority_to_overlapping_strategy_and_ad_media():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    strategy = {
        "id": "strategy-copy", "name": "ICP Strategy.txt", "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:55:00Z",
    }
    canonical = {
        "id": "canonical-copy", "name": "Package-Ad-Copy.txt", "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:54:00Z",
    }
    media = {"id": "same-media", "name": "AD-LAND-01-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    documents = {
        "strategy-copy": """## AD-LAND-01
**Meta headline:** Strategy headline
**Primary text:** Strategy body
""",
        "canonical-copy": """1. LANDSCAPING
Headline: Canonical headline
Primary text:
Canonical body
""",
    }
    service._list_folder_subtree = lambda folder_id: [strategy, canonical, media]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("overlap-package")

    assert result["assets_by_drive_id"]["same-media"]["copy"]["headline"] == "Canonical headline"
    assert result["assets_by_drive_id"]["same-media"]["copy_source_drive_file_id"] == "canonical-copy"


def test_package_copy_source_uses_newer_ad_copy_over_older_handoff_manifest():
    """Drive modifiedTime wins between complete manifests and launch-copy docs."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    manifest = {
        "id": "older-manifest",
        "name": "PACKAGE-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:50:00Z",
    }
    newer_copy = {
        "id": "newer-copy",
        "name": "PACKAGE-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:55:00Z",
    }
    media = {
        "id": "package-ad1-feed",
        "name": "PACKAGE-AD1-Identity-1x1.jpg",
        "mimeType": "image/jpeg",
    }
    documents = {
        "older-manifest": """FINAL HANDOFF MANIFEST
Landing Page
https://example.com/old
Meta Button
Get Quote

AD 1
Primary Text
Old body
Headline
Old headline
1x1 Image
PACKAGE-AD1-Identity-1x1.jpg
9x16 Image
PACKAGE-AD1-Identity-9x16.jpg
""",
        "newer-copy": """AD 1 — Identity
META HEADLINE
New headline
PRIMARY TEXT
New primary text
CTA: GET QUOTE
""",
    }
    service._list_folder_subtree = lambda folder_id: [manifest, newer_copy, media]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("package")

    assert result["_copy_source_drive_file_id"] == "newer-copy"
    assert result["_copy_source_drive_modified_time"] == "2026-09-22T10:55:00Z"
    assert result["assets_by_drive_id"]["package-ad1-feed"]["copy"]["headline"] == "New headline"


def test_partial_newer_ad_copy_cannot_displace_complete_handoff_manifest():
    """Freshness never turns a one-good-section draft into the launch source."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    manifest = {
        "id": "complete-manifest",
        "name": "PACKAGE-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:50:00Z",
    }
    partial_copy = {
        "id": "partial-copy",
        "name": "PACKAGE-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:55:00Z",
    }
    feed = {"id": "package-ad1-feed", "name": "PACKAGE-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    stories = {"id": "package-ad1-stories", "name": "PACKAGE-AD1-Identity-9x16.jpg", "mimeType": "image/jpeg"}
    documents = {
        "complete-manifest": """FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP
Landing Page
https://example.com/current
Meta Button
Get Quote

## PACKAGE-AD1
PRIMARY TEXT
Current primary text.
HEADLINE
Current headline
1X1 IMAGE
PACKAGE-AD1-Identity-1x1.jpg
9X16 IMAGE
PACKAGE-AD1-Identity-9x16.jpg
""",
        "partial-copy": """AD 1 — Complete
META HEADLINE
New headline
PRIMARY TEXT
New primary text

AD 2 — Draft
META HEADLINE
Unfinished headline
PRIMARY TEXT
""",
    }
    service._list_folder_subtree = lambda folder_id: [manifest, partial_copy, feed, stories]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("package")

    assert result["_copy_source_drive_file_id"] == "complete-manifest"
    assert result["assets_by_drive_id"]["package-ad1-feed"]["copy"]["headline"] == "Current headline"


def test_newer_strategy_document_cannot_displace_complete_handoff_manifest():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    manifest = {
        "id": "complete-manifest", "name": "PACKAGE-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:50:00Z",
    }
    strategy = {
        "id": "newer-strategy", "name": "PACKAGE-ICP-and-Strategy.md",
        "mimeType": "text/markdown", "modifiedTime": "2026-09-22T10:55:00Z",
    }
    feed = {"id": "package-ad1-feed", "name": "PACKAGE-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    stories = {"id": "package-ad1-stories", "name": "PACKAGE-AD1-Identity-9x16.jpg", "mimeType": "image/jpeg"}
    documents = {
        "complete-manifest": """FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP
Landing Page
https://example.com/current
Meta Button
Get Quote

## PACKAGE-AD1
PRIMARY TEXT
Current primary text.
HEADLINE
Current headline
1X1 IMAGE
PACKAGE-AD1-Identity-1x1.jpg
9X16 IMAGE
PACKAGE-AD1-Identity-9x16.jpg
""",
        "newer-strategy": "## AD-PACKAGE-01\nThis is newer planning material, not launch copy.\n",
    }
    service._list_folder_subtree = lambda folder_id: [manifest, strategy, feed, stories]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("package")

    assert result["_copy_source_drive_file_id"] == "complete-manifest"


def test_newer_unreadable_ad_copy_blocks_older_handoff_manifest():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    manifest = {
        "id": "complete-manifest", "name": "PACKAGE-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:50:00Z",
    }
    unreadable = {
        "id": "unreadable-copy", "name": "PACKAGE-Ad-Copy.txt",
        "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:55:00Z",
    }
    manifest_text = """FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP
Landing Page
https://example.com/current
Meta Button
Get Quote

## PACKAGE-AD1
PRIMARY TEXT
Current primary text.
HEADLINE
Current headline
1X1 IMAGE
PACKAGE-AD1-Identity-1x1.jpg
9X16 IMAGE
PACKAGE-AD1-Identity-9x16.jpg
"""
    service._list_folder_subtree = lambda folder_id: [manifest, unreadable]

    def download(file_id):
        if file_id == "unreadable-copy":
            raise TimeoutError("Drive read timed out")
        return manifest_text

    service._download_text_file = download

    import pytest

    with pytest.raises(RuntimeError, match="Could not verify newer Drive copy source"):
        service._folder_copy_metadata("package")


def test_unreadable_ad_copy_blocks_package_without_manifest_too():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    unreadable = {
        "id": "unreadable-copy", "name": "PACKAGE-Ad-Copy.txt",
        "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:55:00Z",
    }
    strategy = {
        "id": "older-strategy", "name": "PACKAGE-Strategy.md",
        "mimeType": "text/markdown", "modifiedTime": "2026-09-22T10:50:00Z",
    }
    service._list_folder_subtree = lambda folder_id: [unreadable, strategy]

    def download(file_id):
        if file_id == "unreadable-copy":
            raise TimeoutError("Drive read timed out")
        return "## AD-PACKAGE-01\nOlder strategy content\n"

    service._download_text_file = download

    import pytest

    with pytest.raises(RuntimeError, match="Could not verify Drive copy source"):
        service._folder_copy_metadata("package")


def test_freshness_decision_reuses_the_validated_copy_snapshot():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    manifest = {
        "id": "older-manifest", "name": "PACKAGE-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:50:00Z",
    }
    newer_copy = {
        "id": "newer-copy", "name": "PACKAGE-Ad-Copy.txt",
        "mimeType": "text/plain", "modifiedTime": "2026-09-22T10:55:00Z",
    }
    media = {"id": "package-ad1-feed", "name": "PACKAGE-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    documents = {
        "older-manifest": "Batch notes only — copy will be added later.",
        "newer-copy": "AD 1 — Identity\nMETA HEADLINE\nNew headline\nPRIMARY TEXT\nNew primary text\nCTA: GET QUOTE\n",
    }
    reads = []
    service._list_folder_subtree = lambda folder_id: [manifest, newer_copy, media]

    def download(file_id):
        reads.append(file_id)
        return documents[file_id]

    service._download_text_file = download

    result = service._folder_copy_metadata("package")

    assert result["_copy_source_drive_file_id"] == "newer-copy"
    assert reads.count("newer-copy") == 1


def test_non_actionable_handoff_manifest_falls_back_to_canonical_ad_copy():
    """A draft named like a handoff manifest must not hide usable package copy."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    manifest = {
        "id": "draft-manifest",
        "name": "HANDOFF_MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:50:00Z",
    }
    canonical = {
        "id": "canonical-copy",
        "name": "03-Electrical-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:42:00Z",
    }
    media = {
        "id": "electrical-ad1-feed",
        "name": "03-ELEC-AD1-Identity-1x1.jpg",
        "mimeType": "image/jpeg",
        "_parent_folder_path": ["03 - Electrical Contractors", "1x1 Images"],
    }
    documents = {
        "draft-manifest": "Batch notes only — copy will be added later.",
        "canonical-copy": (
            "AD 1 — Identity\nMETA HEADLINE\nCommercial Auto for Electricians\n"
            "PRIMARY TEXT\nElectrician primary text.\nCTA: GET QUOTE\n"
        ),
    }
    service._list_folder_subtree = lambda folder_id: [manifest, canonical, media]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("electrical-package")

    assert result["_copy_source_drive_file_id"] == "canonical-copy"
    assert result["assets_by_drive_id"]["electrical-ad1-feed"]["copy"]["headline"] == "Commercial Auto for Electricians"


def test_incomplete_handoff_manifest_does_not_fall_back_to_canonical_ad_copy():
    """A real but incomplete manifest may be in progress, so launch must stay blocked."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    manifest = {
        "id": "incomplete-manifest",
        "name": "HANDOFF_MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:50:00Z",
    }
    canonical = {
        "id": "canonical-copy",
        "name": "03-Electrical-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:42:00Z",
    }
    media = {
        "id": "electrical-ad1-feed",
        "name": "03-ELEC-AD1-Identity-1x1.jpg",
        "mimeType": "image/jpeg",
        "_parent_folder_path": ["03 - Electrical Contractors", "1x1 Images"],
    }
    documents = {
        "incomplete-manifest": "AD ELEC 01\n1x1: 03-ELEC-AD1-Identity-1x1.jpg\n",
        "canonical-copy": (
            "AD 1 — Identity\nMETA HEADLINE\nCommercial Auto for Electricians\n"
            "PRIMARY TEXT\nElectrician primary text.\nCTA: GET QUOTE\n"
        ),
    }
    service._list_folder_subtree = lambda folder_id: [manifest, canonical, media]
    service._download_text_file = lambda file_id: documents[file_id]

    import pytest

    with pytest.raises(RuntimeError, match="incomplete entries"):
        service._folder_copy_metadata("electrical-package")


def test_self_contained_v2_handoff_manifest_matches_inline_copy_and_media():
    """Production V2 manifests carry their own fields rather than a copy-file link."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    manifest = {
        "id": "v2-manifest",
        "name": "03-ELEC-V2-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T12:03:00Z",
    }
    feed = {
        "id": "v2-feed",
        "name": "03-ELEC-V2-AD1-Identity-1x1.jpg",
        "mimeType": "image/jpeg",
        "_parent_folder_path": ["03 - Electrical Contractors v2", "1x1 Images"],
    }
    stories = {
        "id": "v2-stories",
        "name": "03-ELEC-V2-AD1-Identity-9x16.jpg",
        "mimeType": "image/jpeg",
        "_parent_folder_path": ["03 - Electrical Contractors v2", "9x16 Images"],
    }
    manifest_text = """PACKAGE: Commercial Van Insurance | Electrical Contractors v2
FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP

Landing Page
https://www.getbusinesscoverage.com/commercial-auto-v2

Meta Button
Get Quote

## 03-ELEC-V2-AD1

PRIMARY TEXT
Electrician primary text.

HEADLINE
Commercial Van Insurance for Electricians

DESCRIPTION
Coverage for electricians on the road.

1X1 IMAGE
03-ELEC-V2-AD1-Identity-1x1.jpg

9X16 IMAGE
03-ELEC-V2-AD1-Identity-9x16.jpg
"""
    service._list_folder_subtree = lambda folder_id: [manifest, feed, stories]
    service._download_text_file = lambda file_id: manifest_text

    result = service._folder_copy_metadata("electrical-v2-package")

    assert result["_copy_source_drive_file_id"] == "v2-manifest"
    assert result["assets_by_drive_id"]["v2-feed"]["copy"]["headline"] == "Commercial Van Insurance for Electricians"
    assert result["assets_by_drive_id"]["v2-feed"]["copy"]["primary_text"] == "Electrician primary text."
    assert result["assets_by_drive_id"]["v2-stories"]["aspect"] == "9x16"


def test_self_contained_handoff_manifest_matches_non_v2_religious_ids():
    """Inline manifests use many package ID families, not only V2 IDs."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    manifest = {
        "id": "religious-manifest",
        "name": "RO-PROP-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T12:00:15.894Z",
    }
    feed = {"id": "religious-feed", "name": "RO-PROP-AD1-ThreeAsset-1x1.jpg", "mimeType": "image/jpeg"}
    stories = {"id": "religious-stories", "name": "RO-PROP-AD1-ThreeAsset-9x16.png", "mimeType": "image/png"}
    manifest_text = """FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP
Landing Page
https://www.getbusinesscoverage.com/quote-v2
Meta Button
Get Quote

## RO-PROP-AD1
PRIMARY TEXT
Your church has stood through decades.
HEADLINE
Religious Organization Insurance
DESCRIPTION
One storm can raise more than one property question.
1X1 IMAGE
RO-PROP-AD1-ThreeAsset-1x1.jpg
9X16 IMAGE
RO-PROP-AD1-ThreeAsset-9x16.png
"""
    service._list_folder_subtree = lambda folder_id: [manifest, feed, stories]
    service._download_text_file = lambda file_id: manifest_text

    result = service._folder_copy_metadata("religious-property-package")

    assert result["_copy_source_drive_file_id"] == "religious-manifest"
    assert result["assets_by_drive_id"]["religious-feed"]["copy"]["headline"] == "Religious Organization Insurance"
    assert result["assets_by_drive_id"]["religious-stories"]["copy"]["primary_text"] == "Your church has stood through decades."


def test_self_contained_v2_manifest_rejects_ambiguous_or_cross_ad_media():
    """Inline maps are fail-closed when a declared filename is ambiguous or miswired."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    manifest = {
        "id": "v2-manifest",
        "name": "03-ELEC-V2-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T12:03:00Z",
    }
    feed = {
        "id": "v2-feed-a",
        "name": "03-ELEC-V2-AD1-Identity-1x1.jpg",
        "mimeType": "image/jpeg",
    }
    duplicate_feed = {**feed, "id": "v2-feed-b"}
    stories = {
        "id": "v2-stories",
        "name": "03-ELEC-V2-AD1-Identity-9x16.jpg",
        "mimeType": "image/jpeg",
    }
    manifest_text = """## 03-ELEC-V2-AD1
PRIMARY TEXT
Electrician primary text.
HEADLINE
Commercial Van Insurance for Electricians
1X1 IMAGE
03-ELEC-V2-AD1-Identity-1x1.jpg
9X16 IMAGE
03-ELEC-V2-AD1-Identity-9x16.jpg
"""
    service._list_folder_subtree = lambda folder_id: [manifest, feed, duplicate_feed, stories]
    service._download_text_file = lambda file_id: manifest_text

    import pytest

    with pytest.raises(RuntimeError, match="ambiguous media"):
        service._folder_copy_metadata("electrical-v2-package")


def test_self_contained_v2_manifest_rejects_wrong_aspect_and_draft_sections():
    """A V2 map cannot silently swap placements or ignore a trailing draft section."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    manifest = {"id": "v2-manifest", "name": "04-LAND-V2-HANDOFF-MANIFEST.txt", "mimeType": "text/plain"}
    feed = {"id": "feed", "name": "04-LAND-V2-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    stories = {"id": "stories", "name": "04-LAND-V2-AD1-Identity-9x16.jpg", "mimeType": "image/jpeg"}
    manifest_text = """## 04-LAND-V2-AD1
PRIMARY TEXT
Landscaper primary text.
HEADLINE
Commercial Van Insurance for Landscapers
1X1 IMAGE
04-LAND-V2-AD1-Identity-9x16.jpg
9X16 IMAGE
04-LAND-V2-AD1-Identity-1x1.jpg

## 04-LAND-V2-AD2 — Draft
"""
    service._list_folder_subtree = lambda folder_id: [manifest, feed, stories]
    service._download_text_file = lambda file_id: manifest_text

    import pytest

    with pytest.raises(RuntimeError, match="wrong media aspect"):
        service._folder_copy_metadata("landscaping-v2-package")

    service._folder_metadata_cache = {}
    service._download_text_file = lambda file_id: manifest_text.replace(
        "04-LAND-V2-AD1-Identity-9x16.jpg\n9X16 IMAGE\n04-LAND-V2-AD1-Identity-1x1.jpg",
        "04-LAND-V2-AD1-Identity-1x1.jpg\n9X16 IMAGE\n04-LAND-V2-AD1-Identity-9x16.jpg",
    )
    with pytest.raises(RuntimeError, match="inline AD 2 is missing its 1X1 image"):
        service._folder_copy_metadata("landscaping-v2-package")


def test_package_copy_source_priority_ignores_marker_words_embedded_in_other_tokens():
    """A canonical file's own version suffix or persona note (e.g. "_Variation2",
    "_ICPersonas") must not be mistaken for a real winner-variation or ICP/reference
    doc just because the marker word appears as a substring."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}

    canonical = {
        "id": "canonical-copy",
        "name": "AdCopy_Variation2.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:00:00Z",
    }
    persona_note = {
        "id": "persona-note",
        "name": "AdCopy_ICPersonas.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T09:00:00Z",
    }
    media = {
        "id": "roof-ad1-feed",
        "name": "01-ROOF-AD1-Identity-1x1.jpg",
        "mimeType": "image/png",
        "_parent_folder_path": ["01 - Roofing", "1x1 Images"],
    }
    documents = {
        "canonical-copy": "AD 1 — Identity\nMETA HEADLINE\nCanonical headline\nPRIMARY TEXT\nCanonical body\nCTA: Get My Rate Now\n",
        "persona-note": "AD 1 — Note\nHeadline: Persona headline\n==========\nPersona body\n==========\n",
    }
    service._list_folder_subtree = lambda folder_id: [canonical, persona_note, media]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("roofing-package")

    assert result["_copy_source_drive_file_id"] == "canonical-copy"
    assert result["assets_by_drive_id"]["roof-ad1-feed"]["copy"]["headline"] == "Canonical headline"


def test_metadata_for_media_file_propagates_copy_source_file_name():
    """copy_source_drive_file_name must reach the bound asset on the normal sync
    path (_metadata_for_media_file), not only via the refresh-tags path."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._find_package_folder = lambda file_meta: "package"
    service._folder_copy_metadata = lambda folder_id, force=False: {
        "assets_by_drive_id": {
            "media-1": {"file_name": "AD1-1x1.jpg", "drive_file_ids": ["media-1"], "copy_id": "AD-01"}
        },
        "_copy_source_drive_file_id": "copy-doc",
        "_copy_source_drive_modified_time": "2026-09-22T10:00:00Z",
        "_copy_source_drive_file_name": "Ad Copy.txt",
    }

    bound = service._metadata_for_media_file({"id": "media-1"}, "AD1-1x1.jpg")

    assert bound["copy_source_drive_file_id"] == "copy-doc"
    assert bound["copy_source_drive_modified_time"] == "2026-09-22T10:00:00Z"
    assert bound["copy_source_drive_file_name"] == "Ad Copy.txt"


def _process_file_test_service(backfill_mode):
    """Minimal DriveSyncService double for exercising _process_file's unchanged-file branch."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._backfill_mode = backfill_mode
    service._resolve_drive_path = lambda file_meta: type("R", (), {"brand_folder": "Brand", "folder_path": "p"})()
    service._match_brand_id = lambda brand_folder: "brand-id"
    resolution_calls = []
    service._metadata_for_media_file = lambda file_meta, file_name: resolution_calls.append(file_name) or {}

    class FakeDB:
        def execute(self, *args, **kwargs):
            class Result:
                def mappings(self):
                    return self

                def first(self):
                    return {
                        "id": "row-1",
                        "drive_modified_time": modified_time,
                        "soft_tags": "{}",
                    }
            return Result()

    service.db = FakeDB()
    modified_time = service._parse_drive_time("2026-09-22T10:00:00Z")
    return service, resolution_calls


def test_defer_copy_resolution_skips_metadata_lookup_for_unchanged_files_in_backfill_mode():
    """The combined refresh-copy-metadata endpoint sets _backfill_mode so an
    immediately-following refresh_copy_metadata() pass can re-derive copy tags
    more cheaply at the package level -- per-file resolution here would be
    redundant and, on a large Drive, slow enough to make the UI look hung."""
    service, resolution_calls = _process_file_test_service(backfill_mode=True)
    result = {"skipped": 0, "updated": 0, "unmatched_brand": 0, "errors": 0}

    service._process_file(
        {"id": "media-1", "name": "AD1-1x1.jpg", "mimeType": "image/jpeg", "modifiedTime": "2026-09-22T10:00:00Z"},
        result,
    )

    assert resolution_calls == []
    assert result["updated"] == 1


def test_standalone_backfill_still_resolves_copy_metadata_for_unchanged_files():
    """sync-now?backfill=true (Creative Library's "Sync" button) has no
    guaranteed refresh_copy_metadata() follow-up, so it must keep resolving
    copy metadata per file here -- skipping it would silently stop existing,
    unchanged rows from picking up copy document changes."""
    service, resolution_calls = _process_file_test_service(backfill_mode=False)
    result = {"skipped": 0, "updated": 0, "unmatched_brand": 0, "errors": 0}

    service._process_file(
        {"id": "media-1", "name": "AD1-1x1.jpg", "mimeType": "image/jpeg", "modifiedTime": "2026-09-22T10:00:00Z"},
        result,
    )

    assert resolution_calls == ["AD1-1x1.jpg"]
    assert result["updated"] == 1


def test_sync_once_isolates_a_bad_file_and_commits_successful_files():
    """One malformed Drive object must not roll back the rest of a backfill."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._copy_packages_refreshed_in_sync = set()
    service._validate_tables = lambda: None
    service._client = lambda: object()
    service._get_state_token = lambda: "checkpoint"
    service._get_start_page_token = lambda drive: "start"
    service._initial_folder_walk = lambda drive: [{"id": "bad", "name": "bad.jpg"}, {"id": "good", "name": "good.jpg"}]
    processed = []
    service._process_file = lambda file_meta, result: (
        (_ for _ in ()).throw(RuntimeError("bad file")) if file_meta["id"] == "bad" else processed.append(file_meta["id"])
    )
    unverified = []
    service._mark_package_copy_unverified = lambda file_meta, reason: unverified.append(file_meta["id"])

    class Result:
        def scalar(self):
            return True

    class FakeDB:
        committed = False
        rolled_back = False
        def execute(self, *args, **kwargs):
            return Result()
        class Savepoint:
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, traceback):
                return False
        def begin_nested(self):
            return self.Savepoint()
        def commit(self):
            self.committed = True
        def rollback(self):
            self.rolled_back = True

    service.db = FakeDB()
    result = service.sync_once(backfill=True)

    assert processed == ["good"]
    assert unverified == ["bad"]
    assert result["errors"] == 1
    assert result["processed"] == 2
    assert service.db.committed is True
    assert service.db.rolled_back is False


def test_drive_sync_routes_keep_their_intended_service_composition(monkeypatch):
    """Pin endpoint wiring so a future refactor cannot silently swap paths."""
    from app.api.v1 import drive_assets as route_module
    from app.schemas.drive_assets import DriveCopyRefreshRequest

    calls = []

    class FakeService:
        def __init__(self, db):
            calls.append(("init", db))
        def sync_once(self, **kwargs):
            calls.append(("sync_once", kwargs))
            return {"processed": 1}
        def refresh_copy_metadata(self):
            calls.append(("refresh_all", {}))
            return {"processed": 2}
        def refresh_copy_metadata_for_sources(self, source_ids):
            calls.append(("refresh_sources", source_ids))
            return {"processed": 3}

    monkeypatch.setattr(route_module, "DriveSyncService", FakeService)
    db = object()
    assert route_module.sync_drive_assets_now(backfill=True, db=db, _current_user=object())["processed"] == 1
    assert calls[-1] == ("sync_once", {"backfill": True})

    assert route_module.refresh_drive_copy_metadata(
        payload=DriveCopyRefreshRequest(source_file_ids=["copy-doc"]), db=db, _current_user=object()
    )["processed"] == 3
    assert calls[-1] == ("refresh_sources", ["copy-doc"])

    assert route_module.refresh_drive_copy_metadata(
        payload=DriveCopyRefreshRequest(), db=db, _current_user=object()
    )["processed"] == 2
    assert calls[-1] == ("refresh_all", {})


class _SavepointTrackingDB:
    """Tracks begin_nested()/commit()/rollback() calls so a test can assert a
    real savepoint was used per file, not just a bare try/except."""

    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.nested_entries = 0
        self.nested_exits = []

    def execute(self, *args, **kwargs):
        class Result:
            def scalar(self):
                return True

        return Result()

    def begin_nested(self):
        db = self

        class Savepoint:
            def __enter__(self):
                db.nested_entries += 1
                return self

            def __exit__(self, exc_type, exc, traceback):
                db.nested_exits.append(exc_type)
                return False

        return Savepoint()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_archive_by_drive_id_isolated_uses_savepoint_and_records_error():
    """A failing archive must roll back only its own savepoint, not raise."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._archive_by_drive_id = lambda drive_file_id: (
        (_ for _ in ()).throw(RuntimeError("db constraint violated")) if drive_file_id == "bad" else 1
    )
    service.db = _SavepointTrackingDB()
    result = {"errors": 0}

    archived_good = service._archive_by_drive_id_isolated("good", result)
    archived_bad = service._archive_by_drive_id_isolated("bad", result)

    assert archived_good == 1
    assert archived_bad == 0
    assert result["errors"] == 1
    # A savepoint must be opened for each archive attempt, and the failing one
    # must exit with its exception recorded (proving isolation actually ran
    # through begin_nested(), not a bare try/except around _archive_by_drive_id).
    assert service.db.nested_entries == 2
    assert service.db.nested_exits == [None, RuntimeError]


def test_sync_once_isolates_a_bad_removed_and_trashed_file_and_commits_good_changes():
    """Deletion/trashed-file events must get the same per-item isolation as
    active file processing: one bad removal or bad trashed-file archive must
    not roll back a good removal, a good trashed archive, or a good file."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._copy_packages_refreshed_in_sync = set()
    service._validate_tables = lambda: None
    service._get_state_token = lambda: "existing-checkpoint"

    class FakeChangesRequest:
        def __init__(self, response):
            self._response = response

        def execute(self):
            return self._response

    class FakeChanges:
        def list(self, **kwargs):
            return FakeChangesRequest(
                {
                    "changes": [
                        {"removed": True, "fileId": "bad-removed"},
                        {"removed": True, "fileId": "good-removed"},
                        {"file": {"id": "bad-trashed", "name": "bad-trashed.jpg", "trashed": True}},
                        {"file": {"id": "good-trashed", "name": "good-trashed.jpg", "trashed": True}},
                        {"file": {"id": "good-file", "name": "good-file.jpg"}},
                    ],
                    "nextPageToken": None,
                    "newStartPageToken": "next-checkpoint",
                }
            )

    class FakeDrive:
        def changes(self):
            return FakeChanges()

    service._client = lambda: FakeDrive()
    service._set_state_token = lambda token: setattr(service, "_saved_token", token)

    archived = []

    def fake_archive_by_drive_id(drive_file_id):
        if drive_file_id and drive_file_id.startswith("bad"):
            raise RuntimeError(f"could not archive {drive_file_id}")
        archived.append(drive_file_id)
        return 1

    processed = []

    def fake_process_file(file_meta, result):
        if file_meta["id"].startswith("bad"):
            raise RuntimeError(f"could not process {file_meta['id']}")
        processed.append(file_meta["id"])

    service._archive_by_drive_id = fake_archive_by_drive_id
    service._process_file = fake_process_file
    service._mark_package_copy_unverified = lambda file_meta, reason: None
    service.db = _SavepointTrackingDB()

    result = service.sync_once(backfill=False)

    # The two bad events (one removed, one trashed) are isolated: everything
    # else in the same batch still lands.
    assert archived == ["good-removed", "good-trashed"]
    assert processed == ["good-file"]
    assert result["errors"] == 2
    assert result["archived"] == 2
    assert service._saved_token == "next-checkpoint"
    assert service.db.committed is True
    assert service.db.rolled_back is False
    # 5 changes total: 4 archive attempts (2 removed + 2 trashed) go through
    # _archive_by_drive_id_isolated's savepoint; the 1 real file goes through
    # _process_file_isolated's savepoint.
    assert service.db.nested_entries == 5
