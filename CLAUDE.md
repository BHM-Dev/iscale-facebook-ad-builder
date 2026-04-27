# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Current State (as of 2026-04-27)

**Production (AWS Lightsail VPS):** Running. Login works. All features operational.

**⚠️ INFRASTRUCTURE NOTE — Updated 2026-04-27:**
The app has moved from **Railway to AWS Lightsail VPS** (Golden's server).
- DO NOT reference Railway dashboard, Railway env vars, or Railway deployment for this project going forward
- Env vars are set directly on the server (Golden manages this)
- Deployment process: Golden restarts the server after changes — not auto-deploy from git push
- The startup sequence (`python init_db.py && alembic upgrade head && uvicorn`) still applies but is run on the VPS
- To request env var changes: message Golden in `C041GSZD1NG` with the var name; he adds it server-side and restarts
- `REDTRACK_API_KEY` confirmed added by Golden (2026-04-27). RedTrack cache will populate on first scheduler run.
- `SLACK_BOT_TOKEN` status: confirm with Golden whether this was added in the same update

### Features shipped in this session (2026-04-23 → 2026-04-25)

**BHM logo** — Real logo asset (`/public/bhm-logo.png`) now in sidebar. Expanded state = `<img>` tag with the horizontal PNG. Collapsed state = hand-coded `BHMLogo` SVG fallback. Source: `~/Claude/Sites/BHM Company Site/logo.png`.

**CSS/theme overhaul** — Removed beige/amber theme from `index.css`. Now: gray-50 background, gray-900 text, indigo focus rings. Added `.input-base`, `.btn-primary`, `.btn-secondary` utility classes.

**Performance & Auto-Pause page** (`/campaign-performance`) — Full feature added:
- Live Meta Insights per ad set (Spend, Leads, CPL, Clicks, CTR) via `/auto-pause/insights/{fb_adset_id}`
- Ad set performance table pulls from `/facebook/adsets/saved` (DB-backed, has `fb_adset_id`)
- Rule status badges on each performance row: "Rule active" (indigo) / "Rule triggered" (red)
- Ad Account ID field auto-populates from `GET /facebook/accounts` on mount; field stays editable
- Auto-pause rules CRUD (create, toggle, delete)
- "Check Now" button runs immediate rule evaluation against live Meta data
- Background scheduler checks all rules every 30 minutes (APScheduler in `main.py`)

**`/facebook/adsets/saved` endpoint** — Added to `backend/app/api/v1/facebook.py`. Returns DB-stored ad sets with both internal `id` and `fb_adset_id`. Needed because the live `/adsets` endpoint hits Meta API and doesn't have `fb_adset_id` populated.

**`authFetch` export fix** — `frontend/src/lib/facebookApi.js` changed `const authFetch` → `export const authFetch`. Required for `CampaignPerformance.jsx` import.

**`AutoPauseRule` model + migration** — `auto_pause_rules` table in production. Migration `a1b3c5d7e9f2` has `has_table()` guard. Two performance indexes created manually by Golden (`ix_auto_pause_rules_adset_id`, `ix_auto_pause_rules_is_active`).

**`auto_pause.py` router** — Full CRUD + enforcement at `/api/v1/auto-pause/`. `FacebookService()` constructor takes NO arguments — never pass `ad_account_id=` kwarg.

**Slack notifications** — `backend/app/services/slack_service.py` added. Posts to `C08G7PJJ6NB` (media buying channel) when a rule fires. Uses `httpx` (already in requirements). Requires `SLACK_BOT_TOKEN` server env var — silently skips if not set. Golden needs to add this env var on the VPS.

**CTR display fix** — Meta returns CTR already as a percentage (e.g. `1.5` = 1.5%). Frontend uses `parseFloat(data.ctr).toFixed(2)%`, not `(data.ctr * 100)`.

### Pending

**Golden action required:**
- Add `SLACK_BOT_TOKEN` env var to the VPS (Golden adds server-side) to activate Slack alerts. Token source: check GitHub Actions secrets on automation repos. Channel default (`C08G7PJJ6NB`) is hardcoded — no second var needed.

**Low priority / non-blocking:**
- CI `alembic-round-trip` test failing — pre-existing issue, baseline migration `downgrade()` doesn't drop all tables it creates. Fix: add missing `op.drop_table()` calls for `facebook_campaigns`, `brands`, `customer_profiles`, `api_usage_logs`, `page_blacklist`, `keyword_blacklist`, `brand_scrapes`, `ad_styles`.

### Auto-pause feature roadmap (not yet built)
In priority order for Joel (media buyer at $100k+/month Meta spend):
1. **Scaling rules** — increase daily budget by X% when CPL drops below threshold (mirror of pause)
2. **Ad-level pausing** — pause individual ads, not just the whole ad set
3. **Rule audit log** — persistent history of every rule trigger with metric values at time of fire
4. **Time-window restrictions** — only evaluate rules between configurable hours (avoids noisy early-morning data)

### Slack Campaign Intelligence Bot (specced, not yet built)
Full spec at `SLACK_INTELLIGENCE_SPEC.md`. Three trigger modes:
- **On-demand:** Joel types `@AdBuilder update` in `#media-buying` (C08G7PJJ6NB)
- **Daily proactive:** 9am ET summary via APScheduler
- **Threshold alerts:** frequency >4, ROAS drop >20% day-over-day, MTD pacing off by >15%

**Data sources:** Meta Insights (spend, leads, CPL, ROAS, reach, frequency, CTR) + DB (ad sets, rule history). Three date ranges per ad set: today / last_7d / MTD.

**AI layer:** Gemini analyzes all ad sets, assigns SCALE / WATCH / CUT tiers, produces 3–5 specific named recommendations (e.g. "increase [Ad Set A] budget 25%" not "consider optimizing").

**Response structure:** Account scorecard → ad set ranking by ROAS → AI recommendations → auto-pause status. Readable in <60 seconds.

**New components needed:**
- `backend/app/api/v1/slack_events.py` — inbound Slack Events API handler
- `backend/app/services/campaign_intelligence_service.py` — data fetch + Gemini analysis
- Extend `slack_service.py` — add `post_snapshot()`, `post_daily_summary()`, `post_threshold_alert()`
- New server env vars (Golden adds to VPS): `SLACK_SIGNING_SECRET` (required), `SLACK_BOT_TOKEN` (already needed for auto-pause alerts)
- Slack app: add `app_mentions:read` scope, set Events API URL to `https://[backend]/api/v1/slack/events`

**Open questions before building:**
- Which campaigns to include? All active or scoped?
- Joel's ROAS target for SCALE/WATCH/CUT tier thresholds
- Monthly budget per campaign: DB field on `FacebookCampaign` or `@AdBuilder budget [amount]` Slack command?
- New Slack app or add scopes to existing?

**Phase 3 unlocked by Everflow:** Quality-adjusted ROAS using actual conversions vs. Meta-reported lead values. Junk lead detection per ad set. Full-funnel SCALE/WATCH/CUT scoring.

### Everflow Integration (pending API key from Switchboard/Advertiser)
Use case: cross-check Meta-reported leads against Everflow actual conversions to get ground-truth ROAS and detect junk traffic per ad set. Same endpoint/auth pattern as existing BHM Everflow reporting. Waiting on advertiser-scoped API key.

**init_db.py behaviour (critical to remember):** On every server restart/deploy, `init_db.py` runs `Base.metadata.create_all()` BEFORE Alembic. This creates every table in `models.py`. Any migration that calls `op.create_table()` MUST have the `has_table()` guard or it will crash on the second deploy. See Alembic rules section below.

---

## ⛔ MANDATORY PRE-PUSH CHECKLIST — DO NOT SKIP ANY ITEM

This checklist exists because the same classes of bugs have broken production login 6+ times. Run through every item before committing or pushing ANY backend change.

### 1. New migration created?
- [ ] Does it call `op.create_table()`? → **Must have `has_table()` guard** (see Migration Rules below). No exceptions.
- [ ] Does it call `op.add_column()`? → Use `ADD COLUMN IF NOT EXISTS` raw SQL pattern, not `op.add_column()` which fails if column exists.
- [ ] Is `down_revision` pointing to the correct parent? Trace the full chain: `1b02d74254e5` → `d8f2e1a7b4c9` → `e3a1f9b2c8d4` → `f4b2c8d9e1a7` → `a1b3c5d7e9f2`

### 2. New model added to models.py?
- [ ] Does a migration exist that creates its table? `init_db.py` creates it via `create_all()`, but Alembic still needs the migration file or it will crash trying to create an already-existing table.
- [ ] Is the model imported in `models.py`? `init_db.py` does `from app.models import *` — if it's not there, the table won't be created.

### 3. New router / file added?
- [ ] Is it imported at the **module level** in `main.py`? If yes — any import error in that file crashes the entire app on startup, breaking login. Trace the full import chain of the new file before pushing.
- [ ] Does the new file import anything that doesn't exist yet (e.g. a model not yet in models.py, a method not yet in a service)?

### 4. New package added to requirements.txt?
- [ ] Does it install cleanly on Python 3.11? Check for known conflicts with existing pinned packages.
- [ ] Is startup code that uses it wrapped in `try/except`? If it's used at module import level (not inside a function), an install failure crashes the app.

### 5. Existing routes / models modified?
- [ ] Did any existing model column get renamed or removed? That breaks existing queries.
- [ ] Did any existing API endpoint path change? That breaks the frontend without a matching frontend update.
- [ ] Did any function signature change in `facebook_service.py`? Trace every caller.

### 6. Frontend changes?
- [ ] Do all new CSS classes used (`className="..."`) exist in Tailwind or in `index.css`? Missing classes = invisible/broken UI.
- [ ] Are all new imports at the top of `.jsx` files valid? A single bad import = blank page.
- [ ] Does any new page use `authFetch`? It must be imported as `import { authFetch } from '../lib/facebookApi'` (named export).

### 7. Final gate before push
- [ ] Read the diff one more time (`git diff HEAD`) and ask: "If this breaks, what would the symptom be and how would I fix it in under 5 minutes?"
- [ ] If the answer involves a DB migration, verify the fix path is clear — Golden applies migrations on the VPS by restarting the server (which runs `alembic upgrade head` automatically).

---

## Startup Sequence (memorize this)

**Hosting: AWS Lightsail VPS (not Railway — updated 2026-04-27)**

Every server start runs this exact sequence in order. If ANY step fails, login is broken:

```
python init_db.py          ← creates ALL model tables via Base.metadata.create_all()
  && alembic upgrade head  ← runs any pending migrations
  && uvicorn app.main:app  ← starts the server (login works here)
```

**The deadly pattern:** Adding a new model to `models.py` causes `init_db.py` to create its table. Then `alembic upgrade head` tries to create the same table → crash. Always add the `has_table()` guard.

---

## Startup Checks

On load, verify required tools are installed:

```bash
# Check agent-browser (required for e2e testing)
command -v agent-browser >/dev/null || echo "WARNING: agent-browser not installed. Run: npm install -g agent-browser && agent-browser install"
```

## Project Overview

Facebook Ad Automation App - A full-stack application for automating the lifecycle of Facebook video and image ads, from competitor research to ad creation, launching, and performance reporting.

**Tech Stack:**
- Frontend: React 19 + Vite + TailwindCSS
- Backend: Python FastAPI (Python 3.11+)
- Database: PostgreSQL on Railway
- Storage: Cloudflare R2 (S3-compatible)
- Testing: agent-browser (e2e), Vitest (unit)
- Hosting: AWS Lightsail VPS (migrated from Railway, 2026-04-27)

## Development Commands

### Backend

```bash
cd backend

# Setup virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Initialize database (PostgreSQL required)
python init_db.py

# Run development server
uvicorn app.main:app --reload --port 8000

# Run tests
pytest
pytest test_research.py  # Run single test file
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Run development server
npm run dev  # Runs on http://localhost:5173

# Build for production
npm run build

# Lint code
npm run lint

# Preview production build
npm run preview
```

### Full Stack Development

The backend API runs on `http://localhost:8000` and the frontend on `http://localhost:5173`. API documentation is available at `http://localhost:8000/api/v1/docs`.

## Architecture

### Database Models (backend/app/models.py)

Core entities and their relationships:

- **Brand**: Central entity with logo, colors (primary/secondary/highlight), voice
  - Has many Products (cascade delete)
  - Has many CustomerProfiles (many-to-many via brand_profiles table)
  - Has many GeneratedAds

- **Product**: Belongs to Brand, contains description, product_shots (JSON), default_url

- **CustomerProfile**: Demographics, pain_points, goals - linked to Brands

- **WinningAds**: Template library with structural analysis, blueprint_json for Ad Remix Engine

- **GeneratedAd**: Output from AI generation, links Brand + Product + Template, includes ad_bundle_id for grouping

- **FacebookCampaign/AdSet/Ad**: Hierarchy for Facebook campaign management with fb_*_id fields for syncing

- **ScrapedAd**: Competitor ads from research module

### Backend Structure (FastAPI)

```
backend/app/
├── main.py              # FastAPI app, CORS, router registration
├── database.py          # SQLAlchemy engine, SessionLocal, Base
├── models.py            # All SQLAlchemy models
├── core/
│   └── config.py        # Settings, validates DATABASE_URL is PostgreSQL
├── api/v1/              # API endpoints (all prefixed /api/v1)
│   ├── brands.py
│   ├── products.py
│   ├── profiles.py      # Customer profiles
│   ├── generated_ads.py # AI-generated ads
│   ├── facebook.py      # Campaign/AdSet/Ad management
│   ├── research.py      # Competitor scraping
│   ├── ad_remix.py      # Blueprint deconstruction/reconstruction
│   ├── copy_generation.py
│   ├── templates.py
│   ├── uploads.py
│   └── dashboard.py
├── services/            # Business logic
│   ├── facebook_service.py    # Facebook Marketing API (facebook-business SDK)
│   ├── slack_service.py       # Slack chat.postMessage wrapper (auto-pause alerts)
│   ├── scheduler_service.py   # APScheduler — runs auto-pause check every 30 min
│   ├── research_service.py
│   ├── scraper.py
│   └── ad_remix_service.py    # Uses Gemini Vision for template analysis
└── schemas/             # Pydantic models (if exists)
```

**Key Backend Patterns:**
- All routes use `/api/v1` prefix
- Database dependency injection via `Depends(get_db)`
- PostgreSQL required - config.py validates DATABASE_URL on startup
- Facebook API uses `facebook-business` SDK (AdAccount, Campaign, AdSet, Ad, AdCreative, AdImage)
- AI services use Google Gemini (GEMINI_API_KEY) and Fal.ai (FAL_AI_API_KEY)
- File uploads go to Cloudflare R2 when configured, falls back to local `uploads/` for dev

### Frontend Structure (React + Vite)

```
frontend/src/
├── App.jsx              # Router setup, wraps with ToastProvider/BrandProvider/CampaignProvider
├── main.jsx             # Entry point
├── components/          # Reusable UI components
│   ├── Layout.jsx       # Main layout with navigation
│   ├── Toast.jsx        # Toast notification component
│   ├── Wizard.jsx       # Multi-step wizard
│   ├── BrandForm.jsx
│   ├── ProductForm.jsx
│   ├── CustomerProfileForm.jsx
│   └── ...wizard steps and builders
├── pages/               # Route components
│   ├── Dashboard.jsx
│   ├── Research.jsx     # Competitor analysis
│   ├── CreateAds.jsx    # Ad creation flow
│   ├── ImageAds.jsx
│   ├── VideoAds.jsx
│   ├── AdRemix.jsx      # Template remix engine
│   ├── GeneratedAds.jsx # View generated ads
│   ├── Brands.jsx
│   ├── Products.jsx
│   ├── CustomerProfiles.jsx
│   ├── FacebookCampaigns.jsx
│   ├── WinningAds.jsx   # Template library
│   └── Reporting.jsx
├── context/             # React Context for global state
│   ├── ToastContext.jsx     # useToast() hook
│   ├── BrandContext.jsx
│   └── CampaignContext.jsx
└── lib/                 # Utilities
    ├── supabase.js
    └── facebookApi.js
```

**Key Frontend Patterns:**
- API calls to backend at `http://localhost:8000/api/v1`
- All routes wrapped in Layout component for consistent navigation
- Toast notifications managed via ToastContext

## Critical UI/UX Rules (from specifications.md)

### Toast Notifications (MANDATORY)

**NEVER use browser `alert()`.** Always use the `useToast` hook:

```javascript
import { useToast } from '../context/ToastContext';

const { showSuccess, showError, showWarning, showInfo } = useToast();

showSuccess('Operation completed successfully');
showError('Failed to save. Please try again.');
showWarning('This action cannot be undone');
showInfo('Processing your request...');
```

- Duration defaults to 5 seconds (customizable via second parameter)
- Types: `success` (green), `error` (red), `warning` (amber), `info` (blue)

### Confirmation Modals (MANDATORY)

**NEVER use browser `confirm()`.** Create custom modal components:

```javascript
const [showDeleteModal, setShowDeleteModal] = useState(false);

const handleDelete = () => setShowDeleteModal(true);

const confirmDelete = async () => {
    setShowDeleteModal(false);
    // Perform delete action
    showSuccess('Deleted successfully');
};
```

Modal design requirements:
- Backdrop blur with semi-transparent overlay
- Clear title and description
- Destructive actions use red buttons
- Non-destructive actions use gray/neutral buttons
- Icon to indicate action type (trash, warning, etc.)

## Database Requirements

**PostgreSQL is REQUIRED.** SQLite is deprecated and will cause startup errors.

Production uses PostgreSQL on the AWS Lightsail VPS. Local dev connects to the same production database for shared data.

### Local Development

Uses the production PostgreSQL on the VPS (configured in `.env.local`). No local database setup needed.

### Environment Variables

Create `.env.local` in project root:

```bash
# Database (Railway PostgreSQL)
DATABASE_URL=postgresql://postgres:xxx@host.proxy.rlwy.net:port/railway

# Cloudflare R2 Storage
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET_NAME=your-bucket
R2_PUBLIC_URL=https://pub-xxx.r2.dev

# AI Services
GEMINI_API_KEY=...
FAL_AI_API_KEY=...
KIE_AI_API_KEY=...

# Facebook Marketing API
VITE_FACEBOOK_ACCESS_TOKEN=...
VITE_FACEBOOK_API_VERSION=v24.0

# Auth
SECRET_KEY=...  # Generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Server Environment Variables** (set on VPS by Golden — request via Slack `C041GSZD1NG`):
- `DATABASE_URL` → PostgreSQL connection string on the VPS
- `SECRET_KEY` → Strong random key for JWT auth
- All R2_* variables for Cloudflare R2 storage
- All AI API keys
- `REDTRACK_API_KEY` → Added 2026-04-27 ✅
- `SLACK_BOT_TOKEN` → Pending confirmation from Golden
- `SLACK_SIGNING_SECRET` → Needed for Slack intelligence bot (Phase 2)

## Search & Refactoring Tools

- Use `ast-grep` for structural code search/replace (AST-aware, not text):
  - `ast-grep -p 'const API_URL = $VAL' --lang js` - find API_URL declarations
  - `ast-grep -p 'useState($INIT)' --lang tsx` - find useState patterns
  - `ast-grep -p '$OLD($$$)' -r '$NEW($$$)' --lang js` - rename functions
  - Useful for bulk refactors across React/JS codebase

## Code Style & Standards

### Backend (Python)
- **Style Guide**: PEP 8
- **Formatter**: Black (line length 88)
- **Linter**: Flake8 or Ruff
- **Imports**: Sort with isort
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes

### Frontend (JavaScript/React)
- **Formatter**: Prettier
- **Linter**: ESLint (react, react-hooks plugins)
- **Naming**:
  - Components: `PascalCase.jsx`
  - Functions/Variables: `camelCase`
  - Constants: `UPPER_SNAKE_CASE`

## Security Notes

- CORS restricted to specific origins (configure via ALLOWED_ORIGINS env var)
- JWT-based authentication implemented (access + refresh tokens)
- File uploads limited to images (jpg, jpeg, png, gif, webp), 10MB max
- All secrets stored in environment variables (never committed)
- CSP configured in frontend to restrict resource loading

## Key Features

1. **Brand Management**: Create brands with voice, colors, logos
2. **Product Catalog**: Manage products with descriptions and images
3. **Customer Profiles**: Define target audience demographics
4. **Research Module**: Scrape competitor ads from Facebook Ad Library
5. **Ad Generation**: AI-powered ad creation using Gemini + Fal.ai
6. **Ad Remix Engine**: Deconstruct winning ads into blueprints, reconstruct with new brands
7. **Facebook Campaign Management**: Create/manage campaigns, ad sets, and ads via API
8. **Generated Ads Gallery**: View ads grouped by bundle_id
9. **Reporting**: Analytics dashboard (in development)

## Deployment

**Deployment (AWS Lightsail VPS):**
1. Push changes to `sunbunzz627` fork → PR to `BHM-Dev:develop`
2. Golden reviews, merges, pulls to VPS, and restarts server
3. Server restart runs: `python init_db.py && alembic upgrade head && uvicorn`
4. Always notify Golden on Slack (`C041GSZD1NG`) when a PR includes DB migrations

**Post-Deploy Verification:**
```bash
railway logs --tail 30  # Look for "Uvicorn running on http://0.0.0.0:8080"
```

**MANDATORY - Feature Testing After Deployment:**
For ANY new feature deployment, run ALL applicable tests:

1. **Smoke Tests** (agent-browser):
```bash
cd frontend
BASE_URL=https://your-app.com npm run test:smoke

# Or run individual tests:
BASE_URL=https://your-app.com npm run test:login
TEST_EMAIL=user@example.com TEST_PASSWORD=xxx npm run test:auth
```

2. **Unit Tests** (backend):
```bash
cd backend
pytest tests/test_<feature>.py -v
```

3. **Unit Tests** (frontend):
```bash
cd frontend
npm run test:unit
```

**Test file locations:**
- Frontend e2e: `frontend/tests/agent-browser/*.sh`
- Frontend unit: `frontend/src/**/*.test.js`
- Backend unit: `backend/tests/test_*.py`

**agent-browser Quick Reference:**
```bash
agent-browser open <url>          # Open URL
agent-browser snapshot            # Get accessibility tree
agent-browser click '<selector>'  # Click element
agent-browser fill '<sel>' 'val'  # Fill input
agent-browser screenshot /tmp/x.png
agent-browser close               # Close browser
```

**Cloudflare R2 Setup:**
- Bucket: configured via R2_BUCKET_NAME
- Public access enabled via R2.dev URL
- CORS configured to allow frontend origins

## Common Gotchas

- Database migrations run automatically on deploy via Dockerfile CMD
- Always commit ALL new migration files and their dependencies before pushing
- Frontend API URL set via `VITE_API_URL` env var (build-time, not runtime)
- When adding new origins: update CORS in `main.py` AND CSP in `index.html`
- Ad account IDs auto-prefixed with 'act_' if missing (facebook_service.py)
- Local dev uses same VPS DB + R2 as production (shared data)

## Alembic / Database Migration Rules (hard-won — April 2026)

**Never use `alembic stamp head` in the Dockerfile.** It marks migrations as applied without running DDL. Always use `alembic upgrade head`. The Dockerfile CMD is:
```
CMD python init_db.py && alembic upgrade head && uvicorn ...
```

**Every `create_table` migration must be idempotent.** `init_db.py` runs `Base.metadata.create_all()` on every deploy, which creates ALL model tables before Alembic runs. If a migration tries to `CREATE TABLE` for a table that `init_db.py` already created, it crashes with "relation already exists" — killing the startup CMD chain and breaking login. **Every migration that calls `op.create_table()` must have this guard at the top:**

```python
def upgrade() -> None:
    bind = op.get_bind()
    import sqlalchemy as sa_inspect
    if sa_inspect.inspect(bind).has_table('your_table_name'):
        return
    op.create_table(...)
```

This pattern is in `1b02d74254e5` (baseline) and `a1b3c5d7e9f2` (auto_pause_rules). Apply it to every new table migration without exception.

**When a new column is missing in production:** Always audit ALL columns in the affected model against the migration chain before writing a fix — not just the one that errored. A single `column does not exist` error usually means multiple columns are missing. Fix them all at once with a single `ADD COLUMN IF NOT EXISTS` migration.

**Migration sync rule:** If a migration is already stamped as applied in `alembic_version` but the DDL never ran, the only fix is raw SQL with `IF NOT EXISTS`. The migration file uses `IF NOT EXISTS` throughout, so running the same SQL manually and then letting Alembic mark it applied keeps everything in sync.

## Meta Marketing API Field Names (verified April 2026)

Critical field name distinctions — wrong names are silently ignored by Meta causing hard-to-diagnose errors:

| Field | Correct name | Common mistake |
|-------|-------------|----------------|
| Ad set day-parting schedule | `adset_schedule` | ~~`ad_schedule`~~ |
| Campaign end time | `stop_time` | ~~`end_time`~~ |
| Ad set end time | `end_time` | ~~`stop_time`~~ |
| Day parting flag | `pacing_type: ['day_parting']` | ✓ correct |

**Date format:** Always convert `start_time` and `end_time` to ISO format via `new Date().toISOString()` before sending. The datetime-local input format (`"2026-05-23T23:59"`, no seconds/timezone) is not reliably accepted by Meta.

**Verified correct field names (facebook-business SDK v18+):**
- Campaign: `name`, `objective`, `status`, `special_ad_categories`, `lifetime_budget`, `daily_budget`, `stop_time`, `bid_strategy`, `is_adset_budget_sharing_enabled`
- AdSet: `name`, `campaign_id`, `billing_event` (`IMPRESSIONS` still valid), `optimization_goal`, `is_dynamic_creative`, `status`, `targeting`, `promoted_object`, `lifetime_budget`, `daily_budget`, `start_time`, `end_time`, `adset_schedule`, `pacing_type`, `bid_amount`, `bid_strategy`, `attribution_spec`
- Ad: `name`, `adset_id`, `creative`, `status`

**Enum values:**
- Campaign objectives: always use `OUTCOME_*` format (`OUTCOME_SALES`, `OUTCOME_TRAFFIC`, `OUTCOME_LEADS`, `OUTCOME_ENGAGEMENT`, `OUTCOME_AWARENESS`, `OUTCOME_APP_PROMOTION`)
- Special ad categories: `FINANCIAL_PRODUCTS_SERVICES` (not `CREDIT` — deprecated Jan 2025)
- Attribution windows: no `VIEW_THROUGH` with more than `window_days: 1` (28d/7d view removed Jan 2026)
- `targeting_automation: {advantage_audience: 0}` goes INSIDE the targeting dict, not at AdSet level

**Before any PR that touches facebook_service.py:** Spawn a peer-review agent to audit all field names and enum values against the current SDK source at `github.com/facebook/facebook-python-business-sdk`.
