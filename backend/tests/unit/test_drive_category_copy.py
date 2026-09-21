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


def test_ad_numbered_copy_doc_resolves_a_package_from_sibling_media():
    service = DriveSyncService.__new__(DriveSyncService)
    service._strategy_package_folder_cache = {}
    service._client = lambda: None
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
