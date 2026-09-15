# Ad Launcher + Styles (Templates) — Dev Brief

Combines two threads Steve asked to move on together: (1) fixing the ad-launcher/mass-upload
experience Joel flagged as a gap, informed by the Adnova competitive teardown
(`AdBuilder-Adnova-Competitive-Research.md`), and (2) reworking the Template/Style section around
persuasion angles instead of pure visual descriptors. "Styles" is the working name per Steve — not
tied to it, can rename freely during build.

---

## 1. Executive Summary

**The problem:** Joel told Steve the ad launcher needs work and that mass-upload-from-Drive "may have
been overlooked." Code trace confirms the Drive mass-upload pipeline already exists and works
(`drive_sync_service.py`, 1,034 synced assets, multi-select picker in `AdCreativeStep.jsx`) — but it's
a secondary button buried on step 4 of a 5-step wizard, and the resulting "bulk create" flow is a
sequential, one-Graph-API-call-per-ad loop that always launches ads PAUSED with no server-side draft
state. Separately, our Style catalog for AI image generation is organized by visual descriptors
(mood/lighting/composition) when Joel and Abel actually think in persuasion angles (Before/After,
Problem→Solution, Social Proof) when briefing an ad.

**The solution:** Three independent, sequenceable workstreams — surface the existing Drive picker
better, close the real batch-launch gaps (Meta Batch API, launch-status default, server-side draft
persistence, auto-naming), and re-skin the Style picker around angles. None require a full rebuild;
all build on infrastructure that already exists.

**The economics:** This isn't revenue-generating on its own — it's operator time. Joel currently
hand-launches ad sets one at a time through a wizard that already supports bulk creation but hides it
and self-throttles it. If the real complaint is discoverability (most likely, per the research), the
fix is near-zero engineering cost and immediately removes friction from his daily workflow. The
batch-launch and naming work is heavier but pays back every time he scales a winning angle to more ad
sets — which, per `bhm-context`, is the actual growth lever for RHO's Commercial Insurance account.

---

## 2. Flow Diagrams

### 2a. Current state — how an ad actually gets from Drive to Meta today

```
/facebook-campaigns
  Step 1: Ad Account
  Step 2: Campaign
  Step 3: Ad Set
  Step 4: Ad Creative  ──┐
    "Ad Media" section    │  <- "Browse Drive Creative Library" button lives HERE,
    [Browse Generated]    │     secondary to "Browse Generated Ads Library",
    [Browse Drive Lib] ───┘     easy to miss on first pass
       │
       ▼
    Modal: "Select from Drive Creative Library"
    checkbox multi-select (Set<id>) → "Add N to Campaign"
       │
       ▼
    Fill headlines / bodies / CTA / URL / Page (once, shared across all)
       │
       ▼
  [Batch Mode: Combinations] toggle (separate, above the creative step)
       │
       ▼
  Step 5: Bulk Ad Creation (only reachable in Combinations mode)
    auto cross-multiplies creatives × headlines × bodies
    → grid of "{media} - H{n}B{n}" named ads, each editable
       │
       ▼
    Click "Create N Ads on Facebook" (ONE click)
       │
       ▼
    Sequential loop, N times:
      upload image/video → create Facebook creative → create_ad (Graph API)
      350ms delay between each
       │
       ▼
    All N ads launched — status: PAUSED (always)
       │
       ▼
    Joel manually activates each ad set in real Meta Ads Manager  ← extra manual step
```

### 2b. Target state — after this brief ships

```
/facebook-campaigns  (or a new dedicated "Bulk Launch" entry point — see §3.1)
  Step 4: Ad Creative
    "Ad Media" section — Drive library promoted to CO-EQUAL, first-listed option
    [Browse Drive Library]  [Browse Generated Ads Library]
       │
       ▼
    Drive picker: multi-select + Launch Status / Custom Fields / Tags filters (see §3.3)
       │
       ▼
  Naming: auto-resolved via saved Ad Naming Convention (see §3.4) — no per-card retyping
       │
       ▼
  Step 5: Review grid — server-side draft persisted on every change (see §3.2)
       │
       ▼
    Click "Launch N Ads"
       │
       ▼
    Meta Batch API call(s) — grouped up to Meta's batch limit, not 1-by-1
       │
       ▼
    Ads launch per explicit Launch Status choice (Paused / Active — user picks, no forced default)
       │
       ▼
    Done. No further manual Meta Ads Manager step required for the common case.
```

---

## 3. Detailed Spec

### 3.1 Drive picker discoverability (cheapest fix, do first)

**Problem:** `AdCreativeStep.jsx:1029-1036` renders "Browse Drive Creative Library" as the second of
two buttons under "Ad Media (Images or Videos) *", visually identical weight to "Browse Generated Ads
Library." Nothing distinguishes "1,034 assets already synced from Drive" from "assets we generated."

