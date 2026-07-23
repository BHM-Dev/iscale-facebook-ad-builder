# Codex Brief — Image Generation Fix (ASAP)

**Repo:** `BHM-Dev/iscale-facebook-ad-builder`, branch `develop`. Local: `/Users/Steve1/Claude/AdBuilder`
**File:** `backend/app/api/v1/generated_ads.py` only. NOT a trigger file, NO migration.
**Push:** Codex commits locally → hand to Claude Code. Claude Code does the 2-agent-optional review, **visually validates generated images** (Codex can't see them), and pushes. Do NOT push.

Context: the Ad Builder's creation side has 0 real pushes. One concrete, embarrassing defect is a big part of why the output isn't trusted — plus two gaps. Fix all three.

---

## 1. PRIMARY BUG — niche override substring match (`_get_niche_override`, ~line 299)

Current:
```python
for key, prompts in _NICHE_OVERRIDES.items():
    if key in niche_lower:            # substring match — WRONG
```
`"bar"` is an override key (upscale bar / bartender pouring cocktails). `"bar" in "barber shop insurance"` is `True`, so **"Barber Shop Insurance" renders a cocktail lounge.** Any niche containing a short key as a substring false-matches.

**Fix:** match on **whole words**, not substrings. Use word-boundary matching:
```python
import re
niche_lower = niche.lower()
for key, prompts in _NICHE_OVERRIDES.items():
    if re.search(rf"\b{re.escape(key)}\b", niche_lower):
        ...
```

**Required test cases (must all hold after the fix):**
- `"barber shop insurance"` → **no** `bar` match → returns `None` (falls through to the AI scene-writer, which yields a barbershop). ✅ this is the fix.
- `"neighborhood bar"` / `"bar"` → still matches `bar`. ✅
- `"religious organizations"` → still matches `religious`. ✅
- `"gymnastics studio"` → does **not** match `gym` (whole-word). ✅ (verify this is the desired behavior; `gymnasium`/`gym` are different businesses)
- `"winery"` → still matches `winery`. ✅

Keep the existing random-scene-pick + the debug print.

## 2. GAP — add curated niche overrides for the active verticals

Auto insurance (Abel's focus) and home services (Joel/Abel) currently have **no** entries in `_NICHE_OVERRIDES`, so they fall to the generic AI writer. Add curated scene lists in the same style/format as the existing entries (contemporary, specific, "No text, no logos. Photorealistic.", controlled people/no-people). Suggested keys + scenes (write 3–4 each, match the existing tone):

- `"auto insurance"` / `"auto"`: a car owner beside a clean late-model sedan in a driveway; a driver at the wheel on an open road, natural light; a family SUV parked in front of a suburban home. No text/logos. Photorealistic.
- `"home service"` / `"gutter"` / `"roofing"` / `"hvac"` / `"plumbing"`: a uniformed technician doing the actual job (gutter cleaning on a ladder, roofer on a residential roof, HVAC tech at a condenser unit), suburban home context, natural daylight. Tools, action, craft. No text/logos. Photorealistic.

Match how the trades entries (`welding`, `trucking`) are written. Keep each scene one specific setting.

## 3. CLEANUP — model naming (cosmetic, low risk)

`ImageGenerationRequest.model` defaults to `"flux-kontext-pro"` (~line 25), but the active generator called at ~line 869 is `_kie_generate_nano` (`nano-banana-pro`). The flux path (`_kie_generate_image`) is dead. Change the default to `"nano-banana-pro"` so it reflects reality. Leave the dead `_kie_generate_image` function in place (don't remove — out of scope), just fix the misleading default.

---

## Verify before handing back
- `python3 -m py_compile backend/app/api/v1/generated_ads.py` passes.
- The 5 test cases in §1 behave correctly (a quick local unit check of `_get_niche_override` return values is ideal — no kie.ai calls needed to test the matching logic).
- Do NOT call kie.ai / generate real images (costs credits) — Claude Code will do the visual validation.

## Handoff
Codex: implement §1–§3, commit locally, hand to Claude Code. Claude Code will: review, generate real test images for `barber shop`, `auto insurance`, and a `home service` niche to confirm scenes are on-target, then push to `develop`.
