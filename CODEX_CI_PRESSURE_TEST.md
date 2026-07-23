# Campaign Intelligence — Codex Pressure Test Brief

**Branch:** `develop`  
**Commits to review:** `efaa880` (initial MVP) + `63283a3` (review fixes)  
**Files changed:**
- `backend/app/api/v1/intelligence.py` (new file)
- `backend/app/main.py` (+3 lines: import + router)
- `frontend/src/pages/Dashboard.jsx` (+~300 lines net)

---

## What Was Built

A **Campaign Intelligence card** on the Dashboard. It:

1. Calls `GET /api/v1/intelligence/niche-profitability?preset=last_7d` on first open
2. Joins Meta ad set spend (via `FacebookService`) with RedTrack revenue (via `RedTrackService`)
3. Aggregates by niche (extracted from ad set name pattern `[Date] - [Niche] - [Batch]`)
4. Assigns deterministic verdicts and returns a Claude Haiku AI summary
5. Renders a collapsible card with preset pills, verdict badges, join status column, and AI summary

---

## Key Behaviors to Pressure-Test

### 1. Lazy-load state machine

The card uses a `ciLoadedPresetRef` (useRef, starts `null`) to track which preset was last successfully loaded.

**Expected behavior:**
- Dashboard mounts → no API call, card is collapsed
- User opens card → fetches `last_7d` (ref was null ≠ 'last_7d')
- User opens/closes card again → no re-fetch (ref now equals 'last_7d')
- User clicks "Yesterday" preset while card is open → fetches immediately
- User clicks "Last 30d" preset while card is **closed** → no fetch; state updates to 'last_30d'
- User re-opens card → fetches 'last_30d' (ref is still 'last_7d' from before)
- Fetch fails → ref stays at previous value → next open re-tries

**Verify in code (`Dashboard.jsx`):**
- `ciLoadedPresetRef.current` is set inside `loadIntelligence` on success (after `setCiData`), not before the call
- `handleCiOpen` compares `ciLoadedPresetRef.current !== ciPreset` to decide whether to fetch
- Preset pill click only calls `loadIntelligence` if `ciOpen === true`
- Custom Apply and Retry buttons call `loadIntelligence` directly (ref is set on success inside the function)

**Check for:** any path where the ref is set before the fetch succeeds (would suppress future re-fetches after errors)

---

### 2. Directional verdicts

When `preset` is `weekdays_mtd` or `weekends_mtd`, the backend filters Meta spend by day-of-week but RedTrack revenue uses the full date range. This makes ROI approximate.

**Backend (`intelligence.py`):**
- `_assign_verdict(spend, revenue, join_status, day_filter)` must return `directional_scale`, `directional_run`, `directional_watch`, or `directional_pause` when `day_filter != "all"`
- `tracking_check` and `insufficient_data` are always returned unchanged regardless of `day_filter`
- Row payload includes `is_directional: true` when `day_filter != "all"`

**Frontend (`Dashboard.jsx`):**
- `verdictStyles` and `verdictLabels` maps must include all 8 keys: `scale`, `run`, `watch`, `pause`, `directional_scale`, `directional_run`, `directional_watch`, `directional_pause`
- Directional labels render as: `↑ Scale?`, `→ Run?`, `~ Watch?`, `↓ Pause?`
- Directional badge styles have a dashed/lighter border to visually distinguish from confirmed verdicts

**Check for:** any `row.verdict` value that falls through to `|| 'bg-gray-100 text-gray-500'` or `|| row.verdict` raw string render

---

### 3. AI summary rendering

The Haiku prompt now ends with: `"Output plain text only — no markdown, no bullet points, no headers, no bold."`

The frontend renders `ciData.summary` through `<MarkdownAnswer text={ciData.summary} />` (component defined at line 9 of Dashboard.jsx).

**Check for:**
- `MarkdownAnswer` is called with `text={ciData.summary}` not `text={ciData.summary || ''}` — if summary is empty string, does MarkdownAnswer handle it gracefully?
- The wrapper div has `min-w-0` to prevent flex overflow

---

### 4. Join Status column

Four possible values from the API:

| API value | Label | Color |
|---|---|---|
| `matched` | Matched | green |
| `matched_rt_approximate` | Approx RT | blue |
| `partial_redtrack` | Partial RT | orange |
| `missing_redtrack` | Missing RT | red |

**Check for:**
- Table has 8 columns now (Niche, Spend, Revenue, Profit, ROI, CPL, Verdict, Join) — `colSpan` anywhere in the table that might need updating
- Unknown `join_status` values fall back to `{ label: row.join_status, cls: 'text-gray-400' }` (raw value, gray)

---

### 5. Error / empty state

- **Error state:** shows error message + Retry button (re-calls `loadIntelligence`) + Dismiss button (clears `ciError`)
- **Pre-load state:** card open, no data, no error → shows "Select a preset to load intelligence."
- **Empty results:** API returns 200 with `rows: []` → shows "No data for this period."

**Check for:** can the user reach a state where error is shown but Retry is disabled or calls wrong preset?

---

### 6. Refresh button

Always calls `loadIntelligence(ciPreset, ciCustomFrom, ciCustomTo)` with current state values.

- `e.stopPropagation()` prevents the header click (collapse) from firing
- Button is `disabled={ciLoading}` — no double-fire
- Does NOT clear `ciLoadedPresetRef` — refresh always fires regardless of ref state (it bypasses the lazy-load guard)

**Check for:** does Refresh work when `ciPreset === 'custom'` and `ciCustomFrom`/`ciCustomTo` are populated?

---

### 7. Day-filter footnote

When `ciData.day_filter !== 'all'`, a footnote renders:

```
RedTrack revenue uses full date range (not day-filtered) — ROI is approximate.
```

**Check for:** this note still present in the JSX at the bottom of the results section

---

## What NOT to Test

- RedTrack data accuracy (live API, out of scope)
- Meta API response shape (live API, out of scope)
- AI summary content quality (Haiku output, non-deterministic)
- Performance/load time (acceptable to be slow on first load)

---

## Pass Criteria

- [ ] No API call fires on Dashboard mount
- [ ] Card opens and fetches `last_7d` on first expand
- [ ] Re-opening without preset change does NOT re-fetch
- [ ] Switching preset while card is closed → re-fetch fires on next open
- [ ] `weekdays_mtd` and `weekends_mtd` return `directional_*` verdicts, not hard verdicts
- [ ] All 8 verdict values render correct badge style and label (no raw strings)
- [ ] AI summary renders through MarkdownAnswer (no raw `#`, `**` syntax visible)
- [ ] Join Status column visible with correct 4-color scheme
- [ ] Error state shows Retry and Dismiss; Retry re-calls with current preset
- [ ] `npm run build` passes clean