**Fix:**
- Reorder so Drive Library is the first/primary button (it's the larger, more relevant library for
  bulk work) — swap position, same component.
- Add a live count badge: "Browse Drive Creative Library (1,034)" — pulls from the existing
  `GET /drive-assets` response Steve already gets today, no new endpoint.
- Add a one-time, dismissible callout the first time a user lands on Step 4 pointing at the button
  ("New: browse your synced Drive assets here") — localStorage-dismissed flag, same pattern as other
  onboarding hints in the app if any exist; if not, a simple `localStorage.getItem('driveLibraryHintSeen')` guard is enough.
- **Before building any of the rest of this brief, confirm with Joel directly** whether this alone
  resolves his complaint. If yes, stop here for the discoverability half — no reason to build the
  batch-launch and naming work speculatively if the real ask was just "I didn't see the button."

### 3.2 Server-side draft persistence for the bulk review grid

**Problem:** `BulkAdCreation.jsx`'s `adsData` state (the reviewed N-ad grid) is pure client-side React
state. A refresh, tab close, or crash mid-review loses everything — Joel has to reselect creatives and
retype headlines from scratch.

**Fix:** New table `ad_launch_drafts` (migration required — hand off to Claude Code, not Codex, per
CLAUDE.md):
```sql
id, user_id, campaign_id (nullable, pre-launch), adset_id (nullable), payload JSONB, status
('draft'|'launching'|'launched'|'failed'), created_at, updated_at
```
`payload` stores the full `adsData` array (creative refs, headlines, bodies, per-ad names, CTA, URL).
Autosave on every edit (debounced, same pattern as any other autosave in the app — check for an
existing debounce util before writing a new one). On page load, if an unlaunched draft exists for the
in-progress campaign, offer to restore it. This is the piece that makes "review before you commit" a
real safety net instead of a fragile in-memory state.

### 3.3 Batch launch via Meta Batch API

**Problem:** `BulkAdCreation.jsx:503-658` calls `createCompleteAd` once per ad in a `for` loop
(`facebookApi.js:575-615` → `facebook_service.py:1473-1504`, one `account.create_ad` Graph call each),
throttled by a hardcoded 350ms delay (`metaRateLimit.js:28`). The app's own pre-flight rate-limit
check recommends Joel manually launch "5-10 at a time" (`BulkAdCreation.jsx:198`) instead of the app
handling batching itself.

**Fix:** Meta's Marketing API supports batched requests (`POST /` with a `batch` array, up to 50
sub-requests per call, documented at `graph.facebook.com/vX.Y/`). Restructure `create_ad` (and the
creative-creation call immediately before it) to build a batch payload and submit in chunks of 50
instead of N individual calls. **Before touching `facebook_service.py`: per CLAUDE.md, spawn a
domain-expert review agent against the current `facebook-business` SDK source
(`github.com/facebook/facebook-python-business-sdk`) to confirm the batch endpoint's current field
names, error-handling shape per sub-request, and whether image/video upload (which must precede
creative creation) can be included in the same batch or must stay a separate pre-step.** Image/video
upload is very likely NOT batchable (binary upload), so the realistic shape is: upload all media
first (already parallelizable, currently sequential — cheap parallelization win on its own), then
batch the creative + ad creation calls.

**Expected impact:** N ads today = N sequential round trips × (upload + creative + ad) + 350ms each.
After: media uploads run in parallel, then creative+ad creation collapses to `ceil(N/50)` batch calls.
For a typical 10-20 ad batch, this should cut launch time from tens of seconds to low single digits.

### 3.4 Launch status — explicit choice, not a forced default

**Problem:** `BulkAdCreation.jsx:601` hardcodes `status: 'PAUSED'` for every launched ad. There's no
UI control for this at all today — Joel can't choose, and always needs an extra manual step in real
Meta Ads Manager to go live.

**Fix:** Add a simple toggle to Step 5 ("Launch ads as: Paused / Active", defaulting to **Paused** —
keep the safe default, per how I handled this myself during the Adnova research walkthrough, but make
it an explicit, visible choice instead of a silent hardcode). This is a small, low-risk UI + payload
change, not a trigger-file-severity change on its own — but since it lives inside `BulkAdCreation.jsx`
it still goes through the mandatory review per CLAUDE.md's trigger-file list.

### 3.5 Ad naming — adopt Adnova's Dynamic Tag pattern, revise the pending brief

**Problem:** `CODEX_BRIEF.md` (not yet sent to Codex) currently scopes naming templates only for the
manual `/facebook-campaigns` Campaign Name / Ad Set Name fields, with a narrow fixed token set
(`{date}`, `{objective}`, `{countries}`, `{age_range}`). It doesn't touch ad-level naming at all — that
stays the `H{n}B{n}` pattern in `BulkAdCreation.jsx`, which the original brief explicitly deferred.

