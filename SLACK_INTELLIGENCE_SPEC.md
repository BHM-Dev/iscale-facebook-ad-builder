# Slack Campaign Intelligence Bot — Full Spec

**Project:** BHM Ad Builder  
**Date:** 2026-04-25  
**Primary user:** Joel Welch (media buyer, $100k+/month Meta spend)  
**Status:** Ready for review

---

## 1. Executive Summary

Joel currently has to open the Ad Builder, wait for Meta insights to load per ad set, and mentally synthesize performance across campaigns to make scaling decisions. At high spend, that synthesis needs to happen multiple times per day — and the decisions (scale this, pause that, refresh creative here) need to be fast and confident.

This feature turns the Ad Builder's Meta data pipeline and Gemini AI into a Slack-native campaign analyst. Joel can ask for an update at any time, or receive proactive alerts and a daily morning briefing without opening the app. Every response is structured to answer one question: **where should I put the next dollar, and where should I pull it back?**

**No new data sources needed for MVP.** All inputs are already wired: Meta Insights API, the DB (campaigns, ad sets, auto-pause rule history), Gemini.

---

## 2. Trigger Modes

### Mode 1 — On-demand (Joel initiates)
Joel types any of the following in `#media-buying` (channel `C08G7PJJ6NB`):

| Input | Response |
|---|---|
| `@AdBuilder update` | Full campaign snapshot (see Section 4) |
| `@AdBuilder today` | Today-only snapshot (lighter version) |
| `@AdBuilder mtd` | Month-to-date deep dive |
| `@AdBuilder [ad set name]` | Single ad set breakdown |
| `@AdBuilder help` | Lists available commands |

### Mode 2 — Daily proactive summary
Every weekday at **9:00 AM ET** the bot posts the full snapshot to `#media-buying` unprompted. Joel wakes up to the brief already in Slack.

### Mode 3 — Threshold alerts (async)
Bot posts immediately when:
- An auto-pause rule fires (already built — this extends it with AI context)
- Any ad set's frequency crosses 4.0 (ad fatigue warning)
- MTD spend pacing is >15% above or below expected (over/under-delivery signal)
- ROAS drops >20% day-over-day on any ad set with >$50 spend that day

These fire in addition to the daily summary, not instead of it.

---

## 3. Data Inputs Per Response

Every response is built from a snapshot assembled at request time:

```
For each active ad set in the DB (status != PAUSED):
  → Pull Meta Insights for: today, last_7d, this_month (3 API calls per ad set)
  → Pull from DB: campaign name, ad set name, auto-pause rules, rule trigger history
  → Calculate derived metrics (see Section 4)

Aggregate to campaign level and account level.
```

**Metrics pulled per ad set:**

| Metric | Source | Used for |
|---|---|---|
| Spend (today / 7d / MTD) | Meta Insights | Pacing, budget allocation |
| Leads (today / 7d / MTD) | Meta Insights `actions` | Volume signal |
| CPL (today / 7d / MTD) | Meta Insights `cost_per_action_type` | Efficiency |
| Revenue (today / 7d / MTD) | Meta Insights `action_values` lead types | Profitability |
| ROAS (today / 7d / MTD) | Calculated: revenue ÷ spend | Scaling signal |
| Reach | Meta Insights | Audience saturation |
| Frequency | Meta Insights | Creative fatigue |
| CTR | Meta Insights | Creative relevance |
| Impressions | Meta Insights | Delivery health |
| Auto-pause rule status | DB | Risk flag |
| Last rule trigger | DB | Historical context |

**Derived metrics calculated server-side:**

| Metric | Formula | Threshold |
|---|---|---|
| CPL WoW trend | (7d CPL - prior 7d CPL) / prior 7d CPL | Flag if >10% worse |
| ROAS WoW trend | Same | Flag if >15% worse |
| MTD spend pace | MTD spend / (day_of_month / days_in_month × monthly_budget) | Flag if >115% or <85% |
| Profitability status | ROAS > 1.0 = profitable, < 1.0 = losing money | Hard flag |
| Fatigue risk | Frequency > 3.5 = warning, > 5.0 = critical | |
| Scale headroom | ROAS > target AND frequency < 3.0 AND CPL trending flat/down | Identifies scalable ad sets |

