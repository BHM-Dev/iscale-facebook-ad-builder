# Ad Builder — UX & Functional Improvement Brief
**Date:** 2026-07-16  
**Scope:** Get Joel and Abel creating ads in the app (not just checking stats). Support auto insurance + home services launch.  
**Classification:** Mixed — Codex for UI, Claude Code for migrations + push.

---

## The Problem

Joel uses Campaign Performance daily (stats). He creates ads natively in Meta. Abel is starting fresh with no existing habits. Two things block adoption of the creation side:

1. **No angle to start from** — blank copy fields with no direction = Joel/Abel default to their own process
2. **Wrong default experience** — the app opens to Dashboard, not where creation happens

---

## Target UX (What "Done" Looks Like)

**Joel's session:**
Dashboard → Campaign Performance → clicks top performer → "Quick Variations" → lands in Quick Generate with copy pre-filled → edits, generates, pushes. 5–10 min.

**Abel's session (day 1):**
Opens app → lands on Quick Generate → picks brand (auto insurance) → selects angle ("Rate Shock") → headline/body pre-fill as editable templates → picks visual style → generates → pushes. 5–10 min.

---

## Improvements, Prioritized

### P0 — Required Before Abel Launch

---

#### 1. Vertical Tagging on Brands
**Problem:** All brands appear in one flat list. Joel sees Abel's home services brands; Abel sees Joel's insurance brands. No way to filter.  
**Fix:** Add `vertical_id` FK on the `brands` table pointing to the existing `verticals` table.

**Migration:** `ALTER TABLE brands ADD COLUMN vertical_id VARCHAR REFERENCES verticals(id) ON DELETE SET NULL`  
**Backend:** Expose `vertical_id` on Brand GET/POST/PATCH endpoints. Seed verticals: `auto_insurance`, `home_services`, `personal_loans`, `debt_relief`, `commercial_insurance`.  
**UI:** Vertical filter pill/dropdown in the app header — persists to localStorage. Scopes: Brand Selector in Quick Generate, Campaign Performance, Copy Library, Generated Ads, Brands page.  
**Classification:** Claude Code (migration) + Codex (UI filter everywhere)

---

#### 2. Creative Angle Library
**Problem:** Abel opens Quick Generate and stares at a blank headline field. Joel knows what angles work but Abel doesn't. No structured starting point.  
**Fix:** A DB table of creative angle templates per vertical. In Quick Generate, an "Angle Picker" card grid appears above the copy fields. Selecting one pre-fills headline and body as editable text — not locked, just a starting point.

**DB table:** `creative_angles`
```
id          UUID PK
vertical_id VARCHAR FK → verticals.id
name        VARCHAR   e.g. "Rate Shock"
hook        VARCHAR   e.g. "Most drivers overpay by $800+/yr"
headline    VARCHAR   pre-fill template (editable)
body        TEXT      pre-fill template (editable)
is_active   BOOLEAN   default true
sort_order  INTEGER
```

**Seed angles — Auto Insurance:**
| Name | Hook | Headline | Body |
|------|------|----------|------|
| Rate Shock | Most drivers overpay | "Still paying $180/mo for car insurance?" | "Drivers in [state] are switching and saving an average of $800/year. Takes 2 minutes to compare." |
| Coverage Gap | Hidden gaps | "Your current policy might not cover you" | "Most drivers don't know what their policy actually covers until it's too late. Check yours free." |
| Switch & Save | Easy to switch | "Switch car insurance in 2 minutes" | "No cancellation fees. No paperwork. Just a better rate — guaranteed or we'll tell you why." |
| Good Driver Discount | Reward loyalty | "Clean record? You're leaving money on the table" | "Good drivers get up to 30% off. See what you qualify for today — no commitment required." |
| Comparison Shop | Urgency | "Your renewal is coming. Have you shopped?" | "Rates change every 6 months. The drivers who check save an average of $600. Takes 90 seconds." |

**Seed angles — Home Services:**
| Name | Hook | Headline | Body |
|------|------|----------|------|
| Seasonal Urgency | Now is the time | "Spring is the worst time to ignore your gutters" | "One clogged gutter can cost $3,000+ in foundation damage. Get a free inspection before the rain hits." |
| Price Anchor | Cost fear | "Most homeowners overpay for [service] by 40%" | "Licensed pros in your area are competing for your job. Get 3 quotes free — no obligation." |
| Trust Signal | Reviews | "4,200 homeowners in [city] chose this contractor" | "Verified reviews. Licensed and insured. Free estimates this week only." |
| Before/After | Transformation | "See what your [floor/roof/gutter] could look like" | "Real jobs. Real homeowners. Free estimate, no pressure quote." |
| Emergency Hook | Urgency | "Leak? Crack? Don't wait — it gets worse" | "Same-day service available. Free inspection. Financing options if needed." |

**In Quick Generate:** A collapsible "Creative Angles" section (expanded by default) with card grid. Clicking a card pre-fills headline + body. User can dismiss the panel once comfortable.  
**Classification:** Claude Code (migration + seed data) + Codex (Angle Picker UI in Quick Generate)

