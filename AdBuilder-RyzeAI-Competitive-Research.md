# Ad Builder — RyzeAI Competitive Research (Full Review)

Live walkthrough 2026-09-13/14: signed up for a real RyzeAI trial (`getbusinesscoverage.com`, connected to
the real `RHO - Commercial Insurance` Meta account) and went through onboarding **and every reachable
section of the product** — Home, AI Marketer chat/schedules/templates/reports, Integrations, Brand,
Analytics, Ads, and the paywalled SEO/A-B-Testing tiers. Goal: a complete, item-by-item call on what's
worth adopting into the Ad Builder and what isn't, not just a tour.

## 0. The framing that matters most

RyzeAI is built for **agencies serving external clients**, not an internal media buyer working on owned
media. That single fact explains most of what it has that the Ad Builder doesn't and shouldn't:
client-facing report decks with narrative headlines ("You are not fighting four brands. You are fighting
Restwell Labs"), a "New Client Proposal" pitch-deck template, a "Quarterly Business Review" template,
team-invite/seat management, a tiered SaaS pricing ladder with paid add-ons. The Ad Builder has one
internal user (Joel) reporting to one owner (Steve) inside one company — most of that surface is solving a
problem BHM doesn't have. Read every item below through that filter before deciding what to borrow.

## 1. Onboarding — chat-driven, adaptive, ends in a real deliverable

**BENEFITS THE AD BUILDER: partially — see §5.**

- Conversational, fully skippable at every step: site URL → auto-scraped summary → ad platforms → OAuth
  connect → optional native Claude/MCP connector → optional team invites.
- Live Meta data pull happens *before* calibration questions, not after — the moment the account connected
  it already had $38,039/44-campaigns/30-days.
- Calibration questions **genuinely branch** on prior answers — picking "profit after ad cost and rejected
  leads" triggered insurance-lead-gen-specific follow-ups (CRM matching, acceptance latency, payout
  variance) a fixed form never would have asked.
- Every answer is compressed into a one-sentence rule and written into a `memory` object live, during
  onboarding, not after — see §4.
- A visible, resumable todo list drives the flow, and **its own text updates to reflect what actually
  happened** — when the first-review step was declined, the item reworded itself to "Skip the first account
  review at your request" rather than a generic "done."
- First real deliverable is a chart with an honest caveat baked in ("Raw submissions, not accepted leads"),
  not a vanity number.

## 2. Templates gallery — Monitor / Create / Optimize / Automate / Report

**MOSTLY DOESN'T BENEFIT THE AD BUILDER AS-IS — most of it is Google Ads/SEO-specific or Shopify-specific,
irrelevant to a Meta-only tool. The exceptions are called out below.**

A large pre-built library, filterable by platform (Google Ads, Meta Ads, Google Analytics, Search Console,
Shopify, TikTok Ads), organized into five sections:

