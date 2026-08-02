# Ad Library Intel Import Tutorial

## Goal

Use Facebook Ad Library examples to teach the video workflow what strong auto-insurance ads look like. The goal is not to copy competitor ads. The goal is to save examples with clear hooks, CTAs, pacing, and visual structure so BHM can generate better owned creative.

## Who This Is For

- Joel reviews the flow first and decides what is useful.
- Saule can later run the search/import/save process once Joel approves the workflow.
- Codex/Claude use the saved examples to build scripts, video prompts, and quality rubrics.

## Search Setup

Use Chrome and open Facebook Ad Library.

Default search:

```text
cheap auto insurance
```

Alternate search:

```text
auto insurance
```

Always use:

- Country: United States
- Status: Active ads
- Sort: Most impressions
- Media: All ads, or Video when collecting video-specific examples

Most-impressions sorting is a directional volume signal. It is not exact spend, but it is much more useful for creative research than the current Ad Library API pull.

## Import Flow In Ad Builder

1. Open the Ad Library search in Chrome and scroll until enough ads are loaded.
2. Open Chrome DevTools Console.
3. Paste and run `backend/scripts/ad_library_capture_snippet.js`.
4. Chrome downloads a JSON capture.
5. Go to `Research`.
6. Select `Auto Insurance`.
7. Click `Import Intel`.
8. Paste the downloaded JSON.
9. Click `Import Intel`.
10. Review the cards that appear in Browse.
11. Save the examples worth learning from.
12. Click `Build from this ad` only when the ad has a useful angle for Ad Remix/video generation.

For Codex-assisted runs, Codex can also capture the open Chrome tab and prepare the JSON with:

```bash
python3 backend/scripts/ad_library_prepare_import.py
```

## What The Cards Mean

- `VIDEO`: the capture saw video media or video URLs.
- `Vol ##`: directional volume score.
- `Rank #`: position in the Ad Library page sorted by most impressions.
- `Multiple versions`: the advertiser is testing variants, usually a stronger signal than a one-off ad.
- `Running ##d`: how long the ad has likely been active, based on the Ad Library start date.

Important: if the import toast says `0 with mapped video`, treat the batch as text/angle research only. Facebook's rendered page can expose video elements separately from the ad card, and Phase 1 will not pretend those unmapped videos belong to specific ads.

## What To Save

Save ads that have at least one of these:

- Clear first-line hook.
- Concrete CTA like `Get Quote` or `Compare auto insurance rates`.
- Strong angle: savings, renewal shock, young driver, zip-code pricing, clean-record frustration.
- Video structure we can imitate: talking head, phone check, car shot, caption style, CTA treatment.
- Multiple versions or high volume score.

Do not save:

- Off-vertical insurance ads.
- Accident-lawyer ads.
- Generic insurance-agent brand awareness.
- Ads with unreadable claims or weird compliance language.
- Any ad where the only useful part is a competitor brand/logo.

## Important Rules

Competitor videos are inspiration only. They should not be uploaded or launched as BHM ads.

Use competitor examples for:

- hook structure
- script angle
- pacing
- caption style
- CTA pattern
- shot sequencing

Do not copy:

- exact videos
- exact actor likenesses
- logos
- brand names
- proprietary landing-page claims

## Claude Handoff

After Joel saves a batch, ask Claude to produce:

1. Top patterns across saved examples.
2. 20-30 auto-insurance UGC scripts.
3. Recommended video formats to test.
4. Reject criteria for AI artifacts.
5. Caption/CTA style guidance.

Then Codex can turn that into video presets and run controlled Kie batches.
