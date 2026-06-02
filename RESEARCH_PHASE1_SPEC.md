# Research Section — Phase 1 Spec

**Status:** Ready to build  
**Goal:** Turn the existing Research section into a seamless competitive intelligence layer — browsable by vertical, actionable from within ad creation flows, no jumping around.  
**Scope:** UI overhaul + pre-configured keyword sets + angle tagging + Build New Ad integration  
**Does NOT touch:** `facebook_service.py` (no Meta API changes), `copy_generation.py` (Phase 3)

---

## Core Philosophy

The Research section has one job: help Joel understand what the market is saying before he writes. It should be browsable in two minutes, not managed. The key design constraint: **Joel should never have to leave his ad-building flow to consult research.** That means research output needs to be one click away from wherever copy generation happens.

Two libraries, two roles — they work together:

| Library | Source | What the AI does with it |
|---|---|---|
| Copy Library | Joel's own Meta ads | Voice matching — "sound like Joel" |
| Research Library | Competitor ads via FB Ad Library | Competitive context — "understand the market" |

---

## Verticals in Scope (Phase 1)

Three verticals only. No personal loans, no reverse mortgage.

### 1. Commercial Insurance

Joel's active vertical. These keywords appear in competitor ad creative (not targeting — FB Ad Library searches body/headline text):

```
"commercial insurance"
"business insurance"
"contractor insurance"
"general liability"
"workers comp"
"workers compensation"
"small business insurance"
"commercial auto insurance"
```

### 2. Auto Insurance

Starting soon. Heavy competitive space — Geico, Progressive, Root, Insurify, The Zebra all run constant Facebook spend. These keywords surface the widest range of competitor creative:

```
"auto insurance"
"car insurance"
"vehicle insurance"
"car insurance quote"
"auto insurance quote"
"save on car insurance"
"cheap car insurance"
"switch and save"
"full coverage"
"SR-22"
```

### 3. Home Services (7 sub-verticals)

Thumbtack-validated profitable niches. Each sub-vertical gets its own keyword set. Organized as sub-tabs within the Home Services vertical tab.

**Floor Installation / Replacement**
```
"floor installation"
"flooring contractor"
"hardwood floors"
"laminate flooring"
"floor replacement"
"new floors"
```

**Interior Painting**
```
"interior painting"
"interior painters"
"house painting"
"painting contractor"
"home painting"
"interior paint"
```

**Mold Remediation**
```
"mold remediation"
"mold removal"
"mold inspection"
"black mold"
"mold testing"
```

**Patio Remodel / Addition**
```
"patio installation"
"patio remodel"
"patio addition"
"patio contractor"
"deck installation"
"outdoor living space"
```

**Fence & Gate Installation**
```
"fence installation"
"fence contractor"
"privacy fence"
"gate installation"
"wood fence"
"vinyl fence"
```

**Gutters Installation**
```
"gutter installation"
"gutter replacement"
"rain gutters"
"gutter contractor"
"new gutters"
```

**Tree Service / Trimming / Removal**
```
"tree removal"
"tree trimming"
"tree service"
"tree cutting"
"stump removal"
"arborist"
```

---

## Keyword Set Storage

Store as a **JSON constant in the backend** — no DB table needed for Phase 1. Add a Python dict in `backend/app/api/v1/research.py` (or a new `backend/app/core/vertical_config.py`):

```python
VERTICAL_KEYWORD_SETS = {
    "commercial_insurance": {
        "label": "Commercial Insurance",
        "keywords": ["commercial insurance", "business insurance", ...]
    },
    "auto_insurance": {
        "label": "Auto Insurance",
        "keywords": ["auto insurance", "car insurance", ...]
    },
    "home_services": {
        "label": "Home Services",
        "sub_verticals": {
            "floor_installation": {
                "label": "Floor Installation",
                "keywords": ["floor installation", ...]
            },
            ...
        }
    }
}
```

Expose via `GET /api/v1/research/vertical-config` so the frontend can read it without hardcoding. Makes it easy to edit later without a frontend deploy.

---

## New Route: Bulk Search by Vertical

Existing: `POST /search-and-save` runs one keyword at a time.

Add: `POST /search-and-save-vertical` — runs all keywords for a vertical in sequence, aggregates results, returns total new ads count.

