# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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
- Hosting: Railway (backend + frontend + database)

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

Production uses Railway PostgreSQL. Local dev connects to the same Railway database for shared data.

### Local Development

Uses Railway PostgreSQL (configured in `.env.local`). No local database setup needed.

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

**Railway Environment Variables** (set in dashboard):
- `DATABASE_URL` → Use `${{Postgres.DATABASE_URL}}` to auto-sync with Postgres service
- `SECRET_KEY` → Strong random key for JWT auth
- All R2_* variables for storage
- All AI API keys

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

**Railway Setup:**
1. Backend auto-deploys from `main` branch via Dockerfile
2. Frontend auto-deploys from `main` branch via Nixpacks
3. Database is Railway PostgreSQL service
4. Custom domain → CNAME to Railway

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
- Local dev uses same Railway DB + R2 as production (shared data)

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