- **Monitor**: Organic Traffic Overview, AI Traffic Overview (sessions from ChatGPT/Perplexity/etc. as a
  referral source — not applicable, BHM doesn't run SEO), Product Winners & Losers (Shopify SKU truth —
  not applicable), Paid Ads Overview, All Accounts Overview ("the agency 9am screen across every ad
  account: severity-ranked table with recoverable dollars" — **this pattern is worth stealing**, see §5).
- **Create**: Meta ad creatives, Google RSA copy, **"Create ad angles" — 10 angles mined from real customer
  reviews (pain, desired outcome, objection, hook line)** — a genuinely different copy-research input than
  anything the Ad Builder has (Ad Remix starts from a winning ad image; the Remix drawer starts from a
  manual hook typed by Joel; neither mines review/testimonial text as raw material). **Worth a look**, see
  §5. Also: "Create competitor-inspired creatives" (Meta Ad Library angles → your own creative) — the Ad
  Builder's Research → "Use as Inspiration" flow already covers this ground.
- **Optimize**: almost entirely Google-Ads-specific (Account health audit, Find Google Ads waste, Negative
  keyword sweep, Keyword cannibalization) — not applicable, BHM runs Meta only. "Ad copy audit" (All
  platforms — "every live RSA + Meta ad scored for weak CTAs, missing USPs, thin messaging, LP mismatch")
  is the one Meta-relevant item here and **is a real gap** — the Ad Builder's Copy Library ranks by CPL
  performance only, never a qualitative weakness scorer. Worth a look.
- **Automate**: the section most comparable to the Ad Builder's rules engine — see §4, it gets its own
  section because it's the highest-value comparison in this whole review.
- **Report**: client-facing deliverables (Monthly Client Report, Marketing Audit, Quarterly Business
  Review, Creative Performance Review, SEO Audit, Post-Click Teardown, Competitor Landscape, Media Plan &
  Forecast, New Client Proposal). **Does not benefit the Ad Builder** — per §0, this entire category solves
  an agency-client relationship BHM doesn't have. Steve doesn't need a polished deck pitched at himself.

## 3. Product surface — everything else

**Home** — onboarding checklist + a literal approvals inbox ("Nothing waiting — new findings from your
agent will land here for your decision"). **The approvals-inbox pattern is the single most actionable idea
in this whole review** — see §4/§5.

**Ads → Campaigns** — empty state: *"Create one and the agent sets it up, launches it and reviews it
daily."* Campaigns here are agent-built-and-launched end-to-end from a chat-stated mandate, not
manually assembled by a human with AI assistance. **Fundamentally different operating model from the Ad
Builder** (Joel always drives creation) — not a gap to close, a deliberate philosophy difference. Don't
adopt without Steve explicitly choosing to hand campaign creation to an agent.

**Ads → My Creatives / Ad Templates** — a chat-driven creative generator ("Start from a winning ad in your
niche" is one option among several, not the only path) plus a cross-vertical template gallery (Beauty,
Fashion, Finance & Fintech, etc. — built for a multi-tenant SaaS serving every vertical, not applicable to
BHM's single-vertical focus). **Confirms Ryze also has an optional template-based path**, similar to Ad
Remix — the real difference documented in the Quick Ad brief stands: Ryze's chat-driven from-scratch path
requires no template, Ad Remix's does.

**Analytics → Ads Performance** — a real bug found live, not just a feature to admire: **the persisted
dashboard showed $0.00 spend / 0 results for the same 30-day window the chat agent had just reported
$38,039/44 campaigns on, live, minutes earlier** ("updated 45m ago"). A genuine gap between the agent's
live Meta API tool-calls and whatever separately-synced datastore the dashboard reads from. The Ad
Builder's Campaign Performance page avoids this entire bug class by design — one live query, no separate
ETL layer to drift out of sync. **Worth remembering as the reason not to add a cached/batch layer to
Campaign Performance if anyone ever proposes one for performance reasons.**

**Analytics → Web Analytics** — Ryze's own first-party tracking snippet, installed on-site, forwarding
events to ad platforms (a CAPI-style first-party data layer). **Doesn't benefit the Ad Builder** — BHM
already has mature, independent first-party tracking (RedTrack, Everflow, Meta CAPI via the CAPI Match
Quality feature). Not a gap.

**Ads → Competitor Ads** — showed an unrelated global feed (Malaysian/Australian consumer ads) with zero
competitors configured; not meaningfully evaluated. The Ad Builder's own Research page (live Meta Ad
Library scraping keyed to configured verticals) is more mature for this specific job as observed.

**Chats / Chat History** — a "Chats" tab (conversational Q&A) and a separate "Agent tasks" tab (autonomous
background runs), explicitly two different interaction modes with a mode toggle. **Minor UX idea worth
noting**: distinguishing "ask a question" from "kick off an autonomous task" as a first-class mode switch,
rather than one undifferentiated chat box.

**Brand** — four tabs: Identity (what you sell / industry — filled from the site scrape), **Visual (colors
+ fonts auto-detected from the live site's actual CSS: `#7FE0A8`/`#36D07F`, Inter/Roboto — unprompted)**,
**Tone of voice (a full paragraph auto-inferred from the site's actual copy: "Confident and data-driven,
leaning on precise regulatory and industry terminology... avoiding hype words like 'best' or 'guaranteed'
in favor of sourced claims" — genuinely accurate, and it wasn't asked for)**, Context (client-authored
notes + reference ad creatives, distinct from agent-authored memory), and **Memory (the exact `memory`
facts from onboarding, shown as an editable, deletable list — not a hidden backend construct)**. **The
auto-inferred voice/visual identity from a site crawl is a genuinely reusable idea** — see §5.

**Integrations** — 30+ native connectors across AI (Claude MCP, ChatGPT MCP, bring-your-own-Anthropic-key,
custom MCP server), Analytics (GA4, GSC, AppsFlyer, Ahrefs, Semrush, PostHog, CallRail, Microsoft Clarity),
Commerce/CMS (Shopify, WordPress, Webflow, 10+ more), CRM (Zoho, ClickUp), Advertising (Google/Meta/
LinkedIn/TikTok/Snapchat/Reddit/Pinterest/Criteo/StackAdapt, plus **OpenAI Ads and "Thrad" — ads running
inside ChatGPT itself**), Messaging (Klaviyo/Slack/Mailchimp/Instantly/Omnisend), Files (Google Drive).
**Doesn't benefit the Ad Builder directly** — this breadth exists because Ryze is a general multi-channel
SaaS platform; BHM's tool is intentionally scoped to Meta + RedTrack + Slack + R2. Not a gap, a different
product category. The one forward-looking note worth logging: ads-inside-ChatGPT is a channel that doesn't
exist for BHM today but is worth knowing Ryze is already positioned for it.

**Pricing/monetization structure** (from the paywalled-feature modals): $89/mo (or $74/mo annual) base ads
plan → **$129/mo "SEO Autopilot" add-on** (90 pages/month, content optimized for AI search, competitor-page
rewrites) → **$599/mo "Traffic Printer" add-on** (+ 50 backlinks/month) → **$1,499/mo "A/B Testing," sales-
assisted, not self-serve** ("this plan isn't self-serve — talk to us"). Confirms a real product-tier ladder,
not a flat SaaS price. Not directly applicable to the Ad Builder (an internal tool, not sold), but useful
context for understanding why so much of the product is gated — most of what's behind "Unlock" is a
separate paid product line (SEO, content), not something withheld from the base ads experience.

## 4. Automate section vs. the Ad Builder's rules engine — the real comparison

This is where the two products are actually doing the same job, so it's the most useful comparison in the
whole review.

| RyzeAI template | What it does | Ad Builder equivalent |
|---|---|---|
| Weekly auto-pause rule | Pause ROAS <2 (10+ conv) + frequency >4 with dropping CTR, Slack | Has this — Phase 3 pause rules, absolute thresholds |
| Weekly Meta waste alert | Ad sets with CPA >30% over target → pause/cut/refresh **recommendation**, emailed | Has the detection; **always auto-executes**, never just recommends |
| Weekly scaling check | Campaigns ready for a 20-30% budget bump — ROAS 2x target + impression-share-lost-to-budget >10% + conv volume, combined | **Doesn't have this** — increase_budget exists but requires Joel to already suspect a specific ad set; no proactive multi-signal "ready to scale" detector |
| Spend pacing alert | Daily spend > threshold OR 7-day pacing >15% above plan | **Doesn't have this** — no pacing-vs-plan concept at all |
| Daily anomaly alert | CPC up >25%, CPA up >30%, conv crash, spend pacing >120% — **relative to the account's own trailing baseline** | **Doesn't have this** — every Ad Builder rule threshold is an absolute number Joel sets once (`CPL > $50`), never a dynamic baseline comparison |
| Daily morning brief / Friday weekly recap | Scheduled digest: spend, conv, CPA/ROAS vs 7-day avg, wins/issues, prioritized next steps | **Doesn't have this** — Joel has to manually open Campaign Performance; no proactive digest |
| Budget pacing guard | Daily check that no account is racing ahead/behind its monthly budget | **Doesn't have this** |
| New leads digest | Daily new Meta lead-form leads with cost-per-lead + quality flags | Partially covered by existing Copy Library/Campaign Performance data, not as a proactive digest |

Two structural differences explain the whole table:

1. **Relative/baseline thresholds vs. absolute ones.** RyzeAI's anomaly/pacing templates compare current
   performance to the account's *own recent trailing average* — "CPC up >25%" is relative, not a fixed
   number. Every Ad Builder rule requires Joel to pick and periodically revisit a fixed number. A baseline-
   relative rule type (`% change vs. trailing N-day average`) is a genuinely useful, engineeringly-cheap
   addition — no LLM required, just a rolling average computed in the existing scheduler.
2. **Recommend-then-approve vs. always-auto-execute.** Several RyzeAI templates surface a recommendation
   (pause/cut/refresh/scale) for a human to action, rather than executing automatically. The Ad Builder's
   rules engine has exactly two modes — no rule (manual) or a rule that fires and executes with no human in
   the loop (Slack alert after the fact). There's no middle tier. This is the approvals-queue idea from the
   original writeup, now with three more real template examples (waste alert, scaling check, digest) that
   all want that middle tier specifically.

## 5. Recommendation — ranked, concrete

1. **An approvals queue on the rules engine — build this.** Propose a specific, evidence-backed change
   (mirroring the `approvals` object's shape: entity, evidence points, before/after), wait for one click,
   execute. No LLM reasoning required — pure engineering on top of the existing deterministic rules engine.
   Closes the exact gap the "waste alert" / "scaling check" / recommend-vs-execute pattern above all point
   at.
2. **A relative/baseline threshold rule type — build this alongside #1.** `% change vs. trailing N-day
   average` as a second rule-condition type next to the existing absolute-threshold rules. Cheap (a rolling
   average, no new infra), and it's the mechanism behind three of RyzeAI's most useful automate templates
   (anomaly alert, pacing alert, scaling check).
3. **A daily/weekly digest, sent proactively (Slack or email) — worth scoping.** "Morning brief" / "weekly
   recap" pattern: spend, CPL/ROAS vs. trailing average, top movers, 2-3 prioritized next steps. Doesn't
   need to be LLM-authored — could be templated off existing Campaign Performance data. Solves the real
   problem that Joel only sees performance when he opens the app.
4. **Auto-inferred brand voice/visual identity from a site crawl — worth a look, lower priority.** Cheap to
   try: run one Claude Vision + text-scrape pass on a brand's site once, store the inferred voice paragraph
   and color/font palette as reference for copy generation, exactly like RyzeAI does at onboarding. Low
   risk since it's read-only inference, not automated action.
5. **"Create ad angles" from real customer reviews — worth a look, lower priority.** If BHM has any
   testimonial/review source per brand (App reviews, Trustpilot, etc.), mining it for pain/desired-outcome/
   objection/hook material is a genuinely different copy-research input than what Ad Remix or the Remix
   drawer currently use.
6. **An "Ad copy audit" scorer (weak CTAs, missing USPs, thin messaging, LP mismatch) — worth a look, lower
   priority.** The Copy Library currently ranks only by CPL; a qualitative pass flagging structurally weak
   ads (regardless of spend/data yet) could catch problems before they show up in performance.

**Explicitly not recommended, per §0's framing:** agent-built-and-launched campaigns end-to-end, client-
facing report decks, the SEO/content/backlink product line, team-seat management, a native Claude/MCP
bridge exposing Ad Builder tools externally, and per-client memory the production system reads
automatically (a lighter "why this rule exists" text field is the right-sized version of that idea, not
full agent memory) — these are all real, well-built capabilities that solve problems specific to a
multi-tenant agency SaaS platform, not BHM's single internal tool.

## 6. Last-call checks before cancelling the trial (2026-09-14)

Three things pulled specifically because they disappear once the subscription ends:

**Credits/billing economics** — 233 of the original 250 trial credits remained unused at cancel time.
**Credits expire when a subscription ends** (per their own help docs) — cancelling forfeits them
regardless of the $1 already paid; flagged to Steve before acting, not a blocker. Mechanics, for the
record: Fast/Smart/Powerful model tiers cost 0.25/0.5/1.5 credits per "AI step" (each round of reasoning
the model does, not each tool call — tool calls themselves are free); ad creative generation and SEO data
lookups carry a flat fee on top (5 credits and 0.5 credits respectively, confirmed by a live burn: the
real creative-generation test below cost exactly 5 credits, plus ~6 credits of research/reasoning steps
beforehand). **Approvals-queue research is explicitly free — you're only charged when you approve a
proposal and the agent goes to apply it.** That "detection is free, action costs" split is the same
principle behind recommendation #1 in §5 and is worth keeping in mind if a future LLM-based rules-engine
addition ever needs to justify its own API-cost model to Steve. Top-up packs: 100 credits/$39, 300/$99,
600/$179.

**Locked-feature pricing** (SEO and A/B Testing modals, the two gated nav items whose pricing wasn't
captured in the first pass): **SEO Autopilot $129/mo** (90 pages/month, content optimized for AI search,
competitor-page rewrites) with a **$599/mo "Traffic Printer"** tier above it (+ 50 backlinks/month);
**A/B Testing is a $1,499/mo, sales-assisted-only tier** ("this plan isn't self-serve — talk to us"), done
for you by Ryze's own engineering team rather than self-configured. Confirms the tiered-SaaS pricing
ladder described in §3 with real numbers. (Search Performance and AI Visibility, the two other
nav-listed-locked items, disappeared from the sidebar entirely once Google Search Console wasn't
connected — never got their pricing modal; not worth re-chasing.)

**A real ad-creative generation, run to completion, not just described from a template thumbnail:**
Asked the AI Analyst ("I want to create a creative. Recommend me something") and it independently:
(1) pulled and analyzed the account's real performance data (checked Meta Ads 12+ times across the
research phase) to identify the actual best-performing live ad ("Dealer Plates" — 52 real Meta-reported
forms, $826.04 spend, $15.89/form, 95% of that campaign's forms) as the concept's evidence base;
(2) proposed a specific creative concept building on that winner, including a data-grounded budget/kill
rule ("$14-$19 per raw form... stop if link click rate is below 1.0% after 2,000 impressions or CRM
shows no accepted leads") — notably applying the CRM-acceptance-rate caution from onboarding's `memory`
facts even though CRM still wasn't connected, confirming memory is genuinely read on a later, unrelated
task, not just stored; (3) on approval, generated a real, on-brand 4:5 image — the auto-detected brand
green (`#36D07F`) highlighting "moving parts" in the headline, the logo correctly placed, three
data-derived tag pills ("Dealer plates," "Test drives," "Customer vehicles"), and a footer CTA
("Free comparison · No obligation") pulled straight from its own recommendation text. **Genuinely
production-plausible output** — the one thing a template thumbnail or feature description can't prove,
now confirmed firsthand.

**The one real caveat worth weighing against that quality: it took roughly 4 minutes end-to-end** for a
single creative (the recommendation step alone ran ~90 seconds of live Meta API research before even
proposing a concept, then a separate confirmation step, then ~2 more minutes to actually render the
image) — the "Running Create creative" step specifically sat with no visible progress for over 3 minutes
straight. Not a dealbreaker for an occasional one-off, but a real data point against using this
interaction pattern for anything Joel needs quickly — the Ad Builder's own kie.ai pipeline (Flux Kontext
Pro, ~4-8 credits/image) returns in seconds to low tens of seconds by comparison. Grounding a
recommendation in live account data is worth the wait once; doing it as the default path for every
routine creative would be a real workflow-speed regression versus what Joel has today.

## 7. Real defect found and fixed: logo legibility on dark backgrounds (2026-09-14)

The "Dealer plates" creative above (renamed "Dealer Moving Parts" in the library) shipped with a real
quality bug: the "Get Business Coverage" logo — a dark navy shield + dark navy/teal wordmark — was
composited directly onto a dark navy background scene with zero contrast treatment, making the logo
nearly unreadable. Not a random one-off: it's a systematic gap in the generator (no low-contrast
detection, no auto-backing-plate, no light-logo-variant swap when the chosen scene is dark).

**The agent fixed it correctly on request, in two iterations, once given the actual file:**
1. First ask ("make the logo legible") — from a **fresh chat**, described the creative by name. The
   agent could not locate it: burned 24 credits (222→198) across two separate lookup attempts (9 tools
   the first time, 2 more the second) before concluding it needed the file attached directly. **No
   creative-memory across chat sessions** — confirmed twice, not a fluke.
2. Once the "White Logo Fix" file (which already existed in the library — someone had made a first pass
   at this before, name suggests exactly what changed) was attached directly: it correctly identified
   the shield icon still needed its own outline (distinct ask from the wordmark fix already done),
   generated an "Outlined Shield Fix" version in one pass (~90 seconds), and the result was verified
   correct — thin light outline around the shield, white wordmark, bordered box behind the whole
   lockup. All three elements of the logo now read clearly against the dark scene.

**Total cost: 222 → 194 credits (28 credits)** for one real fix — only ~4 of those credits went to the
actual successful edit; the other 24 were wasted lookup overhead from starting fresh chats instead of
continuing the original generation thread. **Lesson for any future agent-tool use of this pattern:
always continue the original thread when iterating on a specific asset — never start a new chat and
describe it by name.**

**Relevance to our own pipeline:** worth a direct sanity check of `text_overlay_service.py` against the
same failure mode — logo/CTA overlay on a kie.ai-generated dark background. This is exactly the kind of
defect that's invisible in code review and only shows up by looking at real rendered output, which is
why [[verify-in-production-not-by-assertion]] applies to creative-gen QA too, not just data pipelines.
