# Ad Builder — Cross-Platform Launch UX Synthesis (Birch, AdEspresso, RyzeAI, AdStellar)

Written after live-testing all four competitor platforms end-to-end: Birch (`app.bir.ch`), AdEspresso
(`app.adespresso.com`), RyzeAI (`app.get-ryze.ai`), AdStellar (`app.adstellar.ai`). Full per-platform
detail lives in their own briefs — this document is the answer to the actual question that started this
research track: **how are ads created and launched elsewhere, how is the UI laid out for speed, and what
should we actually build.**

Source briefs: [[Birch-Design-Reference-Capture]], [[AdEspresso-Design-Reference-Capture]],
[[AdBuilder-RyzeAI-Competitive-Research]], [[AdBuilder-AdStellar-Competitive-Research]].

## 0. The one governing insight

Every platform reviewed has independently converged on the same idea from a different angle: **stop
making the user re-decide things that have already been proven to work, and make "reuse the proven thing"
as fast as "start from scratch."** Birch does it via ad-set templates that inherit copy/CTA. AdEspresso
does it via saved audiences and "reuse existing posts." RyzeAI does it via a `memory` object every future
agent run reads automatically. AdStellar does it most completely, with a scored, quantitative, one-click
Winners Hub at every level (targeting, creative, and even individual copy fields) plus an "AI Combos"
engine that recombines proven pieces into new untested variations.

Our own Ad Builder already has the *data* to do this — CPL-ranked Copy Library, P&L/RedTrack revenue
tracking, `angle`/`source_ad_id` learning-loop fields already sitting unused in the `GeneratedAd` model —
we just don't expose it as a first-class, browsable, reusable UI object anywhere in the app. That is the
single biggest lever from this whole research track.

## 1. Ranked recommendations — build these

### 1. A "Winners" surface: scored, browsable, one-click-reusable proven performers

**What it looks like elsewhere:** AdStellar's Winners Hub (§4c, §6 of its brief) — real thumbnails/text of
past ads with a computed score and real spend/clicks/results/CTR/cost-per-result, a checkbox to pull
directly into a new ad, filterable by Creative/Headline/Primary Text/Description/CTA independently, and
a landing-page-scoped "Top Ads" view.

**What we already have, unused for this:** `Copy Library` already computes CPL-ranked few-shot examples
(`_get_library_examples()`, ordered `is_pinned desc, cpl asc nulls_last`) — the ranking logic exists, it's
just feeding an LLM prompt invisibly rather than being a browsable UI object. `GeneratedAd.revenue` /
`.profit` / `.last_synced_at` already exist in the model. The Dashboard's "Performance by Niche" table and
the Campaign Performance real-time insights are the other two real data sources.

