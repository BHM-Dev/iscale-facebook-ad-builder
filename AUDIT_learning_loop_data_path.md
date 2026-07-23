# Audit — Generated Ad → Meta → Performance Data Path

**Date:** 2026-07-17
**Scope:** Read-only. Can we join `generated ad → pushed Meta ad → ad set/campaign → spend/leads/revenue/profit`?
**Verdict:** ❌ **Not today.** The chain breaks in two places: (1) two of three push paths never link the Meta ad ID back, and (2) even when it *is* linked, the link is at **ad grain** while all revenue/spend lives at **ad-set grain** — and `GeneratedAd` stores no ad-set/campaign ID to bridge them.

---

## 1. Where is `fb_ad_id` written back after Push to Meta?

There are **three** distinct push paths. Only one links back.

| Path | Entry point | Endpoint | Writes `fb_ad_id` back? |
|------|-------------|----------|--------------------------|
| **Batch push** | `BatchPushModal.jsx:263` | `PATCH /generated-ads/{id}/fb-ad-id` | ✅ Yes — but **fire-and-forget** (`.catch(() => {})`, silent on failure) |
| **Single push** | `PushToMetaModal.jsx` | `createCompleteAd` → returns `adId` | ❌ No — modal has no `generatedAdId` prop; `adId` only stored in local state + `lastUsed*` localStorage |
| **Remix push** | `AdRemix.jsx:507` | `POST /facebook/push-to-meta` | ❌ No — endpoint (`facebook.py:902`) never persists or links a `GeneratedAd` at all |

**Write-back endpoint:** `generated_ads.py:1112` — `PATCH /{ad_id}/fb-ad-id`, sets `ad.fb_ad_id` (`generated_ads.py:1131`). Sound, but only the batch path calls it.

**Who uses which modal:**
- `ImageAds.jsx:2381` → `PushToMetaModal` → **orphaned** (Quick Generate ads pushed here are never linked)
- `GeneratedAds.jsx:987` → `PushToMetaModal` (single) → **orphaned**; `GeneratedAds.jsx:1003` → `BatchPushModal` (batch) → linked
- `BatchGenerate.jsx:1159` → `BatchPushModal` → linked (`generatedAdId` set at `BatchGenerate.jsx:1149`)
- `AdRemix.jsx` → inline `POST /facebook/push-to-meta` → **orphaned**, and the concept is never saved as a `GeneratedAd` in the first place

**Consequence:** The most-promoted new workflow (Quick Generate in ImageAds) and the entire Remix flow produce **zero** attributable records.

---

## 2. Does every generated ad keep brand/product/profile/niche/angle/source metadata?

`GeneratedAd` model (`models.py:283`):

| Field | Stored? | Notes |
|-------|---------|-------|
| `brand_id` | ✅ | FK, `models.py:287` |
| `product_id` | ✅ | FK, `models.py:288` |
| **profile_id** | ❌ | Never stored on the generated ad |
| `niche` | ✅ | `models.py:307` (free-text, e.g. "Religious organizations") |
| **angle** | ❌ | Not on the model. Angle Picker templates (just shipped) are not persisted |
| **source_ad_id** | ❌ | Remix provenance (which winning ad it came from) is lost |
| `template_id` | ✅ | FK → `winning_ads`, `models.py:289` |
| `fb_ad_id` | ✅ (indexed) | `models.py:305` — but only populated by the batch path (see §1) |
| overlay fields | ✅ | niche_line / offer_line / cta / logo_url |

**Caveat:** Even the fields that exist are only captured on the **batch-save path** (`POST /generated-ads/batch`, `generated_ads.py:1069`). The Remix push never creates a `GeneratedAd`, so its brand/niche/angle are gone regardless.

---

## 3. Can dashboard/performance data be joined back to generated ads?

**No — grain mismatch is the core problem.**

- `GeneratedAd` links to **`fb_ad_id`** (ad grain).
- All performance/revenue is keyed at **`fb_adset_id`** (ad-set grain):
  - RedTrack ground truth → `RedTrackCache.fb_adset_id` (`models.py:573`)
  - Meta live insights → keyed by `fb_adset_id` (`facebook_service.py:924` `get_account_insights_bulk`)
  - Dashboard niche-summary → aggregates the above by niche (`dashboard.py:49`)
- `GeneratedAd` has **no `fb_adset_id` and no `fb_campaign_id`**, so there is no key to bridge ad → ad set.

