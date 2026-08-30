"""Shared niche extraction for ad set names."""
import re

# Patterns that indicate the extracted value is a batch/test tag, not a real niche.
# If the niche extraction produces one of these, fall back to None (displayed as "General").
_NON_NICHE_RE = re.compile(
    r'^(batch[\s\d]|set[\s\d]|v\d+[\s_.-]?$|v\d+[\s_.-]|scale|open$|image$|'
    r'calls$|test|broad|retarget|phase[\s\d]|round[\s\d]|\d{4}-\d{2}-\d{2}|'
    r'gbc\s*\||unknown$)',
    re.IGNORECASE,
)

# Strip leading emoji / Unicode pictograph characters from niche candidates.
_LEADING_EMOJI_RE = re.compile(
    r'^[\U0001F000-\U0001FFFF\U00002600-\U000027FF\U00002B00-\U00002BFF'
    r'\U0000FE00-\U0000FE0F\u200d]+\s*',
    re.UNICODE,
)


def _extract_niche(adset_name: str, require_separator: bool = False) -> str | None:
    """Extract niche from ad set name pattern '[Date] - [Niche] - [Batch info]'.

    Returns None for empty names or when the extracted candidate looks like a
    batch/test label rather than a real niche. The caller stores None and the
    frontend displays it as 'General'.

    Leading emoji are stripped from the candidate. Set require_separator=True
    when callers need unstructured names grouped as General instead of using
    the whole ad set name as a best-effort niche.
    """
    if not adset_name:
        return None
    parts = adset_name.split(" - ")
    if len(parts) < 2:
        if require_separator:
            return None
        # No separator: can't extract niche reliably; store the full name if
        # it doesn't look like a batch tag, otherwise None.
        candidate = _LEADING_EMOJI_RE.sub('', adset_name.strip()).strip()
        return None if (not candidate or _NON_NICHE_RE.match(candidate)) else candidate

    candidate = _LEADING_EMOJI_RE.sub('', parts[1].strip()).strip()
    if not candidate or _NON_NICHE_RE.match(candidate):
        return None
    # Normalize ALL-CAPS names (e.g. "HORSES & STABLE" -> "Horses & Stable")
    if candidate == candidate.upper():
        candidate = candidate.title()
    return candidate
