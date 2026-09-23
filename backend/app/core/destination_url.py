"""Single source of truth for destination-URL normalization/validation.

Mirrors frontend/src/lib/destinationUrl.js. Both redtrack_macros.py and
facebook_service.py validated a website_url independently before this existed
(with slightly different normalization each), which meant a URL could pass one
check and fail the other on the same string. Route both through this instead.
"""
from urllib.parse import urlsplit

_ZERO_WIDTH_CHARS = ("​", "‌", "‍", "﻿")


def normalize_destination_url(value) -> str:
    """Strip zero-width/BOM characters a copy-paste can silently introduce."""
    stripped = str(value or "")
    for char in _ZERO_WIDTH_CHARS:
        stripped = stripped.replace(char, "")
    return stripped.strip()


def is_valid_destination_url(value) -> bool:
    normalized = normalize_destination_url(value)
    if not normalized:
        return False
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