```python
# body: { "vertical_id": "auto_insurance", "sub_vertical": null, "limit_per_keyword": 200 }
# Returns: { "total_new": 47, "total_duplicate": 312, "keywords_run": 10 }
```

This is what the "Refresh" button calls. Runs in the background (FastAPI `BackgroundTasks`) so the UI doesn't block. Frontend polls `/research/verticals/{vertical_id}/status` for progress.

---

## Angle Tagging

Add `angle_tag` column to `ScrapedAd` model. Values:

| Tag | Description |
|---|---|
| `fear` | Loss aversion, risk, what happens if you don't act |
| `social_proof` | Numbers, testimonials, "X people switched" |
| `urgency` | Limited time, act now, rates changing |
| `savings` | Price comparison, save X%, cheaper than |
| `authority` | Expert positioning, licensed, rated #1 |
| `story` | First-person narrative, case study |
| `curiosity` | Open loop, "most people don't know..." |

Joel assigns one tag when saving an ad. Optional — can be null.

**Migration:** `ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS angle_tag VARCHAR`

---

## UI Overhaul

### Page Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  🔬 Research Library                      [↻ Refresh Vertical]  │
│  Study what's working in your markets                           │
├─────────────────────────────────────────────────────────────────┤
│  [Commercial Insurance]  [Auto Insurance]  [Home Services ▾]   │
│                                            └─ Floor Installation│
│                                               Interior Painting │
│                                               Mold Remediation  │
│                                               ...               │
├──────────────────────────────────────────┬──────────────────────┤
│  BROWSE   (1,247 ads)                    │  SAVED   (23 ads)   │
│  Filter: All angles ▾  |  Active only □  │                      │
│                                          │  [saved cards here]  │
│  [card] [card] [card]                    │                      │
│  [card] [card] [card]                    │                      │
│  ...                                     │                      │
└──────────────────────────────────────────┴──────────────────────┘
```

Two-column layout within the page:
- **Left (70%):** Browse panel — scrollable card gallery of all scraped ads for the active vertical
- **Right (30%):** Saved panel — Joel's pinned/saved ads for that vertical, always visible

The Saved panel being always visible on the same screen is the core UX improvement — Joel can browse left, save right, without any navigation.

### Ad Card Design

```
┌──────────────────────────────────────┐
│ ● ACTIVE    Progressive Insurance    │  ← advertiser name, status dot
├──────────────────────────────────────┤
│  Switch and save — most drivers      │  ← headline (bold)
│  pay too much for car insurance.     │
│                                      │
│  We checked, and the average driver  │  ← body (truncated, expandable)
│  saves $947 when they compare...     │
│                            Show more │
├──────────────────────────────────────┤
│ [SAVINGS]   📅 Running 47 days       │  ← angle tag badge, duration
│                                      │
│  [⤴ Use as Inspiration]  [★ Save]   │  ← action buttons
└──────────────────────────────────────┘
```

- No image preview (Ad Library image URLs are unreliable/expire — skip for Phase 1)
- Angle tag is shown as a colored badge if already tagged, or shown as a dropdown on "Save"
- "Use as Inspiration" is the seamless integration hook (see below)
- Advertiser name links to their FB Ad Library page in a new tab

### Filter Bar

Sits above the card gallery:
- **Angle filter:** All | Fear | Social Proof | Urgency | Savings | Authority | Story | Curiosity
- **Active only toggle:** Shows only ads currently running (no stop date)
- **Advertiser search:** Filter by page name (useful when Joel wants to study one competitor)

---

## Seamless Integration: "Use as Inspiration"

This is the connective tissue. When Joel clicks "Use as Inspiration" on a research card:

1. Write to localStorage:
```js
localStorage.setItem('pendingResearchInspiration', JSON.stringify({
  headline: ad.headline,
  body: ad.ad_copy,
  advertiser: ad.page_name,
  vertical: currentVertical,
  angle: ad.angle_tag,
  source: 'research'
}));
```

2. Navigate to `/ad-remix` (Build New Ad)

3. `AdRemix.jsx` reads `pendingResearchInspiration` on mount — same pattern as `pendingRemixCreative`. Pre-fills:
   - Step 1 (Hook/Angle): populates the "Reference angle" or "Inspiration" note field with the competitor's approach
   - **Does NOT pre-fill headline/body** — we want Joel to write original copy, not remix a competitor's exact words. The inspiration is strategic context, not copy.

4. A banner appears at the top of the Build New Ad wizard:
   > "Inspired by: Progressive Insurance — Savings angle. Writing original copy for your brand."

This keeps Joel in the flow without ever making him copy-paste or switch tabs.

---

## What Changes in `AdRemix.jsx`

Add a `researchInspiration` state. On mount:
```js
const inspiration = localStorage.getItem('pendingResearchInspiration');
if (inspiration) {
  setResearchInspiration(JSON.parse(inspiration));
  localStorage.removeItem('pendingResearchInspiration');
}
```

Show a dismissable info banner at the top of the wizard when `researchInspiration` is set:
```jsx
{researchInspiration && (
  <div className="flex items-center justify-between px-4 py-2 bg-blue-50 border border-blue-100 rounded-lg text-sm text-blue-700">
    <span>
      Inspired by <strong>{researchInspiration.advertiser}</strong> — 
      {researchInspiration.angle && ` ${researchInspiration.angle} angle`}
    </span>
    <button onClick={() => setResearchInspiration(null)}>✕</button>
  </div>
)}
```

Pass `researchInspiration` to the copy generation API call as an optional field so the AI can see the angle context. In `copy_generation.py`, use it to add one line to the prompt: "The user is inspired by a [savings] angle competitor ad — write in Joel's voice with that angle in mind." (This is the Phase 3 AI integration, but the data flow is wired in Phase 1 so Phase 3 is a one-liner.)

---

## Files to Touch

| File | Change | Trigger? |
|---|---|---|
| `frontend/src/pages/Research.jsx` | Full UI overhaul — card gallery, two-column layout, vertical tabs, sub-vertical dropdown | No |
| `frontend/src/pages/AdRemix.jsx` | Read `pendingResearchInspiration` on mount, show inspiration banner | No |
| `backend/app/api/v1/research.py` | Add `GET /vertical-config` + `POST /search-and-save-vertical` | No |
| `backend/app/core/vertical_config.py` | New file — `VERTICAL_KEYWORD_SETS` dict | No |
| `backend/app/models.py` | Add `angle_tag` column to `ScrapedAd` | Yes — migration needed |
| `backend/alembic/versions/` | New migration: `ADD COLUMN IF NOT EXISTS angle_tag VARCHAR` | Yes — Claude Code handles |

No new env vars. The existing `VITE_FACEBOOK_ACCESS_TOKEN` and Meta API plumbing are unchanged.

---

## Build Checklist (for the build session)

- [ ] Read existing `Research.jsx`, `research.py`, `research_service.py`, and `scraper.py` in full before touching anything — the existing API and data model are used, not replaced
- [ ] Read `AdRemix.jsx` to find the right mount hook for `pendingResearchInspiration` (follow the `pendingRemixCreative` pattern)
- [ ] Create `vertical_config.py` first — all other changes depend on the keyword set structure
- [ ] Add `GET /vertical-config` to `research.py` — frontend needs this before the UI can render
- [ ] Write the migration for `angle_tag` — single column, no breaking changes
- [ ] Build `POST /search-and-save-vertical` using existing `SearchAndSaveRequest` + existing service methods — don't rewrite the scraper
- [ ] Overhaul `Research.jsx` last — build against the real API responses
- [ ] Spot-check "Use as Inspiration" flow end-to-end: Research → localStorage → AdRemix banner renders → banner dismisses cleanly
- [ ] Run 2-agent pre-push review (`models.py` + `AdRemix.jsx` are both sensitive)
- [ ] After push: manually run a vertical refresh for Commercial Insurance (Joel already has data) and verify card gallery renders correctly

---

## Out of Scope for Phase 1

- Scheduled auto-pulls (Phase 2 — wire `schedule_config` to Mac mini cron)
- Research drawer accessible from within Batch Generate (Phase 2 — requires a global drawer component)
- AI prompt injection of competitor context (Phase 3 — the data handoff is wired, just needs the prompt line)
- Performance data on research ads (spend range/impressions from Ad Library — available in API, not displayed in Phase 1)
- Image previews (Ad Library image URLs expire — need a proxy/cache layer first)
