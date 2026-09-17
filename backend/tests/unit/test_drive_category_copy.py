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
"""
    media = [
        {"id": "feed-id", "name": "restaurant.png", "_parent_folder_name": "1x1"},
        {"id": "stories-id", "name": "restaurant-9x16.png", "_parent_folder_name": "9x16"},
    ]

    result = service._category_folder_copy_metadata("package-id", media, document)

    assert result["assets"]["restaurant.png"]["copy_id"] == "CATEGORY-04"
    assert result["assets"]["restaurant-9x16.png"]["aspect"] == "9x16"
    assert result["assets"]["restaurant.png"]["copy"]["primary_text"] == "Restaurant copy."


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


def test_category_metadata_keeps_balanced_duplicate_pairs_separate():
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

    assert result["assets_by_drive_id"]["feed-a"]["copy_id"] == "CATEGORY-04"
    assert result["assets_by_drive_id"]["stories-a"]["copy_id"] == "CATEGORY-04"
    assert result["assets_by_drive_id"]["feed-b"]["copy_id"] == "CATEGORY-04-PAIR-2"
    assert result["assets_by_drive_id"]["stories-b"]["copy_id"] == "CATEGORY-04-PAIR-2"


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
    assert service._category_matches("Protect What You’ve Built.png", "GENERAL, Protect What You’ve Built", 7)