**Fix — revise `CODEX_BRIEF.md` before sending it, don't build the narrower version:**
- Keep the Campaign/Ad Set scope from the existing brief (still valid, still useful, still zero
  migration).
- Extend the token model to a **Dynamic Tags** pattern like Adnova's: tokens that resolve from real
  context already in scope at each level —
  - Campaign scope: `{date}`, `{objective}`
  - Ad Set scope: `{date}`, `{objective}`, `{countries}`, `{age_range}`
  - **New — Ad scope** (wire into `BulkAdCreation.jsx`'s name generation, replacing the fixed
    `H{n}B{n}` string): `{campaign_name}`, `{ad_set_name}`, `{headline_num}`, `{body_num}`,
    `{media_name}`, `{date}` — all of these are already available in scope at the point
    `BulkAdCreation.jsx:94` builds the name string, so this is a resolver-function change, not a new
    data-fetch.
- **Do not** build Adnova's Placeholder Text tier (`{{offer}}`, `{{concept}}`, per-asset manual
  tagging) in this pass — it requires custom fields on `DriveAsset`, which don't exist today (see
  §3.6 for that as a phase-2 item). Keep this pass to Dynamic Tags only, which need zero new schema.
- No migration for the Campaign/Ad Set scope (localStorage, as originally scoped). The Ad-scope
  naming resolver is pure frontend logic in `BulkAdCreation.jsx` — also no migration.
- `CampaignStep.jsx`/`AdSetStep.jsx`/`BulkAdCreation.jsx` naming changes are NOT DB-migration work, so
  this can still go to Codex per the project's routing rules — `BulkAdCreation.jsx` is a trigger file
  requiring hand-off to Claude Code for the final push + review, but Codex can build it.

### 3.6 [Phase 2 — directional, not scoped for this pass] Drive asset custom fields / tags / Launch Status

Adnova's Creatives table shows Launch Status (used/not-used at a glance), Custom Fields, Tags, and
Boards per asset. We have none of this on `DriveAsset` today. This is real, valuable gap-closing work
— but it needs a migration (new columns/table), and per §0 of the research doc, **should only be
built if Joel's answer to the discoverability question in §3.1 says this is actually what he's
missing.** Don't build speculatively.

If it does get greenlit later: minimum viable version is a `launch_status` computed field (join
against `generated_ads`/launched-ad records by matching Drive asset reference — likely derivable
without new columns, since we may already track which asset a launched ad came from) before reaching
for full custom-fields/tags infrastructure.

### 3.7 Styles (Template) section — angle-based taxonomy

**Problem:** Current style catalog (feeding `_build_ai_image_prompt()`/`build_comprehensive_prompt()`
in `generated_ads.py`) is organized around visual descriptors: `mood`, `lighting`, `composition`,
`design_style`. Joel and Abel brief ads in terms of persuasion angle ("give me a before/after," "I
want social proof"), not visual language — they'd have to translate their own intent into
mood/lighting terms today, which is an unnecessary cognitive step.

**Fix — add an angle layer on top of the existing visual-descriptor system, don't replace it:**
- New top-level selector in the Style step of `ImageAds.jsx`/`BatchGenerate.jsx`: **Angle**, with
  options taken from Adnova's Theme Templates taxonomy (directly relevant to insurance/lead-gen, unlike
  their Industry taxonomy which is retail-only and not worth copying):
  - Before/After
  - Benefit Without Objection
  - Comparison
  - Features Callout
  - Problem → Solution
  - Question Framework
  - Results-Driven Showcase
  - Social Proof
  - Testimonial
  - Sale/Offer (maps to existing "urgency" style work if any exists — check before adding a duplicate)
- Each Angle maps to a **default** `mood`/`lighting`/`composition`/`design_style` combination (config,
  not a new DB table — same place the current style catalog constants live; find that file before
  writing new config location). Selecting an Angle pre-fills these fields; user can still override any
  individual visual field afterward — this is additive, not a replacement of the existing style
  picker's flexibility.
- The Angle selection also becomes a piece of context fed into the Sonnet scene-prompt call in
  `_build_ai_image_prompt()` — e.g., a "Before/After" angle should bias the AI-authored scene prompt
  toward a literal before/after visual composition, not just pick matching mood/lighting. This needs a
  short prompt-instruction addition per angle, not a structural change to the function.
- No migration needed if Angle is stored the same way current style selections are stored today
  (check whether style choice persists to DB per generated ad, or is request-only/ephemeral — if it's
  already a column on `generated_ads`, add `angle` the same way, `ADD COLUMN IF NOT EXISTS` per
  CLAUDE.md's column pattern).

**Out of scope for this pass:** copying Adnova's Industry taxonomy (Beauty/Fashion/Food/etc. — none of
it maps to our verticals) or their Season taxonomy (lower priority, cheap to add later as a pure filter
if ever wanted).

