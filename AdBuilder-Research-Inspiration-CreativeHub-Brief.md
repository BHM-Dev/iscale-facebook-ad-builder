# Research → Inspiration → Creative Hub Improvement Brief

## 1. Executive summary

Our current Research page is useful for storing competitor ads, but it is not yet a strong research
workspace. It asks Joel to pull a vertical, inspect a card grid, save individual ads, and then jump to
Ad Remix. Adnova's Inspiration product makes the research loop feel more intentional: discover by
query, filter by creative dimensions, sort by meaningful signals, save into boards, follow brands, and
reuse related inspirations. Its Creative Hub then provides the next layer: a shared, searchable asset
workspace with versions, annotations, comments, and review status.

The highest-value BHM opportunity is not recreating Adnova's 75M/100M-ad corpus. It is turning our
existing Meta Ads Library data and saved competitor ads into a structured creative intelligence system
for insurance and lead-gen:

```text
Meta Ad Library / Chrome capture
              ↓
     normalized competitor ads
              ↓
  search + filters + ranking signals
              ↓
   research boards / saved examples
              ↓
 angle + hook + format + funnel notes
              ↓
     Build from this ad / Ad Remix
              ↓
 generated ad → review → launch → performance feedback
```

### POV

Research should answer Joel's question quickly: **“Show me the best current examples for this angle,
vertical, format, and competitor—and let me turn one into a test.”** The MVP should optimize that loop
before adding a general-purpose DAM.

## 2. What Adnova Inspiration does that matters

### Discovery

- Explore feed with search and a large cross-brand ad corpus.
- Separate Explore, Following, and Saved Ads surfaces.
- Brand following / Detective for monitoring a selected competitor over time.
- “Similar inspirations” on individual ads.

### Filters and ranking

- Format, platform, status, industry, language, date range, run time, scaled, top mover, Facebook rank,
  Adnova rank, spend, location, ad theme, video length, and ad copy.
- Theme taxonomy is much richer than our seven manual angle tags. Live examples included Testimonial,
  Problem Agitation, Transformation, Before and After, Us vs Them, Review, Listicle, Feature/Benefit,
  Founder, Educational, Expert Explainer, Statistic, UGC Selfie, Comment Response, and many others.
- Cards expose rank, reach, estimated spend, trend movement, media type, duration, and similar-ad count.

### Curation and reuse

- One-click “Save to board,” with nested boards and board search.
- Saved ads can be shared and organized independently of the source feed.
- The research object is not just an ad row; it is an example that can be grouped into a creative brief
  or angle collection.

### What is not directly reusable

The corpus scale and cross-platform historical data are defensible moat features, not an MVP target.
Adnova's ranking/spend signals also depend on proprietary data and should not be copied as if they were
Meta truth. We should label our current volume score as directional, as we already do.

## 3. What Adnova Creative Hub does that matters

Creative Hub is closer to a lightweight Frame.io/Air-style review workspace than to Google Drive.
Observed live capabilities included:

- Boards and sub-board organization.
- Grid/list views and central asset search.
- Smart Search plus filters for uploader, custom fields, tags, date, and extension.
- Favorites, “Open Discussion Items,” and “My Uploads” shortcuts.
- Share action for a board/asset workspace.
- Asset versioning rather than duplicate filenames.
- Visual annotations and threaded discussion, including timestamp/on-screen anchors for video.
- Custom fields and tags available on every asset.
- Launch-status visibility in the launcher Creatives table.

For BHM, the useful subset is not “replace Drive.” Drive remains the source of truth for raw creative
assets. The useful subset is a **research board / review layer** for competitor examples and generated
variants:

```text
Saved competitor ad
  ├─ angle / hook / format / funnel tags
  ├─ analyst note: why this is worth testing
  ├─ versioned BHM remix variants
  ├─ reviewer comments / approval state
  └─ Build from this ad → Ad Remix
```

## 4. Current-state gap in our Research page

We already have several strong foundations:

- Vertical tabs and sub-vertical configuration.
- Saved ads across verticals.
- Manual angle tags and angle filtering.
- Active-only and advertiser filtering.
- Rank position, directional volume score, running days, multiple-version signal, seen count, media
  metadata, and destination domain.
- Blacklist advertiser and keyword controls.
- Brand scrape workflow.
- Chrome-captured Meta Ad Library import for cases where the API is weak.
- “Build from this ad” handoff into Ad Remix with competitor context.

The main weakness is workflow shape, not missing CRUD:

- **Discovery is pull-oriented.** Joel starts from our fixed verticals instead of a research question.
- **The Chrome capture flow is too technical.** “Run this DevTools snippet and paste JSON” is a fallback,
  not a daily research experience.
