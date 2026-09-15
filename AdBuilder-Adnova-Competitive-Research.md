# Adnova Competitive Research — Ad Launcher, Mass Upload, Templates

Live walkthrough of `app.adnova.ai`, logged in as the real "Get Business Coverage" workspace, connected
to the real "RHO 4 - Commercial (New CAPI)" Meta ad account. Scope per Steve's request after talking to
Joel: (1) how they handle mass-upload-from-Drive for the ad launcher, since Joel flagged that as
possibly missing from ours, and (2) their ad templates library, to inform our Template/Style section.

## 0. The headline finding: Joel's "Google Drive" ask is a naming problem, not a missing feature

We already have a full Drive-sync pipeline live in production — `drive_sync_service.py`,
`DriveAsset`/`DriveSyncState` models, `/api/v1/drive-assets`, and a "Browse Drive Creative Library"
picker wired into `AdCreativeStep.jsx` with multi-select bulk-add into the campaign. **1,034 real
synced assets**, last synced the morning this research was done.

Adnova, by contrast, has **no Google Drive integration at all** — confirmed via Settings → Integrations
(only Slack listed). Their "mass upload" is a manual drag-drop into their own internal DAM
(`/app/drive` and, inside the launcher, `/app/adlauncher/.../creatives`), the same category of feature
we already have.

**So Joel isn't asking for something Adnova does and we don't.** He's asking for something he either
doesn't know exists in our app, or that doesn't work the way he expects. Before building anything new
here, this needs a direct answer from Joel: is `AdCreativeStep.jsx`'s Drive picker not visible/discoverable
to him, has it broken for him, or is his actual complaint something more specific (e.g., he wants
Drive assets browsable and taggable from a dedicated library page, not just inline mid-wizard)? The rest
of this doc (esp. §2) is about what a best-in-class version of that flow looks like, in case the answer
is "the picker exists but isn't good enough."

## 1. Ad Launcher — structure

Gated behind a one-time, 5-step "Ad account Onboarding" per connected Meta ad account:

1. **Ad Profiles** — pick the Facebook Page to post as (existing OAuth grant, no new consent needed)
2. **Tracking Specs**
3. **Ad Naming Convention** — see §2, the single most valuable idea here
4. **Launch Settings** — "Multi Advertiser" toggle, "Launch Ads as Paused" toggle (defaults to OFF —
   i.e., ads launch **active** by default; worth deciding our own default deliberately rather than
   copying either choice blind)
5. **Creative Enhancements** — full per-format (Image/Video/Carousel) breakout of Meta's native
   Advantage+ flags (visual touch-ups, text improvements, overlays, brightness/contrast, music, image
   animation, site links, catalog items, product tags, CTA enhancement, etc.) — all OFF by default in
   this trial. This is really just a UI for toggles Meta's Ads API already exposes; we could expose the
   same set directly in our launch payload if Joel wants per-format control instead of relying on
   Meta's own Advantage+ defaults.

After onboarding: `/app/adlauncher/.../launch` — a real "Launch Ads" screen with Group Creatives / Load
Templates / Bulk Edit controls and a search-by-ad-name box. "+ Load Creatives" appears to open a native
OS file picker (invisible to browser automation — not a bug, just outside what could be observed).

## 2. Ad Naming Convention — this is the actual idea worth stealing

This is materially more advanced than the naming-templates brief already sitting in
`CODEX_BRIEF.md` (which is scoped to Campaign Name / Ad Set Name in the manual `/facebook-campaigns`
builder). Adnova's version operates at the **ad** level and auto-generates the name for every single ad
at launch time — zero typing, ever, once configured once.

Two categories of token:
- **Dynamic Tags** (system-derived automatically): `{{filename}}`, `{{ad type}}`, `{{counter}}`,
  `{{web link}}`, `{{ad set name}}`, `{{campaign name}}`, `{{date}}`
- **Placeholder Text** (manually tagged per-asset metadata, set once when organizing creatives in the
  DAM): `{{influencer}}`, `{{product}}`, `{{offer}}`, `{{concept}}`, `{{template name}}`

