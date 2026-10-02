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

# Same heading pattern as the sync's inline-manifest parser.
_BLOCK_HEADING_RE = re.compile(
    r"^[ \t]*##[ \t]+(?:(?:[A-Z0-9]+[-_ \t]+)*AD[-_ \t]?(\d+)|(?:[A-Z0-9]+[-_ \t]+)+?(\d+))\b[^\r\n]*$",
    re.IGNORECASE,
)
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


def _label_of(heading_line: str) -> str:
    cleaned = re.sub(r"^[#\s]+", "", heading_line).strip()
    token = re.match(r"[A-Za-z0-9_-]+", cleaned)
    return token.group(0) if token else cleaned


def _field_values(lines: List[str], label: str) -> List[str]:
    """Read a field, stopping only at known structural labels.

    Arbitrary all-caps lines stay body text (the known ``LIMITED TIME OFFER``
    truncation trap).
    """
    stop = re.compile(
        r"^\s*(PRIMARY TEXT|HEADLINE|DESCRIPTION|CTA|META BUTTON|1X1|4X5|9X16|16X9)\b\s*:?[ \t]*(.*)$",
        re.IGNORECASE,
    )
    values: List[str] = []
    target = label.casefold()
    start = None
    for index, raw_line in enumerate(lines):
        match = stop.match(raw_line)
        if not match:
            if start is not None:
                values.append(raw_line.rstrip())
            continue
        if match.group(1).casefold() == target:
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


