# Codex Brief — Research Taxonomy and Filter Upgrade

## 1. Executive summary

Upgrade Research from seven manual angle tags to a small, explainable creative taxonomy and filter surface. This is the next Research increment because boards, structured notes, query search, and the Ad Remix handoff already exist. The goal is faster discovery for Joel, not a new scraping corpus or a proprietary performance-scoring system.

MVP should add controlled metadata for creative theme, CTA type, page type, and media-specific details where the source actually supports them. Keep vendor-style performance claims out of the model: `volume_score` remains directional research context, not spend, reach, or winning truth.

## 2. Flow

```text
Ad Library / Chrome capture
          ↓
  normalize existing ScrapedAd
          ↓
 classify only supported fields
          ↓
 browse + combine filters
          ↓
 save to existing boards
          ↓
 Build from this ad → Ad Remix context
```

## 3. Ready for review — MVP scope

### Existing capabilities to preserve

- Research query bar and vertical presets.
- Active-only and advertiser filters.
- Existing seven angle tags.
- `media_type`, `platforms`, `destination_domain`, rank, running duration, repeat sightings, and multiple-version signals.
- Existing `ResearchBoard` / `ResearchBoardItem` workflow.
- Existing nullable strategy-note fields and `pendingResearchInspiration` handoff.

### New controlled fields

| Field | Values / shape | Source confidence |
|---|---|---|
| `creative_tags` | JSON list of controlled themes: testimonial, problem-agitation, transformation, comparison, review, listicle, founder, educational, statistic, UGC, comment-response | analyst/classifier; nullable |
| `cta_type` | normalized CTA label | Meta/API or capture text; nullable |
| `page_type` | lead form, advertorial, ecommerce, homepage, unknown | crawler/classifier; nullable |
| `video_length_seconds` | integer | only when available; nullable |
| `static_style` | optional controlled label | only after a reliable classifier exists |
| `tech_stack` | JSON object with detected technologies and checked timestamp | crawler; nullable |

Do not automatically infer high-confidence business claims from missing data. Unknown must remain a first-class value.

### UI

- Add multi-select filters for creative tags, CTA type, page type, and media type.
- Add sort controls for longest running, newest seen, most sightings, and multiple versions.
- Show filter provenance/tooltips: “Captured,” “Meta-provided,” “Classified,” or “Unknown.”
- Keep the seven angle tags as a simpler routing field; do not silently replace them.
- Display platform breakdown and destination domain in the ad detail surface before adding a tech-stack crawl.

## 4. Routing / decision logic

| Condition | Behavior |
|---|---|
| Field supplied by Meta or capture | Store as source-backed metadata |
| Field classified from copy/media | Store with classifier version and nullable confidence |
| Field unavailable | Store/display Unknown; never exclude by default |
| Multiple creative tags | OR within a tag filter; AND across independent filter dimensions |
| Active-only | Continue using last-seen proxy until true delivery status exists |
| Volume score | Display as directional only; never label as spend, reach, or winner |

## 5. Integration and migration notes

`ScrapedAd` already contains most base metadata. A migration would likely add nullable queryable fields for `creative_tags`, `cta_type`, `page_type`, `video_length_seconds`, `static_style`, and `tech_stack`, plus classifier/check timestamps if enrichment is asynchronous. Do not write a migration until the final field set and backfill behavior are approved.

`BrandScrapedAd` should only receive corresponding fields if the brand-scrape surface will expose the same filters; otherwise keep the first release scoped to `ScrapedAd`.

The existing `research_inspiration` payload should pass the selected metadata into Ad Remix as strategic context. It must not turn classifier labels into copy instructions or weaken the existing similarity guard.

## 6. Tracking and analytics

Track:

- filter usage by field and value,
- result count before/after filtering,
- saved-to-board rate,
- Build-from-this-ad rate,
- time from Research open to first saved ad,
- unknown-field rate by source.

## 7. Build priority

1. Expose existing platform metadata and add sorting.
2. Add controlled creative tags and CTA/page-type filters where data is available.
3. Add asynchronous enrichment for page type and technology only after measuring demand.
4. Revisit Hook/Body/CTA independent regeneration after this discovery surface proves which patterns Joel repeatedly selects.

## 8. Open questions and dependencies

- Which fields can be populated reliably from the current Meta/Chrome capture payloads?
- Should creative tags be analyst-entered, rule-based, or model-assisted in MVP?
- Is a crawler allowed to fetch competitor landing pages, and what timeout/cache policy is acceptable?
- Do we need the same taxonomy on `BrandScrapedAd`, or is `ScrapedAd` sufficient for the first release?
- What minimum usage threshold should justify the richer enrichment pipeline?

## Phase 2 — directional only

- Brand-level hook mining.
- Daily competitor monitoring snapshots.
- Curated collections built on top of existing boards.
- Independent Hook/Body/CTA regeneration and persistence.
