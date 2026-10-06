import pytest

import app.services.drive_sync_service as drive_sync_module
from app.services.drive_sync_service import DriveSyncService, GOOGLE_DOC_MIME


def test_copy_health_names_current_package_gaps_and_excludes_known_legacy_libraries():
    health = DriveSyncService._build_copy_health_summary([
        {
            "drive_file_id": "ready", "file_name": "AD-01-1x1.png",
            "folder_path": "Commercial Insurance / Electrical Contractors / Current",
            "soft_tags": '{"copy":{"headline":"Current headline","primary_text":"Current body"}}',
        },
        {
            "drive_file_id": "missing", "file_name": "AD-02-1x1.png",
            "folder_path": "Commercial Insurance / Electrical Contractors / Current",
            "soft_tags": '{"copy":{}}',
        },
        {
            "drive_file_id": "legacy", "file_name": "legacy.png",
            "folder_path": "Commercial Insurance - Legacy Images / Master",
            "soft_tags": '{"copy_health_exclusion":"legacy_image_library"}',
        },
        {
            "drive_file_id": "original", "file_name": "florist-original.png",
            "folder_path": "Commercial Insurance / Florist / Original User Supplied Images",
            "soft_tags": '{"copy_health_exclusion":"original_user_supplied_images"}',
        },
    ])

    assert health["current_assets"] == 2
    assert health["ready_assets"] == 1
    assert health["exception_assets"] == 1
    assert health["packages_with_exceptions"] == 1
    assert health["exceptions"][0]["package"].endswith("Electrical Contractors / Current")
    assert health["exceptions"][0]["exception_assets"][0]["file_name"] == "AD-02-1x1.png"
    assert health["excluded_assets"] == 2
    assert {item["reason"] for item in health["exclusions"]} == {
        "legacy image library", "original/source image library",
    }


def test_copy_health_does_not_exclude_any_former_path_without_explicit_metadata():
    for path in (
        "Commercial Insurance Master - Abel / Old Package",
        "Commercial Insurance - LEGACY IMAGES / Old Package",
        "Commercial Insurance / Florist / Original User Supplied Images",
    ):
        health = DriveSyncService._build_copy_health_summary([
            {"drive_file_id": path, "file_name": "old.png", "folder_path": path, "soft_tags": '{}'},
        ])
        assert health["excluded_assets"] == 0
        assert health["exception_assets"] == 1


def test_copy_health_hides_historical_path_from_exclusion_display():
    health = DriveSyncService._build_copy_health_summary([
        {
            "drive_file_id": "historical", "file_name": "old.png",
            "folder_path": "Commercial Insurance Master - Abel / Old Package",
            "soft_tags": '{"copy_health_exclusion":"historical_legacy_import"}',
        },
    ])

    assert health["exclusions"][0]["package"] == "Historical imported media (no active Drive folder)"
    assert health["exclusions"][0]["sample_drive_file_ids"] == ["historical"]
    assert health["exclusions"][0]["historical_paths"] == ["Commercial Insurance Master - Abel / Old Package"]


def test_copy_health_separates_manual_copy_assets_from_broken_drive_copy():
    health = DriveSyncService._build_copy_health_summary([
        {"drive_file_id": "manual", "file_name": "manual.png", "folder_path": "Current Package", "soft_tags": '{"copy_mode":"manual"}'},
    ])

    assert health["exception_assets"] == 0
    assert health["manual_copy_assets"] == 1


def test_copy_health_treats_unverified_and_ambiguous_copy_as_launch_exceptions():
    health = DriveSyncService._build_copy_health_summary([
        {
            "drive_file_id": "unverified", "file_name": "AD-03-1x1.png", "folder_path": "Current Package",
            "soft_tags": '{"copy":{"headline":"H","primary_text":"B"},"copy_refresh_status":"unverified","copy_pairing_status":"ambiguous"}',
        },
    ])

    reasons = health["exceptions"][0]["exception_assets"][0]["reasons"]
    assert "copy source is unverified" in reasons
    assert "ambiguous Feed/Stories pairing" in reasons


def test_copy_health_tolerates_non_object_soft_tag_json():
    health = DriveSyncService._build_copy_health_summary([
        {"drive_file_id": "scalar", "file_name": "AD-04.png", "folder_path": "Current Package", "soft_tags": '[]'},
    ])

    assert health["exception_assets"] == 1
    assert health["exceptions"][0]["exception_assets"][0]["reasons"] == ["malformed copy metadata"]


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


def test_ad_numbered_copy_doc_maps_current_pc_paint_filenames():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """GBC — Painting Contractors
AD 1 — Adjuster Question
META HEADLINE
Does Your Personal Policy Cover Job-Site Driving?
PRIMARY TEXT
Painting contractors need commercial coverage for their work vehicles.
CTA: Get My Rate Now
"""
    media = [
        {"id": "feed", "name": "PC-PAINT-01 — Adjuster Question — 1x1.png"},
        {"id": "stories", "name": "PC-PAINT-01 — Adjuster Question — 9x16.png"},
    ]

    result = service._ad_numbered_folder_copy_metadata("painting", media, document)

    assert result["assets_by_drive_id"]["feed"]["copy_id"] == "AD-01"
    assert result["assets_by_drive_id"]["stories"]["copy_id"] == "AD-01"
    assert result["assets_by_drive_id"]["feed"]["copy"]["primary_text"] == (
        "Painting contractors need commercial coverage for their work vehicles."
    )


def test_readme_handoff_is_recognized_as_a_package_manifest():
    service = DriveSyncService.__new__(DriveSyncService)
    service._package_folder_cache = {}
    service._client = lambda: None
    service.root_folder_id = "root"
    service._folder_chain_to_root = lambda folder_id: [
        {"id": "package", "name": "Painting Contractors"},
        {"id": "brand", "name": "Commercial Insurance"},
        {"id": "root", "name": "root"},
    ]
    service._list_folder_subtree = lambda folder_id: [
        {
            "id": "readme",
            "name": "READ ME — Painting Contractors FINAL Meta Handoff.md",
            "mimeType": "text/markdown",
            "_direct_parent_folder_id": "package",
        },
        {"id": "asset", "name": "PC-PAINT-01 — Adjuster Question — 1x1.png", "mimeType": "image/png"},
    ]

    assert service._is_handoff_manifest_file("READ ME — Painting Contractors FINAL Meta Handoff.md")
    assert service._is_handoff_manifest_file("Painting Contractors — Final Meta Launch Brief.md")
    assert not service._is_handoff_manifest_file("README — Painting Contractors Handoff Notes.md")
    assert service._find_package_folder({"parents": ["package"]}) == "package"


