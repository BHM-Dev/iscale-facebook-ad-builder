"""RedTrack macro enforcement for Meta ads (ad-level url_tags).

Ad Builder historically did NOT set RedTrack tracking macros — sub1 was
populated only because Joel's saved URLs (or a RedTrack/Meta template) already
carried them. One production ad showed an unexpanded ``{{ad.id}}``. This helper
makes the app set the macros so ad-level attribution
(generated_ads.fb_ad_id -> RedTrack sub1) cannot silently drop.

IMPORTANT (Meta behavior): dynamic tags like {{ad.id}} are expanded by Meta
ONLY in the Ad-level ``url_tags`` field — NOT inside the creative's
``link_data.link``. Braces placed in the destination link are treated as literal
characters and never expand. So this module returns a ``url_tags`` query string
to set on the Ad object; it must NOT be folded into the destination URL.

Meta appends ``url_tags`` to the resolved landing URL at click time. It does not
de-duplicate, so we only emit macros for keys NOT already present in the
destination URL (to avoid ``sub1=X&sub1={{ad.id}}``).
"""
from urllib.parse import urlsplit, parse_qsl

# key -> Meta dynamic URL macro (literal braces, expanded by Meta at delivery)
REDTRACK_MACROS = {
    "sub1": "{{ad.id}}",
    "sub2": "{{adset.id}}",
    "sub3": "{{campaign.id}}",
}


def build_redtrack_url_tags(website_url: str) -> str:
    """Return an ``&``-joined url_tags string of RedTrack sub macros.

    Only includes macros whose key is not already present in ``website_url``'s
    query string. Returns "" when there is no valid http(s) destination URL
    (e.g. lead-gen flows) or when all sub keys are already present.
    """
    if not website_url or not isinstance(website_url, str):
        return ""
    stripped = website_url.strip()
    if not stripped.lower().startswith(("http://", "https://")):
        return ""

    parts = urlsplit(stripped)
    existing_keys = {k for k, _ in parse_qsl(parts.query, keep_blank_values=True)}

    additions = [
        f"{key}={macro}"
        for key, macro in REDTRACK_MACROS.items()
        if key not in existing_keys
    ]
    return "&".join(additions)
