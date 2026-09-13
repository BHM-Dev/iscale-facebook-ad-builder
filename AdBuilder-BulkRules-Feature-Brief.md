# Cross-Ad-Set Bulk Rules — Feature Brief

Reference walkthrough: Birch (formerly Revealbot), `app.bir.ch`, live account (RHO 4 – Commercial)
connected 2026-09-11. Screens inspected: Automated Rules builder, action catalog, Stage
(planning-sheet-to-ads). No rule was saved or activated during the walkthrough.

---

## 1. Executive summary

**The problem:** `BulkAdCreation.jsx` already does real bulk creation — media × headline × body
permutations, launched together. What it doesn't do is bulk *management* across ad sets that
already exist. Today, if Joel wants to raise budget on 10 ad sets, pause 6 underperformers, or
notify himself when CPL crosses a threshold, he does it one ad set at a time in
Campaign Performance — same as native Ads Manager, no leverage gained from having a custom tool.

**The solution:** A **Rules** surface — separate from the ad-creation wizard — where Joel defines
a filter (which ad sets a rule applies to) and a task (what happens), and the system runs it on a
schedule against every matching ad set. This is the single most requested category of feature in
every competitor bulk tool we could verify (Birch/Revealbot's own name for it), and it's the
concrete gap identified against BHM's own code.

**The economics:** Joel manually checks and adjusts ad sets multiple times a day per his own
Slack messages (`C0BG015BAJU`, "Value test failing," daily P&L check-ins with Abel). A rule that
auto-pauses a bleeding ad set the moment CPL crosses a threshold, or auto-notifies at 6am instead
of Joel finding out at 11am, is a direct dollars-saved and time-saved feature — not a nice-to-have.

---

## 2. What we saw, verbatim from the reference tool

Birch's Automated Rules screen has three parts, always in this order:

```
┌─────────────────────────────────────────────┐
│ Ad account   → pick 1-5 connected accounts    │
├─────────────────────────────────────────────┤
│ Filter       → scope: campaigns / ad sets / ads │
│               condition rows (e.g. "Ad set     │
│               status is active")               │
│               → live "Estimated match: N ad     │
│                 sets" counter                   │
├─────────────────────────────────────────────┤
│ Task         → action type (see catalog below) │
│               → condition rows that trigger it  │
│                 (metric | time window | op |    │
│                 value, e.g. "Spend | Today | >  │
│                 | $0")                          │
│               → "+ Condition" / "+ Group" to     │
│                 AND/OR-chain more triggers        │
│               → "+ Add task" to chain a second   │
│                 action in the same rule           │
├─────────────────────────────────────────────┤
│ Schedule     → how often the rule runs           │
├─────────────────────────────────────────────┤
│ Save draft   |   Set live                        │
└─────────────────────────────────────────────┘
```

The **live match counter** ("Estimated match: 22 ad sets") is the single most important UX
detail — Joel sees exactly how many ad sets a rule will touch *before* he commits to it. That's
the guardrail that makes bulk action feel safe instead of reckless.

### Action catalog (grouped exactly as shown in-app)

| Category | Actions |
|---|---|
| General | Start, Pause, Delete, Duplicate, Notify, Extend the end date |
| Budget | Increase budget, Decrease budget, Set budget, Scale budget by target |
| Bid | Increase bid, Decrease bid, Set bid, Scale bid by target, Set bid strategy |
| Spending limits | Set spending limits, Remove spending limits, Increase spending limits, Decrease spending limits |
| Name/text | Add to name, Remove from name, Replace text in name |

Pre-built strategy templates on the landing screen (skip-the-blank-page onboarding):
**Notify about key metrics drops** (ROAS drop check, CPP, CPM), **Optimize performance** (ROAS
optimization, budget reallocation, CPP tracking), **Scale ad sets** (ROAS optimization, budget
reallocation, CTR tracking).

### Secondary reference: Stage (planning-sheet → live ads)

Separate feature, same product. Connect a Google Sheet + Drive folder; Stage maps sheet columns
to ad platform parameters and builds ads from the sheet, one ad set per Drive folder, media
grouped by placement. Also supports "duplicate a winning ad set structure, swap in new creative,
keep everything else." Worth a follow-up brief of its own — not scoped here, but the same
"structure stays fixed, only creative swaps" pattern maps directly to your niche-lander rollout
(`getbusinesscoveragequote.com/lp/*` — same shell, different niche content).

---

## 3. What this maps to in the Ad Builder

None of this exists today. The closest thing is `auto_pause.py` / `AutoPauseRules.jsx`
(per `backend/app/api/v1/auto_pause.py`, scheduler job every 30 min) — but per the "Still
pending" list in `CLAUDE.md`, it's scoped narrowly: no scaling rules, no ad-level pausing (only
ad-set), no persistent audit log, no time-window restrictions. This brief proposes generalizing
that existing foundation rather than building a second, parallel rules engine.

