# Ad Builder — Project CLAUDE.md

Auto-loaded by Claude Code at session start. Every line is actionable context. No fluff.

---

## AI Tool Routing

This repo is worked on by both **Claude Code** and **OpenAI Codex**. Use the right tool for the job to manage token costs.

| Task | Tool |
|------|------|
| Multi-agent builds (3+ parallel agents) | Claude Code |
| MCP tools — Slack DMs, browser automation, Loom review | Claude Code only |
| Pre-push review agent pairs | Claude Code |
| DB migrations + pre-push checklist | Claude Code |
| Simple file edits, new fields, wiring endpoints, UI tweaks | Either |
| Boilerplate, adding a column, fixing a typo | Codex preferred |

**Sync rule:** Always `git pull origin develop` before starting a session in either tool. Always push when done. The CLAUDE.md and the repo are the source of truth — session history is not.

**Codex limitations:** No MCP servers (can't DM Golden, can't read Slack/Loom, can't control browser). For anything requiring those, switch to Claude Code.

---

## Codex Quick Reference

Codex doesn't get the MCP toolset Claude Code has. This section is the operating manual — read it before doing anything.

### Preflight (every session)

```bash
git pull origin develop
python3 scripts/check_alembic_heads.py   # only if you'll touch migrations
```

Look at "Still pending" at the bottom of this file. Don't invent work — pick from the list or work on what the user describes.

### File map — where things live

**Backend (`backend/app/`):**
- Routes (all prefixed `/api/v1`): `api/v1/{brands,products,profiles,facebook,ad_remix,copy_generation,auto_pause,generated_ads,research,uploads,dashboard,templates}.py`
- Models: `models.py` — single file, every SQLAlchemy class lives here
- Services: `services/{facebook_service,ad_remix_service,slack_service,scheduler_service,research_service,scraper}.py`
- Config: `core/config.py` (validates `DATABASE_URL` is Postgres at startup)
- DB: `app/database.py`
- Bootstrap script: `backend/init_db.py` (NOT inside `app/` — run from `backend/`)
- Migrations: `backend/alembic/versions/*.py`

**Frontend (`frontend/src/`):**
- Pages: `pages/{Dashboard,CampaignPerformance,AdRemix,BatchGenerate,ImageAds,Brands,Products,CustomerProfiles,FacebookCampaigns,GeneratedAds,Research,WinningAds}.jsx`
- Components: `components/{Layout,Toast,Wizard,BulkAdCreation,AdCreativeStep,...}.jsx`
- Context: `context/{ToastContext,BrandContext,CampaignContext}.jsx`
- API helper: `lib/facebookApi.js` — named export `authFetch`

### Patterns you MUST follow

- **Frontend API calls:** `import { authFetch } from '../lib/facebookApi'`. Never raw `fetch()` — auth header is missing.
- **User notifications:** `import { useToast } from '../context/ToastContext'` → `showSuccess/showError/showWarning/showInfo`. Never `alert()`.
- **Confirmations:** Custom modal with backdrop blur, red button for destructive. Never `confirm()`.
- **New column on existing table:** Raw SQL — `op.execute("ALTER TABLE x ADD COLUMN IF NOT EXISTS new_col TYPE")`. Never `op.add_column()`.
- **New table:** Wrap `op.create_table()` in a `has_table()` guard (see "Alembic Migration Rules" below).
- **New migration:** `down_revision` points to current head. Run `python3 scripts/check_alembic_heads.py` — must return single head.
- **Brand state:** Keyed by `adset.id`, never `campaign_id`.
- **Meta ad ID field:** `ad.ad_id` from `ads-bulk` endpoint, not `ad.id`.

### Files you must NOT edit alone — STOP and hand off to Claude Code

These trigger the mandatory 2-agent pre-push review (see "Pre-Push Rule — Ad Launch Features"):
- `frontend/src/components/BulkAdCreation.jsx`
- `frontend/src/components/AdCreativeStep.jsx`
- `frontend/src/lib/facebookApi.js`
- `backend/app/services/facebook_service.py`

Also hand off for: anything with a DB migration, anything needing Slack/Loom/browser/Meta MCP, multi-file architectural changes, anything where you'd ask "should I do X or Y."

### Common task templates

**Rename a nav link / change UI copy:**
1. `grep -r "Old Text" frontend/src/` — confirm every usage
2. Edit each location
3. Confirm no test references the old string
4. Push (pure string swaps don't need agent review)

**Add a column to an existing model:**
1. Edit the SQLAlchemy class in `backend/app/models.py`
2. Create a migration in `backend/alembic/versions/` — `down_revision` = current head
3. Raw SQL: `op.execute("ALTER TABLE x ADD COLUMN IF NOT EXISTS new_col TYPE")`
4. Run `python3 scripts/check_alembic_heads.py`
5. **STOP.** Hand off to Claude Code (migration → Golden DM required).

**Add a field to an existing form:**
1. Add input to the form component
2. Add field to API payload in the submit handler
3. Add field to backend Pydantic schema + route handler
4. If persisted: add to model + migration (see column template)
5. **STOP** if any trigger file or migration touched — hand off to Claude Code.

**Wire a new API endpoint to an existing page:**
1. Add the route in `backend/app/api/v1/<file>.py`
2. Register the router in `backend/app/main.py` if it's a new file
3. Add the `authFetch` call in the frontend page
4. **STOP.** Hand off to Claude Code.

### Push protocol

**Codex does not push feature code.** End every feature session with:

> "Edits done — ready for Claude Code 2-agent review + push."

**Codex may push directly only when ALL of these are true:**
- Change is limited to `CLAUDE.md`, `README.md`, or in-code comment-only edits
- No file in the never-push list below was touched
- No new dependency, env var, or config was added

**Never-push list (Codex must always hand off):**
- Anything under `backend/alembic/versions/`
- `backend/app/models.py`
- `backend/app/main.py`
- The four trigger files: `frontend/src/components/BulkAdCreation.jsx`, `frontend/src/components/AdCreativeStep.jsx`, `frontend/src/lib/facebookApi.js`, `backend/app/services/facebook_service.py`
- Any `*_SPEC.md` or files under `docs/` (spec changes have downstream code impact)

For anything else: commit locally if useful, but the final push goes through Claude Code so the pre-push review agents run.

**Note for Codex:** Claude Code has a `PreToolUse` hook in `.claude/settings.json` that blocks `git push` until two parallel pressure-test agents have run. That's working as intended, not a bug — it enforces the rule above.

---

## What This App Is

Facebook ad builder used daily by Joel Welch (media buyer). Connects to Meta Ads API. Manages the full lifecycle: competitor research → ad creation → campaign launch → performance monitoring.

**Tech stack:** React 19 + Vite + TailwindCSS (frontend) | FastAPI + PostgreSQL (backend) | Python 3.11+  
**Hosting:** AWS Lightsail VPS (Golden's server). NOT Railway — do not reference Railway dashboard or Railway env vars.  
**Repo:** `BHM-Dev/iscale-facebook-ad-builder`  
**Deploy:** Push directly to `BHM-Dev:develop` (`git push origin develop`). VPS auto-deploys on every push. **Only message Golden if the push includes a DB migration.**  
**Storage:** Cloudflare R2 (S3-compatible) for generated/uploaded images when `r2_enabled` is true.

---

## Infrastructure (Current — 2026-04-27 and later)

- **Backend runs in Docker on the VPS** (confirmed 2026-05-22 by Golden). There is NO local `venv` on the VPS — any script that needs the app's Python deps must be run inside the running backend container.
- VPS shell access pattern (when Golden runs ad-hoc scripts, e.g. account creation, one-off migrations):
  ```bash
  docker exec -it <backend-container> python -c "..."
  # or
  docker exec -it <backend-container> bash
  ```
- Env vars are set directly on the VPS by Golden. Never set them via Railway.
- To request a new env var: message Golden directly at `D075KSE1A1L` with the var name — he adds it server-side and restarts.
- Restart command: `docker compose restart backend` (Golden runs this when env vars change or a manual restart is needed).
- Code deploys auto-trigger on push to `develop`. Env var changes and ad-hoc scripts require Golden manual action.
- `REDTRACK_API_KEY` — confirmed added 2026-04-27.
- `SWITCHBOARD_EVERFLOW_API_KEY` — pending. Source of truth for P&L billable revenue on validated Switchboard accounts.
- `SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS` — pending. Comma-separated Meta account allow-list for accounts that should use Switchboard revenue instead of RedTrack.
- `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS` — pending. JSON map of Meta account id to exact Switchboard offer names, e.g. `{"act_...":["Get Business Coverage"]}`. Required so commercial, auto, and eventually home-services revenue stay tied to the matching Meta spend account.
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
| Dashboard | `/` | Performance overview. Needs Attention click-through fixed (2026-05-21) |
| Campaign Performance | `/campaign-performance` | Live Meta insights, brand assignment, Remix drawer |
| Ad Remix | `/ad-remix` | 6-step wizard. Overlay fields wired (2026-05-21). |
| Batch Generate | `/batch-generate` | Bulk image generation. Gold standard for overlays. Reads `adId` param from Iterate. |
| Image Ads | `/image-ads` | Full 8-step wizard. Overlay panel added to Step 7 (2026-05-21). |
| Brands | `/brands` | Brand management |
| Products | `/products` | Product management (stored inside brands) |
| Customer Profiles | `/profiles` | Audience profiles linked to brands |
| Winning Ads | `/winning-ads` | Template library |
| Facebook Campaigns | `/facebook-campaigns` | Campaign/ad set/ad management |
| Research | `/research` | Competitor ad scraping |
| Generated Ads | `/generated-ads` | Gallery of AI-generated ads. Batch delete added. |
| User Management | `/users` | Admin-only. Create users with optional superuser flag. |

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

**Current head: `t8p6q2r3s5o1`** (20 revisions, linear back to base `1b02d74254e5`).

Don't hand-maintain the chain list here — it goes stale fast. Get the real head with:

```bash
python3 scripts/check_alembic_heads.py
```

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
- `pendingResearchInspiration` — written by Research section "Use as Inspiration", read by `/ad-remix` on mount. Does NOT pre-fill copy — only shows a blue context banner + passes `research_inspiration` object to the reconstruct payload for Phase 3 AI use.
- `pendingBatchCopy` — written by Ad Remix results page, read by `/batch-generate`
- `overlayLogoUrl` — **shared across BatchGenerate, AdRemix, ImageAds**. Written on logo upload, read on mount by all three pages. R2 URL, doesn't expire.
- `overlayOfferLine` — **shared across BatchGenerate, AdRemix, ImageAds**. Written on every keystroke, read on mount. Persists the "From $24.95/Month" line so Joel never retypes it.

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
| `GET` | `/facebook/ads/{fb_ad_id}/creative` | Fetch headline/body/image from Meta + overlay fields from local DB |
| `GET` | `/auto-pause/insights/{fb_adset_id}` | Live Meta Insights for a single ad set |
| `POST` | `/auth/bootstrap` | One-time admin account creation. Validated against `SECRET_KEY`. |
| `PATCH` | `/generated-ads/{id}/fb-ad-id` | Write Meta ad ID back to local DB after push. Enables Iterate to restore overlays. |

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
- [ ] If it involves a DB migration: `alembic upgrade head` runs automatically on deploy — no action needed, no message to Golden.
- [ ] Does this push include a new **env var**? If yes → DM Golden at `D075KSE1A1L` with the var name. That's the only post-push action that requires human intervention.

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
| `SWITCHBOARD_EVERFLOW_API_KEY` | Pending — Switchboard affiliate-realm revenue source for P&L |
| `SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS` | Pending — comma-separated Meta accounts that use Switchboard revenue |
| `SWITCHBOARD_EVERFLOW_ACCOUNT_OFFERS` | Pending — JSON account→offer map; e.g. Commercial Insurance → `Get Business Coverage`, Auto → `Fast Auto Quote.org` |
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

### VPS shell tasks (Docker)

For anything that needs to run inside the production backend (account creation, ad-hoc migration, one-off DB script), ask Golden to run it via `docker exec` — the VPS does not have a local venv. Example pattern Golden used 2026-05-22 to create Steven's admin:

```bash
docker exec -it <backend-container> python -c "
from init_db import seed_roles_and_permissions, create_superuser
seed_roles_and_permissions()
create_superuser('<email>', '<password>', '<name>')
"
```

Do not suggest `./venv/bin/python ...` or `source venv/bin/activate` for VPS work — there is no venv on the VPS.

---

## Deployment Checklist

1. Push directly to `BHM-Dev:develop` (`git push origin develop`) — there is no `sunbunzz627` fork; the dev workflow is push-direct, not PR-based.
2. VPS auto-deploys on every push to `develop` — Golden's container picks up the new code automatically.
3. `alembic upgrade head` runs automatically as part of the Docker startup sequence — confirmed by Golden 2026-06-02. **Do NOT message Golden about migrations.**
4. **Never message Golden after a push** — code and migrations are fully automated.
5. Env var changes → DM Golden at `D075KSE1A1L`. He adds the var, runs `docker compose restart backend`. This is the ONLY reason to message Golden.
6. Post-deploy: check `https://adbuilder-api.velocitymx.io/api/v1/docs` is reachable.

---

## Pending Features / Known Gaps

### Recently shipped (2026-06-02)
- [x] **Ad Copy Library** — pulls all ACTIVE/PAUSED ads from Meta, stores headline+body in `ad_copy_library` table, auto-injects 5 relevant examples as few-shot style reference into every copy generation call (`/generate`, `/remix-variations`, `/regenerate-field`). Joel never needs to manually reference it — injection is automatic.
- [x] **Copy Library page** (`/copy-library`) — Sync from Meta button, table with Niche/Headline/Body/Pin/Delete, post-sync banner, client-side niche filter. `BookOpen` nav entry in sidebar.
- [x] **Niche extraction + blocklist** — `_NON_NICHE_RE` filters "Batch 3", "V2", "SCALE", "RETARGET", "BROAD", "PHASE 2" etc. → stored as `null`, shown as "General". Real niche extracted from `[Date] - [Niche] - [Batch]` pattern.
- [x] **Adset names from Meta API** — `get_adset_name_map()` fetches all adset names directly from Meta (paginated, handles >500 adsets) so niche extraction works even for adsets not yet in the local DB. Fixes "Unknown" niches.
- [x] **Status field on Copy Library** — `effective_status` stored per ad in `status` column (migration `l0h8i4j5k7g3`). Frontend status badge: Codex task queued (see below).
- [x] **Niche wipe protection** — if `get_adset_name_map()` fails or adset not in map, falls back to `existing.adset_name`; also guards against overwriting a valid niche with `None` when `_extract_niche()` can't parse.

### Pending Codex tasks (2026-06-02)
- [x] **Status badge in CopyLibrary.jsx** — green for ACTIVE, gray for PAUSED; `colSpan` bumped to 6; skeleton row updated. Shipped `832ef1f`.
- [x] **AdRemix.jsx subhead copy fix** — updated to "Start from a winning ad and rebuild it with your brand voice." Shipped `832ef1f`.
- [x] **README.md / BUILD_SUMMARY.md doc drift** — "Ad Remix" references updated. Shipped `832ef1f`.

### Recently shipped (2026-05-27)
- [x] **Performance by Niche dashboard section** — New table on Dashboard aggregates Meta ad set performance by niche (extracted from ad set name pattern `[Date] - [Niche] - [Batch]`). Shows Niche | Ad Sets | Spend | CPL | Leads. `adset_name` now flows through `get_account_insights_bulk()` → `GET /dashboard/niche-summary` endpoint. CPL color-rank guard: only fires when ≥5 niches to avoid misleading coloring with small datasets.
- [x] **Rename "Ad Remix" → "Build New Ad"** — Nav link, sidebar label, page h1, tool card, and `prompts.js` constant all updated. AdRemix.jsx route (`/ad-remix`) unchanged — internal only.

### Recently shipped (2026-05-22)
- [x] **Steven's admin account created on VPS** — Golden ran `docker exec` into backend container; superuser `ssun@brighthorizonsmedia.com` confirmed created. Confirmed Docker-on-VPS architecture (no local venv).
- [x] AI Tool Routing + Codex Quick Reference added to CLAUDE.md so Codex sessions can jump in cold.

### Recently shipped (2026-05-21 session)
- [x] CTA button (orange pill) baked into overlays via `text_overlay_service.py`
- [x] Pexels removed — all image generation via kie.ai (Flux Kontext Pro)
- [x] Batch delete in Generated Ads library
- [x] User Management — admin toggle, `POST /users/` endpoint
- [x] `POST /auth/bootstrap` — first admin account creation without VPS access
- [x] Dashboard Needs Attention click-through fixed (CPL criterion added to `isFlagged`)
- [x] Overlay consistency: offer line persists in localStorage, AdRemix wired, ImageAds overlay panel added
- [x] Iterate restores overlay (offer line + logo) from local DB via `fb_ad_id` write-back
- [x] `--timeout-keep-alive 300` on uvicorn — fixes Ad Remix connection drops during kie.ai polling

### Recently shipped (2026-06-02 session 2)
- [x] **Research Phase 1** — full UI rebuild: card gallery, two-column Browse/Saved layout, 3 pre-configured verticals (Commercial Insurance, Auto Insurance, Home Services with 7 sub-verticals). Pre-configured keyword sets in `backend/app/core/vertical_config.py`. `angle_tag` column added to `scraped_ads` (migration `m1i9j5k6l8h4`). New backend routes: `GET /vertical-config`, `POST /search-and-save-vertical`, `GET /config-verticals/{id}/browse-ads`, `PATCH /scraped-ads/{id}/angle`. "Use as Inspiration" writes `pendingResearchInspiration` to localStorage → navigates to `/ad-remix` where a blue banner appears with competitor context. `research_inspiration` field wired through reconstruct payload (Phase 3 AI use).

### Still pending
- [x] **Copy Library performance data** — shipped `3432f20`. `get_ad_insights_map()` pulls lifetime spend + CPL from Meta during sync; Spend + CPL sortable columns (nulls-last, CPL color-coded); validated live (CPL asc surfaces cheapest winners).
- [x] **Copy Library Phase 2 (CPL-weighted few-shot)** — shipped `4f4a03c`. `_get_library_examples()` orders by `is_pinned desc, cpl asc nulls_last, imported_at desc` so copy gen learns from cheapest-CPL proven ads. Validated live (remix-variations 200, variants populated).
- [ ] **P&L Tracker by ad account** — brief at `CODEX_BRIEF_pnl_tracker.md`. Phase 1 done (model `PnlCostEntry`, migration `t8p6q2r3s5o1`, `pnl:read`/`pnl:write` permissions). Phase 2 = Codex: `backend/app/api/v1/pnl.py` (6 endpoints), `frontend/src/pages/Pnl.jsx`, nav entry, Dashboard MTD strip. Spend from Meta, revenue from **RedTrack** (not Meta `action_values`), costs from the new ledger. Abel = $ retainer across all accounts (`ad_account_id NULL`, `by_spend` split) + 5% `pct_of_profit` commission.
- [ ] **Video ad template system** — `VideoAds.jsx` is a wizard shell with no generation backend. Spec of record: `CODEX_BRIEF_ugc_video_mvp.md`. Needs a `video_templates` concept (hook style + shot sequence + captions + CTA overlay, parameterized by niche) and a `video_service.py` provider abstraction. Sequence after P&L Phase 2 so video spend is tracked from day one via `source='auto_video'` on `pnl_cost_entries`.
- [ ] OpenAI API swap (waiting on Golden to add keys): `gpt-5.1` for `/generate`, `gpt-4.1-mini` for `/remix-variations`
- [x] **AdRemix.jsx h1/subhead copy mismatch** — shipped in `832ef1f`. Subhead now reads "Start from a winning ad and rebuild it with your brand voice."
- [x] **README.md / BUILD_SUMMARY.md doc drift** — fixed user-facing "Deconstruct" / "remix engine" wording (README.md:69, BUILD_SUMMARY.md:29).
- [ ] ImageAds "Quick Generate" mode — skip wizard, go straight to niche+copy+generate for media buyers with existing copy
- [x] Template-first Quick Generate — shipped. "Quick Generate" (`Zap` icon) on Campaign Performance ad rows and Dashboard Top Performers, both resolving a real winning `ad_id` and landing in BatchGenerate fully pre-filled + auto-generating. CLAUDE.md was stale; code confirmed live 2026-07-31.
- [ ] Slack Campaign Intelligence Bot — spec at `SLACK_INTELLIGENCE_SPEC.md`
- [ ] Auto-pause scaling rules (increase budget when CPL drops below threshold)
- [ ] Ad-level pausing (pause individual ads, not just ad sets)
- [ ] Rule audit log (persistent trigger history with metric values)
- [ ] Time-window restrictions on auto-pause rules
- [ ] CI `alembic-round-trip` test fix — pre-existing failure
- [ ] Weekly UX audit cron posting to `#media-buys`

---

## Team

| Person | Role | Slack | When to contact |
|--------|------|-------|-----------------|
| Golden | Dev lead, VPS admin | `C041GSZD1NG` | **Only for new env vars** — migrations and code deploys are fully automated. Never message after a push. |
| Joel Welch | Primary user (media buyer) | `C08G7PJJ6NB` | Bug reports, UX feedback |
| Steven Sun | CEO / product decisions | — | All product decisions |
