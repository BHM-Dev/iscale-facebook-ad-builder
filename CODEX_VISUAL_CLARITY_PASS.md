# Visual Clarity Pass — Codex Brief

**Scope:** UI readability only. No new features, no backend changes, no new API calls, no DB migrations. All changes are className / JSX structure only across 5 frontend files.

**Preflight:** `git pull origin develop`

**Files to edit:**
- `frontend/src/pages/CampaignPerformance.jsx`
- `frontend/src/pages/Dashboard.jsx`
- `frontend/src/pages/BatchGenerate.jsx`
- `frontend/src/pages/GeneratedAds.jsx`

**Do not touch:** `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`, `facebook_service.py`, any backend file.

---

## 1. Campaign Performance — Column Alignment + Collapsed Header Row

### Goal
Campaign header rows and ad set rows should feel like they share the same column grid. Right now the campaign header metrics float in their own grid disconnected from the table beneath it.

### What the ad set table currently uses (thead at line ~1847)
```
Ad Set Name | Status | Spend | Leads | CPL | Freq | RT ROAS | Budget | Remix | Pause | Ads
px-6        | px-3   | px-3  | px-3  | px-3| px-3 | px-3    | px-3   | ...   | ...   | ...
```
The key data columns are: **Spend · Leads · CPL · ROAS · Budget** — these 5 should align with campaign header metrics.

### Change A — Mini column header row (collapsed-mode only)
Add a single sticky-style header row just above the first campaign group that shows column labels: `Spend · Leads · CPL · ROAS · Budget`. Only render it when `collapsedCampaigns.size > 0` OR always show it (simpler). This removes the need for per-campaign-row label repetition.

Use the same grid as the campaign header rows: `grid-cols-[minmax(360px,1fr)_96px_84px_96px_96px_124px]`

```jsx
{/* Column header row — always visible */}
<div className="grid grid-cols-[minmax(360px,1fr)_96px_84px_96px_96px_124px] px-6 py-1.5 border-b border-slate-200 bg-slate-50 text-[10px] font-semibold uppercase tracking-wide text-gray-400 sticky top-0 z-10">
  <div /> {/* name column — no label */}
  {['Spend', 'Leads', 'CPL', 'ROAS', 'Budget'].map(col => (
    <div key={col} className="border-l border-slate-200 px-3 text-right">{col}</div>
  ))}
</div>
```

Place this immediately before the `{groupedCampaigns.map(group => ...)}` loop, inside the scrollable section.

### Change B — Remove metric labels from campaign header rows
Since the mini header row provides the column labels, remove the `<span className="block text-[10px] uppercase tracking-wide text-gray-400">` label spans inside each metric div in the campaign header row. Keep only the value span:

```jsx
// Before
<div key={label} className="border-l border-slate-200 px-3 text-right">
  <span className="block text-[10px] uppercase tracking-wide text-gray-400">{label}</span>
  <span className="block text-sm font-semibold text-gray-800">{value}</span>
</div>

// After
<div key={label} className="border-l border-slate-200 px-3 text-right">
  <span className="text-sm font-semibold text-gray-800">{value}</span>
</div>
```

Do the same for the Budget column — remove the `<span className="block text-[10px] uppercase tracking-wide text-gray-400 mb-1">Budget</span>` label.

### Do NOT change
- Campaign collapse/expand toggle behavior
- Budget popover — keep `onClick={e => e.stopPropagation()}` on the budget column div
- Deep-link ad set row highlight (`isHighlighted ? 'bg-indigo-50' : ...`)
- Ad set tbody rows, thead, sorting, filters
- `ml-auto` on the budget button

---

## 2. Campaign Intelligence — 4-Lane Action Queue

### Current state (lines ~240–258 in `CampaignIntelligencePanel`)
```jsx
<div className="mb-4 rounded-xl border border-gray-100 bg-gray-50 p-4">
  <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Action Queue</div>
  <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 text-xs">
    {data.action_queue.scale?.length > 0 && (
      <div><span className="font-semibold text-green-700">Scale: </span>...comma list...</div>
    )}
    ...
  </div>
</div>
```
Items are comma-joined into a dense inline paragraph. Hard to scan.