| Birch concept | Existing BHM equivalent | Gap |
|---|---|---|
| Filter → live match count | None | Auto-pause rules apply globally per account, no ad-set-level filter/preview |
| Task: Pause | `auto_pause.py` enforcement | Exists, but only "pause," no budget/bid actions |
| Task: Increase/Decrease budget | None | Not built |
| Task: Notify | Slack `slack_service.py` posts to `C08G7PJJ6NB` on auto-pause | Exists for pause only, not generalized |
| Task: Duplicate | None | Not built — this is the highest-leverage one for niche-testing workflows |
| Schedule | 30-min scheduler already exists (`scheduler_service.py`) | Reusable as-is |
| Rule audit log | None | Explicitly on the "Still pending" list already |

---

## 4. MVP vs. full-vision scope

**MVP (1-2 weeks):**
- Generalize existing `AutoPauseRules.jsx` + `auto_pause.py` from "pause only" to a small action
  set: Pause, Notify, Increase budget, Decrease budget — the four actions that map directly to
  what Joel and Abel are already doing manually in Slack today (see `C0BG015BAJU`: "I updated all
  the CAPI campaigns in RT to 50/50," "auto dealership CAPI is off to a slow start... turned it on
  in the original account").
- Filter: ad-set level only (matches current scope), with the same "which brand/niche" filter
  primitives already in Campaign Performance.
- **Live match-count preview before save** — the one UX detail from Birch worth copying exactly,
  since it's the trust mechanism that makes bulk changes feel safe.
- Reuse the existing 30-min scheduler; no new infra.
- Persist a rule-trigger audit log (metric values at trigger time) — already flagged as pending,
  do it now while touching this code anyway.

**Full-vision (phase 2, not now):**
- Duplicate action (ad-set-level clone-with-new-creative) — this is the one that most directly
  answers "add features from good ad launchers," but it's a materially bigger build (touches
  `facebook_service.py`, a trigger file) and deserves its own brief once MVP is proven.
  bid actions (Increase/Decrease/Set bid, bid strategy) — lower priority, Joel's campaigns are
  mostly CBO per the CAPI/RT conversation, not manual bid.
  Scale-by-target (auto budget scaling toward a ROAS/CPL target) — genuinely valuable but needs
  the audit log and match-count preview proven safe first.

---

## 5. Routing note

This touches `backend/app/api/v1/auto_pause.py` and likely `backend/app/services/facebook_service.py`
(new actions = new Meta API calls: budget update, campaign duplicate). Per `CLAUDE.md`,
`facebook_service.py` is a trigger file — full 2-agent pre-push review required before any push.
Frontend work on `AutoPauseRules.jsx` is not a trigger file itself but will need the same review
given it's part of the same feature and touches money-affecting logic.

Not a Codex task per the STOP rule — this needs Claude Code from the start (trigger file +
architectural decision on generalizing an existing rules engine vs. bolting on).

---

## 6. Open questions before scoping the MVP for real

1. ~~Confirm with Joel: of the four MVP actions...~~ — shipped all four (Pause/Notify/Increase
   budget/Decrease budget) rather than picking one first; Joel can use whichever he wants per rule.
