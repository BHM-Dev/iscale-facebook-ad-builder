# Birch (Revealbot) — Design Reference Capture

Full walkthrough of `app.bir.ch`, live account (RHO 4 – Commercial), 2026-09-11. No rules were
saved/activated, no real Drive folders were connected. This is a raw capture for design reference
— not a build brief. Pulling from it into Ad Builder tweaks is a separate decision per screen.

---

## 1. Global chrome

- **Top bar:** near-black (#0d0d0d-ish), 48px tall. Left: small gradient-diamond logo mark (blue
  gradient outline) + workspace name in medium-weight sans-serif, white text. Center: flat tab nav
  (Home / Performance / Stage / Hub) — plain text, active tab gets a white underline, no pill/box
  background. Right: product name + a gray "Beta" pill badge next to it, doubling as the button
  that opens the AI slide-out panel (see §5).
- **Left icon rail** (only present inside Performance's sub-areas, not Home/Stage/Hub): white
  background, ~40px wide, 4 icons stacked with generous vertical gaps, no text labels — hover
  reveals a small dark tooltip pill with the label. Active icon gets a dark rounded-square
  background (not a colored highlight — plain charcoal fill, high contrast). Icons seen: lightning
  bolt (Automated Rules), image/frame (Explorer), play-in-square (Post boosting), bell (Activity).
- **Persistent bottom bar:** thin dark strip, marketing/promo message (event/webinar plug) + a
  bright yellow-gold "Register Now" pill button. Present on every screen, doesn't scroll away.
- **Support widget:** circular dark bubble, bottom-right, small red unread-count badge. A proactive
  greeting chat bubble ("Hi Steven, welcome to Birch 🚀 How t...") auto-appears near it — text
  chat, not the AI assistant (separate system from the Birch AI panel).
- **Color palette (visual read, not exact hex):** near-black/charcoal for chrome and primary
  buttons; white content background; a warm canary-yellow as the brand accent (logo bird mark,
  promo banner, "Easy to start" tags sometimes); soft pastels used ONLY for categorization — pink,
  purple/lavender, and yellow-gold as card-header background tints (Rules strategy cards); green
  for positive/success state and "benefit" tags; red for negative/warning deltas; blue for links
  and one chart series color. No gradients in UI chrome itself (only in the small logo mark).

---

## 2. Home / AI-first landing (`/overview`)

- The **entire homepage is the AI assistant**, not a corner widget. Big centered heading "What
  should we work on?" over a single input box labelled "Ask Birch AI" with a small attachment/tool
  icon inside it and a circular send button.
- Below the input: two tabs, **Suggested** and **Meta Ads MCP**, each showing a short list of
  concrete, specific prompt suggestions (not generic examples) — e.g. "Recommend optimizations
  based on the last 30 days' performance," "Suggest 3 starter rules for a new ad account." These
  change per page (Post Boosting's version swapped in "Compare all connected platforms: where are
  we scaling faster?").
- A small persistent "Book a demo with a Birch expert" card, top-left, with an avatar photo — a
  soft, always-available upsell that doesn't block anything.
- **"Highlights" section** below the AI box: KPI cards in a horizontal row (Monthly spend, a Meta
  metric), each with a "..." overflow menu and a single full-width CTA button pinned to the card's
  bottom edge ("Set budget limit," "Define target value"). Further cards to the right are
  **blurred, not hidden** — real card shapes (bar-chart mockup, small badge icons) rendered at low
  opacity behind an "Add ad accounts" CTA. This "show a ghost of the real thing, don't show
  nothing" pattern repeats everywhere in the app (see §6).
- Left sidebar unique to this page: chat history (Search chats, Overview, Business context, Meta
  Ads MCP with a Beta tag, then a Chats list with "+ New chat"). This is the same left-rail
  position as the icon rail elsewhere, but reskinned as a chat-app sidebar when the AI is the
  primary content.

---

## 3. Automated Rules (`/automation/facebook`)

Already covered in the prior feature brief (`AdBuilder-BulkRules-Feature-Brief.md`) for
mechanics. Visual/layout details not in that brief:

- Landing screen headline "Let's begin optimizing your ads" (plain, friendly, not a marketing
  tagline) + one-line explainer directly under it.
- **Three strategy template cards** in a row, each: colored header block (pink/purple/gold, one
  per card) with a centered icon in a small white rounded-square "chip" that casts a soft shadow —
  the icon sits half-overlapping the card's colored header and white body, a common
  "badge-straddles-the-seam" card pattern. A green "Easy to start" pill badge floats in the
  top-left corner of the first card, overlapping the edge.
- Card body: bold title, "Key metrics" label + gray rounded-pill tags, "Benefits" label +
  green-tinted rounded-pill tags (so viewers immediately see the difference between "what it
  tracks" and "what you get" without reading a paragraph).
- CTA at the bottom of each card is a **soft/secondary button** (light gray, full width) — the
  page reserves the solid black button style for the one primary action at the top of the screen
  ("+ Create rule"). Consistent rule across the whole app: one black pill button per screen for
  the single most important action; everything else is gray/secondary or a plain text link.
- Selected/default card gets a **thin green border ring** around the whole card — a subtle
  selection indicator rather than a checkmark or color fill.

---

## 4. Explorer / reporting (`/ads-explorer`)

- Marketing/empty splash: headline "Marketing analytics tailored to you. And by you," a hand-drawn
  yellow scribble/swoosh graphic behind a floating mock UI card (shows the filter-builder and a
  ranked ad list, exactly what the real feature looks like) — the empty state IS a screenshot-like
  preview of the real feature, not abstract illustration.
- **"One click, instant insights"** row below: pre-built report shortcuts as horizontal cards —
  colored icon badge + label + right-chevron. Simple, scannable, no borders between them beyond
  card separation.
- **New report modal:** two-pane layout. Left: vertical list of templates, each row = colored icon
  + name, hover/selected state = light gray row background. Right: for the selected template,
  shows its name, a one-sentence description, a "Use case" heading with a longer plain-English
  paragraph explaining exactly what triggers the report, then the ad-account selector, then a
  black "Use this template" button pinned bottom-right. This description-before-commit pattern is
  worth stealing directly — it removes the guesswork of "what will this actually show me."
- **Report builder screen**, once generated:
  - Collapsible info banner at the top (one-line summary, chevron to expand/collapse) — persists
    from the template description so context isn't lost after generation.
  - Scope shown as compact pills: ad account pill, filter-summary pill ("Campaign status is active
    + 1 other filter") that expands into the full filter editor on click, rather than always
    showing the full editor.
  - **The filter-condition-builder component is reused identically between Rules and Explorer** —
    same AND/OR left rail, same metric/time-window/operator/value row layout. One component, two
    features. Strong signal this app has genuinely componentized its most complex UI piece rather
    than rebuilding it per feature.
  - **Processing state:** communicated redundantly in three places at once — page subtitle
    changes to "Processing...", the top-right action button becomes disabled and relabels itself
    "Settings applied" with a small pulsing blue dot, and the content area shows a spinner +
    "Getting ads data" + "It can take a few minutes. You can leave the page and come back later."
    No ambiguity about whether it's stuck.
  - **Chart + creative thumbnails + table, combined:** small square creative thumbnails sit above
    the line chart as a legend-like strip. Hovering a point on the chart shows a rich tooltip card
    — creative thumbnail, ad name, variant, date range, and the metric value with a colored badge
    — not just a bare number.
  - **Table row/chart series color-linking:** each table row has a checkbox tinted to match that
    ad's chart line color (blue/red/purple) — checking/unchecking a row visually ties directly to
    which line is on the chart. A small, cheap, very effective linking technique.
  - **Comparison-cell pattern in the table:** every metric column shows three stacked lines per
    cell — "Last 7 days" value, "Previous period" value, "Change" (colored, arrow-prefixed
    percentage). This gives period-over-period context without adding extra columns. Directly
    relevant: your Dashboard/Campaign Performance tables currently show one flat number per
    metric, no built-in comparison.
  - A pinned bold "Total" row at the top of the table aggregates all visible rows.
  - "Columns 2/9" control top-right of the table — explicit column visibility picker, so the
    table can start dense but be trimmed to what the buyer actually cares about.
- **Feature-announcement tooltip pattern** (seen once, for "Ad groups" mode): a modal with a
  simple two-panel before/after diagram — colored swatches standing in for filters/ad groups,
  labelled underneath, one paragraph, one "Got it!" button. No screenshots, no video — a
  schematic diagram is enough to teach a new report mode in five seconds.

---

## 5. AI assistant as a slide-out panel (not a floating widget)

Clicking the "Birch AI" label in the top-right nav (not a separate floating button) slides a
panel in from the right edge of the screen:

- Header row: "New chat ⌄" (dropdown — presumably chat history/switch), an expand-to-fullscreen
  icon, and a close (X).
- Body: same "What should we work on?" + Suggested/Meta Ads MCP prompt-chip pattern as the Home
  page — the exact same component reused, just narrower.
- Input row: text field, two small icon buttons inside it (one looked like an attach/plugin icon,
  one a colored brand icon — likely a connected-tool indicator), send button.
- Footer disclaimer, small gray text: "Birch AI can make mistakes. Double-check responses" —
  always visible, not just on first use.

This is a materially different pattern from your current `AskAiWidget.jsx` (floating bottom-right
circular button). Birch's AI is reachable from a persistent, always-visible nav item and opens as
a full-height right-edge panel, not a small popover anchored to a corner button. Worth weighing:
a nav-triggered slide-out reads as "a real feature," while a floating corner bubble reads as "a
bolt-on." Not recommending either as strictly better here — flagging the alternative since it's a
live, considered design choice by a company that ships this as their core product.

---

## 5b. Stage's actual bulk-build screen (follow-up session, real test data)

Set up a disposable test folder (`Birch Stage Test/` with two niche subfolders, two placeholder
images, and a planning sheet) and connected it live to see the real mechanic — not guessing from
the marketing splash this time.

**Two real bugs/quirks found doing this, both worth knowing about:**
- The "Paste Google Drive folder or file links" input on the actual Stage canvas would not accept
  synthetic input at all — not typed keystrokes, not a programmatic value-set, not even a
  simulated Cmd+V. Had to genuinely copy the link from a real page (a Sheet cell) and paste with a
  trusted OS-level paste. The *first* folder-connection screen (`/stage/connect-folders`, part of
  onboarding) did NOT have this restriction — same-looking input, different behavior. Inconsistent
  input-hardening between two screens that look identical is itself a small paper-cut worth
  avoiding in your own build.
- A validation-error toast ("No valid Google Drive links found in the selected rows. Check the
  Google Drive link column mapping.") rendered clipped behind their own sticky bottom promo bar —
  a real z-index/stacking bug in production Birch, not something I misconfigured. Good reference
  point: even a mature product ships this kind of overlap; worth a deliberate check on your own
  toast/banner z-index against any sticky footer.

**The real per-row schema, once a Google Sheet is connected** (`Continue with Google Sheets` →
share with a service-account email → pick the sheet → **Sheet settings** modal):
- Ad platform tabs at the top: Meta / TikTok / Snapchat — one config screen, three destinations.
- Sheet picker + "First row is a header" checkbox + "Show all columns in preview" checkbox.
- **Column mapping**, one row per ad field: `Google Drive link` (tagged **Required**), `Primary
  text`, `Headline`, `Description`, `Website URL`, `Display link`. Three of these (Primary text,
  Headline, Description) have a **"+" button to map multiple columns to the same field** — that's
  how "multiple text variations" (a listed Feature on the same screen) actually works: extra
  sheet columns become extra copy variants for the same ad, no separate step.
  - Each dropdown is a plain **column-letter picker (A, B, C...)**, not the actual header text —
    a real friction point. You have to remember "Headline is column B" instead of the mapper just
    showing "Headline" as an option. A smarter mapper reading the header row and offering the
    header labels directly would remove a whole class of mis-mapping mistakes.
  - Right-side static reference panel, always visible during mapping: **Features** (Multiple text
    variations, Auto-grouping by placement, Advantage+ creative, Dynamic creative) and **Ad
    formats** (Single image/video ads, Multi-advertiser ads, Partnership ads) — tells you what the
    build supports before you've mapped anything, so you're not guessing at capability.
- **Select rows**: All rows / Specific range / **Rows matching a filter** (the literal
  "filter by a status column to choose what goes live next" promise from the marketing splash).
  Once rows validate, you get a clean preview table using your *mapped field names* as headers
  (Google Drive link / Headline / Primary text), not raw column letters — so the friction above is
  front-loaded into the mapping step only, not carried through the rest of the flow.
- **"Create Meta ads" build card** — the actual bulk-creation config, and the closest direct
  analog to `BulkAdCreation.jsx`:
  - **"How to create ads"** dropdown, three modes, each named for its exact real-world effect:
    **Duplicate ad set** (clone one ad set, put all N ads inside it — one new ad set, N ads),
    **Duplicate ad set for each media** (clone a separate ad set per file — N new ad sets, one ad
    each), **Add to ad set** (append ads into an ad set that already exists, no cloning). Your
    current `BulkAdCreation.jsx` only does the equivalent of the first mode, and only within a
    single ad set already selected upstream in the wizard — the "one ad set per creative" and
    "append, don't duplicate" cases aren't options today.
  - A **live, plain-English summary line** directly under the mode picker — "Creates 2 ads in 1
    new ad set" — recalculated from your actual file count and mode selection before you commit to
    anything. This is the single most portable detail in this whole capture: state the literal,
    computed outcome in one sentence, right next to the control that produces it.
  - **"Ad set" section**, expandable, with its own one-line purpose caption ("Used as a source for
    new ad sets, inheriting all settings. Must contain at least one ad — used to create new ads"),
    then a **cascading picker**: Ad account → Campaign → Ad set → Template ad, each disabled until
    the one before it is chosen, each with its own short caption ("Template ad — New ads inherit
    copy, links, and CTA from the template ad"). The Campaign picker is a real, searchable
    dropdown against live data — confirmed pulling genuine RHO 4 campaign names (Horse & Stable,
    Painting Contractors, Janitorial Services, Welders, Auto Dealership, Barber Shops, etc.).
  - "Preview ads" and "Review & Create" buttons, both disabled until the ad-set chain is complete
    — the same gating pattern as the rest of the app.
  - Footer: file count + total size + a "Limitations & requirements" doc link, permanently visible
    at the bottom of the config card.

Backed out before "Review & Create" — nothing was actually launched to the live RHO 4 account.

---

## 6. Cross-cutting patterns worth naming explicitly

1. **"Ghost of the real thing" empty states.** Every empty/locked state we saw (Home's blurred
   highlight cards, Explorer's floating mock-UI illustration, Activity's blurred sample event
   list, Post boosting's blurred mock post) shows a low-opacity, real-shaped preview of what the
   feature produces, rather than a blank box or generic icon. It answers "what do I get" before
   the user commits to connecting anything.
2. **One primary button per screen.** Solid black/dark pill = the one thing you're meant to do on
   this screen. Everything else is a light-gray secondary button or a plain text link. This
   consistency across totally different features (Rules, Explorer, Stage) is what makes the app
   feel calm despite doing a lot.
3. **Compact pill summaries that expand into full editors.** Filters, date ranges, and metric
   pickers default to a one-line pill ("Campaign status is active + 1 other filter") and only
   expand into the full multi-row editor on click. The editor is never shown by default once
   there's a saved state — this is a big part of why screens with genuinely complex configuration
   (Rules, Explorer) don't feel cluttered.
4. **Redundant, layered status communication.** Anything that takes time (report generation,
   processing) is signaled in at least two places simultaneously (page subtitle + button state +
   content-area message), so "is this working?" is never a real question.
5. **Icon rail with tooltips, no persistent labels.** The 4-icon left rail has no text at rest;
   hover reveals a tooltip. Keeps the rail visually quiet at 40px wide instead of a wider
   labeled-icon sidebar.
6. **Description-before-commitment.** Both the report-template modal and the strategy cards show
   a plain-English explanation of exactly what a preset does before the user picks it — not just a
   name and an icon.

---

## 7. Screens explored, and what's left

- **Stage's bulk-build screen** — now fully explored with real test data (see §5b). A disposable
  test folder/sheet was created under Steve's own Drive (`Birch Stage Test/`, two subfolders, two
  1x1 placeholder PNGs, one planning sheet) and shared with Birch's Stage service account so the
  full flow could be walked end to end. Nothing was actually created on the live RHO 4 account —
  backed out at "Review & Create."
- **Hub** — re-confirmed on a second pass: it's the "Signals Gateway" server-side tracking/CAPI
  product (same split-screen dark/light onboarding pattern as everywhere else in the app), not
  related to ad creation. Genuinely out of scope for this design pass, not skipped by oversight.
- **Stage's own local settings** — checked: gear icon opens a small "Shared folders" panel
  (folder name + Unlink action, "Add more folders" link). Feature-scoped, not a global
  account/billing/team settings area — didn't find or look further for the latter, since it's low
  priority for a design-tweak pass focused on bulk ad creation and layout.

**Cleanup note:** the test folder, subfolders, placeholder images, and planning sheet created for
this session are still sitting in Steve's Google Drive (root-level `Birch Stage Test/`) and still
shared with `birch-stage@revealbot-151623.iam.gserviceaccount.com`. Harmless to leave — say the
word if you'd rather I delete them now that the walkthrough is done.