### Target — 4 scannable lanes
Replace the entire action queue block with 4 side-by-side lanes (2×2 on mobile, 4-col on desktop). Each lane has a tinted header and a vertical list of niche pills. Only render lanes that have items.

Lane config:
| Key | Label | Header bg | Border | Text |
|-----|-------|-----------|--------|------|
| `scale` | Scale | `bg-green-50` | `border-green-200` | `text-green-800` |
| `cut_or_pause` | Cut / Pause | `bg-red-50` | `border-red-200` | `text-red-800` |
| `watch` | Watch | `bg-amber-50` | `border-amber-200` | `text-amber-800` |
| `tracking_check` | Tracking | `bg-yellow-50` | `border-yellow-200` | `text-yellow-800` |

```jsx
{data.action_queue && (
  <div className="mb-4">
    <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Action Queue</div>
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
      {[
        { key: 'scale',         label: 'Scale',       hdrBg: 'bg-green-50',  border: 'border-green-200',  text: 'text-green-800'  },
        { key: 'cut_or_pause',  label: 'Cut / Pause', hdrBg: 'bg-red-50',    border: 'border-red-200',    text: 'text-red-800'    },
        { key: 'watch',         label: 'Watch',       hdrBg: 'bg-amber-50',  border: 'border-amber-200',  text: 'text-amber-800'  },
        { key: 'tracking_check',label: 'Tracking',    hdrBg: 'bg-yellow-50', border: 'border-yellow-200', text: 'text-yellow-800' },
      ].map(lane => {
        const items = data.action_queue[lane.key];
        if (!items?.length) return null;
        return (
          <div key={lane.key} className={`rounded-lg border ${lane.border} overflow-hidden`}>
            <div className={`${lane.hdrBg} px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wide ${lane.text}`}>
              {lane.label}
            </div>
            <ul className="px-3 py-2 space-y-1">
              {items.map(item => (
                <li key={item} className="text-xs text-gray-700 truncate" title={item}>{item}</li>
              ))}
            </ul>
          </div>
        );
      })}
    </div>
  </div>
)}
```

---

## 3. Dashboard — Compress Ask AI

### Current state
The Ask AI section has: header row → date preset pills row → input + button row → 4 example question chips (always visible when no answer). The example chips occupy ~40px of vertical space below the input at all times.

### Change
Move example chips behind an **"Examples ▾"** toggle. Default: hidden. Click reveals them inline.

Add a local state variable `const [showAiExamples, setShowAiExamples] = useState(false)` inside the Dashboard component (not global state — this is view-only).

Replace the current examples block:
```jsx
// Current
{!aiAnswer && !aiLoading && (
  <div className="mt-3 flex flex-wrap gap-2">
    {['What are my worst ad sets today?', ...].map(q => (
      <button key={q} onClick={() => setAiQuery(q)} className="text-xs px-2.5 py-1 rounded-full border ...">
        {q}
      </button>
    ))}
  </div>
)}
```

Replace with:
```jsx
{!aiAnswer && !aiLoading && (
  <div className="mt-2">
    <button
      onClick={() => setShowAiExamples(v => !v)}
      className="text-xs text-gray-400 hover:text-violet-600 transition-colors flex items-center gap-1"
    >
      Examples {showAiExamples ? '▴' : '▾'}
    </button>
    {showAiExamples && (
      <div className="mt-2 flex flex-wrap gap-2">
        {['What are my worst ad sets today?',
          'Which creatives have the highest CPL?',
          'Show me frequency issues across all campaigns',
          'Any pixel or tracking problems I should know about?',
        ].map(q => (
          <button
            key={q}
            onClick={() => { setAiQuery(q); setShowAiExamples(false); }}
            className="text-xs px-2.5 py-1 rounded-full border border-gray-200 text-gray-500 hover:border-violet-300 hover:text-violet-600 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    )}
  </div>
)}
```

No other changes to Ask AI. Do not move, remove, or resize the section.

---

## 4. Batch Generate — Accordion Left Rail

