from pathlib import Path

from app.services.drive_manifest_validator import validate_handoff_manifest


# Shape matches the real production manifest (CA-PROVEN): inline copy, filename on the
# line UNDER its label, both placements per ad. 01-H1 / 01-IMG share a number, which
# the sync handles as "variants"; 02-H1 stands alone.
MANIFEST = """PACKAGE: Commercial Insurance | CA-PROVEN
FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP

Meta Button
Get Quote

==================================================

## CA-PROVEN-01-H1

PRIMARY TEXT
🚀 LIMITED TIME OFFER
Get commercial coverage without the usual hassle.

HEADLINE
Compare commercial coverage today

DESCRIPTION
Fast online options

4X5 VIDEO
ca-proven-01-h1-4x5.mp4

9X16 VIDEO
ca-proven-01-h1-9x16.mp4

==================================================

## CA-PROVEN-01-IMG

PRIMARY TEXT
STOP OVERPAYING
See options built for your business.

HEADLINE
Find a better business policy

1X1 IMAGE
ca-proven-01-img-1x1.jpg

9X16 IMAGE
ca-proven-01-img-9x16.jpg

==================================================

## CA-PROVEN-02-H1

PRIMARY TEXT
Coverage that fits the way you work.

HEADLINE
Get a commercial quote

4X5 VIDEO
ca-proven-02-h1-4x5.mp4

9X16 VIDEO
ca-proven-02-h1-9x16.mp4
"""

NAMES = [
    "ca-proven-01-h1-4x5.mp4", "ca-proven-01-h1-9x16.mp4",
    "ca-proven-01-img-1x1.jpg", "ca-proven-01-img-9x16.jpg",
    "ca-proven-02-h1-4x5.mp4", "ca-proven-02-h1-9x16.mp4",
]
TEMPLATE = Path(__file__).resolve().parents[3] / "docs" / "DRIVE_HANDOFF_MANIFEST_TEMPLATE.txt"


def _errors(text, **kwargs):
    return validate_handoff_manifest(text, **kwargs)["errors"]


def test_canonical_manifest_with_matching_folder_is_valid():
    result = validate_handoff_manifest(MANIFEST, folder_media_names=NAMES, file_name="CA-PROVEN-HANDOFF-MANIFEST.txt")

    assert result["ok"] is True, result["errors"]
    assert result["warnings"] == []
    assert len(result["entries"]) == 3
    assert result["entries"]["CA-PROVEN-01-H1"]["4x5"] == "ca-proven-01-h1-4x5.mp4"
    assert result["source_kind"] == "inline_variant"


def test_all_caps_primary_text_is_not_truncated():
    entry = validate_handoff_manifest(MANIFEST)["entries"]["CA-PROVEN-01-H1"]

    assert "LIMITED TIME OFFER" in entry["primary_text"]
    assert "Get commercial coverage without the usual hassle." in entry["primary_text"]


def test_missing_headline_names_the_ad_and_the_line():
    text = MANIFEST.replace("HEADLINE\nCompare commercial coverage today\n", "", 1)

    errors = _errors(text)

    assert len(errors) == 1
    assert "CA-PROVEN-01-H1" in errors[0] and errors[0].startswith("Line ") and "HEADLINE" in errors[0]


def test_single_placement_is_an_error_because_the_sync_rejects_it():
    text = MANIFEST.replace("9X16 VIDEO\nca-proven-02-h1-9x16.mp4\n", "", 1)

    assert any("CA-PROVEN-02-H1" in e and "9X16 VIDEO" in e for e in _errors(text))


def test_filename_on_the_same_line_as_its_label_is_an_error():
    text = MANIFEST.replace("4X5 VIDEO\nca-proven-02-h1-4x5.mp4", "4X5 VIDEO: ca-proven-02-h1-4x5.mp4", 1)

    assert any("UNDER" in e for e in _errors(text))


def test_two_ads_with_the_same_name_is_an_error():
    text = MANIFEST.replace("## CA-PROVEN-01-IMG", "## CA-PROVEN-01-H1", 1)

    assert any("both named CA-PROVEN-01-H1" in e for e in _errors(text))


def test_unsupported_button_is_an_error_with_a_line():
    errors = _errors(MANIFEST.replace("Get Quote", "Make Me Rich", 1))

    assert any("Make Me Rich" in e and e.startswith("Line ") for e in errors)


def test_missing_media_in_folder_is_an_error():
    errors = _errors(MANIFEST, folder_media_names=NAMES[:1])

    assert any("ca-proven-01-h1-9x16.mp4" in e and "isn't in the package folder" in e for e in errors)


def test_path_in_filename_is_an_error():
    text = MANIFEST.replace("ca-proven-01-h1-4x5.mp4", "feed/ca-proven-01-h1-4x5.mp4", 1)

    assert any("without any folder path" in e for e in _errors(text))


def test_per_block_button_line_is_an_error_not_silently_accepted():
    text = MANIFEST.replace("PRIMARY TEXT\n🚀", "CTA: LEARN_MORE\n\nPRIMARY TEXT\n🚀", 1)

    assert any("Remove this line" in e for e in _errors(text))