---

#### 3. Quick Generate as Default Mode
**Problem:** ImageAds opens in Guided Wizard mode. Joel/Abel have to discover and click the toggle.  
**Fix:** Change `useState('wizard')` to `useState('quick')` in ImageAds.jsx.  
**Secondary:** Change the default landing route from `/` (Dashboard) to `/image-ads` for users who are NOT admins (Joel, Abel). Admins (Steve) keep Dashboard as default. Check user role from auth context.  
**Classification:** Codex (both one-liners)

---

### P1 — Makes It Sticky (Week 2)

---

#### 4. Copy Library → Quick Generate Handoff
**Problem:** Copy Library shows winning copy (with Meta sync) but there's no path from "I like this copy" to "generate images with it."  
**Fix:** Add a "Use in Quick Generate" button on each Copy Library row. Writes `{headline, body, cta}` to `localStorage.pendingQuickCopy`, navigates to `/image-ads`. ImageAds reads this key on mount, pre-fills `quickCopy` state, clears the key.  
**Pattern:** Same as `pendingRemixCreative` already used in the Remix flow.  
**Classification:** Codex

---

#### 5. Copy Library Performance Data (CPL + Spend)
**Problem:** Copy Library shows copy but not whether it converts. Joel can't rank angles by what actually works.  
**Fix:** Add `spend` and `cost_per_lead` columns to the Copy Library table (sourced from Meta sync already running). Make columns sortable. Add a "Top Performers" default sort (lowest CPL first, min $50 spend).  
**Note:** This touches `facebook_service.py` — requires 2-agent pre-push review (Haiku + Sonnet).  
**Classification:** Codex (UI) + Claude Code (push, Sonnet API review)

---

#### 6. Campaign Performance → Quick Generate (Direct Path)
**Problem:** "Iterate" button passes `adId` to BatchGenerate (full wizard). There's no lighter path for "just generate image variations with this exact copy."  
**Fix:** Add a secondary "Quick Variations" button (next to the purple Remix button) on top-performer rows. Writes the ad's `headline`, `body`, `cta` to `localStorage.pendingQuickCopy`, navigates to `/image-ads`. Same pattern as #4.  
**Classification:** Codex

---

### P2 — Polish

---

#### 7. Nav Cleanup
The sidebar has 15+ items. Joel and Abel use 4: Campaign Performance, Image Ads, Copy Library, Generated Ads.  
**Fix:** Group nav into sections: **Create** (Image Ads, Batch Generate, Ad Remix), **Review** (Campaign Performance, Generated Ads, Copy Library), **Research** (Winning Ads, Brand Scrapes), **Settings** (Brands, Products, Profiles, Users). Collapse Research and Settings by default.  
**Classification:** Codex

#### 8. Vertical-Specific Image Templates
Auto insurance and home services need templates that look right for those verticals (not just the existing styles). Worth auditing current templates before launch — if they're generic enough, skip this.  
**Classification:** Design review first, then Codex if new templates needed

---

## Work Split

| Task | Who | Migration? | Pre-Push Review |
|------|-----|-----------|-----------------|
| Vertical FK on brands | Claude Code | Yes | 1 Haiku (schema only) |
| Seed verticals + angles | Claude Code | Yes | 1 Haiku |
| Vertical filter UI | Codex | No | — |
| Angle Picker in Quick Generate | Codex | No | — |
| Quick Generate as default | Codex | No | — |
| Default landing by role | Codex | No | — |
| Copy Library → Quick Generate | Codex | No | — |
| Copy Library CPL/Spend columns | Codex + Claude Code push | No | Haiku + Sonnet (facebook_service.py) |
| Campaign Perf → Quick Generate | Codex | No | — |
| Nav cleanup | Codex | No | — |

---

## Open Questions

1. **Angle templates — editable by BHM or code-only?** If Steve/Laura want to add/edit angles without a dev, the backend needs a simple admin UI for `creative_angles`. Otherwise seed via migration and update via code when needed. Recommend: seed in migration for now, build the admin UI if it becomes a need.

2. **Default landing by role** — Do Joel and Abel have a "media_buyer" role in the user table, or are all non-admin users treated the same? Check `UserManagement.jsx` and the auth context.

3. **Quick Generate default mode** — Should this be permanent or should the app remember the user's last-used mode? `localStorage` per-user persistence is simple and respects habit.

4. **Copy Library CPL data** — Is CPL already stored on the `ad_copy_library` table from Meta sync, or does it need to be computed and stored separately? Check `ad_copy_library.py` before scoping the Codex task.

---

## Recommended Build Order

1. Vertical migration + seed (Claude Code) → unblocks everything else
2. Codex batch: Angle Picker + vertical filter + default mode + nav cleanup
3. Copy Library handoff + Campaign Performance handoff (Codex)
4. Copy Library CPL columns (needs Sonnet review, do last)