### Current state
Left rail (`<div className="space-y-5">` at line ~629) has 5 stacked sections: Reference Image, Image Sizes, Niche / Context, Text Overlay, and (lower) Variant copy fields. The sections are always expanded, making the left rail very tall.

### Change
Wrap Reference Image, Image Sizes, Text Overlay, and Niche / Context into collapsible accordion sections. Variant copy stays expanded (those are primary inputs).

Add a local state: `const [openSections, setOpenSections] = useState({ reference: true, sizes: true, overlay: false, context: false })` (Reference and Sizes open by default; Overlay and Context collapsed by default since they're secondary).

Helper:
```jsx
const toggleSection = (key) => setOpenSections(prev => ({ ...prev, [key]: !prev[key] }));
```

Accordion wrapper pattern for each section:
```jsx
<div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
  <button
    type="button"
    onClick={() => toggleSection('reference')}
    className="w-full flex items-center justify-between px-4 py-3 text-sm font-semibold text-gray-800 hover:bg-gray-50 transition-colors"
  >
    <span>Reference Image</span>
    <ChevronDown size={15} className={`text-gray-400 transition-transform ${openSections.reference ? '' : '-rotate-90'}`} />
  </button>
  {openSections.reference && (
    <div className="px-4 pb-4">
      {/* existing reference image content */}
    </div>
  )}
</div>
```

Apply this pattern to: Reference Image, Image Sizes, Niche / Context, Text Overlay. Keep existing content inside unchanged.

**Important:** `ChevronDown` is already imported in CampaignPerformance.jsx — check if it's imported in BatchGenerate.jsx already. If not, add it to the lucide-react import line.

---

## 5. Generated Ads — Lightweight Card Metadata

### Current state
Grid cards (`viewMode === 'grid'`) show image + bottom action bar. No metadata visible on the card face.

### Where to find relevant fields
Each item in the grouped ad list is an array of ads. The first ad in the group has:
- `ad.niche` or `ad.overlay_niche_line` — niche label
- `ad.brand_name` — brand name (if available)
- `ad.created_at` — ISO date string

### Change
Add a small metadata strip at the bottom of each card (above or replacing the existing action row), visible without hover. Keep it minimal — one line, two pieces of info max.

Suggested: `{niche} · {formatted date}`

```jsx
{/* Metadata strip */}
<div className="px-3 py-1.5 bg-gray-50 border-t border-gray-100 flex items-center justify-between gap-2 text-[11px] text-gray-400 truncate">
  <span className="truncate font-medium text-gray-600">
    {items[0]?.niche || items[0]?.overlay_niche_line || 'General'}
  </span>
  <span className="flex-shrink-0">
    {items[0]?.created_at
      ? new Date(items[0].created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : ''}
  </span>
</div>
```

Place this strip between the image area and the existing action buttons in the card. Do not add it to list-view rows.

---

## Validation checklist for Codex

After all changes, run:
```bash
npx eslint src/pages/CampaignPerformance.jsx src/pages/Dashboard.jsx src/pages/BatchGenerate.jsx src/pages/GeneratedAds.jsx
npm run build
```

Both must pass clean (exit 0, no errors).

Chrome checks to run before handing off:
1. Campaign Performance: Collapse all → confirm column header row appears, metrics align under Spend/Leads/CPL/ROAS/Budget labels, no per-row label repetition. Expand one campaign → ad set rows render normally. Budget popover opens. Deep-link highlight still works.
2. Campaign Intelligence: Open CI panel → load Last 7d → confirm Action Queue shows 4 tinted lane cards (only populated lanes appear). No comma-list paragraphs.
3. Dashboard: Confirm Ask AI loads without examples visible. Click "Examples ▾" → chips appear. Click a chip → populates input and collapses examples.
4. Batch Generate: Left rail shows accordion-style sections. Reference Image and Image Sizes open by default. Overlay and Context collapsed. Toggle works. All fields still accessible.
5. Generated Ads: Grid cards show niche + date strip. No extra visual clutter.
6. No console errors on any page.

**When done:** Reply with "Edits done — ready for Claude Code review + push" and list commit hash(es).