2. ~~Match-count preview — live vs. cached?~~ — resolved: local synced cache (`/facebook/adsets/saved`),
   not a live Meta call. The count itself is just `selectedIds.size` (client-side, instant); the
   optional confirm-step budget preview uses the same cached `daily_budget`/`campaign_daily_budget`
   fields, explicitly labeled "as of last sync" — the rule's actual fire always re-reads the true
   live value from Meta regardless, so a stale preview number can't cause a wrong amount to be sent.
3. ~~Replace auto_pause.py outright, or run alongside?~~ — replaced in place, as recommended. Existing
   pause-only rules keep working unchanged (`action` defaults to `'pause'` on every pre-existing row).

## 7. Shipped 2026-09-13 — what actually got built vs. this brief

Built substantially as scoped, plus real fixes surfaced by the mandatory pre-push review (code-auditor
+ joel-perspective + a Meta-API domain-expert pass, since this touches `facebook_service.py` and a
DB migration):

- **All four MVP actions** — Pause/Notify/Increase budget/Decrease budget, per rule.
- **Budget actions are CBO-aware and safety-refuse rather than silently affect siblings.** A CBO
  campaign's budget is shared across every ad set under it — the domain-expert review caught that
  a rule scoped to one ad set could silently move budget for OTHER ad sets sharing that campaign,
  with nothing in the Slack alert or audit log saying so. Fixed conservatively: the rule refuses to
  fire (logs an error, no Meta call made) whenever another ACTIVE ad set shares the same CBO
  campaign, and always labels a campaign-level adjustment explicitly when it does proceed.
  Read-modify-write against Meta's live budget value at fire time (never trusts the local cache for
  the actual write), with a sanity floor+ceiling on the percent adjustment.
- **Rule-trigger audit log** — `auto_pause_rule_logs` table + `GET /rules/{id}/logs`, wired into the
  UI as a per-rule "Fire history" popover (not just built and left unused on the backend).
- **Live match-count + bulk create** — multi-select ad sets with a search box, `POST /rules/bulk`
  creates one independent rule per selected ad set (all-or-nothing validation).
- **Budget-action confirm step** — a mandatory second screen listing every matched ad set's current
  → computed-new budget before any rule is created, plus an explicit "this moves real live spend,
  unattended" warning the moment a budget action is picked. Neither existed in the original build;
  both came out of joel-perspective's review flagging bulk-scoped budget changes as a real footgun
  with only a live count as the guardrail.
- **Notify cooldown** — 4 hours between repeat Slack alerts for the same still-breached notify rule,
  to avoid indefinite alert-fatigue spam (also from joel-perspective review).
- **Shipped 2026-09-13**: an edit UI (`EditRuleModal`) for changing an existing rule's
  action/percentage/metric/operator/threshold/min-spend via PATCH instead of delete+recreate.
  Pre-push review caught a real blocking bug in the first pass — the backend's `RulePatch` schema
  never declared `metric`/`operator`, so Pydantic silently dropped both fields; a user editing
  Metric or Condition got a "Rule updated" success toast while the change was discarded and the
  rule kept firing on its old values. Fixed by adding both fields to the schema and persisting
  them the same way `threshold`/`min_spend` already were.
- **Still not built**: a symmetric ±% single field instead of separate increase/decrease actions;
  Duplicate action and bid actions — deferred to Phase 2 in §4 above, now scoped in full in §8.

---

## 8. Phase 2 scope — Duplicate action + bid actions

Scoping only — not built yet. Grounded against the actual codebase (not assumed) before writing
this, since the two actions turned out to be very different sizes once checked.

### 8.1 Bid actions — small, follows the exact pattern already built

Checked `facebook_service.py`'s `create_adset` (lines ~928-940): `bid_amount`/`bid_strategy`
already flow through ad-set creation today, with the identical CBO-vs-ABO split my Phase 3 budget
work already solved — CBO campaigns carry `bid_strategy` at the **campaign** level (ad sets
inherit it), ABO ad sets carry it themselves. That means `increase_bid`/`decrease_bid` as rule
actions are close to a copy-paste of `adjust_adset_budget_by_percent`, adjusted for `bid_amount`
instead of `daily_budget`/`lifetime_budget`, with the same CBO-refuse-if-shared-siblings posture
carried over rather than re-derived from scratch.

