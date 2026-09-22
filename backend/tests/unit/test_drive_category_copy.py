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
    marked = []
    service._refresh_folder_copy_metadata = lambda file_meta: (_ for _ in ()).throw(RuntimeError("duplicate AD 1"))
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


def test_ad_numbered_copy_metadata_marks_a_valid_pair_ambiguous_when_an_unknown_extra_exists():
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

    assert all(
        result["assets_by_drive_id"][asset_id]["copy_pairing_status"] == "ambiguous"
        for asset_id in ("feed", "stories", "extra")
    )
    assert len({result["assets_by_drive_id"][asset_id]["copy_id"] for asset_id in ("feed", "stories", "extra")}) == 3


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