---

## 4. Response Structure — Full Snapshot

Every `@AdBuilder update` response is structured in this exact order. Designed to be read top-to-bottom in under 60 seconds.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 Campaign Update · [Date] · Last 7 Days
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ACCOUNT SCORECARD
Spend:   $X,XXX    (MTD: $XX,XXX  |  pace: on track ✅ / ahead ⚠️ / behind ⚠️)
Leads:   XXX       (MTD: X,XXX)
CPL:     $XX.XX    (vs. last week: ▲ worse / ▼ better)
ROAS:    X.XXx     (vs. last week: ▲/▼)
Overall: 🟢 Profitable  /  🔴 Losing  /  🟡 Break-even

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AD SET BREAKDOWN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟢 SCALE  (ROAS strong, frequency healthy)
• [Ad Set Name]   ROAS 3.2x  CPL $18  Freq 2.1  Spend $1,200
• [Ad Set Name]   ROAS 2.8x  CPL $21  Freq 1.9  Spend $980

🟡 WATCH  (profitable but signals degrading)
• [Ad Set Name]   ROAS 1.4x  CPL $42  Freq 3.8 ⚠️  Spend $640
• [Ad Set Name]   ROAS 1.2x  CPL $48  Freq 2.2  CPL ▲14% WoW

🔴 CUT / PAUSE
• [Ad Set Name]   ROAS 0.7x  CPL $89  Freq 5.1 🔴  Spend $310  — Auto-pause rule active

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AI RECOMMENDATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. [Ad Set A] has ROAS 3.2x with frequency 2.1 — room to scale. 
   Suggest increasing daily budget 20–30% and monitoring CPL over next 48h.

2. [Ad Set B] frequency is at 3.8 — creative fatigue starting. 
   ROAS still acceptable but trending down WoW. Refresh creative before 
   scaling further or expect CPL to continue rising.

3. [Ad Set C] is losing money (ROAS 0.7x). Frequency at 5.1 suggests 
   audience is exhausted. Recommend pausing and reallocating budget to [Ad Set A].

4. MTD pacing is 94% of expected — slightly under. Either add budget to 
   [Ad Set A] or loosen audience targeting on [Ad Set D] to recover delivery.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AUTO-PAUSE STATUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 3 rules active, no triggers since last update
(or)
⚠️ 1 rule triggered: [Ad Set Name] paused 3h ago — CPL $91 > $60 threshold
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 5. AI Analysis Framework (Gemini Prompt Design)

The Gemini call receives a structured JSON context object and is asked to produce exactly 3–5 recommendations. The prompt enforces specificity — vague outputs ("consider optimizing") are rejected by the prompt structure.

**Context object passed to Gemini:**
```json
{
  "request_type": "full_snapshot",
  "date_range": "last_7d",
  "account": {
    "total_spend": 8420.00,
    "total_leads": 312,
    "blended_cpl": 27.00,
    "blended_roas": 2.1,
    "mtd_spend": 32100.00,
    "mtd_pace_pct": 94
  },
  "ad_sets": [
    {
      "name": "...",
      "spend": 1200,
      "leads": 67,
      "cpl": 17.91,
      "roas": 3.2,
      "frequency": 2.1,
      "ctr": 1.8,
      "cpl_wow_pct": -8,
      "roas_wow_pct": 12,
      "auto_pause_rule": { "metric": "cpl", "threshold": 60, "is_active": true },
      "triggered_at": null
    }
  ]
}
```

**System prompt (key constraints):**
```
You are a Meta media buying analyst. Analyze this campaign data and produce 
3–5 specific, actionable recommendations for a media buyer managing 
$100k+/month in Meta spend.

Rules:
- Every recommendation must name the specific ad set
- Scaling recommendations must include a specific budget increase (% or $)
- Pause recommendations must include the reason (ROAS, frequency, CPL trend)
- Creative fatigue recommendations must define what "refresh" means (new image, 
  new hook, new audience, etc.)
- MTD pacing recommendations must include which ad sets to adjust and by how much
- Do not hedge. Give a clear directional call on each ad set.
- Maximum 5 recommendations. Prioritize by dollar impact.
```

