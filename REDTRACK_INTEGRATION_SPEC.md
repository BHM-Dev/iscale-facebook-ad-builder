# RedTrack Integration Spec

**Project:** BHM Ad Builder  
**Date:** 2026-04-26  
**Status:** Ready to build — pending `REDTRACK_API_KEY` in Railway  

---

## 1. Executive Summary

RedTrack is already tracking every Meta click with `sub2={{adset.id}}` in the tracking URL and auto-syncing spend from Meta via the "Auto update costs" toggle. This means RedTrack has ground-truth data — actual conversions + revenue per Meta ad set ID — with no manual setup required on our end.

**The mapping is zero-config:** RedTrack's `sub2` = Meta ad set ID = `fb_adset_id` in our DB. Query RedTrack grouped by `sub2`, join to our ad sets table, done.

**What this unlocks:**
- True conversion count per ad set (not Meta's pixel-reported leads — actual postback conversions)
- Actual revenue per ad set (offer payout × conversions from affiliate network postback)
- Ground-truth ROAS: `redtrack_revenue ÷ redtrack_spend`
- Quality rate: `redtrack_conversions ÷ meta_leads` — shows which ad sets generate junk vs. real leads
- The Slack intelligence bot works from real numbers, not Meta's self-reported data

---

## 2. Data Flow

```
Meta Ad runs
  → User clicks tracking link (sub2={{adset.id}} passes fb_adset_id)
  → RedTrack records click + spend (pulled from Meta API via Auto update costs)
  → User converts on offer page
  → Affiliate network fires postback to RedTrack
  → RedTrack records conversion + revenue

Our app queries RedTrack API (every 30 min, same cadence as auto-pause)
  → Group by sub2 → get conversions + revenue per fb_adset_id
  → Join to facebook_adsets table on fb_adset_id
  → Surface alongside Meta Insights data in performance table
```

---

## 3. Performance Table — Updated Layout

The performance table gets two data sources shown side by side. Meta owns delivery. RedTrack owns revenue truth.

### Meta Insights (left side — delivery metrics)
| Metric | What it means |
|---|---|
| Spend | Meta-reported spend for date range |
| Reach | Unique accounts reached |
| Frequency | Avg times each person saw the ad |
| Impressions | Total views |
| Clicks | Link clicks |
| CTR | Click-through rate |
| Leads | Meta-counted lead events (pixel) |
| Meta CPL | Spend ÷ Meta leads |

### RedTrack (right side — revenue truth)
| Metric | What it means |
|---|---|
| RT Conversions | Actual postback conversions recorded by RedTrack |
| RT Revenue | Actual payout from affiliate network |
| RT Spend | Spend as RedTrack has it (sourced from Meta, reconciled) |
| RT ROAS | RT Revenue ÷ RT Spend — ground truth |
| RT CPL | RT Spend ÷ RT Conversions |
| Quality Rate | RT Conversions ÷ Meta Leads — % of Meta leads that actually converted |

### Key derived signal
**Quality Rate** is the most valuable new metric. If Meta says 50 leads and RedTrack shows 28 conversions, quality rate is 56%. An ad set with a 30% quality rate vs. one with 80% should never get the same budget — even if their Meta CPL is identical.

---

## 4. API Integration Design

### Authentication
```
Header: x-api-key: [REDTRACK_API_KEY]
Base URL: https://api.redtrack.io
```

### Primary endpoint — Report grouped by sub2
```
GET /report?group_by=sub2&date_from=YYYY-MM-DD&date_to=YYYY-MM-DD
```

Returns metrics per `sub2` value (= fb_adset_id). Fields requested:
- `sub2` — Meta ad set ID (the join key)
- `clicks` — click volume
- `conversions` — actual postback conversions
- `revenue` — actual payout
- `cost` — spend (pulled from Meta by RedTrack)
- `profit` — revenue - cost
- `roas` — revenue / cost (RedTrack calculates this)
- `cpl` — cost / conversions

### Fallback — if sub2 grouping isn't supported
Some RedTrack API versions group by campaign first. Fallback:
```
GET /report?group_by=campaign_id&date_from=...&date_to=...
```
Then match by campaign name to `facebook_campaigns.name` in our DB.

### Campaign list (for initial setup validation)
```
GET /campaigns
```
Returns all campaigns with their IDs and names. Used to validate API key works and confirm the sub2 parameter is present in tracking URLs.

---

## 5. New Backend Components

### `backend/app/services/redtrack_service.py`

```python
class RedTrackService:
    BASE_URL = "https://api.redtrack.io"
    
    def __init__(self):
        self.api_key = os.getenv("REDTRACK_API_KEY")
    
    def is_configured(self) -> bool:
        return bool(self.api_key)
    
    def get_report_by_adset(self, date_from: str, date_to: str) -> dict:
        """
        Pull conversions + revenue grouped by sub2 (= Meta fb_adset_id).
        Returns dict keyed by fb_adset_id:
        {
          "23850123456": {
            "conversions": 31,
            "revenue": 2170.00,
            "cost": 940.00,
            "roas": 2.31,
            "cpl": 30.32,
            "clicks": 412
          },
          ...
        }
        """
        
    def get_campaigns(self) -> list:
        """List all RedTrack campaigns — used for validation."""
```

### `backend/app/api/v1/redtrack.py`

```
GET  /api/v1/redtrack/status          — is API key configured? returns bool
GET  /api/v1/redtrack/report          — report by adset for a date range
GET  /api/v1/redtrack/campaigns       — list RedTrack campaigns
GET  /api/v1/redtrack/adset/{fb_adset_id}  — single adset RedTrack data
```

### Updates to `auto_pause.py` — _run_check()
When evaluating ROAS rules, prefer RedTrack ROAS over Meta's if available:
```python
# ROAS rule evaluation — prefer RedTrack ground truth
if rule.metric == 'roas' and rt_data:
    metric_value = rt_data.get('roas')  # RedTrack ROAS
else:
    metric_value = _get_metric_value(insights, rule.metric)  # Meta fallback
```

### Updates to `campaign_intelligence_service.py` (Slack bot — Phase 2)
Feed RedTrack data into Gemini context alongside Meta data:
```python
"redtrack": {
  "conversions": 31,
  "revenue": 2170.00,
  "roas": 2.31,
  "quality_rate": 0.62,   # rt_conversions / meta_leads
  "cpl": 30.32
}
```

---

## 6. Frontend Changes — CampaignPerformance.jsx

### InsightsCard — updated layout
Two visual sections separated by a divider:

```
[Meta Insights]                    |  [RedTrack]
Spend · Leads · CPL · Reach ·      |  Convs · Revenue · ROAS · 
Freq · Impressions · Clicks · CTR  |  RT CPL · Quality Rate
```

RedTrack section shows a subtle "RT" label prefix and slightly different background (`bg-blue-50`) to make it visually distinct from Meta data.

If RedTrack data is unavailable for an ad set (sub2 not matched, or API key not configured), the RT section shows a muted "—" for all values rather than erroring.

### New `RedTrackStat` component
Similar to the existing `Stat` component but with a blue accent and "RT" badge:
```jsx
<RedTrackStat label="ROAS" value="2.31x" highlight={data.roas < 1} />
<RedTrackStat label="Quality" value="62%" highlight={data.quality_rate < 0.5} />
```

Quality Rate highlights red below 50% — that's the threshold where an ad set is generating more junk than real leads.

### Settings page addition
Add a "RedTrack" tab to Settings showing:
- Connection status (green/red dot)
- Last sync time
- Number of matched ad sets
- Button to manually refresh

---

## 7. Matching Logic

```python
def match_redtrack_to_adsets(rt_report: dict, db_adsets: list) -> list:
    """
    rt_report: { fb_adset_id: { conversions, revenue, ... } }
    db_adsets: list of FacebookAdSet objects
    
    Returns each adset with rt_data attached (or None if no match).
    """
    for adset in db_adsets:
        adset.rt_data = rt_report.get(adset.fb_adset_id)
    return db_adsets
```

Match rate will be high because sub2 is already in every tracking URL. Any unmatched ad sets are ones that either:
- Haven't had any clicks yet (new ad sets)
- Were created before RedTrack was set up (older campaigns)

---

## 8. Scheduler Integration

Add RedTrack sync to the existing 30-min APScheduler job alongside auto-pause checks:

```python
# Every 30 minutes (same job that runs auto-pause)
def scheduled_check():
    _run_check(db)           # auto-pause rule evaluation (existing)
    _sync_redtrack(db)       # RedTrack data sync (new)
```

`_sync_redtrack()` caches the latest RedTrack report in a simple DB table (`redtrack_cache`) so the performance page doesn't have to wait for a live API call on every page load.

### New table: `redtrack_cache`
```sql
CREATE TABLE redtrack_cache (
    id          VARCHAR PRIMARY KEY,
    fb_adset_id VARCHAR NOT NULL,
    date_from   DATE NOT NULL,
    date_to     DATE NOT NULL,
    conversions INTEGER,
    revenue     NUMERIC(10,2),
    cost        NUMERIC(10,2),
    roas        NUMERIC(6,2),
    cpl         NUMERIC(8,2),
    clicks      INTEGER,
    quality_rate NUMERIC(4,3),  -- rt_conversions / meta_leads
    synced_at   TIMESTAMP WITH TIME ZONE DEFAULT now()
);
CREATE INDEX ix_redtrack_cache_adset_id ON redtrack_cache(fb_adset_id);
CREATE INDEX ix_redtrack_cache_date ON redtrack_cache(date_from, date_to);
```

Requires a new Alembic migration with `has_table()` guard.

---

## 9. New Railway Env Vars

| Var | Value | Required |
|---|---|---|
| `REDTRACK_API_KEY` | From RedTrack → Settings → Tools → Integrations | Yes |

No other vars needed. Base URL is hardcoded (`https://api.redtrack.io`).

---

## 10. Build Plan

### Phase 1 — Backend + data pipeline (build first)
- [ ] `redtrack_service.py` with `get_report_by_adset()` and `get_campaigns()`
- [ ] `/api/v1/redtrack/*` endpoints (status, report, campaigns, single adset)
- [ ] `redtrack_cache` table + Alembic migration (with `has_table()` guard)
- [ ] 30-min scheduler sync (`_sync_redtrack()`)
- [ ] Validate matching: hit `/redtrack/report` and confirm sub2 values match `fb_adset_id` in DB

### Phase 2 — Frontend
- [ ] `RedTrackStat` component
- [ ] Updated `InsightsCard` with two-section layout (Meta | RedTrack)
- [ ] Quality Rate display + red highlight below 50%
- [ ] RedTrack connection status on Settings page

### Phase 3 — Auto-pause + Slack bot
- [ ] Auto-pause ROAS rules prefer RedTrack ROAS over Meta's when available
- [ ] RedTrack data fed into `CampaignIntelligenceService` for Slack bot analysis
- [ ] Quality Rate added to SCALE/WATCH/CUT scoring logic

---

## 11. Open Questions

| Question | Impact |
|---|---|
| Does RedTrack API support `group_by=sub2`? (Check Swagger at api.redtrack.io/docs) | Determines primary query strategy |
| Are all active campaigns using `sub2={{adset.id}}`? | Determines match rate |
| Is `REDTRACK_API_KEY` added to Railway yet? | Blocks Phase 1 start |

---

## 12. What Good Looks Like After This Ships

Joel opens the Performance page and sees two columns per ad set:

```
Commercial Insurance - Welders
Meta:      Spend $1,240  Leads 52  CPL $23.85  Freq 2.1  CTR 1.8%
RedTrack:  Convs 38      Rev $2,660  ROAS 2.15x  Quality 73%  RT CPL $32.63
```

He can immediately see: Meta counted 52 leads, RedTrack confirmed 38 real conversions. Quality rate 73% is solid. ROAS 2.15x is profitable. Scale it.

Compare to another ad set:
```
Commercial Insurance - Florist
Meta:      Spend $890   Leads 47  CPL $18.94  Freq 3.2  CTR 2.1%
RedTrack:  Convs 9       Rev $630   ROAS 0.71x  Quality 19%  RT CPL $98.89
```

Meta CPL looks great at $18.94 — Joel might have scaled this without RedTrack. But quality rate 19% and ROAS 0.71x means he's losing money. Pause it. That's the value of ground truth.
