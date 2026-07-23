# Codex Brief — Quick Generate Polish (Character Counters + Logo Preview)

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**Classification:** CODEX (frontend-only, single file, no backend, no migrations, no trigger files).
**Hand off to Claude Code for the `git push origin develop`** — Codex commits locally only.

---

## Goal

Two small polish fixes to the Quick Generate panel in `frontend/src/pages/ImageAds.jsx` (added in commit `dc02099`). Both items are P2/P3 UX improvements flagged in the post-ship review.

## Exact file to touch

- **`frontend/src/pages/ImageAds.jsx`** only. Do not touch any other file.

---

## Change 1 — Character counters on Quick Generate copy fields

### Where
Inside the `QuickGeneratePanel` function component (near bottom of the file). Find the "Your Copy" section — three inputs: Headline, Body, CTA.

### What to add
Below each input, add a character count line matching the exact pattern already used in `CopySelectionStep` (search for `/ 40 characters` in the file to see the existing pattern):

- **Headline:** `{quickCopy.headline.length} / 40 characters` — use `text-xs text-gray-500 mt-1`
- **Body:** `{quickCopy.body.length} / 125 characters (recommended)` — same class
- **CTA:** `{quickCopy.cta.length} / 20 characters` — same class

These are display-only. No validation change needed.

---

## Change 2 — Logo preview in Quick Generate overlay panel

### Where
Inside the `QuickGeneratePanel` function component. Find the "Text Overlay" section — the block that currently shows:
```jsx
{overlayLogoUrl && (
    <p className="text-xs text-green-700 flex items-center gap-1">
        <Check size={12} /> Logo from previous session will be applied
    </p>
)}
```

### What to replace it with
Replace the plain text note with the full logo preview UI — thumbnail, Replace button, Remove button — matching the pattern in `CampaignDetailsStep` (search for `overlayLogoPreview` in the file to find it).

You need to add these props to `QuickGeneratePanel`:
- `overlayLogoPreview` — the preview URL (string)
- `setOverlayLogoPreview` — setter
- `uploadingLogo` — boolean
- `logoFileInputRef` — ref
- `uploadLogoImage` — upload handler function

And pass them through from the `ImageAds` parent component where `QuickGeneratePanel` is rendered (all five already exist in parent state — search for `uploadLogoImage`, `logoFileInputRef`, etc.).

The logo UI to render (copy from `CampaignDetailsStep`, lines ~1075–1116):
```jsx
<input
    type="file"
    accept="image/*"
    className="hidden"
    ref={logoFileInputRef}
    onChange={e => { const f = e.target.files?.[0]; if (f) uploadLogoImage(f); e.target.value = ''; }}
/>
{overlayLogoPreview ? (
    <div className="flex items-center gap-3">
        <img
            src={overlayLogoPreview}
            alt="Logo preview"
            className="h-10 w-auto rounded border border-gray-200 bg-gray-50 object-contain p-1"
        />
        <div className="flex flex-col gap-1">
            <button
                type="button"
                onClick={() => logoFileInputRef.current?.click()}
                disabled={uploadingLogo}
                className="text-xs text-amber-600 hover:text-amber-800 disabled:opacity-40"
            >
                {uploadingLogo ? 'Uploading…' : 'Replace'}
            </button>
            <button
                type="button"
                onClick={() => {
                    setOverlayLogoUrl('');
                    setOverlayLogoPreview('');
                    try { localStorage.removeItem('overlayLogoUrl'); } catch (_) {}
                }}
                className="text-xs text-red-400 hover:text-red-600"
            >
                Remove
            </button>
        </div>
    </div>
) : (
    <button
        type="button"
        onClick={() => logoFileInputRef.current?.click()}
        disabled={uploadingLogo}
        className="flex items-center gap-2 text-sm border border-dashed border-gray-300 rounded-lg px-3 py-2 w-full text-gray-500 hover:border-amber-400 hover:text-amber-600 disabled:opacity-40 transition-colors"
    >
        <Upload size={13} />
        {uploadingLogo ? 'Uploading…' : 'Upload logo (PNG recommended)'}
    </button>
)}
<p className="text-xs text-gray-400 mt-1">Saved for future sessions.</p>
```

Note: `Upload` is already imported at the top of the file.

---

## Patterns to follow
- No `alert()` or `confirm()`
- Match existing Tailwind classes — don't introduce new ones
- No new state, no new imports needed beyond what's already in the file

## Verify before handing back
- Character counters appear below all three copy inputs in Quick Generate mode
- Logo upload/preview/replace/remove works in Quick Generate overlay panel
- Guided Wizard mode is completely unchanged
- No console errors

## Handoff
Codex: implement + commit locally. **Do not push.** Hand back to Claude Code for pre-push review + push.
