"""Validation for the canonical Drive Final Handoff Manifest format.

"Valid" here must mean "the sync will import it".  The sync's inline-manifest
path (`DriveSyncService._folder_copy_metadata`, the ``NonActionableHandoffManifestError``
fallback that builds ``declared_blocks``) is the parser of record, and it is
strict: every ad needs BOTH placements of one media type, each filename sits on
the line UNDER its label, the filename's ad number must match the heading, and so
on.  This module mirrors those rules (reusing the sync's own helpers where it
can) and adds the checks a person needs before saving: leftover template text,
unreadable lines, and a line number on every message.

Messages are written for a media buyer, not an engineer.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.services.drive_sync_service import DriveSyncService, bind_handoff_manifest


META_CTA_OPTIONS = {
    "LEARN_MORE",
    "SHOP_NOW",
    "SIGN_UP",
    "CONTACT_US",
    "DOWNLOAD",
    "BOOK_NOW",
    "BUY_TICKETS",
    "GET_QUOTE",
    "GET_STARTED",
    "APPLY_NOW",
    "DONATE_NOW",
}

_ANY_HEADING_RE = re.compile(r"^[ \t]*##[ \t]+(.+?)\s*$")
_VALID_PLACEMENT_LABEL_RE = re.compile(r"^[ \t]*(1X1|4X5|9X16|16X9)[ \t]+(IMAGE|VIDEO)\b", re.IGNORECASE)
# A mistyped placement label: aspect plus one short word and nothing else ("9x16 IMG").
# Ad copy such as "24x7 claims support" or "3x faster quotes" is longer prose and is left alone.
_LOOKS_LIKE_PLACEMENT_RE = re.compile(r"^[ \t]*\d{1,2}[ \t]*[xX][ \t]*\d{1,2}[ \t]+([A-Za-z]{2,10})[ \t]*:?[ \t]*$")
# Requires a letter right after "<" so ordinary copy like "under <25 or >65" is left alone.
_PLACEHOLDER_RE = re.compile(r"<[A-Za-z][^<>\n]{0,59}>")
_TEMPLATE_HEADER_MARKERS = ("how to use this file", "delete everything above", "delete everything above the")
# Text that only exists in docs/DRIVE_HANDOFF_MANIFEST_TEMPLATE.txt. Keep in sync with it.
_TEMPLATE_SAMPLE_LINES = {
    "first line of the ad text.",
    "second paragraph of the ad text.",
    "one-line headline",
    "optional one-line description",
    "ad text for a video ad.",
    "video headline",
}
_TEMPLATE_SAMPLE_FILENAME_RE = re.compile(r"\bPKG-\d+-Name-", re.IGNORECASE)


def _message(severity: str, text: str) -> Dict[str, str]:
    return {"severity": severity, "message": text}


def _manifest_source_parser() -> DriveSyncService:
    """Create the parser without opening a database or Drive connection."""
    return DriveSyncService.__new__(DriveSyncService)


def validate_handoff_manifest(
    text: str,
    *,
    folder_media_names: Optional[Iterable[str]] = None,
    file_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate a canonical manifest without writing to Drive or the database."""
    body = text or ""
    lines = body.splitlines()
    errors: List[str] = []
    warnings: List[str] = []
    parser = _manifest_source_parser()

    # --- Leftover template text -------------------------------------------------
    package_line_index = next(
        (i for i, line in enumerate(lines) if re.match(r"^\s*PACKAGE\s*:", line, re.IGNORECASE)),
        None,
    )
    header_zone = lines[: package_line_index if package_line_index is not None else len(lines)]
    if any(marker in line.lower() for line in header_zone for marker in _TEMPLATE_HEADER_MARKERS):
        errors.append(
            "Lines 1-%d are the template's how-to instructions. Delete everything above the line that starts with "
            "'PACKAGE:' before saving to Drive." % max(package_line_index or len(lines), 1)
        )
    for index, line in enumerate(lines, start=1):
        for placeholder in _PLACEHOLDER_RE.findall(line):
            errors.append(f"Line {index}: replace the placeholder {placeholder} with the real value.")
        stripped = line.strip().lower()
        if stripped in _TEMPLATE_SAMPLE_LINES or _TEMPLATE_SAMPLE_FILENAME_RE.search(line):
            errors.append(f"Line {index}: this is still the template's sample text ({line.strip()[:60]}). Replace it with your real copy or filename.")

    # --- Package header and Meta button ----------------------------------------
    package = ""
    if package_line_index is None:
        errors.append("Add a first line like 'PACKAGE: Vertical | Package name'.")
    else:
        package = re.sub(r"^\s*PACKAGE\s*:\s*", "", lines[package_line_index], flags=re.IGNORECASE).strip()
        if not package:
            errors.append(f"Line {package_line_index + 1}: the PACKAGE line is empty. Add the vertical and package name.")

    cta_raw = parser._extract_manifest_value(lines, r"Meta button")
    cta = parser._normalize_cta(cta_raw) if cta_raw else None
    cta_line = next((i + 1 for i, line in enumerate(lines) if re.match(r"^\s*meta\s+button\b", line, re.IGNORECASE)), None)
    if not cta_raw:
        errors.append("Add a 'Meta Button' line near the top, with the button name on the next line (for example Get Quote).")
    elif cta not in META_CTA_OPTIONS:
        errors.append(
            f"Line {cta_line or 1}: '{cta_raw}' is not a button Meta supports. Use one of: "
            "Get Quote, Learn More, Sign Up, Apply Now, Get Started, Contact Us, Book Now, Shop Now, Download."
        )

    if file_name and not re.search(r"handoff[\s_-]*manifest", file_name, re.IGNORECASE):
        warnings.append("This file's name should end in HANDOFF-MANIFEST (for example CA-PROVEN-HANDOFF-MANIFEST.txt) so the sync recognizes it.")

    # --- Ad blocks: the sync's own binder, so "valid" means "the sync imports it" ----------------
    media_items = None
    folder_names_by_key: Dict[str, List[str]] = {}
    if folder_media_names is not None:
        for name in folder_media_names:
            cleaned = str(name).strip()
            if cleaned:
                folder_names_by_key.setdefault(cleaned.casefold(), []).append(cleaned)
        # Every name, duplicates included, so "more than one file is named X" shows here like it does in the sync.
        media_items = [{"id": None, "name": name} for names in folder_names_by_key.values() for name in names]
    bound = bind_handoff_manifest(
        body, media_items, parser._media_aspect, parser._parse_ad_copy_doc, parser._ad_number_from_file_name,
        parse_cta=parser._normalize_cta,
    )
    blocks = bound["blocks"]
    if not blocks:
        errors.append("No ads found. Each ad starts with a line like '## PKG-01-IMG', then its copy and files.")

    heading_lines = [i for i, line in enumerate(lines) if _ANY_HEADING_RE.match(line)]
    entries: Dict[str, Dict[str, Any]] = {}
    declared_media: Set[str] = set()
    for block in blocks:
        start = block["line"] - 1
        end = next((i for i in heading_lines if i > start), len(lines))
        block_lines = lines[start + 1:end]
        for message in block["errors"]:
            errors.append(f"Line {block['line']}: {message}")
        in_copy_body = False
        for offset, raw in enumerate(block_lines):
            if re.match(r"^\s*(?:PRIMARY TEXT|HEADLINE|DESCRIPTION)\b", raw, re.IGNORECASE):
                in_copy_body = True
            elif _VALID_PLACEMENT_LABEL_RE.match(raw):
                in_copy_body = False
            if re.match(r"^\s*(?:CTA|META BUTTON)\b", raw, re.IGNORECASE):
                errors.append(f"Line {start + 2 + offset}: the button is set once for the whole file ('Meta Button' near the top). Remove this line.")
            lookalike = _LOOKS_LIKE_PLACEMENT_RE.match(raw)
            if lookalike and not _VALID_PLACEMENT_LABEL_RE.match(raw) and (not in_copy_body or lookalike.group(1).isupper()):
                errors.append(
                    f"Line {start + 2 + offset}: couldn't read '{raw.strip()[:40]}'. "
                    "Use labels like 1X1 IMAGE, 9X16 IMAGE, 4X5 VIDEO, 1X1 VIDEO or 9X16 VIDEO."
                )
        placements = [
            {"aspect": p["aspect"], "media_type": p["kind"], "filename": p["filename"]} for p in block["placements"]
        ]
        for placement in placements:
            key = placement["filename"].casefold()
            declared_media.add(key)
            matches = folder_names_by_key.get(key, [])
            if len(matches) == 1 and matches[0] != placement["filename"]:
                warnings.append(f"Line {block['line']} ({block['label']}): '{placement['filename']}' differs in capital letters from the Drive file '{matches[0]}'. Copy the name exactly.")
        if len(placements) == 1:
            warnings.append(f"Line {block['line']} ({block['label']}): only one placement is listed, so this ad runs in that placement only.")
        section = block["section"] or {}
        copy_id = f"AD-{block['number']:02d}" if bound["unique_numbers"] else block["label"]
        entry: Dict[str, Any] = {
            "copy_id": copy_id,
            "line": block["line"],
            "primary_text": section.get("primary_text") or "",
            "headline": section.get("headline") or "",
            "description": section.get("description") or None,
            "cta": cta,
            "placements": placements,
        }
        for placement in placements:
            entry[placement["aspect"]] = placement["filename"]
        entries[copy_id] = entry

    if folder_media_names is not None:
        for key, names in folder_names_by_key.items():
            if key not in declared_media:
                warnings.append(f"The file '{names[0]}' is in the folder but isn't listed in any ad, so it won't be launchable.")

    messages = [_message("error", message) for message in errors]
    messages.extend(_message("warning", message) for message in warnings)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "entries": entries,
        "cta": cta,
        "package": package,
        "source_kind": "handoff_manifest" if bound["unique_numbers"] else "inline_variant",
        "messages": messages[:10],
    }
