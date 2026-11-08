# Naming Templates — Brief

**Date:** 2026-11-07 · **Owner:** Steve · **Builder:** Codex (UI), Claude Code (migration, trigger-file review, push)
**Prototype:** `docs/briefs/AdBuilder-Naming-Templates-Prototype.html` (open in a browser; uses real name examples)

---

## 1. Executive summary

**This is not a from-scratch build.** Naming templates already exist:

- `lib/namingTemplates.js` and `NamingTemplateField.jsx`
- used in CampaignStep, AdSetStep, and BulkAdCreation's "Ad Naming Pattern"

They don't help Joel, for three reasons.

**1. The tokens don't match how he names things.** Here is his real convention, pulled from the RHO Commercial DB on 2026-11-07:

| Level | Real example | Structure |
|---|---|---|
| Campaign | `RHO v1 \| ABO \| VEHICLE W2 FUNERAL HOMES \| CAPI \| 10.19.2026` | brand+version · budget type · [LEADS] · wave + niche · tracking · MM.DD.YYYY |
| Ad set | `WW8-FUN \| FLEET AND CREW` · `BW1-BAKE \| BAKERIES` | wave-nichecode · angle |
| Ad | `WW8-FUN-02-HearseAndStaff-IMG-1x1.jpg` | wave-nichecode-seq-concept-media-ratio (today this is just the Drive filename, `.jpg` included) |

The tokens on offer today are `{date}` ("Mon D"), `{objective}`, `{countries}`, `{age_range}`, `{media_name}` and `H{n}B{n}`. None of them produces any part of his convention, so he hand-types every campaign and ad set name.

**2. Templates live in localStorage, per browser.** Abel can't use Joel's templates, and a new laptop starts empty.

**3. Two of the five launch paths ignore templates.**
- `BatchPushModal` and `PushToMetaModal` default ad sets to `{today} - {niche} - Testing`.
- They name ads after the **headline**.

Those names break the convention and the niche parsing that Max CPL and the dashboards rely on.

**Fix:** server-side presets shared per ad account, with tokens that produce Joel's real names. Every launch path uses them, and every launch shows a preview with a convention check.

**Economics.** Joel launches waves of roughly 12 ad sets at a time (`WW8-*` is 12 ad sets and about 60 ads).

- Campaign and ad-set names: today he types each one; afterwards he picks a wave code and niche and the names fill in.
- Ad names: these come out right today only if he renames every Drive file correctly. Afterwards they're generated.

The second-order win is cleaner data. Template-built names parse back into fields exactly. Today, `niche_extraction` reads `VEHICLE W2 FUNERAL HOMES` as the niche, with the wave fused into it. That fragments niche-level Max CPL and Compass grouping across waves. See §8, Q2.

**Not in scope:** renaming anything already in Meta, and forcing names. The convention check warns; it never blocks.

---

## 2. Flow

```
Account settings (once)                     Every launch
┌──────────────────────────┐   ┌──────────────────────────────────────────────┐
│ Brand code   RHO v1      │   │ Campaign: [wave W2 ▾] [niche Funeral Homes ▾] │
│ Tracking tag CAPI        │──▶│   → RHO v1 | ABO | VEHICLE W2 FUNERAL HOMES | │
│ Niche codes  FUN, LOCK…  │   │     CAPI | 11.09.2026            ✓ matches    │
│ Templates (3 levels)     │   │ Ad set: angle [Fleet and crew]                │
└──────────────────────────┘   │   → WW8-FUN | FLEET AND CREW     ✓            │
                               │ Ads (5 creatives): concept from filename      │
                               │   → WW8-FUN-01-FleetMargin-IMG-1x1  ✓ (×5)    │
                               │ Any name stays editable; edits are kept       │
                               └──────────────────────────────────────────────┘
```

---

## 3. Spec (Phase 1, ready for review)

### 3.1 Tokens

New tokens are added to `resolveNamingTemplate`. The existing tokens stay.

