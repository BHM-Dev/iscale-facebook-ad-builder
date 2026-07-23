# Codex Brief — User Management: assign ad accounts per user

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**File:** `frontend/src/pages/UserManagement.jsx` (+ its API calls). Frontend-only. NOT a trigger file. No backend/migration — the endpoints already exist and are live.
**Push:** Codex commits locally → Claude Code reviews + pushes.

## Why
Per-user ad-account scoping shipped (backend live). Admins currently can only set a user's accounts via the API. Add a UI so Steve can manage it in User Management.

## Backend endpoints (already deployed — just call them)
- `GET /api/v1/users/{user_id}/ad-accounts` → `{ ad_account_ids: ["act_..."], is_superuser: bool, unrestricted: bool }`
- `PUT /api/v1/users/{user_id}/ad-accounts` with body `{ "ad_account_ids": ["act_...", ...] }` → sets the allow-list. **Empty array = unrestricted (user sees all accounts).** Superuser-only (the page is already admin-gated).
- `GET /api/v1/facebook/accounts` → the account list to choose from. Note: for an admin (superuser) this returns ALL accounts (RHO 3 is already excluded server-side), so it's the correct pick-list.

## UI to build
On each user row in User Management, add an **"Ad Accounts"** action (button → modal, matching the existing roles/edit modal pattern in this file):
- On open: `GET /facebook/accounts` for the full list + `GET /users/{id}/ad-accounts` for the user's current selection.
- Render a checkbox list: account name + id, checked = assigned.
- **Helper text:** "No accounts selected = this user sees all accounts (unrestricted)." So an empty selection is a valid, meaningful state — don't force a minimum.
- If the user `is_superuser`: show a disabled note "Admins always see all accounts" and skip the editor (superusers are unrestricted regardless).
- Save → `PUT /users/{id}/ad-accounts` with the checked ids → `showSuccess`. Use `authFetch` + `useToast` (never fetch/alert).
- Reflect the count somewhere on the row (e.g. "3 accounts" or "All accounts" when unrestricted) so it's visible at a glance.

## Current live state (for context, don't hardcode)
Abel = 2 accounts, Joel = 3, everyone else unrestricted. The UI just needs to read/write; don't bake in specific users/accounts.

## Verify
`npm run build` passes; opening the modal loads current selection; saving persists (re-open shows the saved set); empty selection saves as unrestricted.