**Concrete build:** a new page (or a tab on Copy Library) listing every past creative/headline/body/CTA
with its real CPL, revenue, and ROAS, sortable by a computed score, with a "Use This" action that seeds a
new Batch Generate / Ad Remix / Build New Ad session from it. Start with creative-level only (matches
Copy Library's existing granularity); field-level (headline vs. body vs. CTA independently) is the AdStellar
stretch goal, not v1.

### 2. Token-based naming templates, at every level

**What it looks like elsewhere:** AdStellar's naming system (§4a of its brief) — one consistent mechanic
applied to Campaign name, Ad Set name, and Ad name: a saved named template containing tokens
(`{campaign_objective}`, `{launch_date}`, `{audience_template_name}`, `{creative_template_name}`,
`{headline}`, `{media_filename}`, etc.) with a live-resolved preview before commit.

**The actual pain point this solves:** Joel currently hand-types `[Date] - [Niche] - [Batch]` for every
campaign/ad-set/ad name — every session. This is the single most direct, low-effort, high-frequency-impact
build in this whole list.

**Concrete build:** add a naming-template field to `BulkAdCreation.jsx` / `AdSetStep.jsx` / campaign
creation, backed by a small token-substitution function server-side or client-side (niche, date, brand
name, angle, batch number are all already known at generation time). Persist named templates per brand in
a new small table, or even just localStorage to start — this does not need a migration to deliver value.

### 3. A relative/baseline threshold rule type for the rules engine

**Carried over from the Ryze brief (still valid, now reinforced by AdStellar):** AdStellar's Automate-style
templates and its own auto-inferred campaign goals ("CPA ≤ $16.70," computed the moment a campaign is
imported) both lean on baseline/relative comparisons, not just absolute thresholds. Our own rules engine
(`auto_pause.py`) is absolute-threshold-only. Adding "CPC up >25% vs. trailing 7-day average" as a rule
type remains cheap and directly extends Phase 2/3 work already shipped.

### 4. Saved audience/targeting presets

**What it looks like elsewhere:** AdStellar's Audience Templates (§3 of its brief) — save locations,
interests/behaviors, age/gender, custom audiences as one named, reusable preset; also AdEspresso's saved
audiences in Asset Manager and its "test multiple saved audiences" split-test mode.

**What we have today:** nothing. `AdSetStep` builds targeting fresh every single time.

**Concrete build:** the smallest version of this is a "Save this targeting as a preset" button on
`AdSetStep` that persists the current form state (locations, age, gender, interests) under a name, and a
picker to reload one. Given Joel reuses similar targeting across niches within the same vertical
(commercial insurance sub-niches), this is a real, frequent time-save, not a nice-to-have.

### 5. A live-preview mock while building creative, with an honest fidelity disclaimer

**What it looks like elsewhere:** AdStellar's real-time Facebook Feed mock in the Ads step (§4d) — updates
as headline/primary-text/image are filled, with an explicit *"Not identical to Meta. Review in Ads Manager
before turning ads on."* disclaimer.

**Why now:** `BulkAdCreation.jsx` and `AdCreativeStep.jsx` are pure forms today — no rendered mock at all
until the ad is actually pushed to Meta and viewed in Ads Manager. A lightweight client-side mock (Page
name/avatar, "Sponsored" label, headline, body, image, CTA button) is a real trust-and-catch-mistakes
improvement, and the disclaimer pattern is important to copy exactly — never claim pixel-perfect Meta
fidelity for an approximation, or a caught discrepancy erodes trust in the whole feature.

### 6. Explicit "reuse-vs-fresh" dial at generation time

**What it looks like elsewhere:** AdStellar's AI Launch three-way dial (§5) — "Proven winners / Mix proven
+ new / Generate new," independently for Targeting, Creatives, and Ad Copy.

**Why this matters beyond #1:** having a Winners surface (recommendation #1) is necessary but not
sufficient — it still requires Joel to manually go find and click a winner. Making "how much should this
generation lean on what's already proven" an explicit, per-field control at the moment of generation is
the natural next step once #1 exists. Sequence this after #1 ships and is validated with real usage.

### 7. Combinatorial ad-set generation via targeting variants (stretch)

**What it looks like elsewhere:** AdStellar's audience-variant system (§4b) — every targeting dimension
independently multipliable, with a live computed "Total ad sets" count; AdEspresso's separate targeting-
permutation axis (`1 creatives × 1 targets = 1 Ads, Max 250 Ads`).

**Why this is a stretch, not a near-term build:** our current model is one targeting configuration per ad
set, matching how Joel actually thinks (one ad set = one audience). This is real power but real complexity
— flag as a phase-3-or-later idea, not something to build reactively off this research alone. Revisit only
if Joel explicitly asks for "test this audience against that one" as a recurring workflow.

### 8. Pre-spend cost confirmation with embedded prompt tips (new, cheap)

**What it looks like elsewhere:** AdStellar's Canvas image-generation flow (full detail in §8b of its
brief, added after a deeper live-credit-spending pass 2026-09-14) shows an exact "Ready to generate?" modal
before every generation — credits this will cost (53), balance before/after, a "skip this next time"
checkbox — plus three embedded, always-visible prompt-engineering tips: keep content brand-safe (off-policy
renders auto-reject and refund), lead with the product and the hook (models weight the first 30-50 words
heavily), and direction beats description (specific photographic direction beats vague description).

**Why this is worth building:** our own `kie.ai` generation flow has no equivalent — Joel or Steve click
generate with no visibility into cost or a nudge toward better prompts before the ~4-8 credits are spent. A
small tips panel next to the generate button in `BatchGenerate.jsx`/`ImageAds.jsx` costs almost nothing to
build and directly reduces the "generated a bad ad and had to redo it" cost. Skip the credit-balance-math
part (kie.ai billing isn't per-generation-visible to Joel today) and keep the tips + a lightweight "this
will use ~N credits" line.

**Related, no new build needed:** AdStellar's confirmation that GPT Image 2.5 Flare respects explicit
composition/negative-space instructions ("reserve the upper-left third for text") validates the same
pattern our own prompt engineering already ships (commit `1447c26`, reserve-overlay-zone-space) — good
independent confirmation across model families, not a gap.

### 9. AI prompt-rewrite-and-approve step before spending generation credits (new, video track)

**What it looks like elsewhere:** AdStellar's Canvas Video mode (full detail in §8c of its brief, from a
2026-09-14 video-focused pass) doesn't send your typed prompt straight to the model. It first shows a
**"Review your prepared prompt"** modal: your raw input side-by-side with a fully AI-rewritten, materially
richer prompt (camera framing, lighting, shot composition added), with a plain-English note when it
adjusted something ("we adjusted your prompt so the actor doesn't sound rushed in the selected duration").
You approve or cancel before any credits are spent.

