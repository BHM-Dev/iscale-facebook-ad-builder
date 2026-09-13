# Meta → RedTrack Tracking Links — What To Check

**For: Joel, Abel** · Prepared 2026-09-13 · Source: live Meta + Everflow data, not theory

---

## The one thing that matters

Every ad's **Website URL** must carry the full tracking string. Copy this exactly:

```
?sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}&sub4={{ad.name}}&sub5={{adset.name}}&sub6={{campaign.name}}&sub7={{placement}}&sub8={{site_source_name}}&utm_source=facebook&utm_medium=paid
```

Appended to the RedTrack click link, e.g.:

```
https://go.getfbquotes.com/<offer-id>?sub1={{ad.id}}&sub2={{adset.id}}&...
```

The double braces are correct and must stay literal — Meta swaps them for real IDs at delivery.
Do not "clean them up."

---

## What it costs when it's wrong

| Date | What happened | Cost |
|---|---|---|
| Aug 2026 | 3 campaigns ran with `sub2={{campaign.id}}` | RedTrack showed **$0 spend** on all three while revenue kept flowing |
| Aug 2026 | Some links sent a literal `{{campaign.name}}` | **$3,254** of real billable revenue could not be matched to an ad set in the P&L |

Both were the same root cause: **a link that didn't get updated.** Neither threw an error. Neither
looked broken in Meta. The only symptom was numbers that quietly didn't add up.

---

## When to check — the only three moments

1. **Duplicating a campaign or ad set in Meta.** This is where August broke. Duplicating copies the
   URL; if the original was wrong, every copy is wrong.
2. **Pasting a new offer link from RedTrack.** The click link arrives bare — the sub string is not
   included. You have to append it.
3. **Editing a Website URL by hand** for any reason.

---

## The 30-second check

Open the ad in Ads Manager → **Website URL** field → confirm, in order:

- [ ] `sub1={{ad.id}}` — not `{{adset.id}}`, not a number
- [ ] `sub2={{adset.id}}` — **this is the one that broke in August**
- [ ] `sub3={{campaign.id}}`
- [ ] `sub4` through `sub8` present
- [ ] No stray value where a macro belongs (`sub1=12345`, `sub3={{campaign.name}}`)

If a sub holds a **number instead of braces**, that link is broken. A hardcoded number sends the
same value for every ad, so RedTrack lumps all of them together and per-ad numbers become fiction.

---

## Examples — right vs. wrong

### ✅ Correct (this is a real live ad, Florist - Scale)

```
https://go.getfbquotes.com/69df01f81836df8a44e6aa04?sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}&sub4={{ad.name}}&sub5={{adset.name}}&sub6={{campaign.name}}&sub7={{placement}}&sub8={{site_source_name}}&utm_source=facebook&utm_medium=paid
```

At delivery Meta rewrites it to something like:

```
...?sub1=120214891234567890&sub2=120214887654321098&sub3=120214880011223344&sub4=Florist%20-%20Ad%203...
```

---

### ❌ Wrong #1 — the August failure

```
?sub1={{ad.id}}&sub2={{campaign.id}}&sub3={{campaign.id}}&sub4=...
             ^^^^^^^^^^^^^^^^^^^^^^ should be {{adset.id}}
```

**What you see:** RedTrack shows **$0 spend** on the campaign while revenue keeps coming in. ROAS
looks infinite or blank. Nothing errors.

**Why:** every ad set reports under the same campaign ID, so RedTrack can't match Meta's spend rows
to anything. **Cost in August: 3 campaigns, all spend attribution lost.**

**Fix:** set `sub2` back to `{{adset.id}}`.

---

### ❌ Wrong #2 — a name where an ID belongs

```
?sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.name}}
                                       ^^^^^^^^^^^^^^^^ should be {{campaign.id}}
```

**What you see:** revenue appears in Everflow but can't be tied to any ad set — it lands in the
P&L's "unknown" bucket, so profit looks lower than it is.

**Why:** names contain spaces and punctuation and don't survive the trip. **Cost in August: $3,254
of real revenue unattributed.**

**Fix:** `.id` macros only in `sub1`–`sub3`. Names belong in `sub4`–`sub6`.

---

### ❌ Wrong #3 — hardcoded number

```
?sub1=120214891234567890&sub2={{adset.id}}&sub3={{campaign.id}}
      ^^^^^^^^^^^^^^^^^^ a real ID, but frozen
```

**What you see:** reports look completely normal — populated, plausible, and wrong.

**Why:** usually someone copied a *delivered* URL out of a browser instead of the template. Every
ad now reports as that one ad. This is the most dangerous version because nothing looks broken.

**Fix:** put the braces back.

---

### ❌ Wrong #4 — braces "cleaned up"

```
?sub1=ad.id&sub2=adset.id
      ^^^^^ braces removed
```

**What you see:** RedTrack rows with the literal text `ad.id` as the ad identifier.

**Why:** the double braces are the macro. Without them it's just a word.

**Fix:** `{{ad.id}}`, two braces each side.

---

### ❌ Wrong #5 — bare offer link

```
https://go.getfbquotes.com/69df01f81836df8a44e6aa04
```

**What you see:** clicks and conversions in RedTrack, but no ad, ad set, or campaign breakdown —
everything collapses to one unnamed row.

**Why:** RedTrack click links come out of the platform bare. The sub string is never included; it
has to be appended every time.

**Fix:** append the full string from the top of this doc.

---

### ❌ Wrong #6 — trimmed string

```
?sub1={{ad.id}}&sub2={{adset.id}}&sub3={{campaign.id}}
```

**What you see:** spend and revenue match correctly, but ad name, ad set name, placement and
platform columns are all blank.

**Why:** `sub4`–`sub8` carry those. Attribution still works — reporting detail is what's lost.

**Fix:** add `sub4`–`sub8` back.

---

## Two traps worth knowing

**Meta's URL Parameters field is not the same as the Website URL field.** Macros work in both, but
`sub4`–`sub8` only ever live in the Website URL. If you move the string into URL Parameters and
trim it, you silently lose ad name, ad set name, and placement reporting.

**`{{campaign.name}}` is never a valid sub value.** Names contain spaces and punctuation; they
break on the way through. Only the `.id` macros belong in `sub1`–`sub3`.

---

## What the Ad Builder does and does not do

**Does:** when it launches an ad, it adds any missing `sub1`/`sub2`/`sub3` macro via Meta's
`url_tags`, so an ad launched from the tool can't ship with those three absent.

**Does not:** repair a *wrong* value. If the saved URL already says `sub2={{campaign.id}}`, the tool
leaves it — so the August failure mode is still possible on a link edited outside the tool, and on
anything duplicated in Ads Manager. It also does not touch `sub4`–`sub8` at all.

**So the check above is still yours.** The tool is a backstop for omissions, not a fix for errors.

---

## Current state (verified 2026-09-13)

All 14 live ads across the Barber Shop and Florist scale campaigns carry the complete, correct
tracking string. Nothing needs fixing right now. The only ads missing tracking are paused internal
test ads.
