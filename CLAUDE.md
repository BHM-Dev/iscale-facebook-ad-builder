# Ad Builder — Project CLAUDE.md

Auto-loaded by Claude Code at session start. Every line is actionable context. No fluff.

---

## What This App Is

Facebook ad builder used daily by Joel Welch (media buyer). Connects to Meta Ads API. Manages the full lifecycle: competitor research → ad creation → campaign launch → performance monitoring.

**Tech stack:** React 19 + Vite + TailwindCSS (frontend) | FastAPI + PostgreSQL (backend) | Python 3.11+  
**Hosting:** AWS Lightsail VPS (Golden's server). NOT Railway — do not reference Railway dashboard or Railway env vars.  
**Repo:** `BHM-Dev/iscale-facebook-ad-builder`  
**Deploy:** Push to `sunbunzz627` fork → PR to `BHM-Dev:develop` → Golden reviews + merges + restarts VPS. NO auto-deploy.  
**Storage:** Cloudflare R2 (S3-compatible) for generated/uploaded images when `r2_enabled` is true.

---

## Infrastructure (Current — 2026-04-27 and later)

- Env vars are set directly on the VPS by Golden. Never set them via Railway.
- To request a new env var: message Golden in `C041GSZD1NG` with the var name — he adds it server-side and restarts.
- Deployment = Golden restarts the server. Startup sequence runs automatically on every restart (see below).
- `REDTRACK_API_KEY` — confirmed added 2026-04-27.
- `SLACK_BOT_TOKEN` — confirm status with Golden.

---

## Joel's Daily Workflow (what he does every day)

1. **Campaign Performance** (`/campaign-performance`) — his home base. Shows all Meta ad sets with live insights (CPL, ROAS, spend, CTR). He assigns brands to ad set rows using the dropdown pill.
2. **Remix drawer** — clicks "Remix" on any ad row → right-side drawer opens. Shows source ad copy, brand pill (pre-filled if assigned), hook/angle field, niche field (auto-extracted from ad set name). He tweaks the hook → clicks "Generate 3 Variations" → Gemini returns 3 copy variants.
3. **Build Ad** — clicks "Build Ad ↗" on a variation → opens `/ad-remix` in a new tab with everything pre-filled. For brands with exactly 1 product and 1 profile, Product and Profile steps are auto-skipped; Joel lands directly on Campaign Details. He clicks "Generate Remix" → gets image concept + final copy.
4. **Batch Generate** (`/batch-generate`) — bulk image generation. Can arrive here from the Ad Remix results page.

Joel thinks in Meta Ads Manager terms. Any UX that diverges from how Ads Manager works needs to be flagged.

---

## Pages and Routes

| Page | Route | Purpose |
|------|-------|---------|
| Dashboard | `/` | Performance overview |
| Campaign Performance | `/campaign-performance` | Live Meta insights, brand assignment, Remix drawer |
| Ad Remix | `/ad-remix` | 6-step wizard: Template → Brand → Product → Profile → Campaign → Review |
| Batch Generate | `/batch-generate` | Bulk image generation with copy variants |
| Brands | `/brands` | Brand management |
| Products | `/products` | Product management (stored inside brands) |
| Customer Profiles | `/profiles` | Audience profiles linked to brands |
| Winning Ads | `/winning-ads` | Template library |
| Facebook Campaigns | `/facebook-campaigns` | Campaign/ad set/ad management |
| Research | `/research` | Competitor ad scraping |
| Generated Ads | `/generated-ads` | Gallery of AI-generated ads |

---

## Known Brands (Joel's Actual Setup)

| Brand | Products | Profiles | Notes |
|-------|----------|----------|-------|
| Get Business Coverage | 1 (Commercial Insurance - Base) | 1 (Religious Organizations - Commercial Insurance) | Joel's primary winner brand. 1+1 = auto-skip fires on both Product and Profile steps in Ad Remix wizard |
| Resource Help Online (RHO) | 1 | 10 | Many profiles = Profile step always shown |
| BHM-Branch | 1 | 1 | <!-- TODO: Steven — what vertical/use case? --> |
| Nike | 1 | 1 | <!-- TODO: Steven — test brand or real? --> |

---

## Critical Technical Patterns

### Startup Sequence (memorize — any failure breaks login)

```
python init_db.py          ← creates ALL model tables via Base.metadata.create_all()
  && alembic upgrade head  ← runs pending migrations
  && uvicorn app.main:app  ← starts the server
```

If `alembic upgrade head` fails, backend never starts. ALL endpoints (including login) return errors.

### Alembic Migration Rules (hard-won)

**Chain must be linear — single head only.** `scripts/check_alembic_heads.py` blocks `git push` if multiple heads exist. Run it before every push.

**Current chain:**
`1b02d74254e5` → `d8f2e1a7b4c9` → `e3a1f9b2c8d4` → `f4b2c8d9e1a7` → `a1b3c5d7e9f2` → `b2c4d6e8f0a1` → `g5c3d9e0f2b8` → `h6d4e0f1g3c9`

Every new migration's `down_revision` must point to the current single head. The branched chain was the root cause of the login outage on 2026-05-10.

**Every `op.create_table()` must have a `has_table()` guard.** `init_db.py` runs `Base.metadata.create_all()` before Alembic — it creates every table in `models.py`. Any migration that calls `op.create_table()` without this guard will crash on the second deploy:

```python
def upgrade() -> None:
    bind = op.get_bind()
    import sqlalchemy as sa_inspect
    if sa_inspect.inspect(bind).has_table('your_table_name'):
        return
    op.create_table(...)
```

**For new columns:** Use `ADD COLUMN IF NOT EXISTS` raw SQL, not `op.add_column()` (fails if column exists). Always audit ALL columns in the affected model against the full migration chain — a single error usually means multiple columns are missing. Fix them all in one migration.

**Never use `alembic stamp head`.** Always `alembic upgrade head`.

### Auto-Skip in Ad Remix Wizard

When arriving from the Remix drawer with a brand pre-assigned:
- If brand has exactly 1 product → auto-select, skip to Profile step
- If brand has exactly 1 profile → auto-select, skip to Campaign step
- `skipAutoAdvance` ref prevents auto-skip from re-firing when user presses Back
- Guard: check `skipAutoAdvance.current` at the top of the profile auto-skip effect

### Brand Assignment (adset level, not campaign level)

Brand is stored on `facebook_adsets.brand_id` — NOT `facebook_campaigns.brand_id`. Two ad sets in the same campaign need independent brand assignments. All state must be keyed by `adset.id`, never `adset.campaign_id`.

### Meta CDN Image URLs Expire

URLs from Meta's CDN expire within minutes to hours. `reconstruct-from-url` endpoint wraps `deconstruct_template` in its own try/except and falls back to a generic blueprint. Never assume a Meta image URL fetched at remix-click time will still be valid by generate-time.

### localStorage Handoffs Between Pages

- `pendingRemixCreative` — written by Remix drawer "Build Ad ↗", read by `/ad-remix` on mount, deleted immediately after reading
- `pendingBatchCopy` — written by Ad Remix results page, read by `/batch-generate`

### Copy Generation

Uses Gemini (`gemini-flash-latest`) via `backend/app/api/v1/copy_generation.py`.  
Framework: Eugene Schwartz Breakthrough Advertising — 5-stage awareness diagnosis (Unaware → Problem-Aware → Solution-Aware → Product-Aware → Most Aware) + market sophistication diagnosis.  
Avatar voice matching baked in by vertical: auto insurance, commercial, personal loans, debt relief, reverse mortgage.  
**Pending:** Swap to OpenAI (`gpt-5.1` for `/generate`, `gpt-4.1-mini` for `/remix-variations`) once Golden adds API keys to the VPS.

### Key API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/facebook/adsets/saved` | Returns ad sets with `brand_id`/`brand_name` from adset (not campaign) |
| `PATCH` | `/facebook/adsets/{id}/brand` | Assign or clear brand on an adset |
| `POST` | `/copy-generation/remix-variations` | Generate 3 remix copy variations (Gemini) |
| `POST` | `/ad-remix/reconstruct-from-url` | Generate ad concept from Meta image URL (with expiry fallback) |
| `GET` | `/facebook/ads/{fb_ad_id}/creative` | Fetch headline/body/image from Meta for any ad ID |
| `GET` | `/auto-pause/insights/{fb_adset_id}` | Live Meta Insights for a single ad set |

### `FacebookService()` Constructor

Takes NO arguments. Never pass `ad_account_id=` kwarg.

---

## Common Failure Patterns (check on every diff)

1. **React state auto-advance loops** — any `useEffect` that calls `setCurrentStep` must have a guard (ref or condition) preventing re-fire when user navigates backward
2. **Alembic branch** — new migration's `down_revision` must point to current head, not any earlier revision. Run `check_alembic_heads.py` before push.
3. **SQLAlchemy relationship without DB column** — adding `relationship()` or `ForeignKey()` to a model before the migration runs causes backend to fail on queries even though mappers configure fine
4. **Meta URL expiry** — any code that stores a Meta CDN URL and uses it later must handle 403/404 gracefully
5. **`adset.id` vs `adset.campaign_id`** — brand assignment, remix state, and all adset-keyed maps use `adset.id`. Multiple ad sets share a `campaign_id` — never use it as a unique key for adset-level state.
6. **`ad.ad_id` field name** — the correct field from the `ads-bulk` endpoint is `ad.ad_id`, not `ad.id`
7. **Null product/profile** — `wizardData.product.id` and `wizardData.profile.id` are sent in reconstruct payload; if auto-skip misfires these can be null, causing a 422 from the backend

---

## Meta Marketing API Field Names (verified April 2026)

| Field | Correct | Wrong |
|-------|---------|-------|
| Ad set day-parting schedule | `adset_schedule` | ~~`ad_schedule`~~ |
| Campaign end time | `stop_time` | ~~`end_time`~~ |
| Ad set end time | `end_time` | ~~`stop_time`~~ |
| Day parting flag | `pacing_type: ['day_parting']` | — |

**Date format:** Always convert to ISO format via `new Date().toISOString()` before sending. `datetime-local` input format (no seconds/timezone) is not reliably accepted.

**Enum values:**
- Campaign objectives: `OUTCOME_*` format only (`OUTCOME_SALES`, `OUTCOME_TRAFFIC`, `OUTCOME_LEADS`, `OUTCOME_ENGAGEMENT`, `OUTCOME_AWARENESS`, `OUTCOME_APP_PROMOTION`)
- Special ad categories: `FINANCIAL_PRODUCTS_SERVICES` — not `CREDIT` (deprecated Jan 2025)
- Attribution windows: no `VIEW_THROUGH` with more than `window_days: 1` (28d/7d view removed Jan 2026)
- `targeting_automation: {advantage_audience: 0}` goes INSIDE the targeting dict, not at AdSet level

**Before any PR that touches `facebook_service.py`:** Spawn a peer-review agent to audit all field names and enum values against the current SDK source at `github.com/facebook/facebook-python-business-sdk`.

---

## Mandatory Pre-Push Checklist

Run through every item before committing or pushing any backend change. These bugs have broken production login 6+ times.

### New migration?
- [ ] Does it call `op.create_table()`? Must have `has_table()` guard — no exceptions.
- [ ] Does it call `op.add_column()`? Use `ADD COLUMN IF NOT EXISTS` raw SQL pattern, not `op.add_column()`.
- [ ] Is `down_revision` pointing to the correct (current) single head?
- [ ] Does `python3 scripts/check_alembic_heads.py` pass with a single head?

### New model added to `models.py`?
- [ ] Does a migration exist that creates its table?
- [ ] Is the model imported in `models.py`? (`init_db.py` does `from app.models import *`)

### New router/file added?
- [ ] Imported at the **module level** in `main.py`? Any import error in that file crashes the entire app.
- [ ] Does the new file import anything that doesn't exist yet?

### New package added to `requirements.txt`?
- [ ] Installs cleanly on Python 3.11?
- [ ] Startup code using it wrapped in `try/except` if at module import level?

### Existing routes/models modified?
- [ ] Any column renamed or removed? That breaks existing queries.
- [ ] Any endpoint path changed? That breaks the frontend without a matching frontend update.
- [ ] Any function signature changed in `facebook_service.py`? Trace every caller.

### Frontend changes?
- [ ] All new CSS classes (`className="..."`) exist in Tailwind or `index.css`?
- [ ] All new imports valid? A single bad import = blank page.
- [ ] Any new page using `authFetch`? Import as `import { authFetch } from '../lib/facebookApi'` (named export).

### Ad Remix wizard changes?
- [ ] Does Back work from every step without looping?
- [ ] Does auto-skip fire correctly for single product/profile brands?
- [ ] Is `wizardData.product` and `wizardData.profile` always defined before reconstruct?

### Campaign Performance changes?
- [ ] Brand state keyed by `adset.id` (not `campaign_id`)?
- [ ] Remix drawer closes and re-opens cleanly?
- [ ] "Build Ad ↗" opens a new tab (not navigate away)?

### Final gate
- [ ] Read the diff one more time (`git diff HEAD`). Ask: "If this breaks, what's the symptom and the 5-minute fix?"
- [ ] If it involves a DB migration: Golden applies it on VPS restart. Verify the fix path is clear.
- [ ] Does this push include a DB migration? If yes → **message Golden in `C041GSZD1NG`** with the `alembic upgrade head` instruction. Code-only pushes don't need a message.

---

## Pre-Push Rule — Ad Launch Features

Before pushing any change that touches the ad launch flow, run the pressure test agent team using the reusable agent definitions in `.claude/agents/`:

- **`code-auditor`** — traces UI state → permutation → handleSubmit → Meta API for correctness, silent failures, and edge cases
- **`joel-perspective`** — reviews from Joel's media buyer POV: Ads Manager workflow match, UX gaps, money/time risks

**Trigger files** (run agent team before pushing any change to):
- `frontend/src/components/BulkAdCreation.jsx`
- `frontend/src/components/AdCreativeStep.jsx`
- `frontend/src/lib/facebookApi.js`
- `backend/app/services/facebook_service.py`

**Rating scales:**
- Code auditor: `blocking`, `high`, `medium`, `low`
- Joel perspective: `P0` (launch blocker), `P1` (support ticket), `P2` (friction), `P3` (nice to have)

Fix all `blocking` and `P0` findings before push. Document `high`/`P1` findings as follow-up tasks.

---

## Backend Structure

```
backend/app/
├── main.py              # FastAPI app, CORS, router registration
├── database.py          # SQLAlchemy engine, SessionLocal, Base
├── models.py            # All SQLAlchemy models
├── core/config.py       # Settings, validates DATABASE_URL is PostgreSQL
├── api/v1/              # All routes prefixed /api/v1
│   ├── brands.py
│   ├── products.py
│   ├── profiles.py
│   ├── generated_ads.py
│   ├── facebook.py      # Campaign/AdSet/Ad management + /adsets/saved
│   ├── research.py
│   ├── ad_remix.py      # Blueprint deconstruct/reconstruct
│   ├── copy_generation.py
│   ├── auto_pause.py    # CRUD + enforcement
│   ├── templates.py
│   ├── uploads.py
│   └── dashboard.py
└── services/
    ├── facebook_service.py     # facebook-business SDK (NO constructor args)
    ├── slack_service.py        # chat.postMessage to C08G7PJJ6NB (auto-pause alerts)
    ├── scheduler_service.py    # APScheduler — auto-pause check every 30 min
    ├── research_service.py
    ├── scraper.py
    └── ad_remix_service.py     # Gemini Vision for template analysis
```

**Key backend patterns:**
- All routes use `/api/v1` prefix
- Database dependency injection via `Depends(get_db)`
- PostgreSQL required — `config.py` validates `DATABASE_URL` on startup
- Facebook API uses `facebook-business` SDK
- Copy generation uses Google Gemini (`GEMINI_API_KEY`)
- Image generation: kie.ai (`KIE_AI_API_KEY`). Async model: POST `/api/v1/jobs/createTask`, poll `GET /api/v1/jobs/recordInfo?taskId=`. Bearer auth. Model: `flux-kontext-pro`. ~4–8 credits/image. Low credits → HTTP 500 with real error message.
- File uploads → Cloudflare R2 when configured, falls back to local `uploads/` for dev

## Frontend Structure

```
frontend/src/
├── App.jsx              # Router, ToastProvider/BrandProvider/CampaignProvider
├── pages/
│   ├── Dashboard.jsx
│   ├── CampaignPerformance.jsx  # Joel's home base — Remix drawer lives here
│   ├── AdRemix.jsx              # 6-step wizard with auto-skip logic
│   ├── BatchGenerate.jsx        # Bulk image gen; reads adId URL param + pendingBatchCopy
│   ├── Brands.jsx
│   ├── Products.jsx
│   ├── CustomerProfiles.jsx
│   ├── FacebookCampaigns.jsx
│   ├── WinningAds.jsx
│   ├── Research.jsx
│   └── GeneratedAds.jsx
├── components/
│   ├── Layout.jsx       # Navigation + sidebar with BHM logo
│   ├── Toast.jsx
│   ├── Wizard.jsx
│   └── ...
├── context/
│   ├── ToastContext.jsx
│   ├── BrandContext.jsx
│   └── CampaignContext.jsx
└── lib/
    └── facebookApi.js   # authFetch (named export — import as { authFetch })
```

---

## UI/UX Rules (mandatory)

### Toast notifications — never use `alert()`

```javascript
import { useToast } from '../context/ToastContext';
const { showSuccess, showError, showWarning, showInfo } = useToast();
```

### Confirmation modals — never use `confirm()`

Custom modal with backdrop blur, clear title, red button for destructive actions.

---

## Environment Variables

**Server (VPS, managed by Golden — request via `C041GSZD1NG`):**

| Var | Status |
|-----|--------|
| `DATABASE_URL` | Active |
| `SECRET_KEY` | Active |
| `R2_*` (4 vars) | Active |
| `GEMINI_API_KEY` | Active |
| `KIE_AI_API_KEY` | Active |
| `VITE_FACEBOOK_ACCESS_TOKEN` | Active |
| `VITE_FACEBOOK_API_VERSION` | Active (`v24.0`) |
| `REDTRACK_API_KEY` | Added 2026-04-27 |
| `SLACK_BOT_TOKEN` | Confirm with Golden |
| `SLACK_SIGNING_SECRET` | Needed for Slack intelligence bot (Phase 2, not yet built) |

**Local dev (`.env.local` in project root):** Connects to production VPS DB + R2 for shared data.

---

## Development Commands

```bash
# Backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python init_db.py
uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev    # http://localhost:5173

# Check Alembic heads (run before any push with migrations)
python3 scripts/check_alembic_heads.py
```

API docs: `http://localhost:8000/api/v1/docs`

---

## Deployment Checklist

1. Push to `sunbunzz627` fork
2. Open PR targeting `BHM-Dev:develop`
3. If PR includes a DB migration → message Golden in `C041GSZD1NG` with the `alembic upgrade head` instruction
4. Code-only pushes → no message to Golden needed (server restarts on his schedule)
5. Golden merges, pulls to VPS, restarts server
6. Post-deploy: check server logs for `Uvicorn running on http://0.0.0.0:8080`

---

## Pending Features / Known Gaps

- [ ] OpenAI API swap (waiting on Golden to add keys to VPS): `gpt-5.1` for `/generate`, `gpt-4.1-mini` for `/remix-variations`
- [ ] Rename "Ad Remix" nav link → "Build New Ad"
- [ ] Slack Campaign Intelligence Bot — spec at `SLACK_INTELLIGENCE_SPEC.md`. On-demand (`@AdBuilder update`), daily 9am ET proactive, threshold alerts. Gemini analysis assigns SCALE/WATCH/CUT tiers.
- [ ] Auto-pause scaling rules (increase budget when CPL drops below threshold)
- [ ] Ad-level pausing (pause individual ads, not just ad sets)
- [ ] Rule audit log (persistent trigger history with metric values)
- [ ] Time-window restrictions on auto-pause rules (avoid noisy early-morning data)
- [ ] CI `alembic-round-trip` test fix — pre-existing failure; baseline migration `downgrade()` missing `op.drop_table()` calls for several tables
- [ ] Weekly UX audit cron posting to `#media-buys`

---

## Team

| Person | Role | Slack | When to contact |
|--------|------|-------|-----------------|
| Golden | Dev lead, VPS admin | `C041GSZD1NG` | ONLY when push includes a DB migration. Code-only pushes = no message needed. |
| Joel Welch | Primary user (media buyer) | `C08G7PJJ6NB` | Bug reports, UX feedback |
| Steven Sun | CEO / product decisions | — | All product decisions |