Plus: a separator dropdown (`_`, seen as default), an "add space around separator" toggle, a "remove
dimensions from filename" toggle (strips resolution suffixes before using `{{filename}}`), a drag/chip
naming-convention builder, and a **live-resolved preview** (`Traffic_Broad_UK_Video2_1x1`).

**Why this matters for us specifically:** our `BulkAdCreation.jsx` already generates ad names via the
`H{n}B{n}` headline×body pattern (per the project CLAUDE.md, deliberately out of scope for the
naming-templates work). Adnova's model shows a cleaner version of the same idea — a **set-once
convention that reads real values off the ad set/campaign/creative** rather than a static counter.
Given `CODEX_BRIEF.md` hasn't shipped yet, it's worth revising it before sending to Codex: at minimum,
borrow the Dynamic Tags idea (`{{ad_set_name}}`, `{{campaign_name}}`, `{{date}}` are all things we
already have in scope in `CampaignStep.jsx`/`AdSetStep.jsx`) instead of the narrower fixed-token set
currently drafted. The Placeholder Text idea (tagging creatives with `{{concept}}`/`{{offer}}` at
upload time) is a bigger lift — it implies per-asset custom fields, which we don't have today — and is
probably a phase 2, not part of the current brief.

## 3. Creatives library (mass upload) — what a good version looks like

`/app/adlauncher/.../creatives`, separate from the generic `/app/drive`: table view (Name / Dimension /
Launch Status / Uploaded At / Uploaded By / Size / Action), filters (Boards / Launch Status / Uploader /
Custom Fields / Tags / Extension), search with a "Starts with" mode, a green "Upload creatives" button,
row checkboxes → bulk "Delete Selection," pagination.

Compared to our `AdCreativeStep.jsx` Drive picker, the notable gaps if we ever revisit this:
- **Launch Status column** — at-a-glance whether a given creative has already been used in a live ad.
  We don't currently surface this; it would directly answer "have I already used this asset" without
  Joel needing to remember.
- **Custom Fields / Tags** — structured per-asset metadata (this is also what would back the
  `{{offer}}`/`{{concept}}` naming tokens in §2). We have none of this on `DriveAsset` today.
- **Boards** — a lightweight folder/collection concept distinct from Google Drive's own folder
  structure — lets them curate a working set without reorganizing the source Drive.

None of this is urgent — it's real gap-closing work, not a launcher-blocking bug — but if Joel's actual
complaint turns out to be "I can't tell what I've already used" or "I can't tag things by offer," this
is the shape of the fix.

## 4. Ad Copy Templates — a separate, parallel template system

`/app/adlauncher/.../settings/ad-copy-templates` (nav group "Ad Copy", separate from the design
templates in §5): manages saved ad copy (headline/body/CTA/link) as reusable templates. Three ways to
create one: "Create New Template" (blank), "Load From Existing Ads" (import from what's already
running), "Import CSV" (bulk). Empty on this trial account, so the actual editor UI wasn't observed.

We already do something adjacent to "Load From Existing Ads" — the Ad Copy Library
(`copy_generation.py`'s few-shot injection, `/copy-library` page) pulls every ACTIVE/PAUSED ad from Meta
automatically and uses it as style reference for every generation call. Adnova's version is more
manual/curatorial (you pick specific ads to save as a named template); ours is automatic (all synced
ads feed every generation). Ours is arguably the better default for Joel's actual workflow — he doesn't
pick reference ads by hand today — so this isn't a gap so much as a different, already-adequate design.
No action recommended here.

## 5. Ad Templates library — real competitor-ad layouts, not AI generation

This is the part explicitly asked about for our Template/Style section, and it's a fundamentally
different mechanism than what we have.

**Ours:** a style catalog of `mood`/`lighting`/`composition`/`design_style` descriptors that get fed
into a Sonnet-authored scene prompt, then rendered by kie.ai (Flux Kontext Pro). Fully generative, no
real ad ever existed until the model makes one.

**Adnova's:** every "template" is a **real, scraped competitor ad screenshot** (their own ad-spy
`/library/discover` feed is almost certainly the source), pre-rebuilt as an editable, layered Figma
design. Clicking "Copy" on a template pops "Copied to clipboard. Now paste in Figma" — it's a
clipboard-to-Figma handoff, not an in-app editor. There's a second "Copy" button per card (a separate
icon) that's almost certainly "copy the ad copy text" rather than the design — a deliberate
design/copy split, same idea as our own separated image-generation vs. copy-generation pipelines.

