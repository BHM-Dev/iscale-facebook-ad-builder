"""Shared niche extraction for ad set and campaign names."""
import re

# Patterns that indicate the extracted value is a batch/test tag, not a real niche.
# If the niche extraction produces one of these, fall back to None (displayed as "General").
_NON_NICHE_RE = re.compile(
    r'^(batch[\s\d]|set[\s\d]|v\d+[\s_.-]?$|v\d+[\s_.-]|scale|open$|image$|'
    r'calls$|test|broad|retarget|phase[\s\d]|round[\s\d]|capi$|creative(?:\s+\d+)?$|abo$|cbo$|'
    r'rho\s*v\d+$|'
    r'\d{4}-\d{2}-\d{2}|gbc\s*\||unknown$)',
    re.IGNORECASE,
)

# Strip leading emoji / Unicode pictograph characters from niche candidates.
_LEADING_EMOJI_RE = re.compile(
    r'^[\U0001F000-\U0001FFFF\U00002600-\U000027FF\U00002B00-\U00002BFF'
    r'\U0000FE00-\U0000FE0F\u200d]+\s*',
    re.UNICODE,
)

_DATE_LABEL_RE = re.compile(
    r'^(?:(?:\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)|'
    r'(?:\d{1,4}[-/]\d{1,2}[-/]\d{1,4}))'
    r'(?:\s+\d{1,2}:\d{2}(?:\s*[AP]M)?)?$',
    re.IGNORECASE,
)
_MONTH_DATE_LABEL_RE = re.compile(
    r'^(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
    r'jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|'
    r'nov(?:ember)?|dec(?:ember)?)\.?\s+\d{1,2}(?:,?\s+\d{2,4})?$',
    re.IGNORECASE,
)


def _is_date_label(value: str) -> bool:
    value = value.strip()
    return bool(_DATE_LABEL_RE.fullmatch(value) or _MONTH_DATE_LABEL_RE.fullmatch(value))


def _candidate(name: str, require_separator: bool) -> str | None:
    if not name:
        return None
    parts = []
    for part in name.split(" - "):
        parts.extend(piece.strip() for piece in part.split("|") if piece.strip())
    if len(parts) < 2 and require_separator:
        return None

    candidates = parts[1:] if len(parts) >= 2 else parts
    if "|" in name and " - " not in name:
        candidates = list(reversed(candidates))
    for part in candidates:
        candidate = _LEADING_EMOJI_RE.sub('', part).strip()
        if candidate and not _is_date_label(candidate) and not _NON_NICHE_RE.match(candidate):
            return candidate
    if len(parts) >= 2:
        candidate = _LEADING_EMOJI_RE.sub('', parts[0]).strip()
        if candidate and not _is_date_label(candidate) and not _NON_NICHE_RE.match(candidate):
            return candidate
    return None


def _extract_niche(adset_name: str, campaign_name: str = "", require_separator: bool = False) -> str | None:
    """Extract niche from ad set name pattern '[Date] - [Niche] - [Batch info]'.

    Returns None for empty names or when the extracted candidate looks like a
    batch/test label rather than a real niche. The caller stores None and the
    frontend displays it as 'General'.

    Leading emoji are stripped from the candidate. Set require_separator=True
    when callers need unstructured names grouped as General instead of using
    the whole ad set name as a best-effort niche.
    """
    # An ad set must have a structured separator when strict mode is enabled;
    # a campaign name is allowed to be a plain niche label such as
    # "Commercial Insurance".
    return _candidate(adset_name, require_separator) or _candidate(campaign_name, False)
