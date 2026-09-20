from app.services.drive_sync_service import DriveSyncService


def _service():
    return DriveSyncService.__new__(DriveSyncService)


def test_handoff_id_extractor_normalizes_live_formats_and_rejects_prose():
    service = _service()

    assert service._extract_handoff_copy_id("FLR_F01_PEAK_WEEK_BLIND_SPOT") == "FLR F01"
    assert service._extract_handoff_copy_id("BSR F01 | Policy Assumption") == "BSR F01"
    assert service._extract_handoff_copy_id("Copy ID: WLD TRK 01") == "WLD TRK 01"
    assert service._extract_handoff_copy_id("AD-DEALER-CR-00-DealerOperations") == "AD DEALER CR 00"
    assert service._extract_handoff_copy_id("Copy: Ad Copy/file.txt | FLR F01", allow_embedded=True) == "FLR F01"
    assert service._extract_handoff_copy_id("01 - Truck Winner Variations") is None
    assert service._extract_handoff_copy_id("Quote in 7 minutes.") is None
    assert service._extract_handoff_copy_id("AD-DEALER-CR-00-image-1x1.jpg") is None
    assert service._extract_handoff_copy_id("Copy ID") is None
    assert service._extract_handoff_copy_id("Batch 3") is None
    assert service._extract_handoff_copy_id("Batch 3 | variation") is None
    assert service._extract_handoff_copy_id("Phase 2") is None
    assert service._extract_handoff_copy_id("Phase 2 - retarget") is None
    assert service._extract_handoff_copy_id("V2") is None


def test_handoff_manifest_parses_inline_copy_reference_and_folder_paths():
    service = _service()
    manifest = """LANDING PAGE
https://example.com/quote
META BUTTON
Get Quote

FLR_F01_PEAK_WEEK_BLIND_SPOT
Copy: Ad Copy/Florist_Fresh_Creative_Ad_Copy_FINAL.txt | FLR F01
1x1: 1x1 Images/FLR_F01_peak_week_blind_spot_1x1.png
9x16: 9x16 Images/FLR_F01_peak_week_blind_spot_9x16.png
"""

    parsed = service._parse_handoff_manifest(manifest)

    assert parsed["landing_page"] == "https://example.com/quote"
    assert parsed["cta"] == "GET_QUOTE"
    assert parsed["entries"] == {
        "FLR F01": {
            "copy_file": "Florist_Fresh_Creative_Ad_Copy_FINAL.txt",
            "1x1": "FLR_F01_peak_week_blind_spot_1x1.png",
            "9x16": "FLR_F01_peak_week_blind_spot_9x16.png",
        }
    }


def test_handoff_manifest_carries_global_copy_file_and_reads_next_line_fields():
    service = _service()
    manifest = """Every row below has copy in auto-dealerships-compliance-set.txt.

01 - Winner Variations

AD DEALER CR 00
Copy concept
Dealer operations
1x1
AD-DEALER-CR-00-DealerOperations-1x1.jpg
9x16
AD-DEALER-CR-00-DealerOperations-9x16.jpg
"""

    parsed = service._parse_handoff_manifest(manifest)

    assert list(parsed["entries"]) == ["AD DEALER CR 00"]
    assert parsed["entries"]["AD DEALER CR 00"] == {
        "copy_file": "auto-dealerships-compliance-set.txt",
        "1x1": "AD-DEALER-CR-00-DealerOperations-1x1.jpg",
        "9x16": "AD-DEALER-CR-00-DealerOperations-9x16.jpg",
    }


def test_copy_file_uses_id_headers_as_blocks_across_divider_styles():
    service = _service()
    copy_file = """==================================================
AD ID: BSR_F01
==================================================
PRIMARY TEXT
Barber primary one.
HEADLINE
Barber headline one
DESCRIPTION
Barber description one
==================================================
WLD TRK 02 | SHOP ON WHEELS
PRIMARY TEXT
Welder primary two.
HEADLINE
Welder headline two
1X1 IMAGE
WLD_TRK_02_shop_1x1.png
"""

    parsed = service._parse_copy_file(copy_file)

    assert parsed["bsr f01"] == {
        "primary_text": "Barber primary one.",
        "headline": "Barber headline one",
        "description": "Barber description one",
    }
    assert parsed["wld trk 02"]["primary_text"] == "Welder primary two."
    assert parsed["wld trk 02"]["headline"] == "Welder headline two"


def test_copy_file_keeps_auto_dealer_headline_out_of_image_fields():
    service = _service()
    copy_file = """AD DEALER CR 00
PRIMARY TEXT
Dealer primary.
HEADLINE
Dealer headline
1X1 IMAGE
AD-DEALER-CR-00-DealerOperations-1x1.jpg
9X16 IMAGE
AD-DEALER-CR-00-DealerOperations-9x16.jpg
"""

    parsed = service._parse_copy_file(copy_file)

    assert parsed["ad dealer cr 00"]["headline"] == "Dealer headline"


def test_copy_file_ignores_bare_batch_label_inside_copy_body():
    service = _service()
    copy_file = """AD DEALER CR 00
PRIMARY TEXT
Dealer primary text line one.
Batch 3
More primary text after the stray line.
HEADLINE
Dealer headline
1X1 IMAGE
AD-DEALER-CR-00-DealerOperations-1x1.jpg
"""

    parsed = service._parse_copy_file(copy_file)

    assert "batch 3" not in parsed
    assert parsed["ad dealer cr 00"]["primary_text"] == (
        "Dealer primary text line one.\nBatch 3\nMore primary text after the stray line."
    )
    assert parsed["ad dealer cr 00"]["headline"] == "Dealer headline"


def test_copy_file_ignores_non_id_labels_before_field_headers():
    service = _service()
    copy_file = """AD DEALER CR 00
PRIMARY TEXT
Dealer primary text.
Phase 2
HEADLINE
Dealer headline
"""

    parsed = service._parse_copy_file(copy_file)

    assert "phase 2" not in parsed
    assert parsed["ad dealer cr 00"]["primary_text"] == "Dealer primary text.\nPhase 2"
    assert parsed["ad dealer cr 00"]["headline"] == "Dealer headline"


def test_manifest_ignores_bare_batch_label_between_real_copy_ids():
    service = _service()
    manifest = """WLD TRK 01
1x1
welders-01-1x1.jpg
Batch 3
This is an incidental batch note.
AD DEALER CR 00
1x1
dealer-00-1x1.jpg
"""

    parsed = service._parse_handoff_manifest(manifest)

    assert "BATCH 3" not in parsed["entries"]
    assert list(parsed["entries"]) == ["WLD TRK 01", "AD DEALER CR 00"]


def test_package_folder_can_resolve_manifest_nested_beside_media():
    service = _service()
    service._package_folder_cache = {}
    service._list_folder_subtree = lambda folder_id: {
        "ad-copy": [{"name": "HANDOFF_MANIFEST.txt", "mimeType": "text/plain"}],
        "package": [
            {"name": "HANDOFF_MANIFEST.txt", "mimeType": "text/plain"},
            {"name": "creative.jpg", "mimeType": "image/jpeg"},
        ],
    }[folder_id]

    class _Request:
        def execute(self):
            return {"id": "ad-copy", "parents": ["package"]}

    class _Files:
        def get(self, **_kwargs):
            return _Request()

    class _Drive:
        def files(self):
            return _Files()

    service._drive = _Drive()

    resolved = service._find_package_folder({"parents": ["ad-copy"]})

    assert resolved == "package"
    assert service._package_folder_cache["ad-copy"] == "package"