def _required_placements(block_text: str) -> Tuple[Tuple[str, str, str], Tuple[str, str, str]]:
    """The two placements the sync demands for this block (aspect label, kind, normalized)."""
    if re.search(r"^[ \t]*16X9[ \t]+VIDEO\b", block_text, re.IGNORECASE | re.MULTILINE):
        return ("16X9", "VIDEO", "16x9"), ("9X16", "VIDEO", "9x16")
    if re.search(r"^[ \t]*(?:4X5|9X16)[ \t]+VIDEO\b", block_text, re.IGNORECASE | re.MULTILINE):
        return ("4X5", "VIDEO", "4x5"), ("9X16", "VIDEO", "9x16")
    return ("1X1", "IMAGE", "1x1"), ("9X16", "IMAGE", "9x16")


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

    # --- Ad blocks --------------------------------------------------------------
    block_headings: List[Tuple[int, str, int]] = []  # (line index, heading line, ad number)
    for index, line in enumerate(lines):
        any_heading = _ANY_HEADING_RE.match(line)
        if not any_heading:
            continue
        block = _BLOCK_HEADING_RE.match(line)
        if block:
            block_headings.append((index, line.strip(), int(block.group(1) or block.group(2))))
        elif re.search(r"\d", any_heading.group(1)):
            errors.append(
                f"Line {index + 1}: '{line.strip()}' isn't read as an ad, so everything under it is skipped. "
                "Name each ad like '## CA-PROVEN-01-IMG' (letters, a dash, then the number)."
            )

    if not block_headings:
        errors.append("No ads found. Each ad starts with a line like '## PKG-01-IMG'.")

    numbers = [number for _, _, number in block_headings]
    is_variant_doc = len(set(numbers)) != len(numbers)
    labels = [_label_of(heading) for _, heading, _ in block_headings]
    first_line_for_label: Dict[str, int] = {}
    for (index, _heading, _n), label in zip(block_headings, labels):
        key = label.casefold()
        if key in first_line_for_label:
            errors.append(f"Lines {first_line_for_label[key] + 1} and {index + 1}: two ads are both named {label}. Give each ad its own name.")
        else:
            first_line_for_label[key] = index

    preamble = "\n".join(lines[: block_headings[0][0]]) + "\n" if block_headings else ""
    if block_headings and not is_variant_doc:
        sections = parser._parse_ad_copy_doc(body)
        if set(sections) != set(numbers):
            errors.append("The copy under the ad headings couldn't all be read (check that every ad has PRIMARY TEXT and HEADLINE under it).")

    media_by_key: Dict[str, List[str]] = {}
    if folder_media_names is not None:
        for name in folder_media_names:
            cleaned = str(name).strip()
            if cleaned:
                media_by_key.setdefault(cleaned.casefold(), []).append(cleaned)

    entries: Dict[str, Dict[str, Any]] = {}
    declared_media: Set[str] = set()
    seen_media_in_blocks: Dict[str, str] = {}
    for position, ((line_index, heading, number), label) in enumerate(zip(block_headings, labels)):
        end = block_headings[position + 1][0] if position + 1 < len(block_headings) else len(lines)
        block_lines = lines[line_index + 1:end]
        block_text = "\n".join(block_lines)
        where = f"Line {line_index + 1} ({label})"

        parsed_sections = parser._parse_ad_copy_doc(f"{preamble}{heading}\n{block_text}")
        parsed_entry = next(iter(parsed_sections.values()), {}) if len(parsed_sections) == 1 else {}
        primary_text = parsed_entry.get("primary_text") or "\n".join(_field_values(block_lines, "PRIMARY TEXT")).strip()
        headline = parsed_entry.get("headline") or "\n".join(_field_values(block_lines, "HEADLINE")).strip()
        description = parsed_entry.get("description") or "\n".join(_field_values(block_lines, "DESCRIPTION")).strip()
        if not primary_text:
            errors.append(f"{where}: add a PRIMARY TEXT line with the ad text underneath it.")
        if not headline:
            errors.append(f"{where}: add a HEADLINE line with the headline underneath it.")
        if is_variant_doc and primary_text and headline and len(parsed_sections) != 1:
            # Both fields exist, yet the sync's parser can't read them (typically a value on
            # the same line as its label, e.g. "PRIMARY TEXT: ...").
            errors.append(
                f"{where}: the sync can't read this ad's copy. Put PRIMARY TEXT, HEADLINE and DESCRIPTION each on their own line, with the text underneath."
            )

        in_copy_body = False
        for offset, raw in enumerate(block_lines):
            if re.match(r"^\s*(?:PRIMARY TEXT|HEADLINE|DESCRIPTION)\b", raw, re.IGNORECASE):
                in_copy_body = True
            elif _VALID_PLACEMENT_LABEL_RE.match(raw):
                in_copy_body = False
            if re.match(r"^\s*(?:CTA|META BUTTON)\b", raw, re.IGNORECASE):
                errors.append(f"Line {line_index + 2 + offset}: the button is set once for the whole file ('Meta Button' near the top). Remove this line.")
            lookalike = _LOOKS_LIKE_PLACEMENT_RE.match(raw)
            if lookalike and not _VALID_PLACEMENT_LABEL_RE.match(raw) and (not in_copy_body or lookalike.group(1).isupper()):
                errors.append(
                    f"Line {line_index + 2 + offset}: couldn't read '{raw.strip()[:40]}'. "
                    "Use labels like 1X1 IMAGE, 9X16 IMAGE, 4X5 VIDEO or 9X16 VIDEO."
                )

        required = _required_placements(block_text)
        kinds = {m.group(2).upper() for m in (_VALID_PLACEMENT_LABEL_RE.match(raw) for raw in block_lines) if m}
        if len(kinds) > 1:
            warnings.append(f"{where}: has both image and video labels; only the {required[0][1].lower()} pair will be used.")

        placements: List[Dict[str, str]] = []
        for aspect_label, kind, normalized in required:
            under = re.search(
                rf"^[ \t]*{aspect_label}[ \t]+{kind}[ \t]*\r?\n[ \t]*([^\r\n]+)",
                block_text,
                re.IGNORECASE | re.MULTILINE,
            )
            if not under:
                inline = re.search(
                    rf"^[ \t]*{aspect_label}[ \t]+{kind}[ \t]*:?[ \t]*(\S[^\r\n]*)$",
                    block_text,
                    re.IGNORECASE | re.MULTILINE,
                )
                if inline:
                    errors.append(
                        f"{where}: put the filename on the line UNDER '{aspect_label} {kind}', not on the same line."
                    )
                else:
                    errors.append(f"{where}: this ad needs both a '{required[0][0]} {required[0][1]}' and a '{required[1][0]} {required[1][1]}' line, each with a filename under it (missing '{aspect_label} {kind}').")
                continue
            filename = under.group(1).strip()
            if "/" in filename or "\\" in filename:
                errors.append(f"{where}: '{filename}' must be just the file's name, without any folder path.")
            if any(item["filename"].casefold() == filename.casefold() for item in placements):
                errors.append(f"{where}: the same file ('{filename}') is listed for both placements. Each placement needs its own file.")
            placements.append({"aspect": normalized, "media_type": kind.lower(), "filename": filename})

            key = filename.casefold()
            declared_media.add(key)
            if key in seen_media_in_blocks and seen_media_in_blocks[key] != label:
                errors.append(f"{where}: '{filename}' is already used by {seen_media_in_blocks[key]}. Each file belongs to one ad.")
            seen_media_in_blocks.setdefault(key, label)

            file_number = parser._ad_number_from_file_name(filename)
            if file_number is not None and file_number != number:
                errors.append(f"{where}: '{filename}' is numbered {file_number:02d} but this ad is number {number:02d}.")
            file_aspect = parser._media_aspect({"name": filename})
            if file_aspect and file_aspect != normalized:
                errors.append(f"{where}: '{filename}' looks like a {file_aspect} file but is listed under {aspect_label} {kind}.")
            if is_variant_doc:
                variant_token = re.split(r"[-_]", label)[-1].lower()
                if not variant_token.isdigit() and variant_token not in re.split(r"[-_ .]", filename.lower()):
                    errors.append(f"{where}: '{filename}' doesn't look like it belongs to this ad (its name should include '{variant_token.upper()}').")

            if folder_media_names is not None:
                matches = media_by_key.get(key, [])
                if not matches:
                    errors.append(f"{where}: '{filename}' isn't in the package folder in Drive. Copy the file's name straight from Drive.")
                elif len(matches) > 1:
                    errors.append(f"{where}: more than one file in the folder is named '{filename}'.")
                elif matches[0] != filename:
                    warnings.append(f"{where}: '{filename}' differs in capital letters from the Drive file '{matches[0]}'. Copy the name exactly.")

        entry: Dict[str, Any] = {
            "copy_id": label,
            "line": line_index + 1,
            "primary_text": primary_text,
            "headline": headline,
            "description": description or None,
            "cta": cta,
            "placements": placements,
        }
        for placement in placements:
            entry[placement["aspect"]] = placement["filename"]
        entries[label] = entry

    if folder_media_names is not None:
        for key, names in media_by_key.items():
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
        "source_kind": "inline_variant" if is_variant_doc else "handoff_manifest",
        "messages": messages[:10],
    }
