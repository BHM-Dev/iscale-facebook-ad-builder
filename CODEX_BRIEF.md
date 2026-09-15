# Naming templates for Campaign Name, Ad Set Name, and generated Ads

Item #1 of the post-research build order (`AdBuilder-CrossPlatform-Launch-UX-Synthesis.md`, recommendation
#2 — originally ranked #1 for smallest scope + highest daily-use impact). Solves Joel's actual daily pain:
hand-typing `[Date] - [Niche] - [Batch]`-style names for every campaign and ad set in the manual Facebook
Campaigns builder (`/facebook-campaigns`).

Matches AdStellar's own naming-template pattern (documented in `AdBuilder-AdStellar-Competitive-Research.md`
§4a): a saved named template containing `{token}` placeholders, with a live-resolved preview shown before
the resolved value is applied to the real name field. Campaign and Ad Set templates are user-managed;
generated Ad names use the same resolver with a safe default pattern.

No migration needed — templates persist to `localStorage`, matching the synthesis doc's explicit guidance
("this does not need a migration to deliver value").

## Investigated first, don't guess

- Campaign Name field: `frontend/src/components/CampaignStep.jsx` around line 304-313 — plain
  `<input value={campaignData.name} onChange={...} />`, no auto-generation today.
- Ad Set Name field: `frontend/src/components/AdSetStep.jsx` around line 544-555 — same pattern.
- Both components already call `useCampaign()` from `frontend/src/context/CampaignContext.jsx` and have
  `campaignData` in scope (confirmed: `AdSetStep.jsx` destructures `campaignData` at line 73). So both
  fields can access `campaignData.objective` without new prop plumbing.
- Neither component has brand/niche/product context available (this is the manual `/facebook-campaigns`
  builder, not the brand-based Image Ad/Ad Remix flow) — **don't invent a `{niche}` token that isn't backed
  by real data.** Niche-specific wording belongs in the saved template's own literal text (e.g. save a
  template named "Auto Insurance Launch" with pattern `"{date} - Auto Insurance - {objective}"` — the niche
  is baked into which template you pick, not a token).
- `CampaignStep.jsx`'s `CAMPAIGN_OBJECTIVES` array (top of file) already maps `OUTCOME_SALES` →
  `"Sales - Drive purchases and conversions"` — reuse it (split on `" - "`, take the first part) to turn the
  raw enum into a human-readable `{objective}` token instead of showing `OUTCOME_SALES` literally.

## 1. Shared utility — `frontend/src/lib/namingTemplates.js` (new file)

```js
// resolveNamingTemplate("{date} - {objective}", { date: "Sep 15", objective: "Sales" })
//   -> "Sep 15 - Sales"
// Unknown tokens are left as literal text (never throws, never silently drops content).
export function resolveNamingTemplate(pattern, tokens) { ... }

// localStorage-backed, keyed by `namingTemplates_${scope}` (scope: 'campaign' | 'adset').
// Each saved template: { id, label, pattern }.
export function getSavedTemplates(scope) { ... }
export function saveNamingTemplate(scope, label, pattern) { ... }
export function deleteNamingTemplate(scope, id) { ... }
```

The resolver is also used for generated Ad names in `BulkAdCreation.jsx`. The optional localStorage key
`adNamingPattern` can provide the pattern; when absent, the safe default is
`{media_name} - H{headline_num}B{body_num}`. Supported Ad-level Dynamic Tags are
`{campaign_name}`, `{ad_set_name}`, `{headline_num}`, `{body_num}`, `{media_name}`, and `{date}`.
Unknown tokens remain literal. Per-asset Placeholder Text tags such as `{offer}` and `{concept}` are
Phase 2 and are intentionally not supported here because they require a DriveAsset migration.

## 2. Shared component — `frontend/src/components/NamingTemplateField.jsx` (new file)

Wraps the existing name `<input>` — the input itself stays exactly as-is (still bound directly to
`campaignData.name` / `adsetData.name`, still fully manually editable, nothing about current behavior
changes). Adds a small toolbar directly below it:

