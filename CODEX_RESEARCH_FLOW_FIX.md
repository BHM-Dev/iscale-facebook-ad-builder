# Research → Build Ad Flow Fix

**Scope:** Frontend only. Two files: `Research.jsx` (minor) + `AdRemix.jsx` (main fix). No backend changes.

**Preflight:** `git pull origin develop`

---

## What's broken

Joel's reported flow:
1. Goes to Research tab, finds a competitor ad
2. Clicks "Use as Inspiration"
3. Gets taken to Build New Ad (`/ad-remix`) — but it shows Step 1: **"Model a live ad"** (asks him to paste a Meta ad URL or pick one of his own running ads)
4. That makes no sense — he's here from a competitor ad, not from his own Meta library

**Root cause (`AdRemix.jsx` line 147–158):**
```javascript
useEffect(() => {
    const raw = localStorage.getItem('pendingResearchInspiration');
    if (!raw) return;
    const inspiration = JSON.parse(raw);
    localStorage.removeItem('pendingResearchInspiration');
    setResearchInspiration(inspiration);
    // ← NOTHING advances the step. Joel stays on Step 1.
}, []);
```

The `pendingRemixCreative` flow (from Campaign Performance) correctly jumps to Step 7. The research flow never jumps — it dumps Joel on the "pick a live Meta ad" screen with no explanation of what to do.

---

## Fix 1 — AdRemix.jsx: skip Step 1 when arriving from Research

**File:** `frontend/src/pages/AdRemix.jsx`

Find the research inspiration mount effect (~line 147). After setting the inspiration, advance to Step 2 (Brand selection) so Joel skips the "Model a live ad" screen entirely:

```javascript
useEffect(() => {
    const raw = localStorage.getItem('pendingResearchInspiration');
    if (!raw) return;
    try {
        const inspiration = JSON.parse(raw);
        localStorage.removeItem('pendingResearchInspiration');
        setResearchInspiration(inspiration);
        setCurrentStep(2); // skip "Model a live ad" — we're building from competitor context
    } catch (e) {
        // malformed localStorage — ignore
    }
}, []);
```

---

## Fix 2 — AdRemix.jsx: show competitor context in Step 2

Right now the only signal to Joel that he arrived from Research is a blue banner — but it only appears at a specific step. Make the competitor context visible at Step 2 (Brand selection) so Joel understands the full picture.

Find where `researchInspiration` is checked/displayed. It's likely shown as a banner only at Step 5 or Step 7. Add a compact reference card at Step 2 as well.

**Find the Step 2 render block** (`{currentStep === 2 && (...)}`). Add this above the brand selector if `researchInspiration` is set:

```jsx
{currentStep === 2 && (
  <div>
    {researchInspiration && (
      <div className="mb-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm">
        <div className="text-xs font-semibold text-blue-500 uppercase tracking-wide mb-1">Modeling competitor ad</div>
        <div className="font-medium text-gray-800 truncate">{researchInspiration.advertiser}</div>
        {researchInspiration.headline && (
          <div className="text-gray-600 text-xs mt-0.5 line-clamp-2">"{researchInspiration.headline}"</div>
        )}
      </div>
    )}
    {/* existing brand selector content */}
  </div>
)}
```

---

## Fix 3 — AdRemix.jsx: pre-fill copy fields at Step 5

Step 5 is the Campaign Details / hook step. When Joel arrives from Research, pre-populate the "Source Hook / Angle" field with the competitor's `angle` tag (if present), and show the competitor copy as a reference panel.

Find Step 5 render block (`{currentStep === 5 && (...)}`). 

**a) Pre-fill the hook/angle field** — find where `wizardData.hook` is set. On entering Step 5 from Research (i.e., `researchInspiration` is set AND the hook field is still empty), default the hook field to `researchInspiration.angle`:

In the Step 5 useEffect or initialization, add:
```javascript
// Pre-fill hook from research inspiration if blank
useEffect(() => {
    if (currentStep === 5 && researchInspiration?.angle && !wizardData.hook) {
        setWizardData(prev => ({ ...prev, hook: researchInspiration.angle }));
    }
}, [currentStep]);
```

**b) Show competitor copy panel** — add a collapsed reference section in Step 5 when `researchInspiration` exists. If `researchInspiration.headline` or `researchInspiration.body` is set, show:

```jsx
{researchInspiration && (researchInspiration.headline || researchInspiration.body) && (
  <div className="mb-4 rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-xs text-gray-500">
    <div className="font-semibold text-gray-700 mb-1">Competitor reference — {researchInspiration.advertiser}</div>
    {researchInspiration.headline && <div className="font-medium text-gray-600">"{researchInspiration.headline}"</div>}
    {researchInspiration.body && <div className="mt-1 line-clamp-3 text-gray-500">{researchInspiration.body}</div>}
  </div>
)}
```

---

## Fix 4 — Research.jsx: rename button to be clearer

**File:** `frontend/src/pages/Research.jsx`

The button currently says "Use as Inspiration". That's vague. Rename to "Build from this ad" so Joel's expectation is set correctly before he clicks.

Find all occurrences of "Use as Inspiration" in Research.jsx (line ~182 and ~244) and replace with "Build from this ad".

---

## Validation

```bash
npm run build
```

Chrome test flow:
1. Go to `/research`
2. Find any saved or browsed ad card
3. Click "Build from this ad"
4. Confirm: lands on Step 2 (Brand), NOT Step 1 (Model a live ad)
5. Confirm: blue competitor reference card shows at top of Step 2
6. Select a brand, advance through to Step 5
7. Confirm: hook/angle field is pre-filled from the competitor's angle tag (if it had one)
8. Confirm: competitor copy panel shows in Step 5
9. Generate — confirm it works end-to-end

**When done:** "Edits done — ready for Claude Code review + push" + commit hash(es).
