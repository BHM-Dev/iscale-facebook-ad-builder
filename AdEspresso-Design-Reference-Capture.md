# AdEspresso — Design Reference Capture

Live trial walkthrough, `app.adespresso.com`, real RHO 4 account connected. Reached the actual
combinatorial-grid screen (the one thing Birch's capture didn't show). Campaign named
"Design Reference Test - Do Not Publish," never saved as draft, nothing created — confirmed via
campaign search after the fact (0 results).

**Second pass (this update):** full account tour — Overview dashboard, all four Tools (Optimization
Rules, Asset Manager, Report Generator, Product Catalogs), Services marketplace, University,
Collaboration Hub, and a second, deeper run through the campaign wizard (Ads Design → Audience →
Budget & Bidding). Two test drafts created along the way ("Design Reference Test" and "Design
Reference Test 2 - Do Not Publish"); neither was ever saved as a draft or published — both wizard
sessions were abandoned by navigating away, never via the "Save As Draft" button. One Optimization
Rule Set was created for inspection and explicitly deleted afterward (confirmed via UI). The
post-hoc campaign search hung on "Searching..." indefinitely (see §9) rather than confirming
cleanly a second time, but nothing was ever committed via a save/publish action in either pass.

---

## 1. The mechanic itself — "Create all permutations"

Campaign wizard: Create Campaign → **Ads Design** → Audience → Budget & Bidding → Publish
(standard 5-step linear wizard, right-rail numbered stepper — closer to your AdRemix/ImageAds
shape than Birch's card-based flow).

On Ads Design, three top-level modes:
- **Create all permutations** — split-test every creative element you enter (the one explored)
- **Reuse existing posts** — pull existing live Facebook posts into the new campaign
- **Test Ad Templates** — run specific, pre-defined combinations rather than the full cross product

Each text field (Headlines, Ad Texts, Link Description) uses the same **inline "+ to test more"**
pattern: type a value, hit the blue "+" button next to the field, it drops below as its own row
with a delete icon — no modal, no separate step. Images/videos are added via **Upload new
images / Select from your gallery / Design an ad** (a built-in creative editor, not explored).

**The gallery picker pulled real, live BHM creative assets** synced from the connected account —
actual "Get Business Coverage" niche ads (Welders Insurance, Painting Contractors, Auto
Dealership, Electricians) with thumbnail, filename, and dimensions, multi-select with a running
"Add Images (N)" counter. Confirms AdEspresso already has real visibility into your existing
Meta creative library the moment an account connects — no separate import step.

## 2. The live combinatorial counter

The right rail keeps a running **literal multiplication formula** as you add elements:

```
1 HEADLINE × 1 TEXT × 2 IMAGES × 1 URL × 1 CALL TO ACTION
2 /50 variations          Show All
```

Every field you fill adds a term to the formula and multiplies the total live. The 50-variation
cap is a real, visible ceiling (not just a soft warning) — worth knowing if a BHM build wanted a
similar cap for cost/spend-safety reasons on a bulk launch.

One rough edge found while testing: filling the **URL field via one method didn't stick** (typed
via a coordinate click that landed correctly per the accessibility read, but the field silently
stayed empty and the counter's `× 1 URL` term vanished) — refocusing the exact field and retyping
fixed it. Possibly a race between page reflow (selecting the Page dropdown shifted layout) and
the click landing. Minor, but the counter's live "term appears / term vanishes" behavior is itself
a good pattern to copy regardless: it's obvious at a glance which required field is still missing.

## 3. "Show All" — the actual preview grid

This is the mechanic Birch doesn't have. Clicking **Show All** opens a scrollable modal rendering
**every generated combination as a real, native Facebook feed-preview card** — Page name and
avatar, "Sponsored"/"Ad" label, the actual headline/body text, the real creative image, and the
live CTA button ("Learn More," "Get quote"), styled exactly like it would look live on Facebook.
Two placement variants shown per combination (a feed-style card and a second format).

Each card carries its own **"..." menu and a small "✕"** — meaning you review the full generated
batch visually and can **individually exclude one specific bad combination** before publishing,
rather than accepting the whole batch or nothing. This is the direct, concrete answer to "catch a
bad combo before 12 ads go live" — a real screenshot-accurate preview per ad, not a list of names
or a single summary sentence.

**Compared to Birch:** Birch tells you the *outcome* in one computed sentence ("Creates 2 ads in
1 new ad set"). AdEspresso shows you the *actual ads*, rendered, before you commit. Different
tools solving the same trust problem two different ways — worth having both patterns in mind:
Birch's line is cheap and fast to build; AdEspresso's grid is more expensive to build but removes
far more guesswork for something as visual as ad creative.

## 4. Other details worth naming

- **Full top nav, more surface area than Birch showed:** Your Campaigns / New Campaign / Tools /
  Services / University (help/education content) / Collaboration (team features) — a materially
  bigger app than what we saw of Birch's four-tab shell. Not explored beyond Ads Design; flagging
  as existing, not reviewed in depth.
- **"We will not publish anything and not spend any money until you publish the campaign at the
  end of the last step"** — same reassurance-banner pattern as Birch's "Our promise," placed at
  the very top of step 1. Worth copying verbatim as a pattern: state the safety guarantee once,
  visibly, right where the risk would otherwise cause hesitation.
- **Campaign list / management view** (`Your Campaigns`) has real, useful filter chrome:
  campaign-name search, start/end date range, a full status checklist (Completed / Running /
  Paused / In review / Failed / Saved as draft / Deleted), an ad-performance metric filter
  (`Filter by... < = > value`), column customization, and Excel export — a notably more complete
  filter/management surface than what Campaign Performance currently offers per the CLAUDE.md
  page list.
- **Special ad category checkbox** ("I am creating a campaign for ads in a special ad category...
  Ads related to credit, employment, or housing") sits right on the campaign-name step, not
  buried later — consistent with what `facebook_service.py` already handles server-side
  (`FINANCIAL_PRODUCTS_SERVICES`), just a confirmation the field is real and front-loaded in a
  live competitor tool too.
- **Onboarding questionnaire** (5 questions, one revealed at a time as each is answered, all
  collapsing into a summary line once done) — a clean progressive-disclosure form pattern,
  functionally identical to the "compact pill summary once answered" pattern already logged for
  Birch. Confirms it's a common SaaS-onboarding technique, not one company's trick.

## 5. Overview dashboard

Real, saturated color-blocked KPI tiles (Spend/Clicks/CPC/Conversions/CPA), each a solid color
block (red-orange, blue, orange, purple, dark blue) with a dropdown chevron, sitting directly above
a multi-line performance chart whose line colors match the tiles above them — the same
tile-color-to-chart-line-color linking technique already logged for Birch's Explorer, confirmed as
a repeatable, cross-product pattern rather than one company's trick. Below: three tabs (Ad
Accounts / Latest Campaigns / Latest Drafts), a sortable ad-account summary table, and an
**"Improve Your Performances" gamified checklist** — each unchecked task ("Drive traffic to your
website," "Automatically promote your Facebook posts," "Learn the ins & outs of AdEspresso") tied
to an unlocked trial discount percentage, with a "Do now" button per row. Not directly portable to
an internal tool (no discount to dangle), but the underlying pattern — a persistent progress
checklist that nudges toward full adoption of a feature set — is worth stealing for onboarding a
new Ad Builder user (e.g., Abel), swapping the discount reward for something like "you're now set
up to do X."

## 6. Optimization Rules — a second rules-engine design, worth contrasting with Birch

Structure: **Rule Set** (a named container, shows rollup "Rules inside: N rules" / "Applied to: N
campaigns") → one or more **Rules** inside it. This grouping layer doesn't exist in Birch, where
every rule stands alone.

The rule-authoring UI itself is a genuinely different, distinctive approach from Birch's
labeled-section form: **a single fill-in-the-blank sentence**, read left to right like plain
English, with each clickable token opening its own inline picker:

```
IF the Ad has a CPC greater than 1 $ (...) ,
THEN pause it
APPLY this rule every 1 days, based on the last 7 days of data.
```

- First token: scope (Campaign / Ad / AdSet — identical set to Birch's Campaign/Ad Set/Ad).
- Condition token: opens a metric/operator/value picker inline; a small trash icon removes a
  condition, `(...)` adds another (AND-chained).
- Action token: a plain dropdown, but the **catalog is much narrower than Birch's** — only
  **pause it / increase bid / decrease bid** (3 actions total, vs. Birch's ~15 across
  General/Budget/Bid/Spending-limits/Name-text categories).
- Schedule: two more inline-editable numbers (frequency in days, lookback window in days).
- The same sentence, unexpanded, is also what shows as the one-line summary in the collapsed row
  header — no separate "preview" needed, because the editable form *is* the readable summary.

**Contrast worth internalizing:** Birch's structured form (Filter section → Task section →
Schedule section) scales better to a wide, categorized action catalog and to multiple stacked
conditions/tasks in one rule. AdEspresso's sentence format is more approachable and immediately
readable at a glance, but visibly strains once the action catalog needs to grow past a handful of
options — worth keeping in mind if BHM ever expands past the MVP four actions (Pause/Notify/
Increase budget/Decrease budget) proposed in the bulk-rules brief: the sentence format works
cleanly at four actions, but Birch's form-based approach is the one that scales to fifteen.

## 7. Asset Manager, Report Generator, Product Catalogs

- **Asset Manager**: a genuine file-explorer UI over ad assets — left-side folder tree (per ad
  account, with a nested "Saved Audiences" folder confirming it also stores targeting presets, not
  just creative), a full sortable/searchable table on the right (Name/CTR/Created At/Actions),
  bulk "Actions" dropdown, "Search in this folder" scoping checkbox. More file-manager-like than
  anything BHM's Ad Builder currently has for creative organization (Copy Library and Generated Ads
  are both flat galleries/tables, no folder hierarchy).
- **Report Generator**: a genuine white-label client-report builder — its own 4-step breadcrumb
  (Settings → Layout → Preview → Delivery & Export), network selector (Facebook only currently),
  a scrollable template gallery (blank / bar chart / pie chart / more) with a **live template
  preview pane** next to the picker. This whole surface is agency-shaped (client-facing PDF/deck
  reports) and not something BHM needs internally — flagging its existence, not recommending it.
- **Product Catalogs**: Dynamic Product Ads catalog management, tied to e-commerce. Not applicable
  — BHM doesn't run DPA campaigns.

## 8. Services, University, Collaboration — mostly out of scope, one exception

- **Services**: a paid-services marketplace inside the product itself (Campaign Review $27,
  1:1 Coaching Call $197+) — pure monetization upsell, no design pattern worth borrowing.
- **University**: gated education hub (Courses/Ads Gallery/Webinars/Experiments), paywalled behind
  a separate registration. Not explored past the paywall.
- **Collaboration Hub** — the one worth naming: **Campaign Approvals** ("Create a campaign and
  send an approval request") and **Onboarding Requests** ("Send a request to get access to the
  advertiser accounts"), both currently at 0 for this trial account. This is an agency-to-client
  approval-gate pattern — a designated reviewer signs off on a campaign before it goes live. BHM
  is internal-only, not agency/client, so the literal feature doesn't transfer — but the
  *concept* (a lightweight, in-product approval step before launch) is directly relevant given
  how much of `CLAUDE.md`'s engineering discipline is about pre-launch review gates. Worth a
  passing thought, not a build recommendation.

## 9. A second, deeper pass through the campaign wizard

Confirmed the design language holds across every step, not just Ads Design:

- **Placement & Previews** (end of Ads Design, easy to miss by scrolling past it quickly): a
  per-placement checklist (Desktop Feed, Instagram, Instagram Story, Messenger Home, Right Column,
  Marketplace — each tagged Desktop/Mobile) with a checkmark toggle per row and an inline collapsed
  live preview beneath each one — a second preview surface in addition to the "Show All" modal
  from §3, this one scoped to a single placement rather than the whole combinatorial batch.
- **Goal Tracking** (also end of Ads Design): three checkboxes — Track with Google Analytics, Add
  extra options to your URL (a UTM-style parameter builder), Track goal conversions with Facebook
  Pixels — surfaced as a first-class step in ad creation, not an afterthought. Directly resonant
  with BHM's own "`session_id` passthrough is non-negotiable" doctrine: this is what "make
  attribution setup impossible to skip" looks like as a concrete UI section.
- **Audience step**: standard Meta targeting (Location, Demographics, Detailed Targeting with an
  "all of above / any of above" match-logic toggle, Custom Audiences), plus **Single Audience vs.
  Test multiple Audiences** — a mode that lets you split-test several *saved* audiences within one
  campaign, a targeting-level combinatorial axis that's separate from (and stacks with) the
  creative-level combinatorics in Ads Design. The right rail mirrors the same running-total
  pattern as the variation counter, but for reach: **"Audience — 216.2M – 254.4M people"**, with a
  full itemized plain-English breakdown underneath ("Location - living in United States," "Age:
  25-65+," "Placements: ...") that updates live as fields are filled in.
- **A genuinely new mechanic**: an interstitial modal, **"What do you want to test?"**, appears
  between Audience and Budget & Bidding. It offers targeting dimensions (Gender, Relationship
  Status, Placement — each tagged with how many variants exist, e.g. "Relationship Status (12)")
  as one-click toggles, and shows the exact same style of live combinatorial math as the creative
  step: **"1 creatives × 1 targets = 1 Ads, Max 250 Ads."** This confirms AdEspresso's
  combinatorial system spans *two* axes — creative permutations (Ads Design) and targeting-variant
  permutations (this modal) — multiplied together into one final ad count, with a hard ceiling
  (250) shown before commit. Neither Birch nor the first AdEspresso pass surfaced a targeting-level
  testing axis; this is the single most novel mechanic found in this second pass.
- **Budget & Bidding**: Budget (Total vs. Per day toggle), a "Use Facebook campaign budget
  optimization" checkbox with an explicit cross-reference — *"Rules for optimizing Ad Set budget
  will not be applied to CBO campaigns"* — that proactively tells you a setting here will silently
  disable a DIFFERENT feature (Optimization Rules, §6) if left checked. That's a genuinely good
  detail: surface a cross-feature conflict at the moment it's created, not as a support ticket
  later. Schedule (start/end date-time pickers), Optimization dropdown, and an EU-audience
  compliance banner (not relevant to BHM's US-only traffic policy).
- **The right rail is the single strongest pattern in the whole app.** By the Budget & Bidding
  step, it shows a persistent, accumulating summary of every commitment made so far — creative
  variation count, audience reach + itemized targeting, and budget/schedule — all visible
  simultaneously, growing as you move through the wizard. This is meaningfully different from
  (and arguably better than) a single review screen at the very end: at every step you can see
  the full running cost of your decisions, not just the current step's inputs.
- **Publish step**: not reached — stopped deliberately once Budget & Bidding confirmed the pattern
  held, to avoid any risk of an accidental real launch.

## 10. Not explored

- The Publish step itself (final review + launch screen).
- "Design an ad" built-in creative editor.
- "Reuse existing posts" and "Test Ad Templates" creation modes (only "Create all permutations"
  walked through, twice).
- University content past its registration paywall.
- Anything requiring an actual e-commerce product feed (Product Catalogs).

## 11. One UI bug worth flagging (not fixed, just noted)

The top-left "Search a campaign" quick-search box got stuck on a permanent "Searching..." state
with no results ever rendering, on the second attempt to verify test-campaign cleanup. The
Facebook Campaigns page's own filter form (name + status checkboxes + Apply Filter) also didn't
visibly refresh its result table after several clicks in this session — either a real bug in a
13-day-old trial account, or a caching/timing quirk specific to this session. Not investigated
further since it didn't block confirming the actual goal (no draft was ever saved via "Save As
Draft" in either wizard pass, which is the only action that would have created a persistent
artifact).

---

## Unrelated finding surfaced during this session, verified separately

AdEspresso displayed a banner: *"Effective August 6, 2026, Meta requires administrators to
manually activate certain data breakdowns, such as 'Impressions by Device', directly in Ads
Manager. This opt-in must be completed for each ad account; if no action is taken, this data will
no longer populate."*

**Confirmed real** against Meta's own developer documentation (not just AdEspresso's banner or
third-party blog summaries):
- [Marketing API — Breakdowns](https://developers.facebook.com/docs/marketing-api/insights/breakdowns/) — "This breakdown may be unavailable for some ad accounts. If a synchronous request returns no results, the account administrator can opt in to this breakdown via Ads Manager, or you can retrieve the data through an asynchronous report job." (effective August 6, 2026)
- [Marketing API — Out-of-Cycle Changes 2026](https://developers.facebook.com/documentation/ads-commerce/marketing-api/out-of-cycle-changes/occ-2026) — same change, same effective date, same opt-in mechanism.

**Checked against the Ad Builder repo:** `grep` across `backend/app` found no use of
`impression_device` or the affected breakdown anywhere — the only "breakdown" hit was
`_combine_event_breakdowns` in `pnl.py`, which is unrelated (Everflow/CAPI event data, not a Meta
Insights API breakdown). **This change does not currently affect the Ad Builder.** Worth
remembering if a future feature ever pulls device-level Meta Insights — silent empty-array
failures (not an error) are the actual risk per Meta's own docs, exactly the kind of thing
`CLAUDE.md`'s "Common Failure Patterns" section is built to catch.
