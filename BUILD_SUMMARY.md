# BHM Ad Builder — Build Summary
**Last updated:** 2026-04-25  
**Environment:** Production on Railway  
**Primary users:** Joel Welch (media buyer), BHM team

---

## What the App Does

A full-stack tool that automates the entire lifecycle of Facebook advertising — from competitor research and creative generation, to campaign launch and live performance management. Built specifically for BHM's lead-gen operations at scale.

---

## Features Built

### 1. Brand & Product Management
Create and manage brands with logo, colors, and voice guidelines. Each brand has products with descriptions and images, and customer profiles defining target audience demographics, pain points, and goals. Everything downstream (ad creation, targeting, copy) pulls from these profiles.

### 2. Competitor Research
Scrapes Facebook Ad Library for competitor ads. Outputs structured data on creative format, copy angles, and hooks. Used to inform creative strategy before building new campaigns.

### 3. AI Ad Generation
Generates Facebook ad creatives (image and video) using Google Gemini + kie.ai. Takes brand, product, and customer profile as input. Groups generated ads by `ad_bundle_id` so variants from the same session stay together. Ads go to a gallery where they can be reviewed, selected, and launched.

### 4. Ad Remix Engine
Deconstructs winning ads into structural blueprints (hook type, visual structure, CTA format, copy pattern). Reconstructs those blueprints with a new brand's assets and voice. Lets Joel apply what works for one brand to another without starting from scratch.

### 5. Winning Ads Library
Internal template library. Ads that prove out get saved here with their blueprint JSON. The remix engine pulls from this library.

### 6. Facebook Campaign Management
Full campaign creation wizard:
- Create campaigns with objective, budget type (daily/lifetime), bid strategy, special ad categories
- Create ad sets with targeting (location, age, gender, interests, Advantage+), schedule, budget, day-parting
- Attach generated creatives and launch ads directly to Meta via the Marketing API
- All campaigns, ad sets, and ads stored in DB with their Meta IDs for sync

**Verified Meta API field names (corrected April 2026):**
- Campaign objectives use `OUTCOME_*` format
- `adset_schedule` (not `ad_schedule`) for day-parting
- `FINANCIAL_PRODUCTS_SERVICES` (not `CREDIT` — deprecated Jan 2025)
- Dates converted to ISO format before sending

### 7. Performance & Auto-Pause *(shipped April 2026)*

**Live Meta Insights table**  
Shows real-time performance for every launched ad set on a single screen. All data pulled live from Meta Insights API on demand.

| Metric | Notes |
|---|---|
| Spend | Campaign-to-date for selected date range |
| Leads | Counts `lead`, `onsite_conversion.lead_grouped`, `offsite_conversion.fb_pixel_lead` |
| CPL | From `cost_per_action_type`; calculated from spend/leads if not returned |
| Revenue | From `action_values` — checks purchase types first, then lead types (lead-gen payout value) |
| ROAS | Meta `purchase_roas` if available; calculated as revenue ÷ spend for lead-gen campaigns |
| Reach | Unique accounts reached |
| Frequency | Average times each person saw the ad — highlights red above 4x |
| Impressions | Total ad views |
| Clicks | Link clicks |
| CTR | Click-through rate — Meta returns as percentage, displayed as-is |

Date range selector: Today / Yesterday / Last 7 Days / Last 14 Days / Last 30 Days.

Ad Account ID auto-populates from the connected Facebook account on page load. Green dot indicator confirms it's populated.

**Rule status badges on each ad set row**
- 🟣 **Rule active** — an auto-pause rule is watching this ad set
- 🔴 **Rule triggered** — a rule fired and paused this ad set

**Auto-Pause Rules**  
Create rules that automatically pause an ad set when a performance threshold is breached:

| Setting | Options |
|---|---|
| Metric | CPL, CTR, ROAS |
| Condition | Greater than / Less than |
| Threshold | Any number (step 0.1 for ROAS) |
| Minimum spend | Rule won't fire until this dollar amount is spent (default $20) |

Rules are evaluated automatically every 30 minutes via APScheduler. "Check Now" button runs an immediate evaluation against live Meta data. After a rule fires it self-disables (prevents re-pausing an ad set Joel manually re-activates). Rules can be individually enabled, disabled, or deleted.