def test_markdown_handoff_file_is_a_text_source_when_mime_type_is_unknown():
    service = DriveSyncService.__new__(DriveSyncService)

    assert service._is_text_file(
        "application/octet-stream",
        "READ ME — Painting Contractors FINAL Meta Handoff.md",
    )


def test_final_painting_markdown_handoff_maps_its_numbered_assets():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """| Landing page | https://example.com/paint |
| CTA | Learn More |
### PC-PAINT-01 — Adjuster Question
| Primary text | Painting copy. |
| Headline | Painting Contractors Insurance |
| Description | Work van coverage. |
"""
    normalized = service._markdown_handoff_to_ad_copy_doc(document)
    assert service._is_painting_markdown_handoff_media(
        {"name": "PC-PAINT-01 — Adjuster Question — 1x1.png", "mimeType": "image/png"}
    )
    assert not service._is_painting_markdown_handoff_media(
        {"name": "CVI-PAINT-01-legacy-1x1.png", "mimeType": "image/png"}
    )
    assert not service._is_painting_markdown_handoff_media(
        {"name": "AD-01 — Different Package — 1x1.png", "mimeType": "image/png"}
    )
    result = service._ad_numbered_folder_copy_metadata("painting", [
        {"id": "feed", "name": "PC-PAINT-01 — Adjuster Question — 1x1.png"},
        {"id": "story", "name": "PC-PAINT-01 — Adjuster Question — 9x16.png"},
    ], normalized)

    assert result["assets_by_drive_id"]["feed"]["copy"]["primary_text"] == "Painting copy."
    assert result["assets_by_drive_id"]["story"]["copy"]["headline"] == "Painting Contractors Insurance"
    assert result["assets_by_drive_id"]["feed"]["cta"] == "LEARN_MORE"


def test_final_painting_launch_brief_maps_bold_table_fields_and_single_placements():
    service = DriveSyncService.__new__(DriveSyncService)
    document = """| **Landing page** | `https://example.com/paint` |
| **CTA** | `Learn More` |
### PC-PAINT-01 — Static
| **Primary text** | Painting static copy. |
| **Headline** | Commercial Auto for Painters |
| **Description** | Work vehicle coverage. |
### PC-PAINT-05 — Video
| **Primary text** | Painting video copy. |
| **Headline** | Protect the Van |
| **Description** | Commercial auto. |
"""

    normalized = service._markdown_handoff_to_ad_copy_doc(document)
    result = service._ad_numbered_folder_copy_metadata("painting", [
        {"id": "static", "name": "PC-PAINT-01 — Static — 4x5.png"},
        {"id": "video", "name": "PC-PAINT-05 — Video — 9x16.mp4"},
    ], normalized, allow_single_placements=True)

    assert result["assets_by_drive_id"]["static"]["aspect"] == "4x5"
    assert result["assets_by_drive_id"]["static"]["copy_pairing_status"] == "single"
    assert result["assets_by_drive_id"]["video"]["copy_pairing_status"] == "single"
    assert result["assets_by_drive_id"]["static"]["landing_page"] == "https://example.com/paint"
    assert result["assets_by_drive_id"]["video"]["cta"] == "LEARN_MORE"


def test_video_aspect_allows_a_descriptive_suffix_after_its_size():
    service = DriveSyncService.__new__(DriveSyncService)

    assert service._media_aspect({
        "name": "PC-PAINT-05 — The Adjuster Question — 9x16 Captions + Music.mp4"
    }) == "9x16"


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


def test_nested_handoff_manifest_does_not_claim_its_parent_legacy_package():
    """A new RB-style child batch must not strand legacy siblings beside it."""
    parent_manifest = {
        "id": "nested-manifest",
        "name": "ELEC-RB-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "_direct_parent_folder_id": "rb-batch",
        "_parent_folder_path": ["ELEC-RB | Personal Policy Gap"],
    }
    direct_copy_manifest = {
        "id": "copy-manifest",
        "name": "PACKAGE-HANDOFF-MANIFEST.txt",
        "mimeType": "text/plain",
        "_direct_parent_folder_id": "ad-copy",
        "_parent_folder_path": ["Ad Copy"],
    }

    assert not DriveSyncService._is_handoff_manifest_for_folder(parent_manifest, "legacy-package")
    assert DriveSyncService._is_handoff_manifest_for_folder(direct_copy_manifest, "legacy-package")


def test_parent_copy_metadata_excludes_nested_handoff_batch_media():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    legacy_feed = {
        "id": "legacy-feed", "name": "AD1-1x1.jpg", "mimeType": "image/jpeg",
        "_parent_folder_path": ["1x1 Images"],
    }
    legacy_story = {
        "id": "legacy-story", "name": "AD1-9x16.jpg", "mimeType": "image/jpeg",
        "_parent_folder_path": ["9x16 Images"],
    }
    legacy_copy = {
        "id": "legacy-copy", "name": "Legacy-Ad-Copy.txt", "mimeType": "text/plain",
        "modifiedTime": "2026-10-01T00:00:00Z", "_parent_folder_path": ["Ad Copy"],
    }
    nested_manifest = {
        "id": "nested-manifest", "name": "RB-HANDOFF-MANIFEST.txt", "mimeType": "text/plain",
        "modifiedTime": "2026-10-02T00:00:00Z", "_direct_parent_folder_id": "rb-package",
        "_parent_folder_path": ["RB Package"],
    }
    nested_feed = {
        "id": "nested-feed", "name": "RB-01-1x1.jpg", "mimeType": "image/jpeg",
        "_parent_folder_path": ["RB Package", "1x1 Images"],
    }
    service._list_folder_subtree = lambda _: [legacy_feed, legacy_story, legacy_copy, nested_manifest, nested_feed]
    service._download_text_file = lambda file_id: {
        "legacy-copy": "AD 1\nMETA HEADLINE\nLegacy headline\nPRIMARY TEXT\nLegacy primary text.\n",
        "nested-manifest": "ignored by parent",
    }[file_id]

    metadata = service._folder_copy_metadata("legacy-package")

    assert set(metadata["assets_by_drive_id"]) == {"legacy-feed", "legacy-story"}


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