def test_extra_media_in_folder_is_only_a_warning():
    result = validate_handoff_manifest(MANIFEST, folder_media_names=[*NAMES, "unlisted.png"])

    assert result["ok"] is True
    assert any("unlisted.png" in w for w in result["warnings"])


def test_capital_letter_difference_with_drive_is_a_warning():
    names = [n.replace("ca-proven-01-h1-4x5.mp4", "CA-PROVEN-01-H1-4x5.mp4") for n in NAMES]

    result = validate_handoff_manifest(MANIFEST, folder_media_names=names)

    assert result["ok"] is True
    assert any("capital letters" in w for w in result["warnings"])


def test_heading_with_a_digit_that_is_not_read_as_an_ad_is_flagged_not_dropped():
    text = MANIFEST.replace("## CA-PROVEN-02-H1", "## PKG02", 1)

    assert any("'## PKG02' isn't read as an ad" in e for e in _errors(text))


def test_unreadable_placement_label_is_flagged():
    text = MANIFEST.replace("1X1 IMAGE", "1X1 IMG", 1)

    assert any("couldn't read '1X1 IMG'" in e for e in _errors(text))


def test_file_numbered_for_a_different_ad_is_an_error_in_a_non_variant_manifest():
    text = """PACKAGE: Commercial Insurance | RHO
Meta Button
Get Quote

## RHO-AD-03

PRIMARY TEXT
Some copy.

HEADLINE
Some headline

1X1 IMAGE
rho-ad01-1x1.jpg

9X16 IMAGE
rho-ad01-9x16.jpg
"""

    assert any("is numbered 01 but this ad is number 03" in e for e in _errors(text))


def test_aspect_in_filename_must_match_its_label():
    text = MANIFEST.replace("4X5 VIDEO\nca-proven-02-h1-4x5.mp4", "4X5 VIDEO\nca-proven-02-h1-9x16.mp4", 1)

    assert any("looks like a 9x16 file but is listed under 4X5" in e for e in _errors(text))


def test_untouched_template_fails_with_plain_instructions():
    result = validate_handoff_manifest(TEMPLATE.read_text(encoding="utf-8"))
    joined = "\n".join(result["errors"])

    assert result["ok"] is False
    assert "how-to instructions" in joined
    assert "replace the placeholder <Vertical>" in joined
    assert "template's sample text" in joined


def test_missing_package_header_and_no_ads_use_plain_wording():
    errors = _errors("Meta Button\nGet Quote\n")

    assert any("PACKAGE: Vertical | Package name" in e for e in errors)
    assert any("No ads found" in e for e in errors)


def test_google_doc_manifest_without_extension_is_not_warned_about_its_name():
    result = validate_handoff_manifest(MANIFEST, file_name="CA-PROVEN Handoff Manifest")

    assert not any("should end in HANDOFF-MANIFEST" in w for w in result["warnings"])


def test_folder_field_accepts_a_pasted_drive_url_or_a_bare_id():
    from app.api.v1.drive_assets import _drive_folder_id

    assert _drive_folder_id("https://drive.google.com/drive/folders/1OKFpd90RRk8bp8O987zrteZSNoAiQFAu?usp=sharing") == "1OKFpd90RRk8bp8O987zrteZSNoAiQFAu"
    assert _drive_folder_id("1OKFpd90RRk8bp8O987zrteZSNoAiQFAu") == "1OKFpd90RRk8bp8O987zrteZSNoAiQFAu"
    assert _drive_folder_id("not a folder") is None
    assert _drive_folder_id("   ") is None


def test_ordinary_ad_copy_is_not_mistaken_for_a_placeholder_or_a_label():
    text = MANIFEST.replace(
        "Get commercial coverage without the usual hassle.",
        "Drivers <25 or >65 pay more.\n24x7 claims support\n3x faster quotes\n4x4 trucks covered",
        1,
    )

    result = validate_handoff_manifest(text, folder_media_names=NAMES)

    assert result["ok"] is True, result["errors"]


def test_same_file_for_both_placements_is_an_error():
    text = MANIFEST.replace("ca-proven-02-h1-9x16.mp4", "ca-proven-02-h1-4x5.mp4", 1)

    assert any("listed for both placements" in e or "already used" in e for e in _errors(text))


def test_variant_manifest_also_checks_the_ad_number_in_filenames():
    text = MANIFEST.replace("## CA-PROVEN-02-H1", "## CA-AD-02-H1", 1).replace(
        "ca-proven-02-h1-4x5.mp4", "ca-ad03-h1-4x5.mp4"
    ).replace("ca-proven-02-h1-9x16.mp4", "ca-ad03-h1-9x16.mp4")

    assert any("is numbered 03 but this ad is number 02" in e for e in _errors(text))


def test_inline_field_values_are_rejected_in_variant_manifests_like_the_sync_does():
    text = MANIFEST.replace("PRIMARY TEXT\nCoverage that fits the way you work.", "PRIMARY TEXT: Coverage that fits the way you work.", 1)

    assert any("can't read this ad's copy" in e for e in _errors(text))
