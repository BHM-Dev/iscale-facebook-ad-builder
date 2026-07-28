# Codex Brief: Everflow (Switchboard) as P&L Revenue Source

**Status:** Investigated and validated against the live API 2026-07-28. Ready to build once the env var lands.
**Supersedes:** the "timezone residual" follow-up in `CODEX_REVIEW_pnl_phase2.md`. This solves it properly instead of working around it.

---

## Why this changes the design

The P&L currently reads revenue from RedTrack. RedTrack interprets a `YYYY-MM-DD` range in `REDTRACK_TIMEZONE` while Meta interprets it in the ad account's timezone (Pacific), so the two never quite agree on what "July" means. Best case we set both to Pacific by config and hope nobody changes it.

Everflow takes **`timezone_id` as a request parameter**. `timezone_id: 90` is Pacific. That makes the alignment structural rather than configuration luck — every call explicitly asks for the same clock Meta bills on.

And it turns out Switchboard's Everflow has better attribution than the RedTrack path: **ad-set-level Meta IDs**, plus ad-level underneath.

## What was verified live (30-day window, `timezone_id: 90`)

**Realm.** BHM is an **affiliate** in Switchboard's network. Use `POST /v1/affiliates/reporting/entity`. The `networks` and `advertisers` realms both return `403 {"Error":"Out of realm"}` for this key — do not use them.

**Offers — only 3, and the right one is there:**

| Offer | Revenue (30d) | Events | Clicks | RPC |
|---|---|---|---|---|
| **Get Business Coverage** | **$28,202.01** | 2,324 | 10,042 | $2.81 |
| Fast Business Quote | $0 | 0 | — | — |
| Fast Auto Quote.org | ~$19 | 7 | — | — |

**Join key — `sub3` is the ad set. NOT sub2.**

An earlier draft of this brief guessed sub2 from ID cardinality. That was wrong. Row-level conversion records (`/v1/affiliates/reporting/conversions` with `show_events: true`) carry the *names* alongside the IDs, which settles it:

| Sub | Distinct (7d) | Contents | Meaning |
|---|---|---|---|
| sub1 | many | `IwcGRvZgVmZGlkFlCvI-3gRDar…` | Meta click id (base64). Not useful. |
| **sub2** | 9 | `120247970572310048` | **campaign id** |
| **sub3** | 17 | `120249991472540048` | **ad set id ← JOIN ON THIS** |
| sub4 | 25 | `1 - The Storm Ad`, `2 - The Repair Bill Ad` | ad name |
| sub5 | many | `6a5f349e9a7ffc67ea8d17b1` | click id (24-char hex) |
| sub8 | 16 | `Autobody - Base`, `June 12 - SCALE`, `BATCH 2 (AS3)` | **ad set name** |
| sub9 | 9 | `DIN \| CBO \| LEADS \| AUTO \| OPEN TARGET \|07.22.2026` | **campaign name** |
| sub10 | 13 | `Facebook_Mobile_Reels`, `Facebook_Desktop_Feed` | placement |

The proof is the cardinality cross-tab:

- `sub2 ↔ sub9` is **strictly 1:1** (9 ↔ 9). sub9 is unmistakably a campaign name — it contains `CBO`, `LEADS`, `OPEN TARGET`. Therefore **sub2 is the campaign id.**
- `sub3 → sub8` is **1:1 for all 17** values, and sub8 values are ad set names in the `[Date] - [Niche] - [Batch]` convention `extract_niche()` already parses. Therefore **sub3 is the ad set id.**
- `sub9 → sub8` fans out 1→1..4, i.e. one campaign holds several ad sets. Consistent.

Ad-set-grain revenue coverage is the same 95.7% ($27,002.63 of $28,220.93 over 30 days) — the remaining 4.3% sits on non-Meta-shaped values and is unattributable.

**`sub8` is a free bonus: ad set names arrive with the revenue.** That means niche extraction works off the Everflow payload directly, without joining to `facebook_adsets` at all — useful for the Dashboard's Performance by Niche section and as a fallback when an ad set isn't in the local DB.

---

## Hard-won details — get these wrong and the numbers are silently wrong

1. **The money column on the affiliate realm is `revenue`, not `payout`.** `revenue` here is what BHM is *paid*. This is the opposite of the network-realm convention in the global CLAUDE.md ("buyer-side: CPC = payout ÷ unique_clicks") — that guidance applies to network-realm keys, not this one. Reading `payout` returns `None` and you will report $0 revenue.

2. **`cv` is always 0 — and `event` is three different things added together.** Confirmed by Steve: Switchboard broke this offer's payable actions into three events. Over the last 7 days:

   | Event | Count | Revenue | revenue_type |
   |---|---|---|---|
   | `Lead Rev` | 226 | $4,569.66 | CPS |
   | `Click` (the click/paywall) | 223 | $1,598.09 | CPS (1 × PRV) |
   | `Call` | 11 | $508.00 | CPS |
   | **total** | **460** | **$6,675.75** | — |

   That total reconciles exactly with the entity endpoint's summary (`event: 460`, `revenue: 6675.752`), so the two endpoints agree.

   **Revenue sums all three events.** That is the number the P&L shows.

   Do not compute a CPL from `event` — dividing by leads + paywall clicks + calls understates it roughly 2×. Per the scope guard, the P&L shows no CPL at all, so the safest handling is not to derive one here. Store the lead count if it's free to do so; don't surface it.

   The global CLAUDE.md note "the correct conversion field is `cv`, not `conversion`" does **not** hold here — `cv` is 0 and always will be on this offer.

