# Build Brief — Learning Loop Instrumentation

**Date:** 2026-07-17
**Source audit:** `AUDIT_learning_loop_data_path.md`
**Goal:** Make `generated ad → Meta ad → ad set/campaign → revenue/profit` a real, queryable join.
**Guiding principle:** The migration is the easy 10%. The unlock is recording `fb_adset_id` on every push and persisting the two flows that currently drop data. Ship the schema + instrumentation together, or the columns stay null.

---

## Phase 0 — RESOLVED (2026-07-17)

**Verified live against production** (`ad-builder-api`, `last_7d`): RedTrack `sub1` contains real Meta **ad-level** IDs.
- `/report/sub1`: 63 distinct ads, 62/63 valid 18-digit Meta ad IDs, 25 carrying revenue. (1 outlier = unexpanded `{{ad.id}}` macro on one ad.)
- `/report` (sub2): 19 ad sets. `sub1 ∩ sub2 = 0` — ad and ad-set key spaces are disjoint, confirming sub1 = ads.
- **63 ads / 19 ad sets ≈ 3.3 creatives per ad set** — Joel already runs multiple creatives per ad set.

**Decisions:**
- **Do NOT require one creative per ad set.** Ad-level attribution is live, so multiple creatives per ad set is fully supported.
- **Primary attribution join is ad-grain:** `generated_ads.fb_ad_id → RedTrack sub1`.
- `fb_adset_id` / `fb_campaign_id` remain useful for rollups/campaign views but are **not** the primary revenue/profit join.
- Because `fb_ad_id` is the join key, **no push path may leave `fb_ad_id` null when Meta returned an ad ID.**

---

## Phase 1 — Migration (Claude Code)

Additive columns on `generated_ads`. `down_revision = p4l2m8n9o1k7` (current head). Use `ADD COLUMN IF NOT EXISTS`, no `op.add_column()`.

```sql
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS angle          VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS source_ad_id   VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS profile_id     VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_campaign_id VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_adset_id    VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_creative_id VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS revenue        NUMERIC(10,2);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS profit         NUMERIC(10,2);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_generated_ads_fb_adset_id ON generated_ads (fb_adset_id);
```

- `niche` and `fb_ad_id` already exist — leave them. `fb_ad_id` is already indexed (`models.py:305`) — it is the **primary RedTrack sub1 join key**.
- `profile_id` intentionally **not** a hard FK (keep it a plain VARCHAR) to avoid an insert-order dependency; it mirrors how `niche` is stored loosely.
- `fb_creative_id` added so the write-back can persist the Meta creative ID where the push returns one.
- Add matching columns to the `GeneratedAd` SQLAlchemy model (`models.py:283`) — plain `Column`s, no new `relationship()`.
- Extend `GeneratedAdCreate` Pydantic schema (`generated_ads.py:99`) with `angle`, `sourceAdId`, `profileId`, `fbCampaignId`, `fbAdsetId`, `fbCreativeId` (camelCase in, snake_case on the model in `batch_save_ads` at `generated_ads.py:1069`).
- Run `python3 scripts/check_alembic_heads.py` — single head.

**Owner:** Claude Code (migration + models.py + main.py are never-push-for-Codex).

---

## Phase 2 — Instrument the push paths (Claude Code — touches trigger files)

This is the real work. Every successful push must record **`fb_ad_id`** (the RedTrack sub1 join key — highest priority), plus `fb_adset_id`, `fb_campaign_id`, and `fb_creative_id` where available, onto the `GeneratedAd`. The ad-set/campaign IDs are already selected in every push modal — they just aren't being persisted.

**Hard invariant (the 2-agent review must verify this):** if Meta returns an ad ID from a push, the corresponding `GeneratedAd.fb_ad_id` must be non-null afterward. No successful push may leave a generated ad unlinked. This applies to all three push paths.

### 2d. Enforce RedTrack macros via the creative's `url_tags` (NOT the link)
RedTrack `sub1` is populated today only because Joel's URLs / a RedTrack template already carry the macros — Ad Builder does not set them, and one ad in production showed an unexpanded `{{ad.id}}`. Make the app set them so tracking can't silently drop.

**Critical Meta detail (verified against the live SDK, 2026-07-17):** Meta expands `{{ad.id}}` / `{{adset.id}}` / `{{campaign.id}}` **only** in the creative's `url_tags` field (`AdCreative.Field.url_tags`) — NOT inside `link_data.link`. Braces in the link are literal text and never expand (this is the exact production bug). There is **no** `url_tags` field on the `Ad` object in this SDK; it lives on the **creative**. Meta appends `url_tags` to the clicked URL at delivery time.

Implementation (shipped):
- Helper `build_redtrack_url_tags(website_url) -> str` (`app/core/redtrack_macros.py`) returns an `&`-joined macro string for keys **not already present** in the destination URL (Meta does not de-dupe, so we avoid `sub1=X&sub1={{ad.id}}`).
- Set in `facebook_service.create_creative` as `params[AdCreative.Field.url_tags]` — the single choke point both push paths (`/facebook/creatives` and `push-to-meta`) route through with `website_url`.
- **Lead-gen / URL-less flows:** helper returns `""` (no valid http URL) → no `url_tags` set. Meta lead forms have no click URL; lead-gen attribution relies on Meta's native lead tracking, not RedTrack subs.
- Existing params preserved (parsed via `urlsplit`/`parse_qsl`); never string-concatenated. Failures are logged, never block a push.