**Slack notifications**  
When a rule fires, an alert posts immediately to `#media-buying` with the ad set name, metric, and threshold values. Requires `SLACK_BOT_TOKEN` Railway env var (pending Golden).

**Raw insights diagnostic endpoint**  
`GET /api/v1/auto-pause/insights-raw/{fb_adset_id}` — returns unprocessed Meta API response showing every action type and value exactly as Meta sends it. Used to verify lead value and event structure.

### 8. Navigation & UI
- Dark navy sidebar (`#2D2463`) with BHM logo (PNG asset, horizontal version)
- Collapsed sidebar shows logo SVG fallback
- Facebook section is an expandable sub-nav: Campaigns → Performance & Auto-Pause
- Theme: gray-50 background, indigo focus rings, no amber/beige
- Utility CSS classes: `.input-base`, `.btn-primary`, `.btn-secondary`
- Toast notifications (no browser `alert()` anywhere)
- Custom modals for destructive actions (no browser `confirm()`)

### 9. Authentication
JWT-based auth (access + refresh tokens). All API routes protected. Role-based access (admin sees User Management in sidebar). `authFetch` utility in `frontend/src/lib/facebookApi.js` handles token attachment and refresh.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 19 + Vite + TailwindCSS |
| Backend | Python FastAPI (3.11+) |
| Database | PostgreSQL on Railway |
| Storage | Cloudflare R2 (S3-compatible) |
| Image generation | kie.ai (`flux-kontext-pro` model) |
| AI analysis | Google Gemini |
| Facebook API | `facebook-business` SDK v18+ |
| Background jobs | APScheduler (30-min auto-pause checks) |
| Hosting | Railway (backend + frontend + PostgreSQL) |
| Notifications | Slack API via `httpx` |

---

## Infrastructure Notes

**Railway startup sequence (every deploy):**
```
python init_db.py → alembic upgrade head → uvicorn
```
`init_db.py` runs `Base.metadata.create_all()` before Alembic. Every migration that creates a table must have a `has_table()` guard or it crashes on the second deploy.

**Current migration chain:**
```
1b02d74254e5 (baseline) → d8f2e1a7b4c9 → e3a1f9b2c8d4 → f4b2c8d9e1a7 → a1b3c5d7e9f2 (auto_pause_rules)
```

**Cloudflare R2:** Used for generated/uploaded images when `r2_enabled` is true.

**GitHub:** `BHM-Dev/iscale-facebook-ad-builder`. Changes go to `sunbunzz627` fork → PR to `BHM-Dev:develop`. Golden reviews and merges.

---

## Pending / In Progress

| Item | Owner | Priority |
|---|---|---|
| Add `SLACK_BOT_TOKEN` to Railway to activate Slack auto-pause alerts | Golden | High |
| Verify ROAS is populating correctly (awaiting Joel's confirmation) | Joel | High |
| `SLACK_SIGNING_SECRET` needed to build Slack intelligence bot | Steve | Medium |
| Everflow API key from Switchboard (advertiser) | Steve | Medium |
| CI `alembic-round-trip` test fix (pre-existing, non-blocking) | Golden | Low |

---

## Roadmap

### Next: Slack Campaign Intelligence Bot *(specced in `SLACK_INTELLIGENCE_SPEC.md`)*
Joel types `@AdBuilder update` in `#media-buying` and receives an AI-generated campaign snapshot: account scorecard, ad sets ranked SCALE / WATCH / CUT by ROAS and frequency, and 3–5 specific named recommendations from Gemini. Daily 9am ET proactive summary and threshold alerts (frequency >4, ROAS drop, MTD pacing off) also planned.

### After Everflow API key is obtained
Cross-check Meta-reported leads against Everflow actual conversions. Ground-truth ROAS. Junk lead detection per ad set. Quality-adjusted SCALE/WATCH/CUT scoring.

### Auto-pause enhancements
1. Scaling rules — increase budget when ROAS exceeds target
2. Ad-level pausing (not just ad set)
3. Rule audit log
4. Time-window restrictions (no evaluation before 10am to avoid noisy early data)

---

## Key Contacts

| Person | Role | Slack |
|---|---|---|
| Steve | CEO / product decisions | `U6M6033G9` |
| Golden (Moses) | Dev lead, Railway/DB ops | `C041GSZD1NG` |
| Joel Welch | Media buyer, primary app user | `U08HPNNGHBJ` |
| Dan | Product & engineering alignment | — |