- **Saved ads are a flat sidebar.** There are no boards, collections, briefs, or multi-tag curation.
- **Our angle taxonomy is too coarse.** Seven tags are useful for routing but insufficient for creative
  analysis.
- **Ranking is opaque.** The volume score is directional, but the UI does not explain the inputs or let
  Joel sort by longevity, recency, format, or repeated sightings.
- **No persistent competitor watch.** Brand Scrapes exist, but the main Research loop does not feel like
  “follow this competitor and tell me what changed.”
- **No analysis layer.** Saved ads carry copy/media, but not structured hook, persona, promise, proof,
  CTA, funnel stage, or visual treatment notes.
- **No review bridge.** Generated variants and saved references are not grouped into a reviewable board
  with comments or approval status.

## 5. Ready for review — MVP scope

### MVP objective

Make Research a daily creative-intelligence workspace for BHM verticals without building a new ad-data
platform.

### MVP features

#### A. Research query bar

Add a prominent query field with saved query presets:

- `Auto insurance — cheap quote`
- `Commercial insurance — niche / industry`
- `Reverse mortgage — homeowner benefit`
- `Personal loans — debt consolidation`
- `Debt relief — problem aware`

The query should work against the existing vertical search endpoint and preserve the selected country,
active status, source, and date range. Keep the fixed vertical tabs as shortcuts, not the only entry
point.

#### B. Better filter and sort model

Add filters that are backed by data we can actually explain:

| Filter / sort | MVP backing | UI treatment |
|---|---|---|
| Active / inactive | Meta delivery status or captured status | Filter chip |
| Running duration | `start_date` + current date | Sort: longest running |
| Repeated sighting | `seen_count` | Sort: seen most |
| Multiple versions | `is_multiple_versions` | Toggle |
| Media type | `media_type` | Image / video / carousel |
| Advertiser | `brand_name` | Search |
| Angle | Existing `angle_tag` | Multi-select |
| Creative theme | New optional `creative_tags` | Multi-select, progressive |
| Last seen | `updated_at` / last scrape | Sort: newest / stale |

Do not call the directional score “spend,” “reach,” or “winning.” Show a tooltip: “Directional research
signal based on rank, longevity, repeat sightings, versions, and media presence—not Meta spend truth.”

#### C. Boards / collections

Replace the flat Saved panel with named boards. Initial board examples:

- `Auto — Problem Agitation`
- `Commercial — Religious Organizations`
- `Offers to Test`
- `UGC / Selfie References`
- `Joel Review Queue`

An ad can belong to multiple boards and retain its source vertical. Board membership is the first
version of Creative Hub; do not build arbitrary folder moves or a general asset browser in MVP.

#### D. Structured creative notes

When saving an ad, offer optional fields:

- Angle / theme
- Hook type
- Audience/persona
- Core promise / offer
- Proof mechanism
- CTA
- Funnel stage
- “Why save this?” free-text note

Only angle is required in MVP. The remaining fields can be nullable from day one to preserve the schema
for later AI tagging.

#### E. Better reuse handoff

“Build from this ad” should pass the selected board, notes, and structured tags into Ad Remix so the
generation prompt can distinguish:

- source ad angle,
- source ad copy context,
- source visual/media type,
- BHM analyst's intended adaptation.

The model must continue to use competitor material as strategic context, never as copy to reproduce.

## 6. Phase 2 — directional Creative Hub layer

Build only after Joel uses boards and notes enough to expose a collaboration need.

- Generated BHM variants can be attached to a research board.
- Version history: v1 / v2 / approved.
- Reviewer note and status: Draft → Needs review → Approved → Launched.
- Lightweight comments on an ad/variant, not frame-accurate video annotations initially.
- Shareable read-only board link for Dan, Joel, or a client.
- “Open discussion” queue for unresolved reviewer notes.
- Launch status linked back to Meta ad ID.

This gives us the operational value of Creative Hub without committing to a full DAM or duplicating
Google Drive/R2 storage.

## 7. Phase 3 — competitor intelligence

Only if research usage justifies it:

- Follow a competitor page and schedule recurring captures.
- Store ad history and detect newly seen / stopped / materially changed ads.
- Auto-cluster copy and creative tags by advertiser.
- Generate a weekly “what changed” report.
- Add AI analysis across hook, persona, USP, proof, CTA, visual treatment, and funnel stage.
- Add “similar ads” based on structured tags and embeddings, not only keyword matching.

This is where Adnova's Detective/brand-following model becomes relevant. It is more valuable to BHM than
their generic launcher because it could turn competitor research into a repeatable source of creative
angles. It is also substantially larger than an MVP.

## 8. Routing / decision logic