| Token | Source | Example |
|---|---|---|
| `{brand_code}` | account preset | `RHO v1` |
| `{budget_type}` | campaign budget mode (CBO when a campaign budget is set, else ABO) | `ABO` |
| `{objective_tag}` | preset map from objective; blank for most | `LEADS` |
| `{wave}` | launch input, remembered per account (last used) | `VEHICLE W2` / `WW8` |
| `{wave_code}` | short form of wave, from the preset's wave list | `WW8` |
| `{niche}` | launch input: the niche picker (niche list from existing ad-set data) | `FUNERAL HOMES` |
| `{niche_code}` | niche-code dictionary in the preset; auto-suggested as the first 3–5 letters, editable | `FUN` |
| `{angle}` | launch input (ad-set level) | `FLEET AND CREW` |
| `{tracking}` | account preset | `CAPI` |
| `{date:FMT}` | launch date; `FMT` ∈ `MM.DD.YYYY`, `MM.DD`, `Mon D`; bare `{date}` stays "Mon D" for back-compat | `11.09.2026` |
| `{seq:NN}` | 1-based position of the creative within the ad set, zero-padded | `02` |
| `{concept}` | creative name with the extension and any leading `wave-code-seq-` stripped (from the Drive filename or upload name) | `HearseAndStaff` |
| `{media}` | `IMG` / `VID` from the creative type | `IMG` |
| `{ratio}` | aspect bucket of the creative: `1x1`, `4x5`, `9x16` | `1x1` |

**Case rule:** campaign and ad-set names are uppercased except `{brand_code}` (matching `RHO v1`). Ad names keep `{concept}` case. This is a preset flag (`uppercase: true`), not hard-coded.

**Empty tokens:** a token that resolves empty takes its separator with it, so you never get `| |`. Unknown tokens stay visible as `{token}`, as today, so the mistake is obvious.

### 3.2 Default templates (seeded per account on first open, editable)

These are seeded as template *strings* only. No business data is created.

```
campaign: {brand_code} | {budget_type} | {objective_tag} | {wave} {niche} | {tracking} | {date:MM.DD.YYYY}
adset:    {wave_code}-{niche_code} | {angle}
ad:       {wave_code}-{niche_code}-{seq:02}-{concept}-{media}-{ratio}
```

### 3.3 Account naming settings

Open them from a "Naming" link next to every name field, as a drawer. They are stored server-side per `ad_account_id`, and Joel and Abel share them.

- **Brand code** and **tracking tag**: text fields.
- **Wave list:** rows of `wave` → `wave_code`, plus "last used". Example: `VEHICLE W2 → VW`, `BREADTH W1 → BW1`, `WAVE 8 → WW8`.
- **Niche-code dictionary:** rows of `niche` → `code`.
  - Prefill it from codes already used in this account's ad-set names (the `XX-CODE |` prefix), so Joel starts with his real codes, not guesses.
  - Show each row's source: "seen in 12 ad sets" or "added by Joel 11/09".
- **Templates:** the three levels, using the existing `NamingTemplateField` (token chips plus live preview). Saved templates move from localStorage to the server.
  - On first load, migrate any `namingTemplates_*` localStorage entries into the account's presets, then clear them.

### 3.4 Launch paths (all five)

| Path | Today | Phase 1 |
|---|---|---|
| CampaignStep | free text, tokens date/objective | default = account campaign template; wave and niche inputs above the name |
| AdSetStep | free text | default = adset template; angle input |
| BulkAdCreation ad names | `{media_name} - H{n}B{n}` (localStorage) or raw filename | default = account ad template; `{seq}` per ad set; the H/B suffix is auto-appended **only** when one creative has more than one copy variant (otherwise names collide) |
| BulkAdCreation per-media ad sets (`buildPerMediaAdsetName`) | `{base} - {category} \| {creative} ({n})` | adset template, with `{angle}` = creative concept |
| BatchPushModal / PushToMetaModal | `{today} - {niche} - Testing`; ad = headline | adset and ad templates; ad never named after the headline |

**Rules:**

- **Manual edits win.** Keep the existing `nameManuallyEdited` behavior. Changing an input re-resolves only names that haven't been hand-edited.
- **Uniqueness:** if two ads in one ad set resolve to the same name, append `-b`, `-c` and so on, and show it in the preview.
- **Convention check:** a green ✓ when the name parses back with the account's template, a grey "custom" when it doesn't. It never blocks a launch.

### 3.5 Parse-back (frontend only in Phase 1)

`parseName(name, template)` returns `{wave, wave_code, niche, niche_code, angle, seq, concept, …}` or `null`. It drives the ✓/custom check. Unit-test it against the real names in §1. The backend parser is Phase 2 (§7).

