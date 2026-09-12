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

1. Confirm with Joel: of the four MVP actions (Pause/Notify/Increase budget/Decrease budget),
   which does he actually want first? He's doing manual notify-equivalent work in Slack daily —
   Notify might be the fastest win with the least risk (no ad spend touched).
2. Match-count preview — do we compute this live against Meta's API (adds a request) or against
   the local synced ad-set cache (faster, could be stale by a sync cycle)? Given the 30-min
   scheduler already exists, staleness window is bounded either way.
3. Does a generalized rules engine replace `auto_pause.py` outright, or run alongside it during a
   transition? Recommend replace-in-place since it's a superset, but worth confirming before
   Claude Code starts.
