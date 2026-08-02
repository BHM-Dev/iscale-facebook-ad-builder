# Codex Brief — Ad Library Import: snippet fix + 2 review findings

Context: the Chrome-assisted Ad Library Import feature (`/research/ad-library-import`, migration `v0r8s4t5u7q3`, `Research.jsx` import modal) shipped in commit `2d31732` on `develop` and is live in production. Two things surfaced after shipping that need cleanup — one real bug, two minor correctness gaps flagged in pre-push review but not blocking.

No DB migration needed for any of this. No trigger files touched. Safe for Codex to commit locally; final push still goes through Claude Code per the repo's push protocol.

---

## 1. Fix broken brand/page-name extraction in the capture snippet (real bug)

**File:** `backend/scripts/ad_library_capture_snippet.js`

**The bug:** the snippet splits `document.body.innerText` on `"Library ID:"` and treats the first non-metadata line in each chunk as the page name. In production this fails — it picks up UI chrome like `"Platforms"` as the brand name instead of the actual advertiser (e.g. "Freeway Insurance", "OTTO Insurance"). Verified live on `facebook.com/ads/library` today: `getLineAfter(lines, "Page ID")` never matches (that label doesn't appear in rendered cards), so it falls through to `lines.find(line => !/^Library ID:/.test(line) && !/^Started running/.test(line))`, which grabs whatever text line happens to come first — usually a filter-chrome label, not the page name.

**The fix:** don't split `body.innerText` at all — walk the DOM directly. Each ad card has a `Library ID:` marker as a small leaf-ish element; its ancestor 4 levels up is the full card container. The page/brand name is reliably the line immediately before the literal `"Sponsored"` line in that container's `innerText`. This was tested live against ~470 real search results and correctly extracted every brand name (Freeway Insurance, OTTO Insurance, Cheap Auto Quotes, Save Max Auto, individual agent names, etc.) with zero misses across 49 cards.

Replace the whole IIFE body with this logic (keep the same download-a-JSON-file behavior at the end):

```js
/*
Paste this into Chrome DevTools Console while viewing Facebook Ad Library.
It downloads a JSON capture that can be pasted into Research > Import Intel.

Required page setup:
- Country: United States
- Status: Active ads
- Sort: Most impressions
- Query: "cheap auto insurance" or "auto insurance"
*/
(() => {
  // Find every "Library ID:" marker, then walk up to the card container
  // (4 ancestor levels up is where the full card's rendered text lives —
  // verified against facebook.com/ads/library's current DOM structure).
  const markers = Array.from(document.querySelectorAll('*')).filter(e => {
    const t = e.textContent && e.textContent.trim();
    return t && t.startsWith('Library ID:') && e.children.length < 3 && t.length < 60;
  });

  const cardRoots = new Set();
  for (const m of markers) {
    let node = m;
    for (let i = 0; i < 4 && node.parentElement; i++) node = node.parentElement;
    cardRoots.add(node);
  }

  const seen = new Set();
  const ads = [];
  for (const root of cardRoots) {
    const lines = root.innerText.split('\n').map(l => l.trim()).filter(Boolean);
    const idLine = lines.find(l => l.startsWith('Library ID:'));
    if (!idLine) continue;
    const libraryId = idLine.replace('Library ID:', '').trim().split(/\s+/)[0];
    if (!libraryId || seen.has(libraryId)) continue;
    seen.add(libraryId);

    const startedLine = lines.find(l => /^Started running on/i.test(l));
    const started = startedLine ? startedLine.replace(/^Started running on /i, '').trim() : '';
    const sponsoredIdx = lines.findIndex(l => l === 'Sponsored');
    const page = sponsoredIdx > 0 ? lines[sponsoredIdx - 1] : '';
    const multipleVersions = lines.some(l => /this ad has multiple versions/i.test(l));
    const ctaLabels = ['Get Quote', 'Get quote', 'Get offer', 'Call Now', 'Call now', 'Sign Up', 'Contact Us', 'Learn More', 'Shop Now', 'Send Message'];
    const ctaIdx = lines.findIndex(l => ctaLabels.includes(l));
    const cta = ctaIdx >= 0 ? lines[ctaIdx] : '';
    const bodyStart = sponsoredIdx >= 0 ? sponsoredIdx + 1 : 0;
    const bodyEnd = ctaIdx >= 0 ? ctaIdx : lines.length;
    const body = lines.slice(bodyStart, bodyEnd).join(' ').slice(0, 5000);
    const domainLine = lines.find(l => /^[A-Z0-9.-]+\.[A-Z]{2,}(\/[A-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]*)?$/i.test(l));

    ads.push({
      library_id: libraryId,
      page,
      body_preview: body,
      cta,
      domain: domainLine || '',
      started_running: started,
      multiple_versions: multipleVersions,
      rank_position: ads.length + 1,
      media_type: /Video player|Play video/i.test(root.innerText) ? 'video' : 'image',
    });
  }

  const videos = Array.from(document.querySelectorAll('video')).map((video, index) => ({
    index,
    url: video.currentSrc || video.src || '',
    poster: video.poster || '',
    width: video.videoWidth || null,
    height: video.videoHeight || null,
  })).filter(video => video.url || video.poster);

  const payload = {
    captured_at: new Date().toISOString(),
    page_url: location.href,
    query: new URLSearchParams(location.search).get('q') || '',
    country: new URLSearchParams(location.search).get('country') || 'US',
    sort_mode: 'total_impressions_desc',
    visible_ads: ads,
    videos,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `ad-library-capture-${Date.now()}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  console.log(`Captured ${ads.length} unique ad cards and ${videos.length} video elements. Paste the downloaded JSON into Ad Builder > Research > Import Intel.`);
})();
```

Note the DOM structure (`4 ancestor levels`, class names like `xh8yej3`) is Facebook's atomic CSS — it's not stable long-term, but the "walk up from the Library ID marker" approach is more resilient than the old text-splitting approach because it doesn't depend on line-order guessing. If FB changes their DOM again, the marker/ancestor depth is the first thing to re-verify (test in DevTools: `document.querySelectorAll('*')` filtered for `Library ID:` text, then check parentElement chain length until `innerText.length` roughly matches one visible card, ~700-1200 chars).

**Also update** the two other copies of this same broken extraction logic:
- `backend/scripts/ad_library_prepare_import.py` — check if it duplicates the same line-splitting brand-name logic server-side; if so, apply the equivalent fix (or just note that the Python script consumes the JSON the snippet produces, so fixing the snippet alone may be sufficient — verify before touching).

---

## 2. Content-hash collision risk (medium, from pre-push review)

**File:** `backend/app/api/v1/research.py:45-63` (`_ad_library_content_hash`)

Current code joins fields with `"|"` and no escaping:

```python
raw = "|".join([
    f"ad_library:{external_id}",
    (brand_name or "").strip().lower(),
    (headline or "").strip().lower(),
    (ad_copy or "").strip().lower(),
    (cta_text or "").strip().lower(),
    (destination_domain or "").strip().lower(),
])
```

Two different ads whose field values happen to contain `|` in different places can produce identical concatenated strings (e.g. `brand="Brand|X", headline="Y"` vs `brand="Brand", headline="X|Y"` both give `...brand|x|y...`). This doesn't break current dedup (that's keyed on `external_id`, not content_hash), but it's a latent flaw worth closing.

**Fix:** hash a JSON-encoded structure instead of a raw pipe-join, e.g.:

```python
import json

