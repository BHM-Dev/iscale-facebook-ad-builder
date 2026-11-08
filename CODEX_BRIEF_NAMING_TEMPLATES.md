# Codex brief: Naming templates, Phase 1 (frontend)

**Spec:** `docs/briefs/AdBuilder-Naming-Templates-Brief.md`. §3 and §4 are the contract.
**Visual reference:** `docs/briefs/AdBuilder-Naming-Templates-Prototype.html`. Its resolver and filename logic are a working reference.
**Primary user:** Abel. He builds every campaign and ad set; Joel supplies the creatives through Drive. One shared convention per ad account.

## Preflight

```bash
git pull origin develop
```

## Backend: already built by Claude Code. Do not modify.

- `GET /api/v1/naming-presets/{ad_account_id}` returns:
  ```
  {brand_code, tracking_tag, uppercase, templates:{campaign,adset,ad}, waves:[{wave,code,seen?}], niche_codes:[{niche,code,seen?}], objective_tags:{}, updated_by, updated_at, saved}
  ```
  It returns defaults with `saved:false` when nothing has been saved yet.
- `PUT /api/v1/naming-presets/{ad_account_id}` takes the same body minus the read-only fields. Last write wins.
- `GET /api/v1/naming-presets/{ad_account_id}/observed-codes` returns `{niche_codes:[{niche,code,seen}], waves:[{wave,code,seen}]}`. It is parsed from existing ad-set names like `WW8-FUN | FLEET AND CREW`.

## Files

| File | Change |
|---|---|
| `frontend/src/lib/namingTemplates.js` | Extend `resolveNamingTemplate` with the brief §3.1 tokens. Add `parseName(name, template)` and `conceptFromFilename(name)`. Keep the existing exports working. |
| `frontend/src/lib/namingTemplates.test.js` (new) | See tests below. |
| `frontend/src/lib/useNamingPreset.js` (new) | Hook: load a preset per account, save, merge observed codes, and migrate localStorage once. |
| `frontend/src/components/NamingSettingsDrawer.jsx` (new) | See the drawer section below. |
| `frontend/src/components/NamingTemplateField.jsx` | Saved templates come from the preset, not localStorage. Add a "Naming" link that opens the drawer. Add the ✓ / custom / "fill X" badge. |
| `CampaignStep.jsx` and `AdSetStep.jsx` | Wave and niche pickers (campaign) and an angle input (ad set) above the name. The default name comes from the preset template. |
| `BulkAdCreation.jsx` (**trigger file**) | Ad names use the preset `ad` template, with `{seq}` per ad set and `{concept}` from the Drive filename. `buildPerMediaAdsetName` uses the `adset` template, with `{angle}` set to the concept. See BulkAdCreation rules below. |
| `BatchPushModal.jsx` and `PushToMetaModal.jsx` | The new ad-set name default comes from the `adset` template, replacing `{today} - {niche} - Testing`. Ad names come from the `ad` template and are **never** the headline. |
| `backend/app/api/v1/daily_close.py` (allowlist line only) | Add `naming_preset_saved`, `naming_name_overridden` and `naming_launch`, or use an existing generic event path if there is one. |

**Tests in `namingTemplates.test.js`:**

- The resolver produces these exact real names:
  - `RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | CAPI | 11.09.2026`
  - `WW8-FUN | FLEET AND CREW`
  - `WW8-FUN-02-HearseAndStaff-IMG-1x1`
- An empty token drops its separator, so the output never contains `| |`, `--`, or a trailing `-`.
- With uppercase on, `{brand_code}` keeps its case.
- `conceptFromFilename('WW8-FUN-02-HearseAndStaff-IMG-1x1.jpg') === 'HearseAndStaff'`, and `'NewHearse_v2.png' → 'NewHearse'`.
- `parseName` round-trips each real name, and returns `null` for `Tow Owners Broad`.

**`useNamingPreset.js`:**

- On the first load for an account with `saved:false`, prefill `niche_codes` and `waves` from observed codes in memory. **Do not auto-save.** The user saves.
- Migrate localStorage `namingTemplates_*` once, into the drawer as suggestions. Delete the keys only after a successful PUT.

**`NamingSettingsDrawer.jsx`:** right drawer with a backdrop. It contains:

- brand code and tracking tag
- the 3 templates, with token chips
- the waves table and the niche-code table
- a "seen in N ad sets" source line on each code row
- Save, which calls PUT and shows a toast

Changes that aren't saved show a dot on the Save button.

**`BulkAdCreation.jsx` rules:**

- Append `-H{n}B{n}` **only** when one creative has more than one copy variant.
- Duplicate names within an ad set get `-b`, `-c` and so on.
- Keep `nameManuallyEdited` behavior exactly: never overwrite a hand-edited name.

## Hard rules

- No change to Meta create calls other than the `name` string values they already send.
- Never block a launch on the convention check. It is a badge only.
- Do not seed or auto-save presets. Observed codes are suggestions until a person clicks Save.
- `authFetch` only, toasts only, and no `alert()` or `confirm()`.
- Trigger files are touched, so finish with: "Edits done — ready for Claude Code 2-agent review + push." Do not push.
- Run `npm run build` and `npx vitest run`.

## Done means

Abel can walk through a whole launch without typing a name:

1. Set the account preset once.
2. Pick wave, niche and angle.
3. Pick 5 Drive creatives.

The result is 1 campaign, 1 ad set and 5 ads, all named in his convention with a ✓, and every name still editable.

List anything you couldn't wire, with file:line.