**MVP for this piece:**
- `increase_bid` / `decrease_bid` actions, mirroring the existing budget-action shape exactly:
  read live `bid_amount` from Meta at fire time, adjust by a rule-configured percent, same
  floor/ceiling sanity check, same CBO-sibling refusal, same audit-log/Slack treatment.
- Reuse `AdSetStep.jsx`'s existing bid fields (already present for manual ad-set creation) as the
  reference for what a "bid" even means here — `bid_amount` is a per-action cost cap under manual
  bidding, not meaningful for `LOWEST_COST_WITHOUT_CAP` (the default). **Open question:** does a
  bid-adjustment rule only apply to ad sets already on manual/cost-cap bidding, and refuse
  otherwise (mirroring the budget action's CBO refusal pattern) — recommend yes, for the same
  reason: silently "adjusting" a bid field Meta isn't even using would be a no-op that looks like
  it worked.
- Not scoping `set_bid_strategy` (switching bidding models entirely) — a bigger, riskier action
  than a percent nudge, not requested, not in Birch's own MVP-equivalent tier either.

**Estimate:** genuinely small once Phase 3's budget-action code exists to mirror — a few hours of
focused work plus the mandatory 2-agent + domain-expert review, not a new phase-sized effort.

### 8.2 Duplicate action — the actual big piece

This is the one Birch's own capture flagged as "the one that most directly answers 'add features
from good ad launchers'" — and it's a real, multi-step Meta API orchestration, not a field tweak.

**What "Duplicate" has to actually do, step by step:**
1. Read the target ad set's full config live from Meta (targeting, optimization goal, budget,
   bid settings) — `get_adsets`/`create_adset`'s existing field lists cover most of this already.
2. Read every live ad in that ad set and its creative — `get_ads(adset_id)` (exists) +
   `get_ad_creative(fb_ad_id)` (exists, already used by Copy Library) cover the read side. Meta
   creative objects reference an `image_hash`/`video_id` already uploaded to the ad **account**
   (not the ad set) — needs verifying, but if true, a duplicate within the same account can reuse
   those hashes directly without re-uploading media, which would materially simplify this.
3. Create a new ad set with the copied config (`create_adset`, already proven) — same budget as
   the source unless the rule says otherwise (see open question below).
4. Create a new ad for every ad in the source, using the copied creative
   (`create_creative`/`create_ad`, already proven) — new ad set, same copy/images.
5. Launch PAUSED, matching this app's existing convention everywhere else.

**Update 2026-09-13 — checked live against both tools rather than guessed.** AdEspresso's
Optimization Rules has no Duplicate action at all (re-confirmed live: exactly 3 actions — pause
it / increase bid / decrease bid). Birch's does, and its actual config screen (`app.bir.ch`,
Automated Rules → Duplicate, live RHO 4 account, nothing saved) answers three of the four open
questions directly — real product decisions Birch already made, not assumptions:

1. **All ads, or only the trigger ad?** Birch's Duplicate is ad-set-scoped (matches how BHM's
   rules are already scoped) and defaults to **duplicating every ad in the ad set** — with an
   explicit second radio option, "Duplicate the ad set without the ads inside," for an
   empty-ad-set-only clone. So Birch treats "all ads" as the default, not a forced-only behavior —
   worth offering both, defaulting to "all ads" to match.
2. **Same budget, or a bump?** Confirmed: **no budget field anywhere in Birch's Duplicate
   config.** It's a plain clone — same budget as the source, full stop. A budget bump is a
   separate task chained via Birch's own "+ Add task" (Duplicate + Increase budget as two tasks
   in one rule, not one combined action). My original guess was right, and now it's verified: keep
   this as two composable actions, not a new combined "Duplicate + bump" action.
3. **Naming?** Birch's real fields: an editable "Append to duplicate's name" text box, defaulting
   to literally `- Copy`, plus a checkbox "Append the number of duplicate" for when the same ad
   set gets duplicated more than once (turns `- Copy` into `- Copy 1`, `- Copy 2`, avoiding a
   naming collision the same class as the one fixed in Phase 4). Match this exactly — configurable
   suffix, default `- Copy`, numbered on repeat.