**Bridge options:**
1. **Store `fb_adset_id` + `fb_campaign_id` on `GeneratedAd` at push time** (both are already in hand inside all three push flows — the modal knows the target ad set). *Recommended.*
2. Derive ad→adset from Meta (`FacebookAd.adset_id` exists, `models.py:206`), but `facebook_ads` is only populated by `POST /facebook/creatives` (`facebook.py:598`) — **not** by `push-to-meta` or `BatchPushModal`, so it is not a reliable local bridge.

Until one of these lands, the dashboard can report performance **by niche/ad set** but can never answer *"which generated creative / which angle drove this revenue."*

---

## 4. Where does revenue come from today?

Two sources, both **ad-set grain, neither stored on the creative**:

1. **RedTrack (ground truth)** — `redtrack_service.py:86` `get_report_by_adset`, grouped by `sub2 = fb_adset_id`. Returns `conversions, revenue, cost, profit, roas, cpl, quality_rate`. Cached every 30 min in `redtrack_cache` (`models.py:568`). **This is the real money data** and it already computes `profit`.
2. **Meta insights (secondary)** — `action_values` for pixel purchase, falling back to lead value (`facebook_service.py:887–902`). Live per-query, not persisted.

`session_id` passthrough note: RedTrack keys on `sub2 = fb_adset_id`, so attribution granularity from the money side is capped at ad-set level unless a finer sub is introduced at push time.

---

## 5. What DB fields are missing for a learning loop?

On **`GeneratedAd`**, to close the loop:

| Field | Why |
|-------|-----|
| `angle` | The whole point — "which angle wins." Not captured anywhere today |
| `source_ad_id` | Remix provenance — did remixing winner X produce winners? |
| `profile_id` | Audience attribution |
| `fb_adset_id` | **Bridge to all revenue/spend data (adset grain)** — highest priority |
| `fb_campaign_id` | Campaign rollups |
| `revenue`, `profit` | Optional denormalized snapshot (can be derived by joining `redtrack_cache` on `fb_adset_id` once that column exists) |
| `last_synced_at` | Marks when perf snapshot was last refreshed onto the record |

Plus a **behavioral fix, not a schema fix**: make the Remix and single-push paths (a) persist a `GeneratedAd` and (b) call the write-back — otherwise new columns stay null for the two busiest flows.

---

## 6. Minimal migration

Current head: **`p4l2m8n9o1k7`** (our vertical/angles migration). New `down_revision` = `p4l2m8n9o1k7`.

All additive columns on `generated_ads` — use the `ADD COLUMN IF NOT EXISTS` pattern, no `op.add_column()`:

```sql
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS angle          VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS source_ad_id   VARCHAR;   -- Meta ad_id of the winner remixed from
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_campaign_id VARCHAR;
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_adset_id    VARCHAR;   -- add index — join key to redtrack_cache
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS revenue        NUMERIC(10,2);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS profit         NUMERIC(10,2);
ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_generated_ads_fb_adset_id ON generated_ads (fb_adset_id);
```
(`niche` and `fb_ad_id` already exist — no migration needed for those.)

**Migration alone does not create the join.** It must ship with three code changes, or the columns stay null:
1. **Push flows write `fb_adset_id` + `fb_campaign_id`** (and `fb_ad_id`) at push time — in `BatchPushModal`, `PushToMetaModal`, and the `/facebook/push-to-meta` endpoint. The ad-set/campaign IDs are already selected in every push modal.
2. **Remix + single-push paths persist a `GeneratedAd`** and call the write-back (today they don't).
3. **A perf-sync job** (reuse the 30-min RedTrack refresh) joins `generated_ads.fb_adset_id → redtrack_cache.fb_adset_id`, writes `revenue`/`profit`/`last_synced_at` back onto the creative.

---

## Recommended sequence

1. **Migration** (above) — additive, low risk. Claude Code.
2. **Instrument push paths** to populate `fb_adset_id`/`fb_campaign_id`/`fb_ad_id` on every push — this is the real unlock. Touches `facebook_service.py` + trigger files → 2-agent review.
3. **Persist Remix concepts as GeneratedAd** so the two busiest flows stop dropping data.
4. **Perf-sync** onto the creative via the existing RedTrack cache job.
5. Only then does "which angle/niche/creative drove profit" become a real query.

**Grain reality:** revenue attribution is capped at **ad-set** granularity (RedTrack `sub2 = fb_adset_id`). One creative per ad set = clean attribution. Multiple creatives per ad set = revenue can't be split by creative without a finer RedTrack sub introduced at push time. Worth deciding the intended creatives-per-adset convention before building.
