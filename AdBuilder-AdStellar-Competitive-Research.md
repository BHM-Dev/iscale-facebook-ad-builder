# Ad Builder — AdStellar Competitive Research (Full Review)

Live walkthrough 2026-09-14: signed into a real AdStellar workspace (`app.adstellar.ai`, Bright Horizons
Media workspace), ran the brand-kit auto-extraction against `getbusinesscoverage.com`, connected the real
**RHO - Commercial Insurance** Meta ad account, imported a real live campaign (`RHO | CBO | LEADS | AUTO
DEALERSHIP CAPI`, 3 ad sets, 16 ads, real spend/clicks data), and built a real campaign through both the
manual step-by-step wizard and the "AI Launch" hybrid flow. This is the fourth and final platform reviewed
in this research track, after Birch, AdEspresso, and RyzeAI — see
[[AdBuilder-CrossPlatform-Launch-UX-Synthesis]] for the combined recommendation this produced.

## 0. The framing that matters most

Unlike RyzeAI (pure chat/agent, no traditional wizard) AdStellar is a **structured, form-driven product
with an AI layer on top, not instead of** — every screen a media buyer expects (Campaign Settings, Ad
Sets, Ads, Review & Publish, Ads Manager) exists as a real, traceable UI, and the AI features (AI Launch,
Winners Hub, AI Combos) are optional accelerators layered onto that structure rather than a replacement
for it. This makes it the most directly comparable platform to our own wizard-based Ad Builder of anything
reviewed — the "how are ads created, how are they laid out for speed" question this research track was
started to answer is best answered by this platform, not Ryze.

## 1. Setup — brand kit, Meta connection, campaign import

- Brand kit auto-extraction (`https://yourcompany.com` → Scan → Analyze → Save, ~15-30 sec) — correctly
  pulled "Get Business Coverage" from the real site, same mechanic as Ryze's onboarding scrape.
- Meta connection is a distinct two-step: connect the Meta *account* (OAuth), then a separate **"Import
  campaigns"** action that explicitly lists what it's about to pull (ad account picker → workspace target →
  campaign multi-select with search + "Select all", each row showing name/status/Ad Sets count/Ads count)
  before committing. Real find: **25 real campaigns** were listed for the connected RHO account within
  seconds of connecting, confirming the read access is immediate and complete.