4. **One-shot, or can it chain?** Birch's task-level schedule control (the same "Once a day" /
   "Every N minutes" selector every other action uses) defaults Duplicate to **"Once in a
   lifetime"** — but the dropdown does let a buyer choose a repeating frequency instead. So it's
   not hard-locked to one-shot at the platform level; the safe default is one-shot, with repeat
   available as an explicit, deliberate opt-in rather than the default. Matches the original MVP
   recommendation almost exactly — the one adjustment is to allow (not forbid) a buyer to choose a
   repeat frequency, defaulting to one-shot.

**One additional real detail, not previously asked about:** Birch's Duplicate also has an
"Original ad set" setting — **Keep** (default) vs. **Pause** — controlling whether the SOURCE ad
set stays active after duplicating or gets paused. Worth including: a "scale a winner" workflow
usually wants to keep the original running alongside the new copy, but a "duplicate to test a
structural change" workflow might want the original paused. Default to Keep, matching Birch.

**Revised MVP scope, now grounded in a real, shipped competitor implementation rather than
guessed:** duplicate the whole ad set including all its ads (with an option to duplicate the
empty ad set only), unchanged budget, a configurable name suffix defaulting to `- Copy` with
automatic numbering on repeat duplication, one-shot by default with an explicit opt-in for a
repeat frequency, and a Keep/Pause choice for the original ad set defaulting to Keep. Nothing
here needs Joel's input anymore — it's a direct, verified port of a live competitor's own product
decisions, not a guess.

**Estimate:** comparable in size to Phase 4 (the per-media ad-set work) or larger — real new
orchestration across `facebook_service.py`, a new endpoint surface, and its own domain-expert Meta
API review (image_hash/video_id reuse across ad sets specifically needs verifying against Meta's
current docs, not assumed) plus the standard 2-agent trigger-file review. Not a follow-up-sized
task — recommend treating it as its own phase with its own dedicated pass, same as Phases 1-5 were,
once the open questions above are answered.

**Correction, checked against the actual codebase before finalizing this scope:** `get_ad_creative`
does NOT already cover the read side, as first assumed above. Read it directly (`facebook_service.py`
~line 2084) — it fetches `image_url`/`picture`/`thumbnail_url` for display (built for Copy Library's
UI, which only ever renders a preview), never `image_hash`/`video_id`. `create_creative` (the write
side, confirmed at ~line 1248) takes `image_hash`/`video_id` directly as its media reference — so the
account-level-hash reuse assumption is correct, but the existing read method needs extending
(add `link_data{...,image_hash}` / `video_data{video_id,...}` to its field request) or a new
duplication-specific read method needs to sit alongside it. Small, contained fix once identified —
exactly the kind of gap this scoping pass exists to catch before it becomes a build-time surprise.

### 8.3 Concrete technical plan (once the questions above are confirmed acceptable)

