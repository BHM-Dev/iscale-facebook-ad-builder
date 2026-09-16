# Blip (app.withblip.com) — Competitive Research for Ad Builder

Live walkthrough of Blip logged into our real "RHO 5 / RHO 4 / RHO 3 / RHO-Commercial /
ResourceHelpOnline / DIN Auto Insurance" ad accounts (already connected on our account — this is a
tool BHM already has trial access to, 7 days left on the free trial as of 2026-09-15). Covers the
full onboarding tour, the single-page ad launcher, the Preferences (account defaults) page,
Billing/pricing, and the Analytics dashboard.

## TL;DR — what's genuinely worth stealing

1. **Anomaly Thresholds → Slack, configurable per account** (CPA Spike %, Overspend %) — this is
   the productized version of our own hourly Everflow dip monitor / auto-pause-on-0%-CR feature
   (see `project_adbuilder_offer_performance_monitor.md`), except Blip ships it as a native,
   self-serve, per-account setting with a one-click "Get Anomaly Alerts in Slack" connector. We
   built something similar bespoke; Blip made it a first-class configurable primitive.
2. **Poor Performing Ads panel** — auto-flags ads with spend > 0.5x account avg CPA, running 14+
   days, below account baseline. Shows the account's own 14-day avg CPA as the benchmark, lists
   each flagged ad with spend/CPA/age, and puts a one-click **Pause** button (+ bulk-select) right
   next to each one. Confirmed live and real — it flagged 2 real underperforming ads in our own
   RHO 5 account during this walkthrough (didn't pause them, this was read-only exploration).
3. **Meta Creative Enhancements exposed as ~20 individual toggles** in account Preferences —
   Overlays, Visual Touch-ups, Text Improvements, Enhance CTA, Brightness/Contrast, Relevant
   Comments, Expand Image, AI Text Generation, Translate Text, Reveal Details Over Time, AI Show
   Summaries, Image Animations, Flex Media, Dynamic Descriptions/Overlays (catalog), Highlight
   Carousel Card, Profile End Card, Multi-advertiser ads. This is Meta's own Advantage+ Creative
   feature set, unbundled and given individual on/off switches at the account-default level. Worth
   checking whether we expose any of these — if not, it's a real gap, not just a nice-to-have.
4. **Account-level default naming convention + copy templates + link/UTM defaults**, all with
   "auto-import from your account" buttons (`Auto Import Copy Variants`, `Import Links from Recent
   Ads`) that pull real existing ad copy/links out of Meta to seed the templates — instead of
   making you type from scratch. Directly relevant to the naming-templates feature we just shipped
   (commit `2931145`) — Blip's version lives at the *account* level (shared default) in addition to
   the per-ad override, which addresses exactly the "per-browser storage, not shared" gap our Joel
   review flagged.
5. **Single-page ad launcher, no wizard.** Campaign/Ad Set selection, Page/IG, Ad Name, Copy
   Template, Primary Text, Headlines, Link+CTA, Media upload — all on one scrollable page, not our
   Campaign → Ad Set → Creative step flow. Faster for a media buyer who already knows what they
   want; less guided for someone learning the tool. Worth a conscious decision, not an accident.
6. **Import from most recent ad** — one dropdown + Import button pulls the most recent ad's full
   copy/link/page/IG selection into the form as a starting point for a new ad. We don't have an
   equivalent "clone my last ad's settings" shortcut today.

## Full feature walkthrough

### Onboarding tour (6 steps, all real features, not marketing fluff)
- **Post ID Scaling** — scale a winning ad across ad sets by Post ID without losing social proof
  (existing likes/comments carry over). This is Meta's own "use existing post" mechanic, surfaced
  as a first-class scaling workflow with a searchable table of past ads (thumbnail, ad name, ad
  set, 7-day spend) to pick from.
- **Instagram Scaling** — promote organic Instagram posts/Reels/tagged collab posts as ads directly.
- **Split Ad Data Across Media Files** — upload once, split into different ad sets with different
  naming/copy per split ("Uploads Preview: 6 files selected" → assign different destinations).
- **AI Auto Grouping** — automatically groups different-aspect-ratio statics that belong to the
  same ad (e.g., a 1:1 and a 9:16 crop of the same creative) instead of treating them as 2 ads.
  Explicitly "only works for images."
- **Job Queueing** — launches ads as background jobs with a live progress list (`4 Ads successfully
  posted`, `Posting 4 ads to 2 adsets — 40%`, per-file Facebook processing status, `Queued 3 ads`)
  so you don't wait on one ad set before the next starts.
- **Analytics & Recommendations** — one-click action cards: "Campaign ROAS is 35% above account
  average → Scale", "These ad accounts might be worth consolidating → Join", "Scale these 8 winner
  ads → Duplicate", plus "View Trending Creatives", a Daily CPA by Campaign mini-chart, and buttons
  for Account Audit / Anomaly Detection / Request from Slack.

### Upload sources (Manage Upload Sources)
Local PC, Google Drive, Dropbox, Frame.io, Instagram Posts, Ads Manager Media Library — all listed
as connectable sources with checkboxes, and "Choose Files from Google Drive" / "Choose Files from
Dropbox" buttons sit directly in the main upload dropzone (not buried in a separate picker flow).
Copy: *"Google Drive/Dropbox/Frame files upload 5X faster."* We already have Drive sync
(`project_adbuilder_gdrive_creative_sync.md`) — Blip's Dropbox/Frame.io support and the
inline-in-the-dropzone placement of the picker buttons are the incremental deltas.

### Single-page ad launcher (imported a real ad from ResourceHelpOnline account to see it populated)
- Ad Account → Campaign → new-or-existing Ad Set, with a "Duplicate Existing ads" toggle.
- "Add default settings for this account to speed up your workflow" nudge banner with an inline
  "Add Settings" shortcut straight to Preferences — contextual, not just a settings-page link.
- Page/IG selection, "Add Partnership" toggle (fetches linked partners for tagged collab ads).
- **Set Up Ad Name Formula** button inline in the form (not just in Preferences) — same idea as our
  naming templates but discoverable at the point of use.
- Copy Template selector + "Save as New Template" inline.
- Primary Text (multi-variant, "+ Add text option"), Headlines (multi-variant), optional
  Descriptions.
- Link URL — auto-applies UTMs from Preferences; imported link showed real RedTrack-style macros:
  `https://www.bhgtrack.com/cmp/RMJWTH/24PJ1S2/?uid=1991&sub1={{adset.name}}_{{ad.name}}` — same
  macro-passthrough pattern as our own `Meta url_tags field placement` doctrine
  (`reference_meta_url_tags_field.md`), confirming this is standard practice, not something unique
  to us.
- CTA dropdown, Upload Media (drag-drop + Drive/Dropbox buttons), Publish Ads button, Ad Status
  (Active/Paused at launch — same as ours), "Disclose AI Media" checkbox (Meta's AI-content
  disclosure flag — worth confirming we expose this), "Don't clear media after publishing ads."

### Preferences (account-level defaults) — `/settings`
- Default linked Facebook Page + Instagram Account per ad account.
- Copy Templates: up to 5 Primary Texts + 5 Headlines per template, with an **"Auto Import Copy
  Variants"** button that pulls real existing variants from the account instead of hand-typing.
- **Default ad naming conventions** — slash-command (`/`) variable insertion + "Custom Variables"
  button, same UX pattern as our `NamingTemplateField` but at the account-default layer.
- Link Parameters — saved default Landing Page Links + **"Import Links from Recent Ads"** button +
  dedicated "Set Up UTMs" flow + optional Display Link.
- Default CTA (account-wide fallback if not overridden per-ad).
- **Meta Creative Enhancements** — full toggle list (see TL;DR #3), grouped into General / Catalog /
  Carousel, plus a "Toggle All" master switch and a red inline warning on AI Text Generation
  ("might not be available in some ad accounts, which can lead to errors while launching ads" — a
  nice honest UX touch, flagging a real Meta-side limitation up front instead of failing silently).

### Billing (`/settings?tab=billing`)
Three tiers, **identical feature set across all of them** — the only differentiator is ad account
count:
| Plan | Price/mo | Ad Accounts | Everything else |
|---|---|---|---|
| Blip Starter | $49 | 1 | Unlimited ads, instant setting sync, analytics access, unlimited team seats |
| Blip Light | $199 | Up to 5 | same |
| Blip Pro | $370 | Unlimited | same |

Unlimited team seats on every tier — no per-seat upcharge. Custom pricing available via email/chat
for accounts that don't fit a tier. Worth noting for how we'd think about our own pricing if this
were ever externalized — Blip's model says the thing that scales cost is ad-account count, not
seats or ad volume.

### Analytics (`/analytics`)
- Per-account dashboard: Spend / Conversions / CPA / CPM / Link CTR / Cost-per-Link-Click tiles,
  each with a color-coded period-over-period % delta (e.g., "Spend $1.3k ↓44.1%") — clean
  at-a-glance format, comparable to what we'd want on our own P&L/offer-performance views.
- Weekly CPA by Campaign chart with a dashed benchmark line ("AF Purchase Campaign CPA Goal").
- Traffic Metrics (Cost Per Link Click, CPM) with hover tooltips showing Spend/Impressions/Link
  Clicks/Conversions for the hovered week.
- Spend Breakdown by Placement/Age/Gender, toggle $ vs %, broken out per platform+placement
  (facebook·feed, facebook·facebook_reels, audience_network·an_classic, facebook·facebook_stories,
  instagram·instagram_reels).
- Funnel Health — Frequency + First-Time Impression Rate over time, with per-week tooltip
  (Impressions, Reach).
- **Budget Recommendations** tab — gated behind setting a Target CPA first ("compare each campaign
  against your benchmark").
- **Poor Performers** tab — see TL;DR #2. Real, live, working, one-click Pause.
- **Trending Creatives** — ads with >35% spend growth over the last 7 days vs. the prior 7 days
  (automatic winner detection; showed "No trending creatives in the last 7 days" for this account
  at the time of the check).
- **Reports menu**: "Audit Account Health", "Diagnose Poor Performance", "Summarize Recent
  Changes" — read as AI-generated narrative reports on demand (didn't run one, but the menu
  structure alone tells us the shape: on-demand LLM summarization over the account's own data,
  which is exactly the kind of thing we could bolt onto our own P&L/offer-monitor data).
- **Optimization Focus config** (gear icon next to "Optimization Focus: CPA/ROAS" toggle): per-account
  CPA vs. ROAS focus, Conversion Event picker, Target CPA field, and the **Anomaly Thresholds**
  block — CPA Spike Threshold % (default 50, alerts when CPA rises >X% vs. 7-day avg) and Overspend
  Threshold % (default 150, alerts when daily spend exceeds X% of ABO budget) — both wired to a
  native "Get Anomaly Alerts in Slack" connector button.

## Deep-dive: built and published a real (paused) test ad end-to-end

Went past the click-through tour and actually ran a test ad through Blip's full create → publish
flow on our real DIN Auto Insurance account, into the live "US - BROAD" ad set (5 other active ads
running), to see every field-level behavior. Ad Status was set to Paused before publish — $0 spend,
never served, confirmed after the fact in both Blip's own ad list and Meta's Marketing API response
(`Pending Review`, `$0.00`).

- **Ad Name Formula variable set is bigger than it looks in the tour**: File Name, File Type
  (Static/Video), Date (DD/MM/YYYY), Date (DD-MMM-YYYY), Date (custom — user enters their own
  format string), Iteration (1/2/3...), URL Slug (text after the last `/` in the landing URL), and
  an **Ad Type (CAR/FLEX)** token specific to the vertical. Resolves to `{{Variable Name}}` syntax
  — double-curly, human-readable names — versus our own naming-templates' single-brace `{token}`
  convention. Not better or worse, but worth knowing before we add our own tokens so ours don't
  collide visually with anyone copy-pasting a Blip pattern into our tool.
- **Grammarly is wired directly into Primary Text and Headline fields** — a live suggestion badge,
  not a mockup. Small thing, but it's a real quality-of-life detail Joel would notice immediately
  if we had it and stopped having it.
- **Publish button has a hidden second mode**: the chevron next to "Publish Ads" opens "Save Draft"
  (named, revisitable, doesn't touch Meta) and "Copy Preview Link" (a shareable link to preview the
  ad before it's live — built for getting sign-off from someone who isn't in the tool, e.g. Steve
  or a client, before it actually launches). We have no equivalent today; everything we build goes
  straight to a real Meta object once Publish is clicked.
- **The "Duplicate Existing Ads" picker doubles as a live ad-audit table** — toggle it on, pick a
  campaign + ad set, and it returns every ad in that ad set with thumbnail, name, 30-day spend, and
  live Meta status (`Pending Review`, `Campaign Paused`, etc.) in one screen, independent of the
  Analytics section. Confirmed our test ad appeared here within seconds of publishing, correctly
  labeled.
- **File upload is a real native file input**, not a fake/CSV-only dropzone — confirmed by
  uploading a real local file and watching it flow through to a live Meta creative object.

## Where this maps onto our own roadmap
- **Naming templates (`2931145`)**: Blip's account-level default + auto-import-from-recent-ads
  pattern is the fix for the "per-browser storage, not shared between Joel/Abel" gap the Joel-POV
  review just flagged. Worth considering as the v1.1 direction instead of a from-scratch redesign.
- **Offer-performance monitor**: Blip's Poor Performing Ads panel + Anomaly Thresholds are close to
  a productized version of what we built bespoke. The "Slack alert" delivery mechanism, the
  configurable %-thresholds, and the one-click Pause action are all worth comparing line-by-line
  against our own auto-pause-on-0%-CR (currently off) design.
- **Drive sync**: confirmed again (as with Adnova) that Google Drive integration is table stakes
  among the top ad launchers, not a differentiator — Blip also does Dropbox and Frame.io, which we
  don't.
- **Meta Creative Enhancements toggle exposure — confirmed gap, not hypothetical.** Checked our own
  `backend/app/services/facebook_service.py:1434-1478`: the `AdCreative` creation payload sets only
  `name`, `object_story_spec`, `asset_feed_spec` (dual-placement), and `url_tags` — there is no
  `degrees_of_freedom_spec` / `creative_features_spec` key anywhere in the creative or ad payload,
  and no matching UI in `AdCreativeStep.jsx`. Since we never send that field, **Meta silently
  applies its own defaults** (historically mostly ON) to every ad we launch — meaning Meta may
  already be altering Joel's ad text, images, and CTAs today with zero visibility or control on our
  side. Blip's account-default toggle screen is exactly the fix: expose the same ~20 flags at the
  account-preference level, wire `degrees_of_freedom_spec.creative_features_spec` into
  `create_creative()`, and Joel gets the same control Blip gives its users.

## Prioritized recommendations

1. **Add `degrees_of_freedom_spec` support to `facebook_service.py`** — currently a silent gap, not
   a nice-to-have. Even shipping it as "all OFF by default, opt-in per toggle" would put us ahead
   of where we are now (implicit, invisible Meta defaults). This is a trigger-file change
   (`facebook_service.py` + `AdCreativeStep.jsx`) — needs the mandatory 2-agent pre-push review.
2. **Naming templates v1.1** — move from per-browser `localStorage` to an account-level default
   (mirrors Blip's Preferences-page pattern), which directly closes the "why isn't my template
   here" gap the Joel-POV review already flagged on `2931145`.
3. **Poor Performing Ads / Anomaly Thresholds** — worth comparing line-by-line against our
   auto-pause-on-0%-CR design (currently off). Blip's version is simpler than what we built
   (fixed %-threshold vs. 0% CR trigger) but ships with native Slack alerting as a first-class
   setting, not custom plumbing.
4. **Save Draft / Preview Link before publish** — genuinely new idea for us, not something we have
   any version of. Worth scoping separately; it's a real workflow gap for getting sign-off before
   an ad goes live.