def test_package_copy_source_keeps_complete_sections_when_a_legacy_ad_is_organic():
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    source = {
        "id": "legacy-copy",
        "name": "03-Electrical-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:42:21Z",
    }
    feed = {"id": "ad1-feed", "name": "03-ELEC-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    story = {"id": "ad1-story", "name": "03-ELEC-AD1-Identity-9x16.jpg", "mimeType": "image/jpeg"}
    organic = {"id": "ad5-feed", "name": "03-ELEC-AD5-Trojan-1x1.jpg", "mimeType": "image/jpeg"}
    document = """AD 1 — Identity
META HEADLINE
Electrician headline
PRIMARY TEXT
Electrician body

AD 5 — Trojan
PRIMARY TEXT
Organic body with no launch headline.
"""
    service._list_folder_subtree = lambda folder_id: [source, feed, story, organic]
    service._download_text_file = lambda file_id: document

    result = service._folder_copy_metadata("electrical-package")

    assert set(result["assets_by_drive_id"]) == {"ad1-feed", "ad1-story"}
    assert result["assets_by_drive_id"]["ad1-feed"]["copy_source_drive_file_id"] == "legacy-copy"
    assert result["assets_by_drive_id"]["ad1-feed"]["copy"]["headline"] == "Electrician headline"


def test_partial_legacy_copy_supplements_a_complete_winner_copy_for_disjoint_media():
    """A valid canonical AD section must not be lost to an unrelated winner batch."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_metadata_cache = {}
    legacy = {
        "id": "legacy-copy",
        "name": "03-Electrical-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:42:21Z",
    }
    winner = {
        "id": "winner-copy",
        "name": "03-Electrical-Winner-Variations-Ad-Copy.txt",
        "mimeType": "text/plain",
        "modifiedTime": "2026-09-22T10:50:00Z",
    }
    legacy_feed = {"id": "legacy-feed", "name": "03-ELEC-AD1-Identity-1x1.jpg", "mimeType": "image/jpeg"}
    legacy_story = {"id": "legacy-story", "name": "03-ELEC-AD1-Identity-9x16.jpg", "mimeType": "image/jpeg"}
    winner_feed = {"id": "winner-feed", "name": "03-ELEC-AD2-Winner-1x1.jpg", "mimeType": "image/jpeg"}
    winner_story = {"id": "winner-story", "name": "03-ELEC-AD2-Winner-9x16.jpg", "mimeType": "image/jpeg"}
    documents = {
        "legacy-copy": """AD 1 — Identity
META HEADLINE
Legacy headline
PRIMARY TEXT
Legacy body

AD 5 — Trojan
PRIMARY TEXT
Organic body with no launch headline.
""",
        "winner-copy": """AD 2 — Winner
Headline: Winner headline
==========
Winner body
==========
""",
    }
    service._list_folder_subtree = lambda folder_id: [legacy, winner, legacy_feed, legacy_story, winner_feed, winner_story]
    service._download_text_file = lambda file_id: documents[file_id]

    result = service._folder_copy_metadata("electrical-package")

    assert result["assets_by_drive_id"]["legacy-feed"]["copy"]["headline"] == "Legacy headline"
    assert result["assets_by_drive_id"]["legacy-feed"]["copy_source_drive_file_id"] == "legacy-copy"
    assert result["assets_by_drive_id"]["winner-feed"]["copy"]["headline"] == "Winner headline"
    assert result["assets_by_drive_id"]["winner-feed"]["copy_source_drive_file_id"] == "winner-copy"


def test_direct_legacy_package_layout_is_not_rejected_as_a_broad_container():
    service = DriveSyncService.__new__(DriveSyncService)
    package_files = [
        {"_parent_folder_path": ["Ad Copy"]},
        {"_parent_folder_path": ["1x1 Images"]},
        {"_parent_folder_path": ["9x16 Images"]},
    ]

    assert service._has_direct_copy_package_layout(package_files) is True
    assert service._has_direct_copy_package_layout([
        {"_parent_folder_path": ["Electrical Contractors", "Ad Copy"]},
        {"_parent_folder_path": ["Electrical Contractors", "1x1 Images"]},
        {"_parent_folder_path": ["Electrical Contractors", "9x16 Images"]},
    ]) is False


def test_strategy_resolver_accepts_legacy_package_when_empty_placement_folders_remain():
    """A winner batch may move all media out of the legacy 1x1/9x16 folders."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._strategy_package_folder_cache = {}
    service._direct_legacy_layout_cache = {}
    service.root_folder_id = "root"
    service._folder_chain_to_root = lambda folder_id: [
        {"id": "roofing", "name": "06 - Roofing Contractors"},
        {"id": "root", "name": "Commercial Van Insurance"},
    ]

    class FakeFiles:
        def get(self, **kwargs):
            class Request:
                def execute(self):
                    return {
                        "id": "winner-batch",
                        "parents": ["roofing"],
                    } if kwargs["fileId"] == "winner-batch" else {
                        "id": "placement",
                        "parents": ["winner-batch"],
                    }
            return Request()

        def list(self, **kwargs):
            class Request:
                def execute(self):
                    return {"files": [
                        {"name": "Ad Copy", "mimeType": "application/vnd.google-apps.folder"},
                        {"name": "1x1 Images", "mimeType": "application/vnd.google-apps.folder"},
                        {"name": "9x16 Images", "mimeType": "application/vnd.google-apps.folder"},
                    ]}
            return Request()

    class FakeDrive:
        def files(self):
            return FakeFiles()

    service._client = lambda: FakeDrive()
    service._list_folder_subtree = lambda folder_id: (
        [{"id": "winner-media", "name": "06-ROOF-AD1-PhoneCall-1x1.jpg", "mimeType": "image/jpeg"}]
        if folder_id in {"placement", "winner-batch"}
        else [
            {"id": "copy", "name": "06-Roofing-Contractors-Ad-Copy.txt", "mimeType": "text/plain",
             "_parent_folder_path": ["Ad Copy"]},
            {"id": "winner-media", "name": "06-ROOF-AD1-PhoneCall-1x1.jpg", "mimeType": "image/jpeg",
             "_parent_folder_path": ["Winner Variations - v2", "Feed"]},
        ]
    )
    service._download_text_file = lambda file_id: """AD 1 — Phone Call
META HEADLINE
Coverage headline
PRIMARY TEXT
Coverage primary text.
"""

    assert service._find_strategy_package_folder({"parents": ["placement"]}) == "roofing"


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
    service.get_copy_health_summary = lambda: {
        "exception_assets": 0, "packages_with_exceptions": 0, "exceptions": [],
    }

    class Result:
        def scalar(self):
            return True

        def first(self):
            return None  # no saved retry ledger yet

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


def _sync_failure_service(monkeypatch, *, page_token, lock_acquired=True):
    service = DriveSyncService.__new__(DriveSyncService)
    service._copy_packages_refreshed_in_sync = set()
    service._validate_tables = lambda: None
    service._client = lambda: object()
    service._get_state_token = lambda: page_token
    service._get_start_page_token = lambda drive: (_ for _ in ()).throw(RuntimeError("Drive unavailable"))
    service._initial_folder_walk = lambda drive: (_ for _ in ()).throw(RuntimeError("Drive unavailable"))
    service.blocked = []
    service.alerts = []
    service._persist_global_copy_block = lambda reason: service.blocked.append(reason)
    monkeypatch.setattr(drive_sync_module.slack_service, "send_drive_sync_alert", lambda *args: service.alerts.append(args))

    class Result:
        def scalar(self):
            return lock_acquired

    class FakeDB:
        def execute(self, *args, **kwargs):
            return Result()
        def rollback(self):
            pass

    service.db = FakeDB()
    return service


def test_full_walk_sync_failure_keeps_copy_matches_blocked_after_rollback(monkeypatch):
    service = _sync_failure_service(monkeypatch, page_token=None)

    with pytest.raises(RuntimeError, match="Drive unavailable"):
        service.sync_once()

    assert service.blocked == ["Global Drive sync failed before completion: Drive unavailable"]


def test_backfill_sync_failure_keeps_copy_matches_blocked(monkeypatch):
    service = _sync_failure_service(monkeypatch, page_token="tok")

    with pytest.raises(RuntimeError, match="Drive unavailable"):
        service.sync_once(backfill=True)

    assert len(service.blocked) == 1


def test_incremental_sync_failure_does_not_block_copy_matches(monkeypatch):
    # Nothing would clear a block set here: unchanged copy docs are not revisited.
    service = _sync_failure_service(monkeypatch, page_token="tok")
    service._client = lambda: type("D", (), {"changes": lambda self: (_ for _ in ()).throw(RuntimeError("Drive unavailable"))})()

    with pytest.raises(RuntimeError, match="Drive unavailable"):
        service.sync_once()

    assert service.blocked == []


def test_folder_scoped_sync_failure_does_not_block_copy_matches(monkeypatch):
    service = _sync_failure_service(monkeypatch, page_token=None)

    service._changed_folder_walk = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Drive unavailable"))

    with pytest.raises(RuntimeError, match="Drive unavailable"):
        service.sync_once(folder_id="folder-1")

    assert service.blocked == []


def test_concurrent_sync_409_does_not_block_copy_matches(monkeypatch):
    service = _sync_failure_service(monkeypatch, page_token=None, lock_acquired=False)

    with pytest.raises(drive_sync_module.HTTPException) as exc_info:
        service.sync_once()

    assert exc_info.value.status_code == 409
    assert service.blocked == []
    assert service.alerts == []  # lock contention is not a failure worth paging for


def test_persist_global_copy_block_uses_independent_session_and_swallows_failure(monkeypatch):
    events = []

    class FakeSession:
        def __init__(self, bind=None):
            events.append(("session", bind))
        def begin(self):
            events.append("begin")
            return self
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def close(self):
            events.append("close")

    class Boom(DriveSyncService):
        def __init__(self, db):
            self.db = db
        def _mark_all_copy_assets_unverified(self, reason):
            events.append(("mark", reason))
            raise RuntimeError("secondary failure")

    monkeypatch.setattr(drive_sync_module, "Session", FakeSession)
    monkeypatch.setattr(drive_sync_module, "DriveSyncService", Boom)

    service = DriveSyncService.__new__(DriveSyncService)
    service.db = type("DB", (), {"get_bind": lambda self: "engine"})()

    service._persist_global_copy_block("why")  # must not raise

    assert events == [("session", "engine"), "begin", ("mark", "why"), "close"]


def test_global_copy_refresh_failure_keeps_copy_matches_blocked_after_rollback():
    service = DriveSyncService.__new__(DriveSyncService)
    service._validate_tables = lambda: None
    service._client = lambda: object()
    service._package_folder_cache = {}
    service._strategy_package_folder_cache = {}
    service._folder_metadata_cache = {}
    service._mark_all_copy_assets_unverified = lambda reason: None
    service._initial_folder_walk = lambda drive: (_ for _ in ()).throw(RuntimeError("listing failed"))
    blocked = []
    service._persist_global_copy_block = lambda reason: blocked.append(reason)

    class Result:
        def scalar(self):
            return True

    class FakeDB:
        def execute(self, *args, **kwargs):
            return Result()
        def rollback(self):
            pass

    service.db = FakeDB()

    with pytest.raises(RuntimeError, match="listing failed"):
        service.refresh_copy_metadata()

    assert blocked == ["Global Drive copy refresh failed before completion: listing failed"]


def test_full_copy_refresh_isolates_package_failures_with_savepoints():
    """One bad package must not roll back successful copy matches elsewhere."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._validate_tables = lambda: None
    service._client = lambda: object()
    service._package_folder_cache = {}
    service._strategy_package_folder_cache = {}
    service._folder_metadata_cache = {}
    service._mark_all_copy_assets_unverified = lambda reason: None
    service._initial_folder_walk = lambda drive: [
        {"id": "bad-doc", "name": "Bad Strategy.md", "mimeType": "text/markdown"},
        {"id": "good-doc", "name": "Good Strategy.md", "mimeType": "text/markdown"},
    ]
    service._is_text_file = lambda mime_type, name: True
    service._download_text_file = lambda file_id: "recognized copy"
    service._looks_like_strategy_copy_doc = lambda body: True
    service._looks_like_category_copy_doc = lambda body: False
    service._looks_like_ad_copy_doc = lambda body: False
    service._is_handoff_manifest_file = lambda name: False
    service._metadata_folder_for_copy_document = lambda file_meta: {
        "bad-doc": "bad-package", "good-doc": "good-package"
    }[file_meta["id"]]
    service._refresh_folder_copy_metadata = lambda file_meta, metadata_folder: (
        (_ for _ in ()).throw(RuntimeError("malformed package"))
        if metadata_folder == "bad-package" else 3
    )
    marked = []
    service._mark_package_copy_unverified = lambda file_meta, reason: marked.append(file_meta["id"])
    service._attach_copy_health = lambda result: result

    class Result:
        def __init__(self, scalar_value):
            self.scalar_value = scalar_value

        def scalar(self):
            return self.scalar_value

    class Savepoint:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class FakeDB:
        committed = False

        def execute(self, statement, *args, **kwargs):
            sql = str(statement)
            if "pg_try_advisory_xact_lock" in sql:
                return Result(True)
            return Result(0)

        def begin_nested(self):
            return Savepoint()

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

    service.db = FakeDB()
    result = service.refresh_copy_metadata()

    assert result["errors"] == 1
    assert result["updated"] == 3
    assert marked == ["bad-doc"]
    assert service.db.committed is True


def test_refresh_unverified_copy_assets_retries_a_bounded_targeted_batch():
    service = DriveSyncService.__new__(DriveSyncService)
    calls = []

    class Rows:
        def all(self):
            return [
                ("old-unverified", '{"copy_refresh_status":"unverified"}'),
                ("new-unverified", '{"copy_refresh_status":"unverified"}'),
            ]

    class FakeDB:
        def execute(self, statement, *args, **kwargs):
            return Rows()

    service.db = FakeDB()
    service.refresh_copy_metadata_for_drive_files = lambda ids: calls.append(ids) or {
        "processed": 2, "updated": 2, "errors": 0, "unverified": 0
    }

    result = service.refresh_unverified_copy_assets(max_assets=2)

    assert calls == [["old-unverified", "new-unverified"]]
    assert result["auto_repair"] is True
    assert result["auto_repair_candidates"] == 2


def test_selected_media_refresh_failure_marks_media_and_package_unverified():
    """A source-less picker row must fail closed if its package cannot resolve."""
    service = DriveSyncService.__new__(DriveSyncService)
    service._validate_tables = lambda: None
    service._find_package_folder = lambda file_meta: (_ for _ in ()).throw(RuntimeError("broken package"))
    service._find_strategy_package_folder = lambda file_meta: None
    service._attach_copy_health = lambda result: result
    marked_media = []
    marked_packages = []
    service._mark_drive_media_unverified = lambda drive_file_id, reason: marked_media.append((drive_file_id, reason))
    service._mark_package_copy_unverified = lambda file_meta, reason: marked_packages.append((file_meta["id"], reason))

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

    class FakeFiles:
        def get(self, **kwargs):
            return self
        def execute(self):
            return {"id": "media-1", "name": "ad-1.png", "mimeType": "image/png", "parents": ["folder"]}

    class FakeDrive:
        def files(self):
            return FakeFiles()

    service.db = FakeDB()
    service._client = lambda: FakeDrive()
    result = service.refresh_copy_metadata_for_drive_files(["media-1"])

    assert result["errors"] == 1
    assert marked_media and marked_media[0][0] == "media-1"
    assert marked_packages and marked_packages[0][0] == "media-1"
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
        def refresh_copy_metadata_for_drive_files(self, drive_file_ids):
            calls.append(("refresh_files", drive_file_ids))
            return {"processed": 4}
        def refresh_unverified_copy_assets(self, max_assets):
            calls.append(("repair_unverified", max_assets))
            return {"processed": 5, "updated": 5, "errors": 0, "unverified": 0}
        def get_copy_health_summary(self):
            calls.append(("copy_health", {}))
            return {
                "current_assets": 1, "ready_assets": 1, "exception_assets": 0,
                "packages_with_exceptions": 0, "exceptions": [], "excluded_assets": 0, "exclusions": [],
            }

    monkeypatch.setattr(route_module, "DriveSyncService", FakeService)
    db = object()
    assert route_module.sync_drive_assets_now(backfill=True, db=db, _current_user=object())["processed"] == 1
    assert calls[-1] == ("sync_once", {"backfill": True})

    assert route_module.refresh_drive_copy_metadata(
        payload=DriveCopyRefreshRequest(source_file_ids=["copy-doc"]), db=db, _current_user=object()
    )["processed"] == 3
    assert calls[-1] == ("refresh_sources", ["copy-doc"])

    assert route_module.refresh_drive_copy_metadata(
        payload=DriveCopyRefreshRequest(drive_file_ids=["creative-file"]), db=db, _current_user=object()
    )["processed"] == 4
    assert calls[-1] == ("refresh_files", ["creative-file"])

    assert route_module.refresh_drive_copy_metadata(
        payload=DriveCopyRefreshRequest(), db=db, _current_user=object()
    )["processed"] == 2
    assert calls[-1] == ("refresh_all", {})

    assert route_module.refresh_drive_copy_metadata(
        payload=DriveCopyRefreshRequest(skip_full_refresh=True), db=db, _current_user=object()
    )["processed"] == 5
    assert calls[-1] == ("repair_unverified", 50)

    class FakeResponse:
        headers = {}

    monkeypatch.setattr(route_module, "_table_exists", lambda db, table_name: True)
    health = route_module.get_drive_copy_health(response=FakeResponse(), db=db, _current_user=object())
    assert health["exception_assets"] == 0
    assert calls[-1] == ("copy_health", {})


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

        def files(self):
            # The removed-change handler confirms with files.get: these files really are trashed.
            return _Drive(meta={"id": "x", "trashed": True})

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
    service.get_copy_health_summary = lambda: {
        "exception_assets": 0, "packages_with_exceptions": 0, "exceptions": [],
    }
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
    # 5 per-item savepoints, plus one to load the retry ledger (the save is skipped when unchanged).
    assert service.db.nested_entries == 6


def test_incremental_sync_walks_only_a_new_folder_subtree():
    """A newly added package folder must reveal its existing media without a root walk."""
    service = DriveSyncService.__new__(DriveSyncService)
    service.root_folder_id = "sync-root"
    service._copy_packages_refreshed_in_sync = set()
    service._validate_tables = lambda: None
    service._get_state_token = lambda: "existing-checkpoint"
    service._folder_chain_to_root = lambda folder_id: (
        [{"id": folder_id, "name": "New Package"}, {"id": "sync-root", "name": "Root"}]
        if folder_id == "new-folder" else None
    )

    class FakeChangesRequest:
        def execute(self):
            return {
                "changes": [{
                    "file": {
                        "id": "new-folder",
                        "name": "New Package",
                        "mimeType": "application/vnd.google-apps.folder",
                    },
                }],
                "nextPageToken": None,
                "newStartPageToken": "next-checkpoint",
            }

    class FakeFilesRequest:
        def __init__(self, folder_id):
            self.folder_id = folder_id

        def execute(self):
            assert self.folder_id == "new-folder"
            return {
                "files": [
                    {"id": "feed-video", "name": "feed.mp4", "mimeType": "video/mp4"},
                    {"id": "stories-video", "name": "stories.mp4", "mimeType": "video/mp4"},
                ],
                "nextPageToken": None,
            }

    class FakeChanges:
        def list(self, **kwargs):
            return FakeChangesRequest()

    class FakeFiles:
        def list(self, **kwargs):
            return FakeFilesRequest(kwargs["q"].split("'")[1])

    class FakeDrive:
        def changes(self):
            return FakeChanges()

        def files(self):
            return FakeFiles()

    service._client = lambda: FakeDrive()
    service._set_state_token = lambda token: setattr(service, "_saved_token", token)
    processed = []
    service._process_file = lambda file_meta, result: processed.append(file_meta["id"])
    service._mark_package_copy_unverified = lambda file_meta, reason: None
    service.get_copy_health_summary = lambda: {
        "exception_assets": 0, "packages_with_exceptions": 0, "exceptions": [],
    }
    service.db = _SavepointTrackingDB()

    result = service.sync_once(backfill=False)

    assert processed == ["feed-video", "stories-video"]
    assert result["processed"] == 3  # folder event + its two discovered children
    assert result["errors"] == 0
    assert service._saved_token == "next-checkpoint"


def test_copy_refresh_backfill_imports_only_new_supported_media_and_keeps_path_caches():
    service = DriveSyncService.__new__(DriveSyncService)
    service._package_folder_cache = {"a": 1}
    service._strategy_package_folder_cache = {"b": 2}
    service._folder_metadata_cache = {"c": 3}
    service._list_folder_subtree = lambda folder: [
        {"id": "known", "name": "known-1x1.png", "mimeType": "image/png"},
        {"id": "new", "name": "new-9x16.png", "mimeType": "image/png"},
        {"id": "doc", "name": "copy.txt", "mimeType": "text/plain"},
    ]
    service._is_supported_media = lambda mime, name: mime.startswith("image/")
    imported = []
    service._process_file_isolated = lambda file_meta, result: imported.append(file_meta["id"])

    class Result:
        def all(self):
            return [("known",)]

    statements = []

    class FakeDB:
        def execute(self, statement, *args, **kwargs):
            statements.append(str(statement))
            return Result()

    service.db = FakeDB()
    result = {"processed": 0}

    service._backfill_package_media_for_copy_refresh("pkg", result)

    # Archived rows must count as known, or they are re-imported every refresh.
    assert "archived" not in statements[0].lower()

    assert imported == ["new"]
    assert result["processed"] == 1
    # Importing a DB row cannot alter Drive folder ancestry. Preserving these
    # cached path resolutions prevents one picker repair from recursively
    # walking the same Drive package once per selected creative.
    assert service._package_folder_cache == {"a": 1}
    assert service._strategy_package_folder_cache == {"b": 2}
    assert service._folder_metadata_cache == {"c": 3}


def test_reconcile_imports_only_media_missing_from_the_library():
    service = DriveSyncService.__new__(DriveSyncService)
    service._copy_packages_refreshed_in_sync = set()
    service._validate_tables = lambda: None
    service._client = lambda: object()
    service._initial_folder_walk = lambda drive: [
        {"id": "in-db", "name": "a.png", "mimeType": "image/png"},
        {"id": "archived-in-db", "name": "b.png", "mimeType": "image/png"},
        {"id": "gone", "name": "c.png", "mimeType": "image/png"},
        {"id": "doc", "name": "copy.txt", "mimeType": "text/plain"},
    ]
    service._is_supported_media = lambda mime, name: mime.startswith("image/")
    imported = []
    service._process_file_isolated = lambda file_meta, result: imported.append(file_meta["id"])
    service._ledger_flush = lambda: None

    class Result:
        def __init__(self, rows=None, scalar=None):
            self.rows, self._scalar = rows, scalar
        def all(self):
            return self.rows
        def scalar(self):
            return self._scalar

    class FakeDB:
        committed = False
        def execute(self, statement, *args, **kwargs):
            if "pg_try_advisory_xact_lock" in str(statement):
                return Result(scalar=True)
            return Result(rows=[("in-db",), ("archived-in-db",)])
        def commit(self):
            self.committed = True
        def rollback(self):
            pass

    service.db = FakeDB()

    result = service.reconcile_missing_media()

    assert imported == ["gone"]
    assert result["missing"] == 1 and result["ran"] is True
    assert service.db.committed is True


def test_reconcile_does_nothing_when_another_sync_holds_the_lock():
    service = DriveSyncService.__new__(DriveSyncService)
    service._copy_packages_refreshed_in_sync = set()
    service._validate_tables = lambda: None

    class Result:
        def scalar(self):
            return False

    class FakeDB:
        def execute(self, *args, **kwargs):
            return Result()

    service.db = FakeDB()

    assert service.reconcile_missing_media()["ran"] is False


# ---- change-feed `removed` handling, lookup failures, unmatched brands --------------------

class _Resp:
    def __init__(self, status):
        self.status = status
        self.reason = "test"


def _http_error(status):
    from googleapiclient.errors import HttpError

    return HttpError(_Resp(status), b"{}")


class _Drive:
    def __init__(self, meta=None, error=None):
        self._meta, self._error = meta, error

    def files(self):
        return self

    def get(self, **kwargs):
        return self

    def execute(self):
        if self._error:
            raise self._error
        return self._meta


def _removed_service(monkeypatch):
    service = DriveSyncService.__new__(DriveSyncService)
    service.archived, service.processed = [], []
    service._archive_by_drive_id_isolated = lambda fid, result: service.archived.append(fid) or 1
    service._process_file_isolated = lambda meta, result: service.processed.append(meta["id"])
    return service


def test_removed_change_for_a_file_that_still_exists_is_refreshed_not_archived(monkeypatch):
    service = _removed_service(monkeypatch)

    archived = service._handle_removed_change(_Drive(meta={"id": "f1", "name": "a.png", "mimeType": "image/png"}), "f1", {})

    assert archived == 0 and service.archived == [] and service.processed == ["f1"]


def test_removed_change_for_an_unreadable_file_is_parked_for_a_second_check_not_archived(monkeypatch):
    service = _removed_service(monkeypatch)
    service._ledger_note_failure = lambda *a, **k: service.__dict__.setdefault("noted", []).append(a[0])
    service._retry_state = lambda: {"processed": set()}

    archived = service._handle_removed_change(_Drive(error=_http_error(404)), "f1", {"errors": 0})

    assert archived == 0 and service.archived == [] and service.noted == ["f1"]


def test_removed_change_for_a_trashed_file_is_archived(monkeypatch):
    service = _removed_service(monkeypatch)

    service._handle_removed_change(_Drive(meta={"id": "f1", "trashed": True}), "f1", {})

    assert service.archived == ["f1"]


def test_removed_change_for_a_folder_is_ignored(monkeypatch):
    service = _removed_service(monkeypatch)

    service._handle_removed_change(_Drive(meta={"id": "d1", "mimeType": "application/vnd.google-apps.folder"}), "d1", {})

    assert service.archived == [] and service.processed == []


def test_failed_parent_lookup_is_recorded_so_the_file_is_retried_not_skipped():
    service = DriveSyncService.__new__(DriveSyncService)
    service._path_cache = {}
    service.root_folder_id = "root"
    service._client = lambda: type("D", (), {
        "files": lambda self: type("F", (), {
            "get": lambda s, **k: type("E", (), {"execute": lambda s2: (_ for _ in ()).throw(_http_error(500))})(),
            "list": lambda s, **k: type("E", (), {"execute": lambda s2: {"files": []}})(),
        })(),
    })()

    assert service._folder_chain_to_root("folder-x") is None
    assert "folder-x" in service._chain_lookup_failures


def test_run_log_names_unmatched_brand_folders_without_calling_it_a_failure(monkeypatch):
    import app.services.drive_sync_run_log as run_log

    captured = {}

    class Sess:
        def __init__(self, bind=None): pass
        def execute(self, stmt, params): captured.update(params)
        def commit(self): pass
        def close(self): pass

    monkeypatch.setattr(run_log, "Session", Sess)
    db = type("DB", (), {"get_bind": lambda self: object()})()

    run_log._write_row(db, "incremental", __import__("datetime").datetime.now(), "ok",
                       {"unmatched_brand": 3, "unmatched_brand_names": ["Odd Folder"]}, None)

    assert "3 file(s) skipped" in captured["error_summary"] and "Odd Folder" in captured["error_summary"]


def _process_file_service(chain_failures):
    service = DriveSyncService.__new__(DriveSyncService)
    service._backfill_mode = False
    service._chain_lookup_failures = set(chain_failures)
    service._resolve_drive_path = lambda file_meta: None

    class Mappings:
        def first(self):
            return None

    class Result:
        def mappings(self):
            return Mappings()

    class FakeDB:
        def execute(self, *args, **kwargs):
            return Result()

    service.db = FakeDB()
    return service


_MEDIA = {"id": "m1", "name": "ad-01-1x1.png", "mimeType": "image/png", "parents": ["folder-x"],
          "modifiedTime": "2026-10-01T09:00:00.000Z"}


def test_media_whose_folder_lookup_failed_raises_so_the_retry_ledger_keeps_it():
    service = _process_file_service({"folder-x"})

    with pytest.raises(RuntimeError, match="retried automatically"):
        service._process_file(dict(_MEDIA), {"skipped": 0, "unmatched_brand": 0})


def test_media_genuinely_outside_the_library_is_still_skipped_quietly():
    service = _process_file_service(set())
    result = {"skipped": 0, "unmatched_brand": 0}

    service._process_file(dict(_MEDIA), result)

    assert result["skipped"] == 1


def _http_error_with_reason(status, reason):
    import json as _json
    from googleapiclient.errors import HttpError

    body = _json.dumps({"error": {"errors": [{"reason": reason}]}}).encode()
    return HttpError(_Resp(status), body)


def test_a_rate_limit_403_is_never_treated_as_a_deleted_file(monkeypatch):
    service = _removed_service(monkeypatch)
    service._ledger_note_failure = lambda *a, **k: service.__dict__.setdefault("noted", []).append(a[0])
    service._retry_state = lambda: {"processed": set()}
    result = {"errors": 0}

    archived = service._handle_removed_change(
        _Drive(error=_http_error_with_reason(403, "rateLimitExceeded")), "f1", result
    )

    assert archived == 0 and service.archived == [] and service.noted == ["f1"] and result["errors"] == 1


def test_a_genuine_forbidden_403_is_parked_not_archived_on_one_look(monkeypatch):
    service = _removed_service(monkeypatch)
    service._ledger_note_failure = lambda *a, **k: service.__dict__.setdefault("noted", []).append(a[0])
    service._retry_state = lambda: {"processed": set()}

    service._handle_removed_change(_Drive(error=_http_error_with_reason(403, "forbidden")), "f1", {"errors": 0})

    assert service.archived == [] and service.noted == ["f1"]


def test_a_persistently_erroring_removed_id_is_parked_so_it_cannot_block_the_batch(monkeypatch):
    service = _removed_service(monkeypatch)
    service._ledger_note_failure = lambda *a, **k: service.__dict__.setdefault("noted", []).append(a[0])
    service._retry_state = lambda: {"processed": set()}

    archived = service._handle_removed_change(_Drive(error=_http_error(500)), "f1", {"errors": 0})

    assert archived == 0 and service.noted == ["f1"]  # no exception: the sync carries on


def test_a_hard_404_on_the_parent_lookup_is_not_flagged_for_endless_retries():
    service = DriveSyncService.__new__(DriveSyncService)
    service._path_cache = {}
    service.root_folder_id = "root"
    service._client = lambda: type("D", (), {
        "files": lambda self: type("F", (), {
            "get": lambda s, **k: type("E", (), {"execute": lambda s2: (_ for _ in ()).throw(_http_error(404))})(),
            "list": lambda s, **k: type("E", (), {"execute": lambda s2: {"files": []}})(),
        })(),
    })()

    assert service._folder_chain_to_root("gone-folder") is None
    assert "gone-folder" not in service.__dict__.get("_chain_lookup_failures", set())


def test_a_file_moved_out_of_the_library_has_its_stale_row_archived():
    service = _process_file_service(set())
    service.root_folder_id = "root"
    service._chain_outside_library = {"folder-x"}
    existing = {"id": "row-1", "drive_modified_time": None, "soft_tags": None}
    executed = []

    class Mappings:
        def first(self):
            return existing

    class Result:
        def mappings(self):
            return Mappings()

    class FakeDB:
        def execute(self, statement, params=None):
            executed.append((str(statement), params))
            return Result()

    service.db = FakeDB()
    result = {"skipped": 0, "unmatched_brand": 0, "archived": 0}

    service._process_file(dict(_MEDIA), result)

    assert result["archived"] == 1 and any("archived = TRUE" in sql for sql, _ in executed)


def test_a_corrupt_saved_ledger_resets_instead_of_freezing_all_future_failure_tracking():
    service = DriveSyncService.__new__(DriveSyncService)

    class Row:
        def __getitem__(self, i):
            return "{not json"

    class Result:
        def first(self):
            return Row()

    class Savepoint:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    class FakeDB:
        def begin_nested(self): return Savepoint()
        def execute(self, *a, **k): return Result()

    service.db = FakeDB()

    assert service._ledger() == {}
    assert service._retry_state()["load_ok"] is True


def test_a_non_http_error_from_the_check_also_cannot_block_the_batch(monkeypatch):
    service = _removed_service(monkeypatch)
    service._ledger_note_failure = lambda *a, **k: service.__dict__.setdefault("noted", []).append(a[0])
    service._retry_state = lambda: {"processed": set()}

    archived = service._handle_removed_change(_Drive(error=TimeoutError("socket timed out")), "f1", {"errors": 0})

    assert archived == 0 and service.noted == ["f1"]


def test_outside_library_archives_stop_at_the_circuit_breaker():
    import app.services.drive_sync_service as module

    service = _process_file_service(set())
    service.root_folder_id = "root"
    service._chain_outside_library = {"folder-x"}
    service._outside_archives = module.OUTSIDE_LIBRARY_ARCHIVE_CAP
    existing = {"id": "row-1", "drive_modified_time": None, "soft_tags": None}

    class Mappings:
        def first(self):
            return existing

    class Result:
        def mappings(self):
            return Mappings()

    executed = []

    class FakeDB:
        def execute(self, statement, params=None):
            executed.append(str(statement))
            return Result()

    service.db = FakeDB()
    result = {"skipped": 0, "unmatched_brand": 0, "archived": 0}

    service._process_file(dict(_MEDIA), result)

    assert result["archived"] == 0 and result["skipped"] == 1
    assert not any("archived = TRUE" in sql for sql in executed)


def test_no_root_folder_configured_never_archives_as_outside():
    service = _process_file_service(set())
    service.root_folder_id = ""
    service._chain_outside_library = {"folder-x"}
    existing = {"id": "row-1", "drive_modified_time": None, "soft_tags": None}

    class Mappings:
        def first(self):
            return existing

    class Result:
        def mappings(self):
            return Mappings()

    class FakeDB:
        def execute(self, statement, params=None):
            assert "archived = TRUE" not in str(statement)
            return Result()

    service.db = FakeDB()
    result = {"skipped": 0, "unmatched_brand": 0, "archived": 0}

    service._process_file(dict(_MEDIA), result)

    assert result["archived"] == 0 and result["skipped"] == 1


class _BrandRows:
    def __init__(self, names):
        self._rows = [{"id": f"id-{i}", "name": n} for i, n in enumerate(names)]

    def execute(self, *_a, **_k):
        rows = self._rows

        class _R:
            def mappings(self):
                return self

            def all(self):
                return rows

        return _R()


def _brand_matcher(*names):
    service = DriveSyncService.__new__(DriveSyncService)
    service.db = _BrandRows(names)
    return service._match_brand_id


def test_brand_match_exact_and_alias_and_typo():
    match = _brand_matcher("Commercial Insurance", "Resource Help Online - RHO")
    assert match("Commercial Insurance") == "id-0"
    assert match("commercial   insurance") == "id-0"
    assert match("RHO") == "id-1"
    assert match("Resource Help Online") == "id-1"
    assert match("Commercial Insurence") == "id-0"  # one-letter typo still lands


def test_brand_match_refuses_lookalike_folders():
    match = _brand_matcher("Commercial Insurance", "Resource Help Online - RHO")
    assert match("Commercial Insurance - Legacy") is None
    assert match("Commercial Auto") is None
    assert match("Auto Insurance") is None
    assert match("") is None


def test_brand_match_refuses_ambiguous_fuzzy_and_ambiguous_alias():
    assert _brand_matcher("Acme Home Services", "Acme Home Service")("Acme Home Servce") is None
    assert _brand_matcher("Alpha - RHO", "Beta - RHO")("RHO") is None


def test_ledger_save_failure_is_counted_as_a_run_error():
    service = DriveSyncService.__new__(DriveSyncService)
    service._retry_state = lambda: {"ledger": {"x": {}}, "load_ok": True}
    service._ledger_flush = lambda: False
    result = {"errors": 0}
    service._ledger_flush_or_flag(result)
    assert result["errors"] == 1 and result["ledger_unsaved"] is True

    ok = {"errors": 0}
    service._ledger_flush = lambda: True
    service._ledger_flush_or_flag(ok)
    assert ok["errors"] == 0


def test_shortcuts_are_counted_and_named_not_silently_skipped():
    service = DriveSyncService.__new__(DriveSyncService)
    result = {"skipped": 0}
    service._process_file(
        {"id": "s1", "name": "Link to hero.mp4", "mimeType": "application/vnd.google-apps.shortcut"}, result,
    )
    assert result["shortcuts_skipped"] == 1 and result["shortcut_names"] == ["Link to hero.mp4"]
    assert result["skipped"] == 1


def test_changed_folder_walk_raises_on_lookup_failure_but_not_when_outside_library():
    from app.services.drive_sync_service import FolderLookupFailed

    service = DriveSyncService.__new__(DriveSyncService)
    service._folder_chain_to_root = lambda folder_id: None
    service._chain_lookup_failures = {"f-fail"}
    with pytest.raises(FolderLookupFailed):
        service._changed_folder_walk(None, "f-fail")
    assert service._changed_folder_walk(None, "f-elsewhere") == []


def _ghost_fixture(candidates, previous):
    from googleapiclient.errors import HttpError

    class _Resp:
        def __init__(self, status):
            self.status = status
            self.reason = "x"

    class _Files:
        def get(self, fileId, **_k):
            class _Call:
                def execute(self_inner):
                    if fileId == "trashed":
                        return {"id": fileId, "trashed": True}
                    if fileId == "live":
                        return {"id": fileId, "trashed": False}
                    if fileId == "flaky":
                        raise HttpError(_Resp(500), b"{}")
                    raise HttpError(_Resp(404), b'{"error": {"errors": [{"reason": "notFound"}]}}')

            return _Call()

    class _Drive:
        def files(self):
            return _Files()

    saved = {}

    class _DB:
        def execute(self, stmt, params=None):
            sql = str(stmt)

            class _R:
                def all(self_inner):
                    return [(c,) for c in candidates]

                def first(self_inner):
                    import json as _j
                    return (_j.dumps(previous),)

            if "INSERT INTO drive_sync_state" in sql:
                saved["value"] = params["v"]
            return _R()

    archived = []
    service = DriveSyncService.__new__(DriveSyncService)
    service.db = _DB()
    service._archive_by_drive_id_isolated = lambda fid, _r: archived.append(fid) or 1
    return service, _Drive(), archived, saved


def test_ghost_sweep_archives_trashed_now_but_404_only_on_second_sighting():
    import json
    service, drive, archived, saved = _ghost_fixture(["seen", "trashed", "live", "gone", "flaky"], previous=[])
    result = {"archived": 0}
    service._sweep_ghost_rows(drive, {"seen"}, result)
    assert archived == ["trashed"]  # 404 'gone' is only a first sighting
    assert json.loads(saved["value"]) == ["gone"]

    service, drive, archived, saved = _ghost_fixture(["seen", "trashed", "live", "gone", "flaky"], previous=["gone"])
    result = {"archived": 0}
    service._sweep_ghost_rows(drive, {"seen"}, result)
    assert sorted(archived) == ["gone", "trashed"]
    assert result["ghosts_archived"] == 2 and json.loads(saved["value"]) == []


def test_ghost_sweep_mass_event_never_archives_on_404():
    ids = [f"gone{i}" for i in range(40)]
    service, drive, archived, saved = _ghost_fixture(ids, previous=ids)
    result = {"archived": 0}
    service._sweep_ghost_rows(drive, set(), result)
    assert archived == [] and result["ghost_mass_event"] is True


def test_brand_match_handles_parenthesised_alias():
    match = _brand_matcher("Resource Help Online (RHO)", "Commercial Insurance")
    assert match("Resource Help Online") == "id-0"
    assert match("RHO") == "id-0"
