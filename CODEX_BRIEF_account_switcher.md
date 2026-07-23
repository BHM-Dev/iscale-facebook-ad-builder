# Codex Brief — Global Ad Account Switcher

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**Type:** Frontend-only. No backend/migration — `/facebook/accounts` already exists and is per-user scoped. NOT a trigger file.
**Push:** Codex commits locally → Claude Code reviews + pushes + validates in Chrome.

## Goal
Give media buyers a Meta-Ads-Manager-style **account switcher**: a named dropdown in the app header that sets one app-wide "active account." Campaign Performance and the Dashboard scope to it. Replaces the current raw-ID text box.

## Current state (what you're replacing)
- Both `CampaignPerformance.jsx` and `Dashboard.jsx` read the active account from `localStorage['fb_ad_account_id']`, falling back to `GET /facebook/config` (`{ ad_account_id }`) for the default. This localStorage key is the de-facto app-wide active account — keep using it.
- `CampaignPerformance.jsx` has a free-text **"Ad Account ID"** `<input>` (~line 1608) that sets `adAccountId` state. **Remove this input** — the header switcher replaces it.
- `GET /facebook/accounts` returns `[{ id: "act_...", name, account_status, ... }]`, already filtered to the user's allowed accounts (Abel = 2, Joel = 3, admins = all). This is the switcher's option source.

## Build

**1. Active-account state in a shared context.** An app-wide provider already wraps everything (`CampaignProvider` / `BrandProvider` in `App.jsx`) — add `activeAccountId` + `setActiveAccountId` to the most fitting existing one (prefer `CampaignContext`; don't add a new provider). 
- Initialize: `localStorage['fb_ad_account_id']` → else first account from `/facebook/accounts` → else `/facebook/config` default.
- On change: update state + persist to `localStorage['fb_ad_account_id']` (same key the pages already read, so nothing else breaks).

**2. Header switcher (in `Layout.jsx`).** Place it in the top area (it can sit alongside/above the existing "Vertical filter" bar, but the account switcher is the PRIMARY control — give it visual priority). 
- Fetch `GET /facebook/accounts` once; render a dropdown of account **names** (fallback to id if no name), current = `activeAccountId`.
- On select → `setActiveAccountId(id)`.
- If the user has exactly **1** account: render it as a static label (or disabled dropdown) — no need to choose. If **0**: hide gracefully.
- Show it on every page (it's global), or at minimum on Campaign Performance + Dashboard + the creative pages. Global (in Layout) is preferred.

**3. Wire the pages to the context.**
- `CampaignPerformance.jsx`: read `activeAccountId` from context instead of its local mount-time resolution; **re-fetch** insights/adsets when it changes (add it to the relevant effect deps). Remove the raw-ID input.
- `Dashboard.jsx`: read `activeAccountId` from context; re-fetch niche-summary/insights when it changes.
- Both currently persist/read `fb_ad_account_id` themselves — route that through the context so there's one source of truth.

## Coherence
Keep the existing **vertical filter** (brand scoping in creative flows) — it's a different axis. The account switcher scopes Meta-account *data* (Campaign Performance/Dashboard); the vertical filter scopes *brands* in generation. Make them read as one system: account switcher primary/prominent, vertical filter secondary. Don't build two competing account controls.

## Patterns (mandatory)
`authFetch` from `lib/facebookApi` (never raw fetch). `useToast` for errors (never alert). Match existing Tailwind/dropdown styling.

## Verify before handing back
- `npm run build` passes.
- Switching the account in the header re-loads Campaign Performance AND Dashboard data for that account.
- Selection persists across page navigation and refresh.
- The old raw-ID input is gone.
- A single-account user (mimic by expecting `/accounts` to return 1) shows a static label, not an empty dropdown.

## Claude Code will
Review, push, then validate in the deployed app via Chrome (switch accounts, confirm Campaign Performance + Dashboard rescope, confirm Abel sees 2 / Joel sees 3).