2b. **Splitting the events requires the row-level endpoint.** The entity endpoint cannot break them out — `{"column":"event"}` is silently ignored (returns the same 3 offer rows), and `conversion_event` / `goal` are rejected as invalid columns. Use:

   `POST /v1/affiliates/reporting/conversions` with `{"from","to","timezone_id":90,"show_events":true,"query":{"filters":[]}}`

   Each record carries `event` (the name), `revenue`, `revenue_type`, `sale_amount`, and every sub. Aggregate client-side by `sub3` and by `event`. Note `revenue` ≠ `sale_amount`: a Lead Rev record shows `sale_amount: 25` with `revenue: 19.5` — BHM's cut. **Use `revenue`.**

   This endpoint is paged — honor the `paging` object rather than assuming one response holds the month.

3. **4.3% of revenue (~$1,218/30d) sits on non-Meta-shaped `sub2` values.** That is unattributable to an ad set. It must surface as an explicit "unattributed revenue" figure, not be silently dropped — otherwise account-level revenue won't reconcile with the sum of its ad sets.

4. **Always send `timezone_id: 90`** (Pacific) to match the Meta ad account. Do not omit it and do not let it drift; that is the entire point of the change.

5. `currency_id: "USD"`.

---

## Scope guard — read this before building anything

**This is a revenue-source swap. The P&L page does not change.**

Steve's call, 2026-07-28: the P&L stays simple — easy to follow, accurate, just enough to know whether the account is trending the right way. The five tiles already built are the whole thing:

> Ad Spend · Revenue · Other Costs · Net Profit · Margin, plus the month-over-month table.

**Do NOT add**, despite the detail in this brief:

- A lead / paywall / call breakdown on the page. It's needed to compute revenue correctly; it is not a display element.
- A RedTrack-vs-Everflow comparison column. The P&L carries **one** revenue number or net profit becomes ambiguous.
- Meta's deduped conversion count.
- Any CPL. Two sources with different denominators (deduped people vs payable events) produce two defensible CPLs, and putting them near each other actively misleads. CPL belongs on Campaign Performance, where it already is.

The event-level detail below exists so the revenue figure is right. It stays in the service layer.

### Provider abstraction, not a swap

Do not delete the RedTrack path. Add a revenue provider layer so the source is selectable per ad account:

- `backend/app/services/everflow_service.py` — new. `get_revenue_by_adset(date_from, date_to, timezone_id=90) -> {sub2: {"revenue": Decimal, "events": int, "clicks": int}}`, plus an `unattributed_revenue` total for the non-Meta-shaped remainder.
- Follow the shape of `_live_redtrack_report` in `pnl.py`: it must **raise** on failure, never return `{}` — the P&L distinguishes "no revenue" from "source down" and reports `data_incomplete`. See `CODEX_REVIEW_pnl_phase2.md` B2 for why this matters.
- In `pnl.py`, `_redtrack_revenue()` becomes `_revenue_for_account()` dispatching on the account's configured provider. Extend `revenue_source` to include `everflow_live` / `everflow_cache_fallback`.
- Commercial Insurance (Get Business Coverage) points at Everflow. Everything else stays on RedTrack until validated.

### Where the provider setting lives

Add a nullable `revenue_provider` column (`redtrack` | `everflow`) keyed by ad account. Cleanest home is a small `pnl_account_settings` table — that also gives the eventual spend-override and revenue-true-up fields (open questions 2 and 3 in `CODEX_BRIEF_pnl_tracker.md`) somewhere to live. **Migration + models.py = Claude Code. Do not create it yourself.**

### Env var — blocks the build

`SWITCHBOARD_EVERFLOW_API_KEY`. Golden must add it to the VPS and run `docker compose restart backend`. DM `D075KSE1A1L`. This is the only reason to message him.

---

## Verified — no longer open

The join key was confirmed from Everflow's own row-level data (names next to ids, plus the cardinality cross-tab above). **`sub3` = ad set id.** No DB join was needed.

Worth one sanity check once the env var is in: confirm the sub3 values overlap `facebook_adsets.fb_adset_id` for the Commercial Insurance account. Expect near-total overlap. If it comes back empty, the ad sets simply aren't synced locally yet — fall back to `sub8` (the ad set name) rather than assuming the mapping is broken.

**Landing pages are also available** via `{"column":"offer_url"}` on the entity endpoint, which maps to niche cleanly (30 days): `religious-organization-insurance` $12,545 / 1,139 events · `General business V2` $9,602 / 782 · `commercial-auto-v2` $6,118 / 404. `Call Single step`, `Call Multi Step`, `Commercial Trucking Page`, and `Commercial Auto` were all $0 in that window — worth Joel knowing, but out of scope here.

---

## Not in scope

- Ad-level P&L. sub3 makes it possible later; don't build it now.
- Replacing RedTrack anywhere else. This is Commercial Insurance only until a full month reconciles.
- Backfilling history.

## CLAUDE.md update

Once this ships, add a short "Everflow — Switchboard (affiliate realm)" block to the project CLAUDE.md recording items 1–4 above. They contradict the existing global Everflow notes for network-realm keys, and that contradiction will burn someone.
