# Codex Brief — "Quick Generate" from a Winning Ad

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**Type:** Frontend-only. No backend, no migration, no trigger files. Reuses the existing `adId → BatchGenerate` full-prefill path.
**Push:** Codex commits locally → Claude Code reviews + pushes + validates in Chrome.

## Why
Joel's real workflow starts from a proven winner, not a blank wizard. The machinery to "start from a winning ad" already exists but is fragmented and buried:
- Campaign Performance ad rows have a **"More Variants"** button that navigates `/batch-generate?adId=...` — BatchGenerate then fetches the ad's creative and fully pre-fills headline, body, reference image, link URL, and overlay logo/offer, then **auto-triggers variant generation**. This IS a one-click quick-generate — it's just badly named and buried in the expanded ad breakdown.
- Dashboard "Iterate" (Top Performers) navigates `/batch-generate` with **adset-level params only (no `adId`)**, so it pre-fills niche only — not copy or image. It's not a true quick-generate.

Goal: make "start from a winner" a clear, prominent, one-click action in both places, reusing the existing adId path. **No new wizard, no new picker, no schema change.**

## Build

### 1. Campaign Performance — rename for discoverability (trivial)
In `frontend/src/pages/CampaignPerformance.jsx`, the ad-row **"More Variants"** button (~line 589-596, inside `AdsBreakdown`) already does the right thing. Rename its label to **"Quick Generate"** and give it a lightning `⚡`/`Zap` icon (lucide `Zap`, already used elsewhere — verify import). Behavior unchanged: still `navigate('/batch-generate?adId=...&adName=...&adsetName=...&campaignId=...&adsetId=...')`. Keep it on every ad row.

Do NOT touch the "Remix" button or the RemixDrawer "Build Ad ↗" flow — those stay as-is (they serve the copy-variation-then-wizard path).

### 2. Dashboard — make Top Performers "Iterate" a true Quick Generate
In `frontend/src/pages/Dashboard.jsx`:
- The "Iterate" button in the Top Performers table (~line 1007-1012) currently navigates with adset-level params only.
- Replace it with a **"Quick Generate"** button (`Zap` icon) that resolves the adset's **winning ad_id at click time**, then navigates to the full adId path.
- Resolve the winner: the Dashboard already fetches `/auto-pause/ads-bulk` is NOT currently loaded on Dashboard — check. If `adsBulk`/`ads-bulk` data is already in scope, use `adsBulk[fb_adset_id][0]` (index 0 = top ad by spend). If it is NOT already loaded on the Dashboard, fetch it on click for that account+date range: `GET /auto-pause/ads-bulk?<same insightsParams used elsewhere on the page>`, then pick `[fb_adset_id][0]`.
- On click:
  ```
  const topAd = adsForThisAdset?.[0];   // sorted by spend desc by the endpoint
  if (topAd?.ad_id) {
    navigate(`/batch-generate?adId=${topAd.ad_id}&adName=${enc(topAd.ad_name||'')}&adsetName=${enc(adsetName)}&campaignId=${enc(fb_campaign_id)}&adsetId=${enc(fb_adset_id)}`);
  } else {
    // graceful fallback: current adset-level behavior (niche-only prefill)
    navigate(`/batch-generate?adsetName=${enc(adsetName)}&adsetId=${enc(fb_adset_id)}&campaignId=${enc(fb_campaign_id)}`);
  }
  ```
  Use `encodeURIComponent` for every param. While the click-time fetch is in flight, show a spinner/disabled state on that row's button (reuse the existing per-row loading pattern if one exists; otherwise a local `useState` keyed by adset id). On fetch error → `showError` (useToast) AND still fall back to the adset-level navigate so the button never dead-ends.

### Target page: BatchGenerate (NOT ImageAds)
BatchGenerate is the bulk image tool, is the "gold standard for overlays" per CLAUDE.md, and already has the complete adId prefill + auto-variant-trigger wired. Do not route Quick Generate to ImageAds.

## Coherence / naming
- Use the same label **"Quick Generate"** + `Zap` icon in both places so it reads as one feature.
- Keep the existing adset-level "Iterate" semantics ONLY as the fallback path — the primary action is now ad-level Quick Generate.

## Patterns (mandatory)
- `authFetch` from `lib/facebookApi` (never raw fetch).
- `useToast` (`showError`) for errors (never alert).
- Match existing Tailwind button styling on each page (Dashboard buttons vs. Campaign Performance buttons differ — match the local neighbors).

## Verify before handing back
- `npm run build` passes.
- Campaign Performance: ad-row button now reads "Quick Generate", still lands in BatchGenerate fully pre-filled and auto-generating.
- Dashboard: Top Performers "Quick Generate" resolves a real `adId` and lands in BatchGenerate with headline/body/image pre-filled (not niche-only). Fallback works when an adset has no resolvable ad.
- No console errors; button shows a loading state during the click-time fetch.

## Claude Code will
Review (Haiku code + Joel-perspective), push to develop, validate live in Chrome (click Quick Generate from a Dashboard top performer, confirm BatchGenerate opens fully pre-filled and auto-generates variants).