def _ad_library_content_hash(external_id, brand_name, headline, ad_copy, cta_text, destination_domain) -> str:
    payload = {
        "external_id": external_id,
        "brand_name": (brand_name or "").strip().lower(),
        "headline": (headline or "").strip().lower(),
        "ad_copy": (ad_copy or "").strip().lower(),
        "cta_text": (cta_text or "").strip().lower(),
        "destination_domain": (destination_domain or "").strip().lower(),
    }
    raw = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
```

`json.dumps` escapes embedded quotes/special chars so two different field splits can no longer collide.

---

## 3. `unmapped_video_inventory_count` always reports total, not actual unmapped (medium, from pre-push review)

**Files:** `frontend/src/pages/Research.jsx:80` and `backend/app/api/v1/research.py:827-833`

Frontend currently sets, for every ad in a capture batch:

```js
unmapped_video_inventory_count: videos.length,  // total videos captured on the page, not "unmapped"
```

This means if a capture had 10 ads and 10 videos where 5 videos successfully mapped to their ad via `ad_library_id`, every ad still reports `unmapped_video_inventory_count: 10` — the field name promises "unmapped" but delivers "total observed." The backend then takes the `max()` of this across all ads for the `quality.unmapped_video_inventory` summary shown in the success toast, so the number shown to Joel/Saule is misleadingly high.

**Fix (frontend):** compute the actual unmapped count once per import, not per-ad — videos in the top-level `videos` array that never matched any ad's `library_id`:

```js
const mappedVideoUrls = new Set(
  sourceAds.flatMap(ad =>
    videos.filter(v => v.ad_library_id && v.ad_library_id === ad.library_id).map(v => v.url)
  )
);
const unmappedVideoCount = videos.filter(v => v.url && !mappedVideoUrls.has(v.url)).length;
```

Then set `creative_intel.unmapped_video_inventory_count: unmappedVideoCount` (same value for every ad in the batch is fine — it's a batch-level stat, just make it correct).

No backend change needed for this one — `research.py:827-833`'s `max()` logic is fine once the input value is correct.

---

## Not in scope for this brief (flagging for Steve, not Codex)

There's a second, older "Auto insurance" vertical row in the DB (lowercase "insurance", created 2026-03-16, `id=59242e13-...`) sitting orphaned outside the current Research UI, separate from the "Auto Insurance" vertical the UI now reads from (`id=bc0d6349-...`). It holds ~19 legacy saved ads from before this feature was rebuilt. Merging it into the current vertical is a data decision, not a code fix — don't touch it without Steve's sign-off.

## Test plan for Codex

1. Run the fixed capture snippet in DevTools against `facebook.com/ads/library/?q=auto%20insurance%20cheap&country=US&active_status=active` (or any live Ad Library search) — confirm the downloaded JSON's `visible_ads[].page` values are real advertiser names, not `"Platforms"` or other UI chrome.
2. Unit-test or manually verify `_ad_library_content_hash` no longer collides on the pipe-escaping example above.
3. Import a small test capture via the UI and confirm the success toast's "X unmapped videos observed" number matches the actual count of videos with no matching `ad_library_id`, not the raw video count.