---

## 6. Integration Architecture

```
Joel types "@AdBuilder update" in #media-buying
              │
              ▼
    Slack Events API
    POST → Railway backend
    /api/v1/slack/events
              │
              ├─ Verify Slack signing secret (HMAC-SHA256)
              ├─ Handle URL verification challenge (one-time setup)
              │
              ▼
    CampaignIntelligenceService.build_snapshot()
              │
              ├─ Query DB → all active ad sets + campaigns + rule status
              ├─ Meta Insights API → 3 date ranges per ad set (parallel calls)
              ├─ Calculate derived metrics (WoW trends, pacing, fatigue)
              │
              ▼
    GeminiService.analyze_campaigns(context)
              │
              └─ Returns 3–5 structured recommendations
              │
              ▼
    SlackService.post_snapshot(channel, snapshot, recommendations)
              │
              └─ Formats Slack Block Kit message
              └─ POST to chat.postMessage
              │
              ▼
    Response appears in #media-buying within ~8–12 seconds
```

**Slack app scopes required:**
| Scope | Purpose |
|---|---|
| `chat:write` | Post messages (likely already present) |
| `app_mentions:read` | Receive @AdBuilder mentions |
| `channels:history` | Read channel to detect keywords (optional — mention-only is simpler) |

**New env vars on Railway:**
| Var | Purpose |
|---|---|
| `SLACK_BOT_TOKEN` | Already needed for auto-pause alerts |
| `SLACK_SIGNING_SECRET` | Verify requests are genuinely from Slack (prevents spoofing) |
| `SLACK_ALERT_CHANNEL` | Target channel — defaults to `C08G7PJJ6NB` |

---

## 7. New Backend Components

### `backend/app/api/v1/slack_events.py`
Handles inbound Slack events. Verifies signature, dispatches to intelligence service, responds to Slack's 3-second timeout requirement (acknowledge immediately, process async).

```
POST /api/v1/slack/events
  → Verify SLACK_SIGNING_SECRET HMAC
  → If url_verification challenge → return challenge immediately
  → If app_mention event → parse command keyword
  → Enqueue background task (FastAPI BackgroundTasks)
  → Return HTTP 200 immediately (Slack requires response within 3s)
  → Background task: build_snapshot() → analyze() → post to Slack
```

### `backend/app/services/campaign_intelligence_service.py`
Core analysis engine. Responsibilities:
- Fetch all active ad sets from DB
- Pull Meta Insights for today / last_7d / this_month (use `asyncio.gather` for parallel calls)
- Calculate WoW trends, MTD pacing, fatigue scores
- Build context object for Gemini
- Call Gemini with structured prompt
- Return formatted snapshot dict

### `backend/app/services/slack_service.py` (extend existing)
Add:
- `post_snapshot()` — formats and sends the full Block Kit message
- `post_daily_summary()` — same as snapshot, labeled as daily brief
- `post_threshold_alert()` — async alert (frequency spike, pacing deviation, ROAS drop)

### APScheduler additions (in `scheduler_service.py`)
```python
# Daily 9am ET morning brief
scheduler.add_job(post_daily_summary, 'cron', hour=13, minute=0)  # 13:00 UTC = 9:00 ET

# Every 30min threshold checks (already running for auto-pause)
# Extend _run_check() to also evaluate frequency/pacing alerts
```

---

## 8. MTD Pacing Calculation

```python
from datetime import date, datetime

def mtd_pace(mtd_spend: float, monthly_budget: float) -> dict:
    today = date.today()
    days_in_month = (date(today.year, today.month + 1, 1) - date(today.year, today.month, 1)).days
    day_of_month = today.day
    expected_spend = (day_of_month / days_in_month) * monthly_budget
    pace_pct = (mtd_spend / expected_spend) * 100 if expected_spend > 0 else 0
    return {
        "mtd_spend": mtd_spend,
        "expected_spend": round(expected_spend, 2),
        "pace_pct": round(pace_pct, 1),
        "status": "ahead" if pace_pct > 115 else "behind" if pace_pct < 85 else "on_track"
    }
```

