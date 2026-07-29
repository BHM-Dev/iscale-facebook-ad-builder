# Codex Review Request: P&L Everflow provider

Four unpushed commits on `develop`. Review them, fix what's listed, hand back for push.

```
1f4eb4c  Fix Everflow revenue: account scoping and unpageable conversions endpoint   (Claude)
2a233cf  Drop BreadWinner branding; tighten P&L page header                          (Claude)
892017a  Use Switchboard revenue for PnL provider                                    (you)
5d7c0d4  Document timezone residual; track P&L follow-up brief                       (Claude)
```

Ground truth for the Everflow API is in `CODEX_BRIEF_pnl_everflow_revenue.md`. Everything in there was verified against the live API — treat it as authoritative, don't re-derive it.

---

## What I changed in `1f4eb4c`, and why

**1. Account scoping (was blocking).** `_everflow_revenue` in `pnl.py` built the account's ad-set id set and then did `filtered = by_adset` — summing revenue for *every* ad set Everflow returned, using the set only for the unmapped count. The Everflow key is not account-scoped. With one account in the allow-list the total was right by luck; with two, both accounts report the identical figure. Now filtered to the account's ad sets, mirroring `_redtrack_revenue`.

**2. The conversions endpoint cannot be paged (was silently inflating revenue ~2.5×).** Verified live: `page` / `page_size` in the body are ignored in both flat and nested form — every request returns page 1 — while a response hard-caps at 2000 rows and reports the real size in `paging.total_count`. `_has_next_page` read `total_count` and kept looping, so `page_size=1000` against `total_count=2334` ran three times and accumulated **6000 rows for 2334 real conversions**.

Replaced the paging loop with date-windowing in `everflow_service.py`:
- 7-day initial windows (`INITIAL_WINDOW_DAYS`)
- any window where `total_count > len(rows)` splits in half and retries
- a single day still over the 2000 cap raises, so the P&L reports `data_incomplete` rather than a quietly short number
- `conversion_id` dedupe as a backstop
- `_has_next_page` deleted

Tested against a stub mimicking the cap — 30d/2340 rows → 2340 unique in 5 calls, a 1900-row day splits cleanly, a 2500-row day raises, single-day/empty/reversed ranges handled.

**3. `_rows_from_response` returned `[]`** for an unrecognised envelope, which is indistinguishable from "no conversions" and would report $0 as fact. Raises now.

**4. Semantics change you should sanity-check.** Per-account revenue no longer includes `unattributed_revenue` (~4.3%, roughly $1,218/30d — revenue on sub3 values that aren't Meta ids, plus ad sets outside this account). It isn't assignable to an account, so including it inflates whichever account is on screen. It's returned separately in the summary payload.

---

## Fix these

**A. `/pnl/months` almost certainly makes ~30 Everflow HTTP calls per request.** `_summary` calls `_revenue_for_account` per month, and each Everflow call now fans out into ~5 windowed requests. Six months → ~30 sequential HTTP round trips, on top of the Meta spend calls. Verify, then fix: fetch the full `[earliest month start, latest month end]` range **once**, bucket the conversion rows by month client-side, and pass the result down — the same shape as the `spend_cache` parameter `_summary` already accepts. This is the same class of bug as the Meta `_spend_map` fan-out fixed earlier in `CODEX_REVIEW_pnl_phase2.md` B3.

**B. Is `unattributed_revenue` actually shown anywhere?** It's in the summary payload. If nothing renders it, the ~4.3% silently vanishes from the user's view, which defeats the point of separating it. Add one small line under the Billable Revenue tile or in the amber banner area — read the scope guard in `CODEX_BRIEF_pnl_everflow_revenue.md` first, keep it to one line, do not add a tile or a column.

**C. Does the UI handle `revenue_source: "everflow_unavailable"`?** Check `revenueSourceLabel` / `isRevenueFallback` in `Pnl.jsx` and `pnlRevenueSourceLabel` in `Dashboard.jsx` render something sane for it rather than a raw enum string.

**D. Confirm nothing still references `_has_next_page`.** I deleted it.

**E. `event_breakdown` is computed per ad set in `everflow_service.py` and, as far as I can tell, never consumed.** Either wire it to something or leave it with a comment saying it's reserved — right now it reads like an oversight.

---

## Verify, don't change

- `sub3` = ad set id, `sub8` = ad set name, `revenue` (not `payout`), `timezone_id: 90` on every call, affiliate realm only. Confirm the code matches; do not "fix" it toward sub2.
- `_everflow_account_ids()` must stay fail-safe: env var unset or malformed → every account falls back to RedTrack.
- Decimal throughout the money path; `float()` only at serialisation.
- The scope guard: **the P&L page gains no new tiles, columns, or CPLs.** Steve's call. Spend · Billable Revenue · Other Costs · Net Profit · Margin, plus the month-over-month table. That's it.

---

## Open decision — don't act, just flag your view

`892017a` selects the provider from `SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS`, an env-var allow-list, instead of the per-account DB column in the original brief. It avoids a migration and fails safe, but changing which accounts use Everflow needs Golden plus a container restart rather than a UI toggle. Steve hasn't decided. Note your recommendation; don't build either way.

---

## Constraints

- Do **not** push. Hand back to Claude Code.
- Do not touch `models.py`, `backend/alembic/versions/`, `main.py`, or the four trigger files.
- No migration in this change set. If your answer to the open decision requires one, say so and stop.
- Two env vars are still missing on the VPS (`SWITCHBOARD_EVERFLOW_API_KEY`, `SWITCHBOARD_EVERFLOW_AD_ACCOUNT_IDS`), so the Everflow path is dormant in production. You cannot end-to-end test it; reason from the code.
