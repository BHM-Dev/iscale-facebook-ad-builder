# Niche Summary — Add Profit Column

**Scope:** Frontend only. One file. No backend changes — data already exists.

**Preflight:** `git pull origin develop`

**File:** `frontend/src/pages/Dashboard.jsx`

---

## Context

The "Performance by Niche" table on Dashboard currently shows:
`Niche | Ad Sets | Spend | Revenue | ROAS | CPL | Leads`

Joel asked for a Profit column. The backend already returns `total_revenue` and `total_spend` per niche row. Profit = `total_revenue - total_spend`.

---

## Change — Add Profit column after Revenue

### thead — add `<th>` after Revenue:

```jsx
<th className="px-5 py-3 text-right">Revenue</th>
<th className="px-5 py-3 text-right">Profit</th>   {/* ADD THIS */}
<th className="px-5 py-3 text-right">ROAS</th>
```

### tbody row — add `<td>` after the Revenue cell:

```jsx
{/* After the Revenue td */}
<td className={`px-5 py-3 text-right font-semibold ${
  row.total_revenue === 0 ? 'text-gray-400'
  : (row.total_revenue - row.total_spend) >= 0 ? 'text-green-600'
  : 'text-red-600'
}`}>
  {row.total_revenue > 0
    ? formatMoney(row.total_revenue - row.total_spend)
    : '—'}
</td>
```

**Color rules:**
- No revenue data → gray `—`
- Profit ≥ $0 → `text-green-600`
- Profit < $0 → `text-red-600`

### Skeleton loader — bump col count to match

Find the loading skeleton (3 placeholder rows). It currently uses `grid-cols-7`. Add one more skeleton `<div>` to each row, or if it uses a fixed count, bump to 8:

```jsx
// Find all skeleton rows — each has 7 divs. Add one more:
<div className="h-4 rounded bg-gray-100 animate-pulse" />  {/* +1 for Profit */}
```

---

## Validation

```bash
npm run build
```

Chrome check:
- Dashboard → Performance by Niche → confirm Profit column appears between Revenue and ROAS
- Positive profit rows are green, negative are red, rows with `—` revenue show `—` in gray
- Column header alignment looks clean

**When done:** "Edits done — ready for Claude Code review + push" + commit hash.
