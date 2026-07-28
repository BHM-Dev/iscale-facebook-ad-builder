# Codex Brief: P&L Follow-ups (post-Phase 2)

**Prerequisite:** `git pull origin develop`. Phase 2 must be on develop first (`f5cda92`). Nothing here is blocking — Phase 2 shipped without it.

Full context: `CODEX_REVIEW_pnl_phase2.md`. All blocking/high items there are already resolved — do not re-fix them.

---

## 1. Timezone drift on period bounds (highest value)

**Problem.** `backend/app/api/v1/pnl.py` computes every period boundary with `date.today()` — the VPS clock, which is UTC. RedTrack reports in `REDTRACK_TIMEZONE`. `redtrack_service.py` already has `_today_in_rt_tz()` and a comment on `preset_to_dates` stating that using the VPS UTC clock "pulls the wrong day's data."

So the P&L compares a UTC-bounded month of Meta spend against a RedTrack-bounded month of revenue. It bites hardest on the 1st and the last day of a month — exactly when the books get closed.

**Fix.** Use the RedTrack timezone for period bounds in `_month_bounds()` and `_resolve_period()`. `_today_in_rt_tz()` is module-private in `redtrack_service.py`; either promote it to a public helper or add a small shared date util. Do not duplicate the tz logic in `pnl.py`.

**Watch for:** `get_months()` also calls `date.today()` directly to seed its loop. Fix that too or the history rows drift independently of the summary.

**Verify:** a month-boundary case — with `REDTRACK_TIMEZONE=America/New_York`, an MTD request made at 01:00 UTC on the 1st should resolve to the RedTrack-local date, not the UTC one.

---

## 2. `pct_of_profit` preview base in the cost modal

**Problem.** `frontend/src/pages/Pnl.jsx`, `previewBase` useMemo. For `pct_of_profit` it computes `revenue − spend − summary.other_costs`. But `other_costs` is the resolved total, which *includes* any existing `pct_of_profit` entries. The backend's `profit_base` deliberately excludes them (that is what keeps the commission non-circular).

Exact for the first profit-based entry. Understated once a second one exists — so the modal preview and the resulting ledger row disagree.

**Fix.** The backend already returns `profit_base` on every serialized `pct_of_profit` cost. Read it from `summary.costs` when present and fall back to the current computation only when there is no existing profit-based entry. Do not change the backend math.

---

## 3. Retainer semantics for straddling custom ranges — DECISION NEEDED, do not code yet

`_overlap_months()` counts calendar months *touched*. A custom Jul 15 – Aug 14 window charges a monthly retainer 2× despite spanning ~31 days.

This is defensible: the brief says charge full months and never prorate. But it is a business call, not a bug. **Wait for Steve's answer before changing anything.** Unit tests confirm the current behavior is intentional and internally consistent (8/8 cases in the review doc).

---

## 4. Optional cleanup

- `frontend/src/components/Layout.jsx` deleted an unrelated `showUserMenu` useState during Phase 2. Harmless and ESLint-clean, but out of scope. Revert or leave — your call.
- `create_cost` / `update_cost` return `resolved_amount: 0`, which the UI may momentarily render as $0 before the reload lands. Cosmetic.

---

## Not Codex work

- **`.claude/settings.json` hook fix** — Steve's, the classifier blocks agents from editing it. `"if": "Bash(git push*)"` is not honored on `agent`-type hooks, so hook 4 fires on every Bash call.
- **Runtime verification** (live RedTrack response shape, `unmapped_adsets` on real data, Joel's `/pnl` access, `/pnl/months` latency) — requires the deployed environment and real keys.

---

## Push protocol

Same as always: commit locally, hand back to Claude Code for the pre-push review and the final push. Item 1 touches `redtrack_service.py`, which is shared — flag it in the handoff.
