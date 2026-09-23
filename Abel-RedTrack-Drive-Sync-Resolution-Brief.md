# Abel / RedTrack URL + Drive Sync Resolution Brief

## 1. Executive summary

Two separate problems were mixed together:

1. **RedTrack destination URL launch failure:** the existing frontend required an absolute HTTP(S) URL, while the backend used a loose `startswith("http")` check. The exact Slack error and pasted URL are unavailable because the attached screenshot was intentionally not opened, so the original incident cannot be reproduced conclusively. The safe fix is now implemented: clipboard zero-width characters and surrounding whitespace are normalized, HTTP(S) plus hostname are validated in the browser and API, and malformed URLs fail before Meta writes begin.
2. **Campaign-wide URL request:** the Drive bulk-review flow previously exposed only row-level destination editing once each creative had its own Drive metadata. It now has one explicit campaign-wide URL field with an “Apply to selected ads” action. Individual rows remain editable afterward for legitimate exceptions.
3. **Drive naming proposal:** naming is a matching key, not the source of copy truth. Keep the resolver fail-closed and standardize the minimum filename contract below; use a handoff manifest when copy, landing page, CTA, or multiple visual concepts need to be explicit.

Economically, this removes repeated URL paste work across 10–100-ad batches and prevents a bad URL from consuming Meta image uploads, creative creation, or ad-set budget before failure.

## 2. Flow diagrams

### URL launch

```text
Paste URL
  -> normalize clipboard whitespace / invisible characters
  -> browser validates http(s) + hostname
  -> bulk review validates each selected row
  -> API validates again
  -> Meta image upload -> creative -> ad
```

### Drive creative identity

```text
stable creative stem + placement token
  -> pair 1x1 with matching 9x16
  -> use manifest/copy document for copy truth
  -> persist source Drive IDs + verification state
  -> picker shows only launchable pairs
```

## 3. Detailed spec / copy

Implemented UI copy:

> **Campaign-wide destination URL**  
> Paste one RedTrack or landing-page URL and apply it to every selected ad. You can still edit an individual row afterward.

The action applies only to included, non-protected rows. It marks the URL as a deliberate row override so a later Drive refresh does not silently replace it.

Recommended filename convention:

```text
<creative-id>--<short-concept>--1x1.png
<creative-id>--<short-concept>--9x16.png
```

Examples:

```text
PAINTER-01--before-after--1x1.png
PAINTER-01--before-after--9x16.png
```

Do not put primary text, headline, or landing URLs in filenames. Those belong in the copy document or handoff manifest.

## 4. Routing / decision logic

| Condition | Behavior |
|---|---|
| Complete `http://` or `https://` URL | Accept and continue to review/launch |
| URL has clipboard whitespace or zero-width/BOM characters | Normalize, then validate |
| Missing scheme, malformed host, or non-HTTP scheme | Block with actionable warning |
| Campaign-wide URL applied | Set URL on every selected, non-protected row |
| Row edited after campaign-wide apply | Preserve row-specific URL |
| Drive copy/media naming is ambiguous | Keep fail-closed; require rename or manifest repair |

## 5. Integration specs

- Frontend helper: `frontend/src/lib/destinationUrl.js`.
- Bulk launch: `BulkAdCreation.jsx` normalizes row URLs and adds campaign-wide application.
- Creative step: global URL validation now uses the same exact HTTP(S)+hostname rule.
- Backend: `FacebookService.create_creative()` rejects malformed/non-HTTP(S) destinations with a useful error before calling Meta.
- RedTrack macro builder: accepts only valid HTTP(S) URLs and remains non-throwing for bad input.
- Tracking macros remain in Meta creative `url_tags`; this change does not rewrite the pasted destination URL or alter RedTrack parameter semantics.

## 6. Tracking & analytics spec

No new database fields or analytics events are required for this MVP. Existing launch/reconciliation records continue to capture the per-ad URL sent to Meta. Phase 2 should add an event for `campaign_url_applied` with row count and URL host, excluding query-string values to avoid logging tracking identifiers.

## 7. Build priority / phased rollout

### Ready for review

- URL normalization and exact validation at browser/API boundaries.
- Campaign-wide URL apply control for Drive bulk launches.
- Naming convention decision and fail-closed guidance documented here.

### Phase 2 directional

- Add a “URL source: campaign / Drive / row override” badge to each review row.
- Add a copy-health report that lists unmatched filenames and the exact expected stem.
- Add a preflight endpoint that validates the full selected batch without uploading media to Meta.

## 8. Open questions & dependencies

- The exact Abel screenshot error and pasted URL are still needed to prove whether the original failure was a missing scheme, invisible clipboard character, unsupported RedTrack URL shape, or a Meta-side rejection.
- A real paused test ad should verify how duplicate existing `sub1`/`sub2`/`sub3` parameters interact with `url_tags`; this brief intentionally does not change that behavior.
- Steve, Abel, and Joel should approve the filename convention before asking publishers/designers to rename existing Drive assets.
