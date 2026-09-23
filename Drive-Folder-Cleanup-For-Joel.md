# Drive folders that need copy docs — for Joel

Generated from a live scan of the synced Drive, 2026-09-21. The Ad Builder now
refuses to attach ad copy it can't match with certainty, so these folders either
block a launch or produce creatives with no copy attached.

Live page (rebuilt hourly): **Ad Builder → Drive picker → "Package health"**

---

## The headline

| | Folders | Images |
|---|---|---|
| Will be **refused at launch** today | 7 | 73 |
| No copy doc, real working folders | 16 | 223 |
| Healthy, leave alone | 11 | 130 |
| `LEGACY IMAGES` archive — **excluded, no action** | 110 | 608 |

The raw scan says "126 folders need attention." Ignore that number — 110 of them
are the `Commercial Insurance - LEGACY IMAGES` archive, which has no business
carrying copy docs. The real backlog is **16 folders**.

---

## 1. Blocking launches right now — fix these first

Six sibling niches under `Commercial Van Insurance` share the same generic
filenames (`ad1-identity-1x1.png`, `ad5-trojan-9x16.png`, …) **and** have no copy
doc of their own. With nothing package-specific to match on, the builder can't
tell which niche a given `ad1-identity-1x1.png` belongs to, so it refuses all of
them rather than risk putting roofing copy on a janitorial ad.

- `Commercial Van Insurance / 01 - Painting Contractors` — 10 images
- `Commercial Van Insurance / 02 - HVAC & Plumbing` — 10
- `Commercial Van Insurance / 03 - Electrical Contractors` — 10
- `Commercial Van Insurance / 04 - Landscaping` — 10
- `Commercial Van Insurance / 05 - Janitorial Services` — 10
- `Commercial Van Insurance / 06 - Roofing Contractors` — 10

**Fix:** add a copy doc to each folder. That alone clears it — the filenames can
stay as they are, because a package-level copy doc removes the ambiguity.

Separately:

- `Broad Testing / Batch 1 - Mixed Niche` — 13 images. This one *has* a category
  copy doc, but the same filename appears twice inside the folder, so one of the
  two can't be matched. Rename one of the duplicates **and** update the copy doc
  entry to the new name.

### The colliding filenames, for reference

`ad1-identity-9x16.png`, `ad2-claim-denied-9x16.png`, `ad4-price-anchor-1x1.png`,
`ad5-trojan-1x1.png`, `ad5-trojan-9x16.png` each appear in **6** packages;
`ad2-claim-denied-1x1.png`, `ad3-coi-growth-9x16.png`, `ad4-price-anchor-9x16.png`
in 5; `ad1-identity-1x1.png`, `ad3-coi-growth-1x1.png` in 4; `ad1-identity-v2.png`,
`ad3-coi-growth-v2.png` in 2.

Reusing names across packages is fine **as long as each package has its own copy
doc.** It only breaks when both are missing.

---

## 2. No copy doc — creatives land with no copy

These don't block a launch, but every image in them arrives in the builder with
an empty headline and body that has to be typed in by hand.

**Winner Variations batches (7 folders, 70 images)** — same shape each time:

- `Commercial Van Insurance / 00 - Commercial Auto (General) / Winner Variations - v2`
- `Commercial Van Insurance / 01 - Painting Contractors / Winner Variations - v2`
- `Commercial Van Insurance / 02 - HVAC & Plumbing / Winner Variations — v2`
- `Commercial Van Insurance / 03 - Electrical Contractors / Winner Variations — v2`
- `Commercial Van Insurance / 04 - Landscaping / Winner Variations — v2`
- `Commercial Van Insurance / 05 - Janitorial Services / Winner Variations - v2`
- `Commercial Van Insurance / 06 - Roofing Contractors / Winner Variations - v2`

**Other live folders (9 folders, 153 images):**

- `Commercial Van Insurance / 00 - Commercial Auto (General)` — 36
- `Florist | Joel's Image Options | Abel Selects / Original User Supplied Images` — 27
- `07 - General Commercial Insurance / Creative Factory` — 20
- `07 - General Commercial Insurance / Nick Theriot Method` — 20
- `Auto Body / Winner Variations Trojan` — 10
- `Religious Organizations / Property Exposure Winner Expansion — Sep 2026` — 10
- `Religious Organizations / Winner Variations Storm` — 10
- `Trucking / Winner Variations - Comparison Shock` — 10
- `Trucking / Winner Variations - Market Comparison` — 10

Some of these are probably source/staging rather than launch packages —
`Original User Supplied Images` reads that way. Anything that isn't meant to be
launched from can be skipped; it'll just keep showing on the report.

---

## 3. The pattern that already works

Two folders are already done right, both using a strategy doc:

- `Commercial Van Insurance / 03 - Electrical Contractors v2` — 10 images, healthy
- `Commercial Van Insurance / 04 - Landscaping Contractors v2` — 10 images, healthy

Nine more use a handoff manifest and are equally clean (Barber Shops ×2,
Florist ×2, Horse and Stable, Welders, Auto Dealerships ×2, plus
`Auto Dealerships / Two Winner Expansion — Sep 2026`).

So the template exists in Joel's own Drive — the fix for the rest is to copy what
those folders do, not to invent anything.

---

## What changed on the tool side

The builder used to attach copy by filename alone. If two packages shared a
filename it could attach the wrong package's headline, primary text, landing page
and CTA to a creative and mark it verified — invisible, and it would launch with
real spend. It now refuses any match it can't tie to a specific file, blocks that
creative from selection and from launch, and says which file to rename.

No creative currently carries wrong copy: all 141 copy-tracked assets are verified.
