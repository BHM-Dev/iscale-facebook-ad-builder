# Codex Brief — ImageAds "Quick Generate" mode

**Source:** Nightly Ad Builder task (auto-generated). Pulled from `CLAUDE.md` → "Still pending":
> ImageAds "Quick Generate" mode — skip wizard, go straight to niche+copy+generate for media buyers with existing copy

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**Classification:** CODEX (frontend-only, no backend, no migrations, no trigger files).
**Hand off to Claude Code for the `git push origin develop`** — Codex commits locally only.

---

## Goal

Joel and other media buyers often already have winning copy. They don't want to step through the 8-step guided wizard (Brand → Product → Profile → Template → Variations → Size → Campaign → Review) and have the tool *generate* copy for them. Add a **Quick Generate** mode to the existing `/image-ads` page: pick a brand + niche/template, paste their own headline/body/CTA, set variation count + size, hit Generate. No copy generation step.

This reuses the existing image-generation pipeline — you are NOT building a new generate flow, just a leaner entry into the same handlers.

## Exact files to touch

- **`frontend/src/pages/ImageAds.jsx`** (1913 lines) — the only file that must change. Add the mode toggle + the Quick Generate panel here.
- You MAY reuse existing components already imported in this file: `BrandSelectionStep` (`components/steps/BrandSelectionStep.jsx`), `ImageTemplateSelector`, `StyleSelector`. Do not modify those component files unless strictly necessary; if you do, keep changes additive and backward-compatible.

**Do NOT touch any of these (hard stop — hand back to Steve if you think you need them):** `BulkAdCreation.jsx`, `AdCreativeStep.jsx`, `lib/facebookApi.js`, `backend/app/services/facebook_service.py`, anything under `backend/alembic/versions/`. This task needs none of them.

## What to implement

### 1. Mode toggle
At the very top of the ImageAds page render (above the step indicator), add a segmented control with two options:
- **Guided Wizard** (default — the existing 8-step flow, unchanged)
- **Quick Generate**

Hold the mode in new state: `const [mode, setMode] = useState('wizard'); // 'wizard' | 'quick'`. When `mode === 'wizard'`, render exactly what renders today. When `mode === 'quick'`, render the Quick Generate panel (below) and hide the step indicator + wizard step bodies.

> **Reasonable-default note for Steve:** entry point chosen as an in-page toggle on `/image-ads` rather than a new route or a button on another page. Easy to relocate later if you'd rather it live on the Dashboard.

### 2. Quick Generate panel (single screen)
Render these controls in one compact card (no step navigation):

1. **Brand** — reuse `<BrandSelectionStep brands={...} selectedBrand={wizardData.brand} onSelect={b => updateData('brand', b)} />`. Required (used for image branding + DB save). Brands come from the existing `useBrands()` context already wired in this file.
2. **Niche / Template** — reuse the existing template selector (`<ImageTemplateSelector .../>` as used in the wizard's Template step, or `<StyleSelector/>` per `templateMode`). Sets `wizardData.template`. Required.
3. **Your copy** — three text inputs writing into a local `quickCopy` state object:
   - `headline` (single line, required)
   - `body` (textarea, required)
   - `cta` (single line, optional — default to `GET MY QUOTE` if blank, matching existing overlay default)
4. **Variations** — number input bound to `wizardData.variationCount` (1–10, reuse existing validation).
5. **Size** — reuse the existing size selector that writes `wizardData.imageSizes` (default already `Square 1080x1080`).
6. **Generate button** — disabled unless brand, template, headline, and body are all set. On click call the **existing** handler:
   ```js
   handleImageGeneration({
     headline: quickCopy.headline,
     body: quickCopy.body,
     cta: quickCopy.cta?.trim() || 'GET MY QUOTE',
   });
   ```
   `handleImageGeneration` already: fires `generateImagesForCopy` (POST `/generated-ads/generate-image`), saves via POST `/generated-ads/batch`, shows success/error toasts, and advances to the results view (`setCurrentStep(10)`). Do not reimplement any of that.

### 3. Results
The existing results render keys off `currentStep === 10` / `generatedImages`. After Quick Generate runs, `handleImageGeneration` already sets `setCurrentStep(10)`, so results will show. Make sure the results view renders regardless of `mode` (i.e. don't gate the results block behind `mode === 'wizard'`). Add a "Generate another" / back affordance that returns to the Quick Generate panel (reset `generatedImages`, keep `mode === 'quick'`).

## Patterns you MUST follow (from CLAUDE.md)
- API calls use `authFetch` from `useAuth()` (already destructured at top of file as `const { authFetch } = useAuth();`). Base URL is the existing `API_URL` const.
- Notifications use `useToast()` → `showSuccess` / `showError` (already wired). **Never** use `alert()` or `confirm()`.
- Match the existing Tailwind styling in ImageAds.jsx — reuse the same card/button classes already in the file. No new design system.
- Keep `wizardData` as the single source of truth for brand/template/variationCount/imageSizes so the existing handlers work untouched. Only `quickCopy` and `mode` are net-new state.
- Don't break the guided wizard — it must behave identically when `mode === 'wizard'`.

## Verify before handing back
- Toggle flips cleanly between Guided Wizard and Quick Generate; wizard still works end-to-end.
- Quick Generate with brand + niche + pasted copy produces images and saves to Generated Ads (success toast fires).
- Generate button stays disabled until brand, template, headline, body are filled.
- No `alert()`/`confirm()`, no console errors, no edits to the forbidden files.

## Handoff
Codex: implement + commit locally with a clear message (e.g. `Add Quick Generate mode to ImageAds for buyers with existing copy`). **Do not push.** Then open Claude Code, run the mandatory pre-push agent review (medium change → 2 Haiku agents, diff inline), address findings, and `git push origin develop`.
