"""Validation for the canonical Drive Final Handoff Manifest format.

The sync service remains the parser of record.  This module only adds the
structural checks that are useful before a file is imported and returns the
same copy fields the existing parser uses for launch metadata.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from app.services.drive_sync_service import DriveSyncService


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

_HEADING_RE = re.compile(r"^\s*##\s+(.+?)\s*$")
_PLACEMENT_RE = re.compile(
    r"^\s*(1X1|4X5|9X16|16X9)\s+(IMAGE|VIDEO)\s*:?[ \t]*(.*)$",
    re.IGNORECASE,
)
_FIELD_RE = re.compile(
    r"^\s*(PRIMARY TEXT|HEADLINE|DESCRIPTION|CTA|META BUTTON|"
    r"1X1|4X5|9X16|16X9)\b\s*:?[ \t]*(.*)$",
    re.IGNORECASE,
)
_SEPARATOR_RE = re.compile(r"^\s*(?:={4,}|-{4,}|\*{4,}|_{4,})\s*$")


def _clean_heading(raw: str) -> str:
    return raw.strip().strip("#").strip()


def _looks_like_copy_id(value: str) -> bool:
    """Recognize a block heading without treating prose headings as blocks."""
    cleaned = _clean_heading(value)
    return bool(
        cleaned
        and re.search(r"\d", cleaned)
        and re.search(r"[-_ ]", cleaned)
        and not cleaned.lower().startswith(("package", "recommended", "ad set"))
    )


def _non_empty_after(lines: List[str], index: int) -> tuple[str, int]:
    cursor = index + 1
    while cursor < len(lines):
        value = lines[cursor].strip()
        if value:
            return value, cursor
        cursor += 1
    return "", cursor


def _field_values(lines: List[str], label: str) -> List[str]:
    """Extract a field while stopping only at known structural labels.

    In particular, arbitrary all-caps lines remain body text.  That mirrors the
    existing parser's narrow stop-label contract and prevents the known
    ``LIMITED TIME OFFER`` truncation bug.
    """
    values: List[str] = []
    target = label.casefold()
    start = None
    for index, raw_line in enumerate(lines):
        match = _FIELD_RE.match(raw_line)
        if not match:
            if start is not None:
                values.append(raw_line.rstrip())
            continue
        current = match.group(1).casefold()
        if current == target:
            start = index
            inline = match.group(2).strip()
            if inline:
                values.append(inline)
            continue
        if start is not None:
            break
    while values and not values[0].strip():
        values.pop(0)
    while values and not values[-1].strip():
        values.pop()
    return values


def _block_placements(lines: List[str]) -> tuple[List[Dict[str, str]], List[str]]:
    placements: List[Dict[str, str]] = []
    errors: List[str] = []
    for index, raw_line in enumerate(lines):
        match = _PLACEMENT_RE.match(raw_line)
        if not match:
            continue
        aspect = match.group(1).lower()
        media_type = match.group(2).lower()
        filename = match.group(3).strip()
        if not filename:
            filename, _ = _non_empty_after(lines, index)
        if not filename:
            errors.append(f"{aspect.upper()} {media_type} is missing its filename")
            continue
        if "/" in filename or "\\" in filename:
            errors.append(f"{aspect.upper()} {media_type} filename must not contain a path: {filename}")
        placements.append({"aspect": aspect, "media_type": media_type, "filename": filename})
    return placements, errors


def _message(severity: str, text: str) -> Dict[str, str]:
    return {"severity": severity, "message": text}


def _manifest_source_parser() -> DriveSyncService:
    """Create the parser without opening a database or Drive connection."""
    return DriveSyncService.__new__(DriveSyncService)


def _block_source_kind(block_ids: Iterable[str]) -> str:
    """Match the sync's inline-variant distinction for repeated concepts."""
    concept_numbers: List[str] = []
    for block_id in block_ids:
        tokens = re.split(r"[-_ ]+", block_id)
        concept_numbers.extend(token for token in tokens if token.isdigit())
    return "inline_variant" if len(concept_numbers) != len(set(concept_numbers)) else "handoff_manifest"


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

    package_match = re.search(r"^\s*PACKAGE\s*:\s*(.+?)\s*$", body, re.IGNORECASE | re.MULTILINE)
    package = package_match.group(1).strip() if package_match else ""
    if not package:
        errors.append("Missing PACKAGE header")

    parser = _manifest_source_parser()
    cta_raw = parser._extract_manifest_value(lines, r"Meta button")
    cta = parser._normalize_cta(cta_raw) if cta_raw else None
    if not cta_raw:
        errors.append("Missing Meta Button value")
    elif cta not in META_CTA_OPTIONS:
        errors.append(f"Meta Button is not a supported Meta CTA: {cta_raw}")

    if file_name and "handoff" not in file_name.lower() or file_name and "manifest" not in file_name.lower():
        warnings.append("Filename does not look like a Final Handoff Manifest")

    headings = [
        (index, match.group(1), match)
        for index, line in enumerate(lines)
        if (match := _HEADING_RE.match(line)) and _looks_like_copy_id(match.group(1))
    ]
    if not headings:
        errors.append("No copy blocks found; add at least one ## <copy id> block")

    block_ids = [_clean_heading(raw_id) for _, raw_id, _ in headings]
    seen_ids = set()
    duplicate_ids = set()
    for block_id in block_ids:
        key = block_id.casefold()
        if key in seen_ids:
            duplicate_ids.add(block_id)
        seen_ids.add(key)
    for block_id in sorted(duplicate_ids, key=str.casefold):
        errors.append(f"Duplicate copy block id: {block_id}")

    entries: Dict[str, Dict[str, Any]] = {}
    declared_media: set[str] = set()
    for heading_index, (line_index, raw_id, _match) in enumerate(headings):
        block_id = _clean_heading(raw_id)
        end = headings[heading_index + 1][0] if heading_index + 1 < len(headings) else len(lines)
        block_lines = lines[line_index + 1:end]
        block_text = "\n".join([lines[line_index], *block_lines])
        parsed = parser._parse_ad_copy_doc(block_text)
        parsed_entry = next(iter(parsed.values()), {}) if len(parsed) == 1 else {}

        primary_lines = _field_values(block_lines, "PRIMARY TEXT")
        headline_lines = _field_values(block_lines, "HEADLINE")
        description_lines = _field_values(block_lines, "DESCRIPTION")
        primary_text = parsed_entry.get("primary_text") or "\n".join(primary_lines).strip()
        headline = parsed_entry.get("headline") or "\n".join(headline_lines).strip()
        description = parsed_entry.get("description") or "\n".join(description_lines).strip()

        if not primary_text:
            errors.append(f"{block_id}: PRIMARY TEXT is missing")
        if not headline:
            errors.append(f"{block_id}: HEADLINE is missing")
        if not description:
            warnings.append(f"{block_id}: DESCRIPTION is missing (optional)")

        if any(re.match(r"^\s*(?:CTA|META BUTTON)\b", line, re.IGNORECASE) for line in block_lines):
            errors.append(f"{block_id}: per-block CTA is not supported; use the file-level Meta Button")

        placements, placement_errors = _block_placements(block_lines)
        errors.extend(f"{block_id}: {message}" for message in placement_errors)
        if not placements:
            errors.append(f"{block_id}: no placement filename listed")

        feed = [item for item in placements if item["aspect"] in {"1x1", "4x5", "16x9"}]
        stories = [item for item in placements if item["aspect"] == "9x16"]
        if feed and not stories:
            warnings.append(f"{block_id}: no 9X16 Stories/Reels placement")
        if stories and not feed:
            warnings.append(f"{block_id}: no Feed placement")
        if feed and stories and {item["media_type"] for item in feed} != {item["media_type"] for item in stories}:
            warnings.append(f"{block_id}: Feed and 9X16 placements use different media types")

        entry: Dict[str, Any] = {
            "copy_id": block_id,
            "primary_text": primary_text,
            "headline": headline,
            "description": description or None,
            "cta": cta,
            "placements": placements,
        }
        for placement in placements:
            entry[placement["aspect"]] = placement["filename"]
            declared_media.add(placement["filename"].casefold())
        entries[block_id] = entry

    if folder_media_names is not None:
        media_names = [str(name).strip() for name in folder_media_names if str(name).strip()]
        media_by_key = {name.casefold(): name for name in media_names}
        for entry in entries.values():
            for placement in entry["placements"]:
                filename = placement["filename"]
                if filename.casefold() not in media_by_key:
                    errors.append(f"{entry['copy_id']}: listed media is missing from the package folder: {filename}")
        for key, name in media_by_key.items():
            if key not in declared_media:
                warnings.append(f"Media file is not listed in any copy block: {name}")

    messages = [_message("error", message) for message in errors]
    messages.extend(_message("warning", message) for message in warnings)
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "entries": entries,
        "cta": cta,
        "package": package,
        "source_kind": _block_source_kind(block_ids),
        "messages": messages[:3],
    }