Monthly budget needs to be stored somewhere. Two options:
- **Option A:** Add `monthly_budget` field to `FacebookCampaign` model (requires migration)
- **Option B:** Joel sets it via Slack: `@AdBuilder budget 50000` → stored in a new `campaign_settings` table

Option B is more flexible and doesn't require Joel to use the app UI. Recommend Option B.

---

## 9. Decision Scoring Logic (Ad Set Ranking)

Each ad set gets assigned a status tier used to sort the Slack output:

```python
def score_adset(adset: dict) -> str:
    roas = adset.get('roas') or 0
    frequency = adset.get('frequency') or 0
    cpl_wow = adset.get('cpl_wow_pct') or 0   # positive = worse
    roas_wow = adset.get('roas_wow_pct') or 0  # positive = better

    if roas >= 2.0 and frequency < 3.5 and cpl_wow <= 10:
        return 'SCALE'       # Green — profitable, healthy, trending stable/up
    elif roas >= 1.0 and (frequency < 4.5 or cpl_wow < 20):
        return 'WATCH'       # Yellow — profitable but one signal degrading
    else:
        return 'CUT'         # Red — unprofitable OR multiple signals failing
```

Thresholds are defaults. Joel should be able to override ROAS target via Slack command.

---

## 10. Build Priority

### Phase 1 — MVP (build now)
- [ ] Slack Events API endpoint (`/api/v1/slack/events`)
- [ ] `CampaignIntelligenceService` — data fetch + derived metrics + Gemini analysis
- [ ] On-demand `@AdBuilder update` trigger
- [ ] Full snapshot Slack message (scorecard + ad set ranking + AI recs + auto-pause status)
- [ ] Slack app config: add `app_mentions:read` scope, set Events API URL, add `SLACK_SIGNING_SECRET` to Railway

### Phase 2 — Proactive (after MVP validated)
- [ ] Daily 9am ET summary via APScheduler
- [ ] Frequency threshold alert (>4.0)
- [ ] MTD pacing alert (>115% or <85%)
- [ ] ROAS drop alert (>20% day-over-day)
- [ ] `@AdBuilder today` and `@AdBuilder mtd` command variants
- [ ] `@AdBuilder budget [amount]` to set monthly budget for pacing

### Phase 3 — Conversational (after Everflow is wired)
- [ ] `@AdBuilder [ad set name]` — single ad set deep dive
- [ ] Everflow revenue reconciliation layered into analysis (Meta leads vs. Everflow conversions)
- [ ] Budget reallocation recommendations with specific $ amounts
- [ ] Ad-level creative performance breakdown

---

## 11. Open Questions & Dependencies

| Question | Owner | Impact |
|---|---|---|
| Which campaigns should be included? All active, or scoped? | Joel | Determines API call volume |
| What is Joel's ROAS target? (default used for SCALE/WATCH/CUT scoring) | Joel | Affects all tier assignments |
| Slack app — create new or add scopes to existing? | Steve/Golden | Determines setup path |
| `SLACK_SIGNING_SECRET` — where is it? (Slack app settings → Basic Information) | Steve | Required before any Slack Events work |
| Monthly budget per campaign — DB field or Slack command? | Steve/Dan | Affects Phase 1 pacing calc |

---

## 12. What This Unlocks Long-Term

Once the Everflow API is wired in, the intelligence layer becomes significantly more accurate:

- **Quality-adjusted ROAS** — Meta says 50 leads at $30 CPL. Everflow says 32 converted at $70 payout. Real ROAS = (32 × $70) / ($30 × 50) = 1.49x, not the 2.3x Meta reports. The Gemini recommendation changes entirely when working from ground truth.
- **Junk lead detection per ad set** — Some ad sets generate volume but low Everflow conversion rates. The AI can flag these even when Meta CPL looks fine.
- **Full-funnel scoring** — SCALE/WATCH/CUT decisions based on actual revenue, not pixel-reported lead value.

The architecture built in Phase 1 and 2 is designed to accept Everflow as an additional data source without structural changes.