---

## 4. Decision logic

| Situation | Name shown |
|---|---|
| All tokens resolve | template output, ✓ |
| A launch input is missing (no niche picked) | `{niche}` left visible, amber "fill niche"; launch still allowed |
| Niche has no code yet | suggested code shown dimmed with "save code?"; saving adds it to the dictionary |
| User typed over the name | kept as typed; "custom" badge; never overwritten |
| Duplicate ad name in one ad set | suffix `-b`/`-c`, flagged in preview |
| No preset saved for the account yet | seeded defaults (§3.2), with "set brand code" prompt |

---

## 5. Integration

**New table `naming_presets`.** This needs a migration, which Claude Code handles: `has_table` guard, single head.

| Column | Notes |
|---|---|
| `id` | |
| `ad_account_id` (unique) | |
| `brand_code` | |
| `tracking_tag` | |
| `uppercase` | |
| `templates` JSON | `{campaign, adset, ad}` |
| `waves` JSON | |
| `niche_codes` JSON | |
| `objective_tags` JSON | |
| `variant` | reserved |
| `soft_tags` JSON | reserved |
| `updated_by` | |
| `updated_at` | |

**Endpoints:**

- `GET /naming-presets/{ad_account_id}`. Returns the seeded defaults when no row exists; it does not write one.
- `PUT /naming-presets/{ad_account_id}`. Last write wins; returns `updated_at`.
- `GET /naming-presets/{ad_account_id}/observed-codes`. Parses existing ad-set names for `CODE-NICHECODE |` prefixes, read-only.

**Other constraints:**

- No change to how names reach Meta: still the `name` field on create calls, and no Meta API change.
- Trigger files touched: `BulkAdCreation.jsx` (ad names), and possibly `AdCreativeStep.jsx`. That means the 2-agent pre-push review is mandatory.
- `session_id` passthrough: N/A.

## 6. Tracking

Use the existing event endpoint pattern. Add the new names to an allowlist.

- `naming_preset_saved {level}`
- `naming_name_overridden {level}`. Counts names typed over templates; a high count means the template is wrong.
- `naming_launch {level, matched: bool}`

**Success at 2 weeks:**

- At least 80% of new RHO ad sets match the convention.
- Fewer than 20% of names are overridden.
- Niche grouping on Max CPL stops showing wave-fused niches. This one is Phase 2 dependent.

## 7. Build priority

**Phase 1 (one PR: Codex UI + Claude migration and endpoints)**

1. Migration, model, and 3 endpoints. Claude Code builds these.
2. Tokens (§3.1) and `parseName`, with unit tests on real names.
3. Naming settings drawer, plus migrating localStorage templates to the server.
4. Wire CampaignStep, AdSetStep, BulkAdCreation (both naming spots), BatchPushModal and PushToMetaModal.
5. Preview, convention check, and duplicate suffixing.

**Phase 2 (directional)**

- Backend `parse_name` used by `niche_extraction`. Template-built names give exact niche, wave and angle. This fixes wave-fused niches in Max CPL, Compass and dashboards, and enables "group by wave / angle" reporting.
- Rename helper for existing ad sets (Meta write, needs Joel's and Abel's sign-off). Hold until asked.
- Per-buyer preset variants (the `variant` column).

## 8. Open questions

1. ~~Does Joel launch from the Ad Builder?~~ **Resolved 2026-11-08 (Steve):** Abel builds every campaign and ad set in the Ad Builder; Joel supplies the creatives. One shared convention, so presets are per account with no per-buyer split. Full Phase 1 stands; Abel is the primary user.
2. **Is the wave part of the niche?** Decision for Phase 1: treat them as **separate**. The observed-codes parser already splits `VEHICLE W2 FUNERAL HOMES` into wave `VEHICLE W2` and niche `FUNERAL HOMES`, and the campaign template is `{wave} {niche}`, so names come out identical either way. Confirm with Joel/Abel before Phase 2 changes niche_extraction for Max CPL.
3. **THS:** presets are per account, so if THS uses a different convention it just gets its own preset.

**Not verified:** whether every RHO campaign in the last 30 days was launched through the Ad Builder. The naming sample is the 25 newest campaigns and 30 newest ad sets on RHO Commercial.