---

## 4. Routing / Decision Logic

| Question | Answer | Why |
|---|---|---|
| Codex or Claude Code for §3.1 (discoverability)? | Codex — pure frontend, no trigger file logic beyond a reorder/badge in `AdCreativeStep.jsx` (which IS a trigger file — so Codex builds, Claude Code does final push + review) | `AdCreativeStep.jsx` is a trigger file per CLAUDE.md regardless of change size |
| Codex or Claude Code for §3.2 (draft persistence)? | Claude Code | New migration required |
| Codex or Claude Code for §3.3 (Batch API)? | Claude Code | Touches `facebook_service.py`, a trigger file, and needs the mandatory Meta-API domain-expert review agent |
| Codex or Claude Code for §3.4 (launch status toggle)? | Codex builds, Claude Code pushes | Trigger file (`BulkAdCreation.jsx`), no migration |
| Codex or Claude Code for §3.5 (naming)? | Codex builds, Claude Code pushes | Trigger file touched (`BulkAdCreation.jsx`), no migration |
| Codex or Claude Code for §3.7 (Angle taxonomy)? | Codex builds (unless it touches a migration — confirm first), Claude Code pushes if any trigger file is touched | Depends on where style catalog config lives — verify before starting |
| Build §3.6 now or later? | Later — gated on Joel's answer | Per research doc §0, don't build speculatively |

---

## 5. Integration Specs

- **§3.3 (Batch API):** hard dependency on confirming Meta's current batch endpoint contract via the
  mandatory domain-expert review agent before writing code — do not assume the batch shape from
  memory or older docs, per CLAUDE.md's Meta API rule (this caught real deprecated-enum bugs before).
- **§3.5 (naming):** Ad-scope resolver reads from the same in-scope variables `BulkAdCreation.jsx:94`
  already has when building `"{media} - H{n}B{n}"` — confirm `campaign_name`/`ad_set_name` are
  actually threaded down to that component before assuming zero-plumbing; if not, it's one extra prop,
  not a new fetch.
- **§3.7 (Angle):** if `_build_ai_image_prompt()`'s Sonnet call needs the Angle as extra context,
  confirm the current prompt-construction function signature can take an additional field without
  breaking the `reviewedPrompt`/`customPrompt` aspect-ratio-seeding logic added earlier this session
  (`generated_ads.py`) — trace end-to-end per CLAUDE.md's "trace every feature" rule before calling
  this done.

---

## 6. Tracking & Analytics

No new analytics surface needed for this pass — this is operator-tooling, not a user-facing funnel.
The one thing worth logging: on the batch-launch call (§3.3), log success/failure count per batch
chunk (not per individual ad) so a partial-batch failure is diagnosable without re-deriving it from
Meta's own logs. Where existing launch logging lives (if any) — extend that, don't invent a new
logging path.

---

## 7. Build Priority / Phased Rollout

**Phase 1 — ready for review, build first:**
1. §3.1 Drive picker discoverability (cheapest, might resolve the whole complaint on its own)
2. §3.5 Naming — revise `CODEX_BRIEF.md`, then send to Codex
3. §3.7 Angle taxonomy for Styles

**Phase 1.5 — gate on Joel's answer before starting:**
4. Confirm with Joel whether §3.1 alone resolved his complaint

**Phase 2 — only if Joel's answer says more is needed:**
5. §3.2 Draft persistence (migration)
6. §3.3 Meta Batch API (facebook_service.py, needs domain-expert review)
7. §3.4 Launch status toggle

**Phase 2 directional (not scoped, don't build without a separate greenlight):**
8. §3.6 Drive asset custom fields / tags / Launch Status column

---

## 8. Open Questions & Dependencies

1. **Does Joel's complaint resolve with better discoverability alone, or does he need the deeper
   batch-launch mechanics (§3.2-3.4)?** This gates whether Phase 2 happens at all. Ask before building
   Phase 2.
2. Where does the current style catalog config actually live (file/table)? Needs a quick check before
   §3.7 starts — referenced but not confirmed in this brief.
3. Is style choice persisted per generated ad today (DB column) or ephemeral/request-only? Determines
   whether `angle` needs a migration or not.
4. Are `campaign_name`/`ad_set_name` already threaded into `BulkAdCreation.jsx`'s scope, or does §3.5
   need one extra prop passed down? Quick check before starting.
5. Meta Batch API's exact current contract (field names, per-sub-request error shape, image/video
   upload batchability) — must be confirmed live via `/v1/models`-style verification against the SDK
   source, not assumed, before §3.3 starts.