Two organizing taxonomies, browsable independently:
- **Industry Templates** — Beauty, Fashion, Food & Beverage, Health & Wellness, Home Decor, Jewellery &
  Watches, Kids & Baby, Pets, Sports & Outdoor, Subscription Services. All e-commerce/retail verticals —
  **none map to insurance, financial products, or lead-gen**, so this specific taxonomy isn't directly
  reusable for us.
- **Theme Templates** — this is the one worth stealing: **persuasion-angle-based**, not
  product-category-based. Before/After, Benefit Without Objection, Comparison Ads, Features Callout,
  Media/Press, Native Ads, Problem→Solution, Question Framework, Results-Driven Showcase, Sale, Social
  Proof, Testimonial. Every one of these angles applies directly to insurance/financial lead-gen
  creative — arguably more cleanly than to e-commerce.
- **Season Templates** — calendar-driven (Back to School was the live seasonal push during this
  research). Lower priority for BHM's verticals but cheap to replicate as a filter if we ever build a
  static style-preset library.

**Concrete recommendation for our Style/Template section:** re-organize (or add a parallel axis to) our
existing style catalog by **persuasion angle** (Before/After, Problem→Solution, Social Proof,
Comparison, Testimonial, etc.) instead of purely visual descriptors like mood/lighting. Joel and Abel
already think in angles when they brief an ad — this would let them pick "I want a Problem→Solution ad"
and have that resolve to the right mood/lighting/composition combination under the hood, rather than
requiring them to translate an angle into visual language themselves. This is a copy/prompt-layer
change, not a rendering-architecture change — we'd keep our own generative pipeline, just re-skin the
picker and let angle selection set sensible mood/lighting/composition defaults.

## 6. Not reached / not applicable

- `/app/mcp` (their own MCP integration) — not explored, low priority for this research.
- `/app/analytics` — not explored, out of scope (we have our own Dashboard/CAPI Quality/P&L surfaces
  already covering this ground).
- Ad Copy Template editor detail (empty account, no template existed to open).
- Per-asset detail/tagging panel on the Creatives page — the one video preview opened was closed before
  its panel could be reviewed; based on the Custom Fields filter existing on the table view, this is a
  believable place custom fields/tags get set, but wasn't directly confirmed.

## 7. Recommended build order coming out of this

1. **Ask Joel directly** what's actually missing/broken about the existing Drive picker in
   `AdCreativeStep.jsx` before building anything — the feature exists; the complaint likely isn't "we
   have no mass upload."
2. **Revise `CODEX_BRIEF.md`** (naming templates) to use Dynamic-Tag-style tokens
   (`{{ad_set_name}}`, `{{campaign_name}}`, `{{date}}`) pulled from real context already in scope,
   rather than the narrower literal set currently drafted — small change, same file, not yet sent to
   Codex.
3. **Angle-based Style/Template taxonomy** — re-skin the existing style picker in `ImageAds.jsx` /
   `BatchGenerate.jsx` around persuasion angles (Before/After, Problem→Solution, Social Proof, etc.),
   mapping each to existing mood/lighting/composition/design_style combinations. Medium scope,
   frontend + style-catalog config only, no backend architecture change.
4. **Custom Fields / Launch Status on Drive assets** — only if Joel's answer to #1 points here. Would
   need new columns on `DriveAsset` (migration) plus UI — bigger lift, don't build speculatively.

Everything else from the earlier 4-platform research (naming templates, Winners surface, AdRemix review
gate, silent-fallback audit) remains queued behind this per Steve's explicit ordering.
