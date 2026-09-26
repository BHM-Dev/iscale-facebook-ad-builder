# Ad Builder — Immediate-Impact Backlog

## Objective

Reduce the time for Joel or Abel to turn a verified Drive package into a **reviewed, paused Meta batch** from repeated manual setup to a dependable, repeatable shortcut. The first operational target is a 20-ad batch in under 10 minutes, with no wrong-account, wrong-destination, missing-copy, or invalid-placement surprises reaching Meta.

## What we observed

| Reference | Useful pattern to retain | Application here |
| --- | --- | --- |
| Meta Ads Manager | Dense, row-first operations and full creative inspection on demand | Keep large batches scannable; show the full asset without making each row huge. |
| GetHookd | Compact visual cards, clear actions, saved/favorite behavior, little explanatory copy | Make decisions and next actions obvious; hide guidance until it is needed. |
| Arcads / conversational research tools | A plain-English request narrows a messy creative library | Add assisted discovery only after the launch path is fast and trustworthy. |

## Prioritized delivery plan

### Now — removes repeated work and launch risk

1. **Shared Launch Packs** — save account, campaign, ad set, Page, global URL, CTA, naming rule, and compatible Drive scope as a named shortcut. Loading one resolves the exact target, never a vague “last used” fallback.
2. **Exception-only preflight** — keep the existing validation, but show a compact green batch summary when ready and list only actions that block or change the batch. Include destination-family and placement counts.
3. **Drive package readiness** — identify exact Feed/Stories pairs, verified copy, URL, CTA, and missing placement before selection. The current launch-ready picker is the first slice; package-level status is next.
4. **Post-launch proof** — after paused creation, show created / failed / reconciled counts, created ad links, and a retry path for only failed items.

### Next — makes high-volume execution dependable

5. **Resumable server-side launch queue** — move long batches out of the browser so a tab refresh or transient Meta response cannot abandon a 50–100-ad launch. It must be idempotent and create paused ads only.
6. **Naming and URL guardrails** — preview the exact ad names and UTM/final URL before queueing; block collisions and mixed destination families unless consciously split.
7. **Clone winner into a test pack** — from Campaign Performance, turn a known winner into a saved target and draft the first test batch with the matching Page, CTA, URL, and naming convention.

### After the core launch loop is measured

8. **Research-to-test handoff** — save a research finding with its creative, hook, audience note, and a “build test” action. Do not pretend it has performance data unless Meta supplies it.
9. **Assisted library query** — natural-language filtering such as “show commercial-insurance Feed ads with proof-led hooks and a verified Stories pair.” It should explain which fields it used and never invent performance.
10. **Creative QA overlays** — safe zones, placement cropping checks, duplicate detection, and a full-size hover/preview. This is polish after source-package correctness.

## Explicitly not the immediate priority

- A broad chatbot shell without reliable library metadata.
- A made-up “winning” score based on ad age or activity; those are signals, not spend or conversion performance.
- More explanatory panels in the research or launch UI. Defaults should be compact, with detail on demand.

## Success measures

| Measure | Baseline to capture | First target |
| --- | --- | --- |
| Time from Drive selection to paused 20-ad batch | First live run | Under 10 minutes |
| Launch attempts passing preflight on first attempt | First live run | 90%+ |
| Repeated target-selection clicks per batch | First live run | Near zero via Launch Packs |
| Invalid/mixed URL or missing placement items reaching Meta | First live run | Zero |
| Batch failures requiring manual reconciliation | First live run | Under 2% |

## Delivery order

1. Build shared Launch Packs and exact-target loading.
2. Add exception-only preflight and capture baseline timing.
3. Move batch creation to a resumable server-side queue.
4. Add post-launch reconciliation and test the complete paused-ad path with a real package (stop before activation unless Steven explicitly authorizes it).
