# Research Test Backlog — MVP Brief

## Executive summary

Research currently identifies competitor patterns and hands context to Ad Remix, but the decision to test can disappear after the handoff. The MVP adds a durable, per-user research test backlog for Commercial Insurance and Auto Insurance. A backlog item records the observed source, an original BHM hypothesis, a test status, and optional generated-ad link. It does not infer performance or change the Meta launch contract.

## Flow

```text
Retained research ad / watchlist change
  → Create test hypothesis
  → Backlog: Draft → Building → Launched → Learned / Archived
  → Optional generated-ad link
  → Existing RedTrack/Meta outcome surfaces remain source of truth
```

## MVP specification

- Scope: commercial insurance and auto insurance only.
- Create a test from a retained research ad or a watchlist test brief.
- Persist: source advertiser, source scraped-ad ID when available, vertical, hypothesis, status, notes, creator, timestamps, optional generated-ad ID.
- Never copy competitor claims or represent catalog metadata as performance.
- Backlog is a research planning workspace; it does not write to Meta, spend credits, or schedule scraping.

## Integration and measurement

- Research produces the source context.
- Backlog stores the test decision and status.
- Existing `generated_ads` and RedTrack attribution remain the launch/performance source of truth.
- Reserve `generated_ad_id` for a later explicit link after generation.

## Phased rollout

**Ready for review:** durable backlog CRUD, source-bound creation, status workflow, Commercial/Auto-only guardrails.

**Phase 2:** direct generated-ad linking and a measured outcome summary only when account-level attribution is complete.
