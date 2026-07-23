# Campaign Intelligence — Feature Brief

**Status:** Pre-build. Pending question-set definition from Joel.  
**Primary user:** Joel Welch (media buyer)  
**Goal:** Proactive in-app analysis panel that surfaces actionable decisions from Meta + RedTrack data — without Joel having to manually pull and reconcile reports.

---

## The Problem

Joel currently has to manually cross-reference Meta cost data with RedTrack revenue data to answer basic questions like:
- Which niches are profitable right now?
- Should I pause spend over the weekend?
- What changed since yesterday?

This analysis takes time, happens outside the app, and the insights aren't acted on fast enough.

---

## The Concept

A **Campaign Intelligence** panel — either a full page or Dashboard card — that:

1. Joins Meta spend (campaign/ad set level) + RedTrack revenue by campaign + date
2. Segments performance by niche (extracted from ad set name pattern `[Date] - [Niche] - [Batch]`)
3. Produces a plain-English AI summary + niche breakdown table with verdicts
4. Allows Joel to switch views: **Today / Yesterday / This weekend / Last 7d / Last 30d**

### Example output (from 6/13 Saturday analysis)

| Niche | Spend | Revenue | Profit | ROI | CPL | Verdict |
|---|---|---|---|---|---|---|
| AutoBody | $312 | $462 | +$150 | +48% | $21 | Run weekends |
| Religious Orgs | $124 | $163 | +$39 | +31% | $19 | Run weekends |
| Trucking | $398 | $379 | −$19 | −5% | $26 | Watch |
| Plumbing | $461 | $62 | −$399 | −87% | $29 | Pause weekends |
| Barber | $389 | $213 | −$176 | −45% | $27 | Pause weekends |
| Laundromat | $341 | $48 | −$293 | −86% | $31 | Pause weekends |
| Water Tour | $772 | $63 | −$709 | −92% | $34 | Pause weekends |

**AI summary example:** "Saturday was your worst weekend yet — but it's fixable. CPL is flat vs. weekdays ($25.55). The problem is revenue-side: call centers are closed weekends so leads don't convert. AutoBody + Religious Orgs made +$652. The other 5 niches lost $1,028. Pausing those Friday night would have flipped Saturday profitable."

---

## Joel's Feedback

> "I would need to map out all question sets."

This is the critical open item. Joel's signal is that the panel needs to be built around a defined set of **recurring questions he actually asks** — not just a niche table. The niche breakdown is one answer; there are others.

**Before building, Joel needs to define his question sets.** Examples of what those might look like:

- *"Which niches should I pause this weekend?"* → Niche × weekend ROI
- *"Is my CPL trending up or down?"* → CPL over time, 7-day vs. prior 7-day
- *"What changed since yesterday?"* → Delta view: which ad sets moved significantly
- *"Where should I increase budget?"* → Niches with ROAS > 1 and room to scale
- *"Which ads are dragging down my averages?"* → Ad-level CPL outliers within a niche

Each question set = a different data join, a different segmentation, a different verdict logic.

---

## Data Architecture

**Meta API** → spend, impressions, CPL, leads by campaign/ad set/ad  
**RedTrack API** → revenue by campaign + date  
**Join key:** campaign name + date  
**Niche extraction:** existing `_extract_niche()` logic in `facebook_service.py`

Both APIs are already wired into the backend. The gap is:
1. A dedicated endpoint that joins them by date range
2. A Claude call that takes the joined table + question set and returns structured verdicts + summary
3. A frontend panel to display it

---

## Open Questions for Codex Review

1. **Question set architecture** — should each question set be a hardcoded analysis type (enum: `weekend_by_niche`, `cpl_trend`, `budget_opportunity`), or should Joel be able to define custom questions in the UI?
2. **Where does it live?** Full page at `/intelligence` vs. collapsible card on the Dashboard. Joel's preference TBD.
3. **Caching** — Meta + RedTrack calls are slow. Do we cache the joined table server-side (per account + date range) and refresh on demand, or always pull fresh?
4. **Claude prompt design** — one prompt per question set (cleaner, more precise) vs. one prompt with all question sets (fewer API calls). Given that each question requires different reasoning, leaning toward one prompt per question set.
5. **RedTrack join reliability** — campaign names must match exactly between Meta and RedTrack. What's the fallback when a campaign exists in Meta but not RedTrack (e.g. new campaigns with no revenue yet)?

---

## What's NOT in scope (MVP)

- Automated actions (auto-pause based on intelligence output) — that's the existing auto-pause rules feature
- Cross-account analysis
- Historical trend charts
- Email/Slack delivery of intelligence reports

---

## Suggested MVP Scope

1. Single view: **This weekend** (the highest-value, most immediately actionable)
2. Single question set: **Niche profitability** (spend + revenue + ROI + verdict)
3. AI summary card above the table
4. No date range switching yet — prove the data join works first
5. Lives on the Dashboard as a collapsible card

Full date range tabs + multiple question sets = Phase 2, driven by Joel's question set mapping.

---

## Files This Will Touch

| File | Change |
|---|---|
| `backend/app/api/v1/facebook.py` | New endpoint: `GET /intelligence/weekend-summary` |
| `backend/app/services/facebook_service.py` | New method: join Meta insights + RedTrack by date range + niche |
| `frontend/src/pages/Dashboard.jsx` | Add intelligence card |
| `backend/app/api/v1/copy_generation.py` or new `intelligence.py` | Claude call for summary + verdicts |

`facebook_service.py` is a trigger file → 2-agent pre-push review required before any push touching it.