**Migration + model** — new columns on `auto_pause_rules`, all nullable/defaulted so existing rows
are unaffected (same pattern as Phase 3's `action`/`budget_adjust_pct` addition):
- `duplicate_all_ads` (bool, default `true`) — false = clone the empty ad set only, per Birch's
  second radio option.
- `duplicate_name_suffix` (string, default `'- Copy'`)
- `duplicate_append_number` (bool, default `false`) — turns the suffix into `- Copy 1`, `- Copy 2`
  on repeat firings of a repeat-enabled rule.
- `duplicate_pause_original` (bool, default `false`) — Keep vs. Pause for the source ad set.
- `duplicate_repeat` (bool, default `false`) — one-shot (disables itself after firing, matching
  every other action's default) unless explicitly set. No per-rule frequency field is needed the
  way Birch has one — this app's scheduler is a fixed 30-minute global cycle, not configurable per
  rule, so "repeat" here just means "don't disable `is_active` after firing," same mechanism
  `notify` already uses.
- `increase_bid`/`decrease_bid`/`bid_adjust_pct` reuse the exact same `action`/`budget_adjust_pct`
  columns already on the table — no new columns needed for bid actions, just new accepted values
  for the existing `action` field.

**`facebook_service.py` additions:**
- Extend `get_ad_creative` (or add a sibling read method) to also return `image_hash`/`video_id`,
  not just the renderable URL — the correction above.
- New `duplicate_adset(fb_adset_id, name_suffix, append_number, duplicate_all_ads, pause_original)`:
  read the source ad set's live config (targeting/optimization/budget/bid — the same field list
  `get_adsets` already requests) → if `duplicate_all_ads`, read every ad via `get_ads` + the
  extended creative-hash read → `create_adset` with the copied config and computed name → for each
  source ad, `create_creative` (reusing the hash/video_id, no re-upload) + `create_ad` → optionally
  `update_adset_status(source, 'PAUSED')` if `pause_original` → launch every new ad PAUSED, matching
  this app's convention everywhere else. Partial-failure handling mirrors Phase 4's per-media
  loop exactly: if ad N of M fails mid-duplication, abort with a message naming how many ads
  already exist on the new ad set, don't silently continue.
- New `adjust_adset_bid_by_percent(fb_adset_id, percent_change)` — near-identical structure to
  `adjust_adset_budget_by_percent` (Phase 3), refusing when the ad set isn't on a manual/cost-cap
  bid strategy (mirrors the CBO-refusal posture, same reasoning: adjusting a field Meta isn't
  using would be a silent no-op).

**`auto_pause.py` additions:** `'duplicate'` and `'increase_bid'`/`'decrease_bid'` added to
`VALID_ACTIONS`; a validation function for the duplicate-specific fields (mirroring
`_validate_action`'s pattern); a new branch in `_run_check` calling `duplicate_adset`, writing the
audit log, sending the Slack alert, and disabling the rule unless `duplicate_repeat` is set (if it
is, apply the same notify-cooldown pattern already built for `notify` rules, so a repeat-enabled
duplicate rule can't fire every 30 minutes indefinitely).

**Frontend (`AutoPauseRules.jsx`):** a 5th action option in `ACTION_OPTIONS`, with its own config
block in `AddRuleModal`/`EditRuleModal` — all-ads-vs-empty radio, name-suffix text field +
append-number checkbox, pause-original checkbox, repeat checkbox — all directly mirroring Birch's
actual field layout rather than inventing a new one. Given this action moves ad-set structure (not
just a number), it should get the same confirm-step treatment budget actions already have —
listing exactly what will be created before the rule is saved.

### 8.4 Routing note

Both pieces touch `backend/app/services/facebook_service.py` (trigger file) and need Claude Code
end-to-end, per the same rule that gated Phase 3's budget work. Bid actions can likely go in the
same pass as their own small feature; Duplicate should get its own dedicated session given its
size — bundling it into a "quick follow-up" pass would be the wrong scale of review for what it
actually is.

## 9. Shipped 2026-09-13 — Phase 2 (commit `a89e236`)

Both pieces from §8 built and shipped together in one pass, per plan.

**Backend:** migration `g3h5i7j9k1l3` (5 new nullable `auto_pause_rules` columns:
`duplicate_all_ads`, `duplicate_name_suffix`, `duplicate_append_number`,
`duplicate_pause_original`, `duplicate_repeat`). Three new `facebook_service.py` methods —
`get_ad_creative_for_duplication` (deliberately separate from `get_ad_creative`, which never
fetches `image_hash`/`video_id`), `duplicate_adset` (builds params directly from the live
read-back rather than reusing `create_adset`'s camelCase-keyed transform, which would have
silently dropped nearly every field), `adjust_adset_bid_by_percent` (mirrors the Phase 3 budget
adjuster; refuses when `bid_amount` isn't set, e.g. automatic/"Lowest Cost" bidding). `auto_pause.py`
renamed `BUDGET_ACTIONS` → `PERCENT_ACTIONS` (now covers both budget and bid), added full
CRUD/enforcement-loop wiring for `duplicate`/`increase_bid`/`decrease_bid`.

**Frontend:** `AutoPauseRules.jsx` — 3 new `ACTION_OPTIONS`, full Duplicate config UI (all-ads vs.
empty radio, name-suffix + append-number, pause-original, repeat) in both Add/Edit rule modals,
confirm-step preview extended to bid and duplicate actions.

**Pre-push review (code-auditor + joel-perspective + Meta-API domain-expert) caught and fixed
before push:**
- Duplicate-repeat had no cooldown — would have created a brand-new ad set every 30 minutes
  indefinitely for as long as a breach persisted. Added `DUPLICATE_REPEAT_COOLDOWN` (24h), same
  gate structure as `notify`'s existing 4h cooldown.
- A fully-failed duplication (e.g. an ad set that's 100% lead-gen ads — `get_ad_creative_for_duplication`
  can't yet read lead-gen CTAs) was counted as a "success" in both the internal log and the API
  response Joel's UI renders. Now routes to `errors` instead when `duplicate_all_ads` was requested
  and every single ad failed.
- Sibling-count numbering (`duplicate_append_number`) only read the first page of a campaign's ad
  sets — silently undercounts (and can produce real name collisions) past 500 ad sets. Fixed to
  paginate via `load_next_page()`, same pattern as `get_adset_name_map`.
- `bid_strategy` was copied onto the new ad set unconditionally — under CBO that field lives on the
  campaign, and setting it at ad-set level risks Meta rejecting the create call as conflicting with
  the campaign's own strategy. Now gated on the source ad set actually being ABO (having its own
  budget field).
- A bid-adjust rule against an ad set with no `bid_amount` (the common case — most BHM ad sets run
  automatic bidding) retried silently forever with a green "Active" pill and no visible error state.
  Now detects the permanent-refusal condition and disables the rule with a clear reason.
- `MIN_BID_CENTS` raised from 1¢ to 25¢ — the original value was too low to function as a real
  sanity floor.

**Known follow-ups, documented in code rather than silently left implicit:**
- `duplicate_adset` does not copy day-parting, `frequency_control_specs`, or `is_dynamic_creative` —
  not a fully faithful 1:1 clone of every ad set setting.
- Video-ad link resolution in `get_ad_creative_for_duplication` (`call_to_action` mirror fallback)
  is expected to work based on the pattern already proven for link ads, but hasn't been live-tested
  against a real video ad specifically — worth one live check before duplicating video-heavy ad
  sets at scale.
- True carousel ads (multiple distinct card/link combinations, not just multiple images under one
  headline) still can't be duplicated faithfully — only the first title/body/link is used. Reported
  as a safe single-image simplification, not an error.

## 10. Live-tested 2026-09-13 (commit `dc9c750`) — found and fixed a real bug

Ran the Duplicate action against real production ad sets (not just code review) before calling
Phase 2 done:

- **Empty-mode duplicate** (no ads) — worked correctly first try: PAUSED status, budget, bid
  strategy, and targeting all round-tripped exactly onto the new ad set.
- **Full duplicate** (with ads) — failed 100% of the time on first try. Root cause: the test ads
  used `asset_feed_spec` (this app's own Bulk Match Import dual-placement creative format), which
  `get_ad_creative_for_duplication` never read — only `object_story_spec`. Not a rare case; it's
  this app's flagship creative shape. Fixed (see §9's asset_feed_spec entry — same commit
  message, `dc9c750`) and confirmed the CTA (`call_to_action_types` fallback), headline, body,
  image, and link all reproduce correctly on re-test.
- **Real risk caught mid-fix, before it shipped:** the fix's first draft guessed Feed/Story
  placement assignment for any 2-image `asset_feed_spec` ad. Live evidence from the actual test ad
  showed its `adlabels` were Meta's own auto-generated placement-customization names
  (`placement_asset_...`), not this app's `feed_image`/`story_image` convention — meaning most
  `asset_feed_spec` ads in these accounts were built by Meta's tooling, not this app, with no
  guaranteed 2-image Feed+Story structure. Both the code-auditor and Meta-API domain-expert review
  passes independently flagged this before push. Fixed: dual-placement reconstruction only fires
  when both images carry this app's own explicit labels; anything else duplicates as a plain
  single-image ad rather than risk silently swapping which image lands in which placement.
- Two test ad sets (one in "The Better Normal", one in DIN Auto Insurance — both already-paused,
  low-spend ad sets) were created during this verification and deleted immediately after
  confirming results.
