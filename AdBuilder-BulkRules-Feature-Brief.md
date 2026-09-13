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

**Open questions that need Joel's input before this is buildable, not just a technical
question — same posture as the targeting-variant axis from the redesign brief, flagged rather
than guessed:**
1. **Duplicate ALL ads in the ad set, or only the one(s) that triggered the rule?** A rule fires
   per ad set, evaluated against ad-set-level metrics — if the trigger is really "this specific ad
   is a winner," duplicating the whole ad set (including any losers riding alongside it) may not
   be what's wanted. Recommend asking directly rather than assuming "all ads" is correct.
2. **Does the duplicate keep the source budget, or does the rule set a new one?** Birch's own
   duplicate flow (Stage, not the rules engine) lets you pick — worth confirming whether Joel's
   actual use case ("scale a winner") implies the duplicate should start at a HIGHER budget than
   the source, which would make this action functionally overlap with `increase_budget` and might
   be better modeled as "Duplicate + bump budget by X%" as one combined action, not two rules.
3. **Does duplicating reset ad/ad-set names with a suffix (" - Copy", " - Scaled"), or something
   more specific** (a date stamp, matching this app's other naming conventions like
   `${adsetData.name} - Feed`)?
4. **Should a duplicated ad set get its own new rule automatically** (e.g., "duplicate again if
   this one also proves out"), or is one-shot duplication enough for MVP? Recommend one-shot only
   for MVP — an auto-chaining duplicate rule is a real scope-creep risk (a winner that keeps
   duplicating itself with no cap is its own money-risk story, similar to why budget/pause actions
   disable themselves after firing).

**Recommended MVP scope, once those are answered:** duplicate the whole ad set (all its ads) with
the source budget unchanged, `- Copy` suffix, one-shot (rule disables itself after firing, same as
pause/budget actions today). Anything beyond that (partial-ad duplication, an auto-bumped budget,
auto-chaining) is real Phase 3-of-Phase-2 scope, not MVP.

**Estimate:** comparable in size to Phase 4 (the per-media ad-set work) or larger — real new
orchestration across `facebook_service.py`, a new endpoint surface, and its own domain-expert Meta
API review (image_hash/video_id reuse across ad sets specifically needs verifying against Meta's
current docs, not assumed) plus the standard 2-agent trigger-file review. Not a follow-up-sized
task — recommend treating it as its own phase with its own dedicated pass, same as Phases 1-5 were,
once the open questions above are answered.

### 8.3 Routing note

Both pieces touch `backend/app/services/facebook_service.py` (trigger file) and need Claude Code
end-to-end, per the same rule that gated Phase 3's budget work. Bid actions can likely go in the
same pass as their own small feature; Duplicate should get its own dedicated session given its
size — bundling it into a "quick follow-up" pass would be the wrong scale of review for what it
actually is.