- A "Templates" button/dropdown listing saved templates for this `scope` (label + resolved preview using
  current `tokens`). Clicking one calls `onChange(resolveNamingTemplate(template.pattern, tokens))` —
  applies the resolved string directly into the real name field immediately, no separate "preview then
  commit" step needed since the field is still just a normal editable input afterward (matches the
  synthesis doc's "live-resolved preview... before you commit" — the preview lives in the dropdown row
  itself, before the click). A trash icon per row calls `deleteNamingTemplate`.
- A "+ Save current name as template" row: doesn't try to auto-detect which parts of the current name
  should become tokens (too fragile) — instead opens a small inline form: a "Template name" text input, a
  "Pattern" text input pre-filled with the *current* resolved name as a starting point for the user to
  manually edit in `{token}` placeholders, a row of clickable token chips (from `tokenList`) that insert
  `{key}` at the end of the pattern input on click, a live resolved-preview line below it
  (`resolveNamingTemplate(patternDraft, tokens)`), and a Save button (`saveNamingTemplate`).

Props: `value`, `onChange`, `tokens` (object, e.g. `{ date: 'Sep 15', objective: 'Sales' }`), `tokenList`
(array of `{ key, label }` for the insertable chips, e.g. `[{key:'date', label:'Date'}, {key:'objective',
label:'Objective'}]`), `scope` (`'campaign'` | `'adset'`).

## 3. Wire into `CampaignStep.jsx`

Replace the plain `<input>` for Campaign Name (~line 307-313) with `<NamingTemplateField>`, keeping the
same `value`/`onChange` wiring to `campaignData.name` / `handleInputChange('name', ...)`. Tokens:

```js
const objectiveLabel = CAMPAIGN_OBJECTIVES.find(o => o.value === campaignData.objective)?.label.split(' - ')[0] || '';
const tokens = { date: new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' }), objective: objectiveLabel };
const tokenList = [{ key: 'date', label: 'Date' }, { key: 'objective', label: 'Objective' }];
```
`scope="campaign"`.

## 4. Wire into `AdSetStep.jsx`

Replace the plain `<input>` for Ad Set Name (~line 548-554) the same way. Tokens, using data already in
scope (`campaignData`, `adsetData.targeting`):

```js
const objectiveLabel = /* same lookup as above — either import CAMPAIGN_OBJECTIVES from CampaignStep.jsx or duplicate the small array; your call which is less awkward */;
const countries = (adsetData.targeting.geo_locations.countries || []).join('/') || 'US';
const ageRange = `${adsetData.targeting.ageMin}-${adsetData.targeting.ageMax}`;
const tokens = { date: ..., objective: objectiveLabel, countries, age_range: ageRange };
const tokenList = [
  { key: 'date', label: 'Date' }, { key: 'objective', label: 'Objective' },
  { key: 'countries', label: 'Countries' }, { key: 'age_range', label: 'Age Range' },
];
```
`scope="adset"`.

## Out of scope for this pass
- Ad-level naming (the per-combination `H{n}B{n}` pattern in `BulkAdCreation.jsx`) — that's already a
  reasonable auto-generated pattern for a different reason (disambiguating headline×body combinations, not
  a manual-typing pain point the same way). Revisit only if actually requested.
- No campaign-level "save entire structure as template" (AdStellar's higher-tier template type) — out of
  scope, just the two name fields.
- No backend/DB persistence — localStorage only, per the synthesis doc's explicit guidance.

## Push protocol
`CampaignStep.jsx` and `AdSetStep.jsx` are **not** among the four trigger files requiring the mandatory
2-agent pre-push review (`BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `facebookApi.js`,
`facebook_service.py`) — this only touches campaign/ad-set name fields, no Meta API payload shape changes,
no new endpoints, no migration. Per the repo's CLAUDE.md, Codex may commit locally; final push goes through
Claude Code, which will still scale a review to the size of the diff.
