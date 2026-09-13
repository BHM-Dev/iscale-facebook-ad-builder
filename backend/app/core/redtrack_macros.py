"""RedTrack macro enforcement for Meta ads (ad-level url_tags).

Ad Builder historically did NOT set RedTrack tracking macros — sub1 was
populated only because Joel's saved URLs (or a RedTrack/Meta template) already
carried them. One production ad showed an unexpanded ``{{ad.id}}``. This helper
makes the app set the macros so ad-level attribution
(generated_ads.fb_ad_id -> RedTrack sub1) cannot silently drop.

IMPORTANT (Meta behavior), CORRECTED 2026-09-13: Meta expands dynamic tags like
{{ad.id}} in BOTH the ad-level ``url_tags`` field AND the destination link.

This file previously asserted the opposite — that braces in ``link_data.link``
are literal characters that never expand — and reasoned from it. That was wrong,
and the correction matters because the false version makes stripping subs out of
the destination link look harmless. It is not. Live evidence, from the
``facebook_ads.website_url`` column in production:

    https://go.getfbquotes.com/<offer-id>?sub1={{ad.id}}&sub2={{adset.id}}
      &sub3={{campaign.id}}&sub4={{ad.name}}&sub5={{adset.name}}
      &sub6={{campaign.name}}&sub7={{placement}}&sub8={{site_source_name}}

``sub4``-``sub8`` exist ONLY in the link — ``url_tags`` never carries them — and
those values arrive populated downstream (ad name, ad set name, placement). If
link braces did not expand they would all be literal ``{{ad.name}}``. They are
not. The "one production ad showed an unexpanded {{ad.id}}" anecdote that
motivated this file is far better explained by the missed link update behind the
2026-08-06 incident than by a platform rule contradicted by every other ad.

CONSEQUENCE — do not "fix" a bad link in code. Standing instruction from Steve
(2026-09-13): this tool does not touch destination-link formatting. Appending a
missing macro through ``url_tags`` is the entire mandate. A WRONG value in a
saved link is repaired by a human in Meta's UI, per
``Tracking-Link-Checklist.md`` in the repo root, which is what Joel and Abel
work from. A strip implemented here would have deleted five working tracking
params.

KNOWN GAP: when the destination URL already carries a WRONG value, the click
arrives with the key twice (``sub2=<wrong>&sub2={{adset.id}}``) because Meta
appends ``url_tags`` without de-duplicating, and which one RedTrack honours has
not been tested. So treat this as "correct macros are always PRESENT", not as a
repair of a bad saved URL. Absent keys — the common case — are fixed outright
either way. The duplicate is deliberately left alone rather than resolved by
rewriting the link; see CONSEQUENCE above.

The precedence question would be settled by pushing one test ad and reading
which value lands in RedTrack — worth doing, but it only affects links that are
already wrong. The bug this guards against is real: on 2026-08-06 three live
campaigns ran with ``sub2={{campaign.id}}``, which cost RedTrack every dollar of
spend attribution on them while revenue kept flowing; the same macro defect left
$3,254 of Everflow revenue unattributed in the August P&L.
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

    Includes macros whose key is absent or present with an unexpected value.
    Returns "" when there is no valid http(s) destination URL (e.g. lead-gen
    flows) or when all sub keys are already present with the correct macro.
    """
    if not website_url or not isinstance(website_url, str):
        return ""
    stripped = website_url.strip()
    if not stripped.lower().startswith(("http://", "https://")):
        return ""

    parts = urlsplit(stripped)
    existing = {}
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        existing.setdefault(key, []).append(value)

    additions = [
        f"{key}={macro}"
        for key, macro in REDTRACK_MACROS.items()
        if existing.get(key) != [macro]
    ]
    return "&".join(additions)
