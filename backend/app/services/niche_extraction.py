"""Shared niche extraction for ad set and campaign names."""
import re

# Patterns that indicate the extracted value is a batch/test tag, not a real niche.
# If the niche extraction produces one of these, fall back to None (displayed as "General").
_NON_NICHE_RE = re.compile(
    r'^(batch[\s\d]|set[\s\d]|v\d+[\s_.-]?$|v\d+[\s_.-]|scale|open$|image$|'
    r'calls$|test|broad|retarget|phase[\s\d]|round[\s\d]|breakout$|capi$|creative(?:\s+\d+)?$|abo$|cbo$|'
    # Account/brand and workflow labels are not verticals. In particular, RHO
    # campaign names contain ``RESOURCE HELP ONLINE`` beside the actual
    # campaign structure; treating it as a niche groups unrelated ads under a
    # misleading reporting label.
    r'rho\s*v?\d+(?:\s+account)?$|'
    r'resource\s+help\s+online(?:\s*[-/|]?\s*\(?rho\s*\d*\)?)?(?:\s+account)?$|'
    r'winners?\s+test(?:\s+v?\d+)?$|'
    # Delivery metadata appears in some breakout ad-set names between the
    # creative label and the campaign convention. It must never become a
    # reporting dimension (for example "$150/day").
    r'\$?\s*\d+(?:\.\d+)?\s*(?:/\s*)?(?:day|daily|d)$|'
    r'(?:daily\s*)?\$?\s*\d+(?:\.\d+)?$|'
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
    # Strict dashboard reporting only trusts the explicit ``date - niche -``
    # naming convention on an ad set. Pipe-delimited ad-set names are commonly
    # creative/budget wrappers; campaigns still accept their pipe convention.
    if require_separator and " - " not in name:
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


def _has_date_prefixed_hyphen_convention(name: str) -> bool:
    """Whether an ad-set name uses the explicit ``date - niche - ...`` format.

    This is the one ad-set convention that carries a reliably positioned niche.
    Other pipe-delimited ad-set names often contain creative labels, budgets, and
    test metadata; their campaign name is the authoritative niche source.
    """
    segments = (name or "").split(" - ", 1)
    first_segment = segments[0].strip()
    if not _is_date_label(first_segment) or len(segments) < 2:
        return False
    # A dated BREAKOUT wrapper still carries its niche in the campaign; do not
    # let its following creative/budget payload masquerade as the convention.
    next_label = segments[1].split("|", 1)[0].strip()
    return not _NON_NICHE_RE.match(next_label)


def _extract_niche(adset_name: str, campaign_name: str = "", require_separator: bool = False) -> str | None:
    """Extract niche from ad set name pattern '[Date] - [Niche] - [Batch info]'.

    Returns None for empty names or when the extracted candidate looks like a
    batch/test label rather than a real niche. The caller stores None and the
    frontend displays it as 'General'.

    Leading emoji are stripped from the candidate. Set require_separator=True
    when callers need unstructured names grouped as General instead of using
    the whole ad set name as a best-effort niche.
    """
    # Date-prefixed ad sets have a stable ``date - niche - ...`` contract, so
    # retain that explicit value even where the campaign is a generic wrapper.
    if _has_date_prefixed_hyphen_convention(adset_name):
        adset_niche = _candidate(adset_name, require_separator)
        if adset_niche:
            return adset_niche

    # Breakout ad sets contain creative and budget fragments (for example
    # ``BREAKOUT | CR-WIN-05 | $150/day | Oct 10``). The campaign convention
    # carries the actual niche, so prefer it before using an ad-set fallback.
    campaign_niche = _candidate(campaign_name, False)
    if campaign_niche:
        return campaign_niche

    # Preserve best-effort extraction for callers that explicitly allow it,
    # while Dashboard callers use strict mode and render ambiguous names as
    # General rather than inventing a misleading niche label.
    return _candidate(adset_name, require_separator)
