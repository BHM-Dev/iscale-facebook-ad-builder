# Research Decision Loop — Dynamic Economics and Buyer Queue

**Status:** Implemented 2026-10-08
**Users:** Joel (media buying), Abel (creative/research operations)

## Decision

Do not create a permanent CPL target. Commercial-insurance economics vary by niche, offer, lead quality, and daily revenue. The useful comparison is the current test's RedTrack revenue against Meta lifetime spend:

```text
RPL = RedTrack revenue / Meta leads
CPL = Meta spend / Meta leads
Contribution per lead = RPL - CPL
```

The system suggests Win when a result-ready test has positive contribution, Lose when it has negative contribution, and Inconclusive when spend or revenue is unreadable. Revenue/spend windows are labeled as indicative because the existing sources may not cover identical periods.

Joel or Abel can override the suggested result with Win, Lose, or Inconclusive and an optional reason. This preserves operator judgment for lead quality, delayed revenue, or niche-specific context without forcing a fabricated threshold.

## UI scope

- One compact economics strip on each launched test row: Result ready, RPL, CPL, contribution per lead, and suggested/manual verdict.
- “Use suggested” is the default; no setup or target maintenance is required.
- Research navigation emphasizes Feed and My Queue. Lower-frequency Brief, Advertisers, Watchlist, and Test Backlog surfaces remain available behind More.
- The source-image host allow-list blocks SSRF/private-network targets and reports when Remix falls back to a generic blueprint.

## Competitive rationale

This follows the useful patterns found in Adnova, RyzeAI, AdStellar, GetHookd, and related platform reviews:

- show the evidence behind a label rather than a mysterious score;
- compare against current or trailing economics instead of a stale absolute threshold;
- put the recommended next action beside the evidence;
- use a compact decision view for buyers and keep deeper analysis available without making it the default;
- recommend actions for human approval rather than silently automating a money-moving decision.

We explicitly did not add an AI score, account-average comparison, permanent CPL target, proactive digest, or another analytics panel in this slice.

## Verification

- `backend/tests/test_research_safety.py`: 11 passed.
- `frontend`: `npm run build` passed.
- `scripts/check_alembic_heads.py`: one head.
- ESLint retains the pre-existing Research/AdRemix errors documented in the project feature log; no new lint class was introduced by this change.