**Why this is a step up from recommendation #8:** the tips-panel idea (static, always-visible prompt
advice) is cheap but passive — the user still has to apply the advice themselves. This pattern actually
does the rewriting for them and shows its work before committing spend. Directly relevant if we ever
revisit prompt quality for `kie.ai` generations in `BatchGenerate.jsx`/`ImageAds.jsx`/Ad Remix: an
LLM-rewrite-and-preview step (using the copy-generation Gemini call we already have) between "Joel types a
concept" and "we call kie.ai" would catch weak/vague prompts before spending a generation.

**Scope note:** this is a genuinely bigger build than #8 (needs an LLM call + a review UI + an
approve/cancel gate), so it's additive to #8, not a replacement — ship the cheap tips panel first, revisit
this only if prompt quality turns out to be a recurring problem in practice.

## 2. Confirmed as category-standard, not BHM-specific — validate our existing choices

- **Background jobs with persistent, navigable, reload-surviving progress** (AdStellar's campaign import
  and AI Launch generation, Birch's "Getting ads data..." pattern) — confirms our own async patterns
  (kie.ai polling, Meta sync jobs) are the right shape; the bar to hit is "survives a page reload," which
  is worth explicitly testing on our own long-running jobs if not already verified.
- **Proactive digest / "account heartbeat"** — flagged as a top Ryze recommendation, now confirmed as a
  built-in AdStellar Task too (auto-appears once Slack is connected). This is a real, repeated pattern
  across the category, not a one-off idea — worth prioritizing.
- **"We will not spend money until the final publish step"** safety banner (AdEspresso, front-loaded) and
  AdStellar's default-to-review-before-live pattern at every gate — matches our own existing discipline
  (Quick Ad's persistent breadcrumb, the mandatory pre-push review culture) — no change needed, just
  confirms the instinct is industry-standard, not overcautious.
- **Dual-location validation errors** (top summary banner + inline field-level error, seen in AdStellar) —
  worth an explicit audit of whether our own wizard steps do both consistently, since this was called out
  as a genuinely good pattern and is cheap to retrofit if we're inconsistent about it.

## 3. Explicitly not recommended — philosophically incompatible or no BHM use case

- Full chat/agent-only interaction model (Ryze's core paradigm) — Steve's own "boring, robust, cron-able"
  doctrine (CLAUDE.md) argues for structured, traceable UI over conversational black-boxes as the primary
  interface; AdStellar's hybrid (structured form + optional AI layer) is the validated middle ground, not
  Ryze's all-in approach.
- Dynamic/catalog product ads, AI Actors/UGC avatar video, white-label agency reporting, client-approval
  workflows, team-seat management — all four platforms carry agency- or e-commerce-shaped surfaces BHM has
  no use case for (single internal buyer, no product catalog, video paused per Steve's 2026-08-27 call).
- Rule Sets / sentence-based rule builders (AdEspresso) — our rules engine's structured form already
  covers more action types (~5 vs AdEspresso's 3) without the sentence-format's scaling strain; no reason
  to regress to a more constrained UI pattern for a marginal readability gain.

## 4. Suggested build order

1. **Naming templates** (recommendation #2) — smallest scope, no migration required to start, immediate
   daily-use impact.
2. **Winners surface, creative-level only** (recommendation #1, scoped down) — reuses Copy Library's
   existing CPL-ranking logic and `GeneratedAd.revenue`/`.profit` fields; the data work is already done,
   this is primarily a UI build.
3. **Saved audience/targeting presets** (recommendation #4) — second-smallest scope, clear frequent pain
   point.
4. **Relative/baseline rule type** (recommendation #3) — extends already-shipped Phase 2/3 rules engine
   work.
5. **Live creative preview mock** (recommendation #5) — independent of the above, can be built in parallel
   whenever `BulkAdCreation.jsx`/`AdCreativeStep.jsx` work is next touched.
6. **Reuse-vs-fresh generation dial** (recommendation #6) — sequence after #2 ships and gets real usage.
7. Combinatorial ad-set targeting (recommendation #7) — hold until explicitly requested.
8. **Pre-spend cost/prompt-tips panel** (recommendation #8) — smallest scope of the whole list, can ship
   independently of everything else whenever `BatchGenerate.jsx`/`ImageAds.jsx` is next touched.
9. **AI prompt-rewrite-and-approve step** (recommendation #9) — bigger lift, only worth it if #8 alone
   doesn't move the needle on prompt quality; the video-track research pass that surfaced this is being
   kept open per Steve's 2026-09-14 call (separate from the 2026-08-27 in-house-UGC pause), so revisit
   alongside that track.