### 2a. Batch push (`BatchPushModal.jsx`) — already links `fb_ad_id`, add adset/campaign
- At `BatchPushModal.jsx:263`, the write-back PATCH already fires. Extend the body to also send `fb_adset_id` and `fb_campaign_id` (both known in the modal — `targetAdsetId`, `campaignId`).
- **Fix the silent failure:** the current `.catch(() => {})` (fire-and-forget) means a failed link is invisible. Change to surface a non-blocking toast/warning so a broken loop is noticed. Do not block the push on it.
- Extend `PATCH /generated-ads/{id}/fb-ad-id` (`generated_ads.py:1112`) to accept and persist `fb_adset_id`, `fb_campaign_id` alongside `fb_ad_id`. Keep it backward-compatible (all optional).

### 2b. Single push (`PushToMetaModal.jsx`) — currently orphaned
- Add a `generatedAdId` prop to `PushToMetaModal` (`PushToMetaModal.jsx:25`).
- After a successful `createCompleteAd` (`PushToMetaModal.jsx:184`), if `generatedAdId` is present, call the same extended write-back PATCH with `fb_ad_id` (`result.adId`), `fb_adset_id` (`targetAdsetId`), `fb_campaign_id`.
- Pass `generatedAdId` from both callers: `ImageAds.jsx:2381` (Quick Generate result) and `GeneratedAds.jsx:987` (single push).
- If a push flow has no saved `GeneratedAd` yet (Quick Generate may push before batch-save), save it first via `POST /generated-ads/batch`, then link. Confirm ImageAds' Quick Generate actually persists the ad before push — if not, add that save.

### 2c. Remix push (`AdRemix.jsx` → `POST /facebook/push-to-meta`) — fully orphaned
- The concept is never saved as a `GeneratedAd`. Two changes:
  1. Before/after push, persist the concept via `POST /generated-ads/batch` with brand/niche/angle/`source_ad_id` (the winning ad it was remixed from — available in the remix context) + overlay fields.
  2. Extend `POST /facebook/push-to-meta` (`facebook.py:902`) to accept an optional `generated_ad_id`; on success, set `fb_ad_id`/`fb_adset_id`/`fb_campaign_id` on that record server-side (cleaner than a second round-trip). `adset_id` is already in the request body.
- `source_ad_id` carries remix provenance — this is what answers "does remixing winners produce winners."

**Owner:** Claude Code. `facebook_service.py` is a trigger file; `BulkAdCreation`/`AdCreativeStep` may be adjacent. Mandatory 2-agent review (Haiku code logic + **Sonnet** Meta API correctness) before push. Sonnet must verify no Meta field/enum regressions in the `push-to-meta` and creative payloads.

---

## Phase 3 — Perf-sync onto the creative (Claude Code) — AD-LEVEL

Reuse the existing 30-min RedTrack refresh (`scheduler_service.py` + `redtrack_service.py`).

- **Join at ad grain:** `generated_ads.fb_ad_id → RedTrack sub1` (via `get_report_by_sub(df, dt, group_field='sub1')`, `redtrack_service.py:154`). This gives true per-creative revenue/profit and works with multiple creatives per ad set — no even-split estimation needed.
- Write `revenue`, `profit`, `last_synced_at` back onto each `GeneratedAd` that has an `fb_ad_id` present in the sub1 report.
- Consider a parallel `redtrack_sub1_cache` (mirror of `redtrack_cache` but keyed on ad ID) if the sync needs a persisted ad-level table; otherwise sync directly onto `generated_ads`.
- `fb_adset_id`/`fb_campaign_id` remain available for rollups (group generated ads by adset/campaign) but are not needed for the primary revenue join.
- This is read-mostly backend; single Haiku review is sufficient (no trigger files if isolated to the scheduler/service).

---

## Phase 4 — Surface it (Codex, later)

Once columns populate:
- Add `Angle`, `Revenue`, `Profit` columns to the Generated Ads gallery (`GeneratedAds.jsx`), sortable.
- "Top angles by profit" rollup — group `generated_ads` by `angle`, sum `profit`, min-spend guard.
- Feeds back into the Angle Picker: weight/reorder angles by realized profit.

**Owner:** Codex (pure UI once the data exists). No trigger files.

---

## Build order & ownership

| Phase | What | Owner | Review |
|-------|------|-------|--------|
| 0 | ✅ RESOLVED — RedTrack sub1 = live ad-level IDs | — | — |
| 1 | Migration + model + schema | Claude Code | 1 Haiku (schema) |
| 2 | Instrument 3 push paths + macro enforcement | Claude Code | 2-agent (Haiku + Sonnet API) |
| 3 | Ad-level perf-sync via RedTrack sub1 | Claude Code | 1 Haiku |
| 4 | Gallery columns + angle rollup | Codex | — |

**Do not ship Phase 1 alone.** Without Phase 2 the new columns stay null for every push. Phases 1+2 land together or the audit's core finding isn't fixed.

## Open questions (resolve during Phase 2 build)
1. ~~Creatives-per-ad-set convention~~ — RESOLVED: multiple per ad set, ad-level attribution live.
2. Does ImageAds Quick Generate persist a `GeneratedAd` before push, or only on batch-save? Determines whether 2b needs an extra save call. (Confirm in code during build.)
3. Is `source_ad_id` reliably in scope in the AdRemix context at push time? (It should be — remix starts from a winning ad — but confirm the variable is threaded to the push handler.)