| User action | Result |
|---|---|
| Search a query | Show normalized ads from saved/API/Chrome sources, labeled by source and freshness |
| Save ad without board | Save to default `Unsorted` board and offer board assignment later |
| Save ad with board | Persist board membership plus optional angle/notes |
| Click Build from this ad | Open Ad Remix with source context, board, tags, and notes |
| Generate a remix | Attach generated variation to the originating board when requested |
| Submit for review | Set variant status to `Needs review`; notify only configured reviewers |
| Approve | Set status `Approved`; preserve version and reviewer/date |
| Push to Meta | Set status `Launched` only after Meta returns an ad ID |
| Competitor ad disappears | Keep the saved record and mark source freshness/status; never delete curation |

## 9. Integration and schema notes

### Existing systems to reuse

- `ScrapedAd` and existing research endpoints.
- `angle_tag`, `volume_score`, `seen_count`, `creative_intel`.
- Brand scrape and Chrome import paths.
- `pendingResearchInspiration` handoff into Ad Remix.
- Generated Ads library and Meta ad-ID write-back.
- R2 for BHM-generated assets; Drive remains raw-source storage.

### Reserved fields for MVP

Prefer nullable JSON or normalized tables depending on existing conventions:

```text
research_boards: id, name, vertical_id, owner_id, created_at, updated_at
research_board_items: board_id, scraped_ad_id, generated_ad_id, sort_order, note, created_at
creative_tags: angle, hook_type, persona, promise, proof_type, funnel_stage, visual_theme
review_state: draft | needs_review | approved | launched
reviewed_by, reviewed_at, launched_meta_ad_id
source_last_seen_at, source_status
```

Do not store Meta CDN media URLs as durable assets. Preserve the public Ad Library link, import metadata,
and a local/R2 snapshot only where permitted and operationally necessary.

### Analytics events

Track from day one:

- `research_query_submitted`
- `research_filter_changed`
- `research_sort_changed`
- `research_ad_opened`
- `research_ad_saved`
- `research_board_created`
- `research_note_added`
- `research_build_from_ad_clicked`
- `research_to_remix_started`
- `research_variant_review_requested`
- `research_variant_approved`
- `research_variant_launched`

Primary KPI: **saved-ad-to-remix start rate**, followed by **remix-to-launch rate** and **time from
research open to first Build from this ad click**. The point is to measure whether better research
actually creates more testable BHM ads, not whether Joel browses longer.

## 10. Build priority / rollout

### Ready for review: 1–2 week MVP

1. Query bar + saved query presets.
2. Explainable sort/filter improvements.
3. Named research boards replacing the flat Saved panel.
4. Optional structured notes with nullable schema fields.
5. Pass board/notes/tags through the existing Ad Remix handoff.
6. Add the research funnel events and a small usage readout.

### Phase 2 directional

1. Generated-variant attachments to boards.
2. Review state and reviewer notes.
3. Read-only board sharing.
4. Launch-status write-back.
5. Scheduled competitor monitoring and change detection.
6. AI tagging, similarity search, and weekly competitor reports.

## 11. Open questions / dependencies

- Does Meta's current Ads Library API provide enough stable media/status data for the query experience,
  or should the Chrome capture remain a supported source rather than an emergency fallback?
- What exactly does Joel mean by “research”: finding competitor ads, tracking named advertisers, or
  analyzing BHM's own winners? The MVP above targets competitor discovery → remix.
- Should boards be user-owned, workspace-shared, or both? Default recommendation: workspace-shared with
  owner attribution.
- Do we need local/R2 snapshots of competitor media for reliable review, and what policy governs that?
- Should Creative Hub review attach to generated ads only, or also to saved competitor references? Start
  with both as board items, but keep approval only for BHM-owned/generated variants.
- Can the current `ScrapedAd` model support many-to-many board membership without creating a migration
  branch or breaking the startup chain? Audit the current Alembic head before implementation.

## 12. Decision

Do not build a general Adnova clone. Build a **Research Board** that makes our existing Meta Ads Library
data easier to search, explain, curate, and turn into Ad Remix inputs. Treat Creative Hub as the later
review/versioning layer for generated BHM ads.

Adnova's value here is workflow design, not a reason to buy the product: Inspiration shows the target
research loop, while Creative Hub shows the target collaboration loop. Our advantage is that the output
can be tied directly to BHM verticals, Eugene-Schwartz copy generation, R2/Drive assets, Meta launch, and
post-launch performance.

## Sources

- [Adnova live Inspiration workspace](https://app.adnova.ai/app/library/discover)
- [Adnova live Creative Hub](https://app.adnova.ai/app/drive)
- [Adnova Creative Hub API overview](https://api-docs.adnova.ai/creative-hub)
- [Adnova Detective / competitor strategy overview](https://adnova.ai/adnova-detective)
- [Adnova public product overview](https://www.adnova.ai/)