- Import itself runs as a genuine **background job** with a persistent top-of-page progress bar (name,
  %, "This may take 10-20 minutes depending on campaign size", explicit "you can close this and come back
  later", Cancel Import option) — confirmed the progress bar survives navigating to other pages and even a
  full page reload (still showed accurate % after reload). One real campaign (Auto Dealership CAPI, 3 ad
  sets, 16 ads) imported and appeared in Ads Manager with real spend ($20.33), clicks (6), CTR (1.09%) data
  intact within ~1 minute.
- Setup checklist auto-detects a per-step "Action required" state (e.g. "Set campaign goals" lit up amber
  the moment a real campaign existed) rather than a static onboarding list — the checklist reacts to real
  account state, not just click-through progress.

## 2. Ads Manager — the direct comparison to our Campaign Performance page

**BENEFITS THE AD BUILDER: yes, directly.**

- Three-tab structure (Campaigns / Ad Sets / Ads) with a shared toolbar: search, Status filter, **"Reset
  Columns"**, and a **"Custom"** column picker — genuinely spreadsheet-grade column customization our own
  Campaign Performance/AdsBreakdown tables don't have.
- Bulk-edit action bar (Edit Budgets / Edit Goals / Edit Result Metric) enabled once rows are checked —
  multi-row bulk operations, not one-row-at-a-time.
- Inline on/off toggle switches live in the table at every level (campaign/ad set/ad) — correctly showed
  ad sets as individually toggled "on" even while their parent campaign showed "Paused," matching real Meta
  hierarchy semantics rather than flattening it.
- **Auto-inferred campaign goals** ("CPA ≤ $16.70") appear the moment a campaign is imported, editable
  inline via a pencil icon — not something the user has to configure from scratch per campaign.
- "Imported" provenance badge distinguishes campaigns brought in from Meta vs. built natively in the tool.
- A third-party revenue-attribution partner (**Cometly**) is promoted directly in the Ads Manager banner:
  *"Know which ads actually make you money — Cometly tracks every sale back to the ad that caused it, so
  your ROAS here reflects real revenue instead of Meta's estimates."* This is the same problem our own
  RedTrack/Everflow/P&L reconciliation work solves — AdStellar solves it via a bolt-on integration rather
  than building it in-house, worth noting as validation that this is a real, recognized gap across the
  whole category, not something specific to BHM's stack.

## 3. Library — Products, Media Library, AI Actors, Brand Kit, Templates, Video Editor

- **Creative Templates** ("Save your creatives for reuse") — save a media + headline + primary text +
  description + CTA + landing URL combination as one named, reusable unit. Directly comparable to what
  Joel would want: save a winning headline/image/CTA combo once, reuse it across campaigns without
  retyping.
- **Audience Templates** ("Save your targeting for reuse") — save locations, interests/behaviors, age
  ranges, gender, and custom/lookalike audiences as one named preset. **We have nothing like this at all**
  — our own `AdSetStep` builds targeting fresh every time with no saved-preset concept.
- **Products** (catalog for dynamic/catalog ads) and **AI Actors** (custom avatars for UGC-style video) —
  not relevant to BHM's insurance/services verticals, noted for completeness only.
- Real, pre-populated **Media Library** pulled directly from the connected Meta account's actual creative
  history (searchable, filterable by Images/Videos, multiple grid density options) — not an empty upload
  bucket, an actual asset browser of what's already been used.

## 4. Launch — the manual wizard (direct comparison to our own BulkAdCreation flow)

Walked the real 4-step wizard end to end: **Campaign → Ad sets → Ads → Review & Publish.**

### 4a. The single most reusable finding: token-based naming templates, applied consistently at all 3 levels

Every naming field (Campaign name, Ad set name, Ad name) uses the **same mechanic**: a named template
(`Template: Basic`, with a "+ Save as template" action) containing tokens like `{campaign_objective}`,
`{launch_date}`, `{audience_template_name}`, `{locations}`, `{custom_audiences}`, `{creative_template_name}`,
`{headline}`, `{primary_text_preview}`, `{media_filename}` — with a **live preview** showing the exact
resolved string before you commit (e.g. `Test Creative Template | Get Your Free Quote Today | Protect your
dealership with coverage | Auto_Dealership_Insurance`). This directly solves the exact pain point Joel has
today typing out `[Date] - [Niche] - [Batch]` by hand for every campaign/ad-set/ad name — see
[[AdBuilder-CrossPlatform-Launch-UX-Synthesis]] for the concrete recommendation this produced.

### 4b. Combinatorial ad-set generation via audience variants

The "Audiences" section of Ad Sets is a multi-select: **every audience selected becomes its own ad set**,
with a live "Total Ad sets: N" counter. Inside a single saved audience, every targeting dimension
(Locations, Age ranges, Genders, Languages, Placements, Custom Audiences) supports **"+ Add variant"**
independently, with a live right-rail "Audience Configuration" summary showing `×N` per dimension and a
computed total. This is a true combinatorial targeting-permutation engine — meaningfully more powerful
than our own `AdSetStep`, which only supports one targeting configuration per ad set at a time.

### 4c. Winners Hub — quantitatively scored, one-click-reusable proven performers, at every level

Both the Ad Sets step (targeting) and the Ads step (creative) expose a **"Winners Hub"** tab alongside the
manual editor. For targeting: real Locations/Interests/Custom Audiences/Behaviors from the connected
account's actual last-30-days performance, each with a computed **Score (e.g. 7.5/10)**, real spend
($918.60), clicks (547), results (55), CTR (1.27%), cost/result ($16.70) — checkbox to reuse directly. For
creative: the same pattern across **Creatives / Headlines / Primary Text / Descriptions / CTAs**
independently — real thumbnails of our own actual "Auto Dealership Insurance" ad creatives, scored
(7.6/10 for the top performer), with per-item spend/clicks/results/CTR/cost-per-result, one-click to pull
into a new ad. This is the single best idea from the whole 4-platform research track — see the synthesis
doc for the concrete recommendation.

### 4d. Live ad preview while building

The Ads step renders a genuine Facebook-Feed-style mock (real connected Page name "DailyInsurance.news",
"Sponsored" label, the actual selected image, live-typed primary text and headline) that updates in real
time as fields are filled — with an honest disclaimer banner: *"Not identical to Meta. Review in Ads
Manager before turning ads on."* This is a materially better in-the-moment feedback loop than a form with
no visual preview at all. The disclaimer itself is a good trust-building pattern worth copying if we ever
build a similar live-preview feature — never claim pixel-perfect Meta fidelity for an approximation.

### 4e. Validation UX

Missing-field errors surface in **two places at once**: a summary banner at the top of the step
("Complete 2 required fields to continue:" with bullet points) and inline red-bordered fields with
field-specific error text directly underneath (e.g. "Pixel is required for LEADS campaigns with website
conversions"). Confirmed this correctly reflects real Meta requirements — switching Conversion Location
from Website to Instant Forms removed the pixel requirement and replaced it with a Lead Form requirement,
correctly modeling Meta's actual conditional logic.

### 4f. Exit-intent — three-way save prompt

Attempting to leave a partially-built campaign triggers a **"Save your progress?"** modal offering: Save
as Draft (return to campaigns), **Save as Template** ("Reuse this configuration for future campaigns" —
the *entire* campaign structure, not just one field), Discard Draft, or Cancel. This is a third,
higher-level tier of the same template system (campaign-structure templates, on top of creative templates
and audience templates) — a genuinely complete reuse system spanning every granularity Joel would want.

## 5. AI Launch — the hybrid alternative to the manual wizard

A 3-step guided flow, **not free-form chat**: (1) Campaign Setup — structured fields (Ad Account, Facebook
Page, New Campaign vs. Add to Existing, Landing Page URL, Campaign Objective, Max Daily Budget, Meta
Pixel — auto-populated with the real connected pixel "Auto Insurance - Bankrate", Conversion Event
auto-selected once a URL is entered); (2) Targeting, Creatives & Copy — an explicit three-way dial per
component: **"Proven winners" / "Mix proven + new" / "Generate new"**, independently for Targeting,
Creatives, and Ad Copy; (3) AI Strategy — Historical Data Range selector ("Last 90 days (Recommended)")
and an optional free-text "Custom AI Instructions" field with example prompts and a "Browse Templates"
library of saved instruction sets.

**This three-way dial is the cleanest synthesis of the whole platform's philosophy** — it takes the
Winners Hub concept and turns it into an explicit, per-component exploit/explore control at generation
time, rather than leaving reuse as a manual "go find and click a winner" action. Generation itself runs as
a visible **named multi-agent pipeline** (Page Analyzer → Structure → Targeting → Creative → Copy → Budget
→ Director), each stage checkable, with an overall % bar and realistic ETA ("Campaigns typically take
3-5 minutes"), explicitly backgroundable — confirmed it survives navigating away and a full page reload
(progress bar persisted across both). This is a materially better trust-building pattern than Ryze's
"Thinking..." + collapsed tool-call trace, which required manually expanding to see what happened.

Real caveat found: the AI Launch job for a Leads-objective campaign with no Meta Lead Form configured on
the connected account did not surface a clean draft afterward (checked "AI Drafts" tab, found empty) —
likely blocked by the same missing-lead-form constraint that blocked the manual wizard's Review & Publish
step. Not chased further since creating a real Lead Form in the account was out of scope for this
research session.

## 6. Top Ads / AI Insights — the Winners Hub as a standalone, landing-page-scoped surface

- **AI Insights**: a full sortable leaderboard of every creative component (filterable to
  Creative/Headlines/Primary Text/etc., date-ranged, "11 creatives" for this account), each row showing
  Score, Spend, Clicks, CTR, Results, Cost per Result, Conversions, ROAS — and a **"Generate Similar"**
  quick-action per row that turns a proven performer directly into a new AI-generation prompt. This closes
  the loop from "see what's working" to "make more of what's working" in one click.
- **Top Ads**: the same concept but organized **by landing page** ("go.getfbquotes.com/6a8cfac...") rather
  than flat across the account — a real insight, since performance is fundamentally tied to the specific
  offer/landing page, not just the niche or account overall. Within each landing page: "Top Ads" (proven
  winners) vs. **"AI Combos"** ("New combinations to test").
- **AI Combos** is the most sophisticated feature found in this entire research track: it synthesizes
  brand-new, never-tested ad variations by **mixing individual winning components from different real
  ads** — e.g. a 7.6-scored creative image + a 7.5-scored headline (from a different ad) + a 7.6-scored
  primary text (from yet another ad), assembled into one new combination with a full rendered preview.
  This is genuinely differentiated cross-recombination, not just "relaunch what already worked."

## 7. Tasks — scheduled/recurring automation (Ryze's "Schedules" equivalent)

"What the agent does on its own — it keeps an eye on your account and Slack channels, messages you only
when something's genuinely worth it, sends guardrail alerts, and runs any schedules you set up." Two tabs:
Tasks (user-created, e.g. "Morning standup reminder" style recurring prompts) and Activity (every run's
history). Built-in "account heartbeat" task appears automatically once Slack is connected — same
proactive-digest pattern flagged as a top Ryze recommendation, confirming it's a category-standard
expectation, not a one-off idea.

## 8. Pricing / plan structure (not deeply chased — noted for completeness)

Credit-tiered chat modes confirmed during the Agent tour: **Quick** (up to 200 credits/message, fast
lookups/simple generations), **Standard** (up to 700 credits/message, "Recommended," balanced
thinking/tool use), **Deep research** (up to 1,700 credits/message, big analyses/multi-step planning). Did
not pursue full plan/pricing-tier details since the credit-mode structure was the only pricing-relevant
detail directly touching the UX question this research track was scoped to answer.

## 8b. Second pass — billing, model transparency, and live credit-spend testing (2026-09-14)

Went back in for a deeper pass (Steve: "are you sure you've gone through their platform with a fine
tooth comb? Plus, we have credits to spend here") — this section is genuinely new, not a rewrite of §8.

**Billing confirmed:** $100/month plan = 50,000 AI credits. Account was "Trialing," 7 days left, with an
"End Trial Early & Get 100,000 Bonus AI Credits ($200 value)" upsell banner. Canvas image generation costs
**53 credits per image** — shown in an exact pre-spend "Ready to generate?" confirmation modal (balance
before/after, a "Skip this confirmation next time" checkbox) before every generation.

**AI Preferences page — real, useful pattern worth copying the shape of:** exposes the actual underlying
model family by name (System default, Claude Opus 5 "Recommended," Claude Fable 5.1/5, Claude Opus 4.8/4.6,
Claude Sonnet 4.6 "-40% cost," Claude Haiku 4.5 "-80% cost"), a Reasoning depth selector (Auto/Low/Medium/
High), a Personality/tone dropdown, and a durable **"Custom instructions" field (4000 chars)** that applies
workspace-wide to every AI generation. Conceptually this is AdStellar's version of our own CLAUDE.md — a
persistent, editable instruction layer the AI always reads. **Not recommending we build model choice or a
reasoning-depth picker** (single internal buyer, not a multi-tenant SaaS selling AI transparency as a
feature) — but the "durable custom-instructions field that shapes every generation" idea is worth 1:1
comparing against how `copy_generation.py`'s system prompts are currently hardcoded per-vertical; a
Joel-editable version of that could be a small, cheap win.

**Canvas image model is GPT Image 2.5 Flare (OpenAI-based), not Flux/Nano-Banana** — this matters because
its behavior differs materially from the Flux-Kontext-Pro model our own kie.ai pipeline uses:

- **Confirmed defect: does not reliably honor simple negative-text instructions.** A Painting Contractors
  generation prompted with "no text, no logos, no watermarks" ignored it and baked in a full marketing
  sidebar — headline text, bullet icons, a CTA banner — directly into the photo. **Confirmed fix:** a
  Trucking-niche regeneration with a much more emphatic, repeated instruction ("A single photograph only,
  pure photography with zero graphic design elements... this must be a raw unedited photograph with
  absolutely no text, no words, no letters, no banners, no icons, no infographics, no marketing copy, no
  logos, and no watermarks anywhere in the image") produced a clean result. **Takeaway for our own
  prompting:** GPT-Image-family models need materially stronger/more repetitive anti-text phrasing than
  Flux-family models to get the same result — worth keeping in mind only if we ever add an OpenAI image
  model as an option; not actionable against kie.ai/Flux today.
- **Confirmed working well: composition/negative-space zone-reservation.** A Religious Orgs (storm-damage)
  generation explicitly instructed "compose the shot with the subject in the right two-thirds of the frame,
  leaving the upper-left third visually calm and empty sky/wall for text to be added later" — the model
  complied cleanly (subject correctly right-weighted, calm sky reserved upper-left, no baked-in text). This
  is the same "reserve overlay-zone space" pattern we already ship in our own prompt engineering (commit
  `1447c26`) — good independent confirmation the pattern generalizes across model families, not a new build.
- **Real UX gap: "Launch to Meta" from a generated Canvas image drops the specific image.** Clicking it
  routes to a fresh, empty AI Launch flow rather than carrying that exact generated image forward as a
  pre-filled quick-launch. This is worse than our own Quick Ad pattern, which does carry a specific
  generated ad forward via a `pendingBatchCopy`-style localStorage handoff. Confirms our existing pattern is
  the right one, not a gap to close.
- **The pre-spend confirmation modal's embedded prompt tips are a genuinely reusable, cheap UI pattern**:
  "Keep content brand-safe" (off-policy renders are auto-rejected and refunded automatically), "Lead with
  the product and the hook" (models weight the first 30-50 words heavily), "Direction beats description"
  (specific photographic direction beats vague description). Cheap to add a version of this — a small tips
  panel next to our own kie.ai generation button — see synthesis doc recommendation #8.

**AI Actors library** (Library → AI Actors): 310 pre-built stock UGC avatars, filterable by gender, skin
tone, shooting style (Selfie/Presenter), age band, and style (Professional/Casual), each tagged by use-case
(ugc/podcast/studio) and clip count, plus a "Create AI Actor" custom option. Notable only as a scale
data-point — confirms this is a heavily-invested competitive surface — but reinforces rather than reopens
Steve's 2026-08-27 call to pause video/UGC-avatar work; no action.

**Integrations page** — only 3 listed: Meta Ads (connected), Slack (the agent-in-Slack heartbeat pattern
already flagged in §7), and **Cometly** ("use Cometly's 1st-party attribution data in place of Meta's for
more accurate [reporting]") — a third-party attribution layer competing directly with Meta's own numbers,
conceptually the same slot our RedTrack/Everflow stack already fills. Not actionable, just confirms the
"don't trust Meta's own attribution alone" pattern is category-standard.

## 9. What doesn't apply to BHM (noted, not chased further)

- Products/catalog ads (dynamic product ads) — no e-commerce catalog to sync.
- AI Actors (custom UGC avatar video) — BHM's Video Ads work is explicitly paused per Steve's 2026-08-27
  call to route video creative through Arcads instead of building in-house.
- Multi-workspace/team-seat structure visible in the top-left workspace switcher — single-user (Joel)
  context makes this irrelevant, same conclusion as Ryze's team-seat features.
