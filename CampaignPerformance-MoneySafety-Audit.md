# Campaign Performance — Money-Safety Audit (2026-10-06, HEAD `5651fcb`)

Method: three read-only agents (frontend code trace, backend/Meta API correctness, Joel/media-buyer view). Code reading only — **nothing live-verified**, no Meta calls made. Items marked *unverified* need a throwaway-campaign check before acting on them.

Files: `frontend/src/pages/CampaignPerformance.jsx` (3356 lines), `backend/app/api/v1/{facebook,auto_pause}.py`, `backend/app/services/facebook_service.py`.

## Fix first (can lose money or silently disarm protection)

| # | Finding | Where | Scenario |
|---|---|---|---|
| 1 | **Ad-set "Pause" button sends ACTIVE for any status other than ACTIVE/PAUSED, with no confirm.** `newStatus = current === 'ACTIVE' ? 'PAUSED' : 'ACTIVE'`; label keys off `effectiveStatus === 'PAUSED'`. Sync imports ARCHIVED ad sets. | `CampaignPerformance.jsx` ~3181-3203, ~1881-1883 | Joel clicks "Pause" on an archived/empty-status ad set → PATCH ACTIVE → it restarts; toast says "resumed". |
| 2 | **Budget confirm shows a stale "from $X" while claiming "live".** `/facebook/sync` never updates `daily_budget`/`lifetime_budget` on existing ad sets (only name/status). Backend writes an absolute value without re-reading live. | JSX ~2140-2153, ~3099-3133, ~3331; `facebook.py` 422-430, 567-591 | Real budget $400 (changed in Ads Manager), app holds $100; Joel types 150 → dialog says "$100 → $150"; reality is a 62% cut. Also decides CBO "--" vs editor from the same stale cache. |
| 3 | **No sanity guard on manual budget edits.** Only `ge=100` cents server-side; client only `>= 1`. No ratio warning, no cap; Enter-Enter submits; `type=number` scroll changes value. | `facebook.py:161-166`; JSX 2142, 2183 | $50 → $500 typo: same neutral confirm as $50 → $55. |
| 4 | **Auto-pause rule modal can create a pause-everything (or never-fires) rule.** Metric change doesn't reset threshold; clearing threshold/min-spend → `0`; backend `RuleCreate` has no lower bounds; no confirm; ad set select silently defaults to `adsets[0]`. ROAS "<" keeps default 50. | JSX 1259-1346; `auto_pause.py:95-110, 256-295` | ROAS `< 50x` pauses every ad set at next 30-min check; CPL→CTR keeps "> 50%" and never fires while Joel thinks he's protected. |
| 5 | **`DELETE /facebook/adsets/saved/{id}` has no auth/account scoping, cascades to ads + auto-pause rules; `/sync/cleanup` is also unscoped.** Local-only (Meta ad set keeps spending). | `facebook.py:639-651, 654`; `models.py:249` | Any logged-in user deletes any account's saved ad set; its protective rules vanish; next sync re-imports it with no rules/brand. UI copy is honest, backend is not. |

## High / Medium

- **Resume has no confirm and ignores parent state** (`campaign_status` is available but unused). Resuming under a paused campaign toasts "resumed" while nothing delivers. (JSX 1211-1215, 3181-3190, 2276)
- **Ad rows always render ACTIVE** (`ad.status || 'ACTIVE'`; `ads-bulk` rows have no status) → paused ads show "Pause", can't be resumed; pause confirm claims "stops delivery" for an already-stopped ad. (JSX ~1003, 1077)
- **Status overrides never invalidated** by sync/`loadAdsets` → row can say PAUSED after Joel resumed in Ads Manager and synced. (JSX 1882, 1895, 2064-2120)
- **Status writes use `get_current_active_user`, budget writes use `campaigns:write`** → anyone can resume spend. (`facebook.py:1148-1197`)
- **Budget route is blind to budget type / CBO parent.** Sends `daily_budget` without reading ad set type or parent CBO; lifetime-budget ad sets show "Set budget" and the edit sends `daily_budget` → Meta rejects, raw error. (`facebook.py:579, 609`; JSX 3133)
- **CBO→ABO switch likely fails; if it ever "succeeds" the local mirror lies.** Sends `campaign_budget_optimization: False`, then writes `daily_budget=None` locally. Confirm copy ("Review every ad set budget before delivery continues") is misleading — delivery continues immediately on existing ad set budgets. *unverified: needs throwaway campaign.* (`facebook.py:610-623`)
- **Meta errors flatten to 500/400 with raw SDK text; rate limits never 429.** Status writes drop the error code and `error_user_msg`; rate-limit set has only 80004 (not 80000-80014). `_meta_error` exists but these four writes don't use it. (`facebook.py:588-591, 633-636, 1168-1197`; `facebook_service.py:2420, 2594, 743`)
- **Ambiguous timeouts:** 15s client abort on ad-set status writes; backend may still apply → UI says "try again" with stale state, next click can flip the wrong way. Ad pause has no timeout. (JSX 1788-1793, 1890, 1007)
- **Budget saves can overlap** (confirm closes before request awaited; no in-flight guard). (JSX 2155-2177, 2224-2230)
- **Auto-pause enforcement:** failing pauses retry every 30 min forever (only bid/budget branch disables on permanent errors); uses `last_7d` aggregates with no `effective_status` check; skips on stale local `PAUSED`; a manual Resume here leaves the (already self-disabled) rule unarmed with no message. (`auto_pause.py:965-1083, 1163`)
- **No "last synced" indicator anywhere**; status/budget are local-DB, spend/CPL/ROAS are live — a row can mix a live $400 spend with a stale "$50/day". (Joel P1)

## Low
Rounded budget prefill ($25.50 → $26, Enter submits $26); dialogs lack Escape/focus trap; AddRule 422 toast shows "[object Object]" and decimal ROAS thresholds 422 (`threshold: int`); brand cache never clears; ad-set delete X is hover-only next to Pause and "re-sync brings it back"; no undo; no bulk select (also means no bulk fat-finger risk today).

## Verified OK
Cents↔dollars conversion correct end to end; local-vs-fb id keying consistent; no optimistic UI on budget/delete/brand; Meta-first-then-local write order; ad/ad-set scoped rules keyed correctly; sync partial/RedTrack failures are surfaced; confirms default to non-destructive.

## Suggested fix order (proposal, not started)
1. **Ad-set status button** (#1): only ACTIVE/PAUSED actionable; disable otherwise; Resume gets a confirm and shows parent-paused caveat. Small, frontend.
2. **Budget safety** (#2, #3): fetch live object (`GET /facebook/adsets/{id}`, `/campaigns/{id}` already exist) before opening the dialog; show live "from"; ratio banner + typed confirm above ~3x; server re-reads live and rejects >3x / <0.2x without a `confirm` flag; hard ceiling; sync refreshes budget fields.
3. **Rule modal** (#4): per-metric defaults, sanity warnings, positive-threshold validation client + server, confirm step naming the target ad set/action.
4. **DELETE + status route authz** (#5, permissions): `_assert_adset_allowed` + `campaigns:write`.
5. **Error mapping** via `_meta_error`; 429 for 4/17/32/613/80000-80014.
6. **Last-synced badge**, clear overrides on sync.
7. Live throwaway-campaign check for CBO→ABO and lifetime-budget behavior before touching that path.

Tool routing: items 2 (backend), 4, 5 touch Meta/API → Claude Code with 2-agent review; 1, 3 (frontend) and 6 could go to Codex. `facebook_service.py` is a trigger file.
