# Ad Builder — GetHookd Competitive Research (Full Review)

Live walkthrough 2026-09-18, two passes: (1) continued a real GetHookd (`app.gethookd.ai`) trial
mid-onboarding (`Ssun's Workspace`, ssun@brighthorizonsmedia.com) through the rest of the signup quiz and
every reachable section reached from the main nav; (2) a second pass specifically to close gaps —
Discover Ads' **Shops** tab, Explore's **Brands** sub-tab, the dedicated **Brand Spy** dashboard (not
just its hover preview), and **Swipe Files** (plural — a distinct, staff-curated feature from the
personal "Swipe File"). Three real paid actions were run to completion, not just described from a
thumbnail: an AI Script generation from a saved competitor ad, a 4-variation static image generation via
Clone Ads, and spying a real brand (Tesco Insurance) to see its full tracked-brand dashboard. Goal, same
as the AdStellar/Adnova/Blip/RyzeAI reviews before it: a concrete, item-by-item call on what's worth
adopting into the Ad Builder and what isn't.

## 0. The framing that matters most

GetHookd is **not a launcher**. Read every section below through that filter first, because it reframes
the whole comparison: there is no Meta connection, no ad-account OAuth, no publish/schedule button
anywhere in the product — not hidden behind a paywall, just absent. It stops at creative + copy
generation and hands off to **Canva** (Image Ad Templates) or **Shopify + GemPages** (Funnel Templates)
for the next step. That means GetHookd is not competing with the Ad Builder's actual core job (single +
bulk launch straight to Meta) at all — it is a **research-and-creative-generation front end that assumes
you already have, or will separately use, a launcher**. The comparison that matters is narrower than the
RyzeAI or Adnova reviews: how good is GetHookd's competitor-ad research and its "turn a winning ad into a
new one" generation loop, since those are the two things it actually does. Both, it turns out, are
genuinely strong — stronger in places than what Adnova showed — which is why most of this review's
recommendations land on the Research/Inspiration side of the Ad Builder, not the launcher side.

## 1. Onboarding — a real bug, and a real integration surprise

**Deck step (save 5 ads to personalize your feed) has a live bug**: the "Insurance" niche the account
started on surfaced only **4** ad cards total (no amount of scrolling, filter-tab switching, or waiting
produced a 5th), while the flow's own progress gate requires 5 saves before "Continue" clears its
warning ("Save 1 more. They save to your workspace, not your computer."). Had to back up two steps and
switch niche to Real Estate (which had a deeper pool, including video ads) to complete onboarding at
all. **Relevance to us**: nothing structural — just confirms that any "save N items to continue" gate
needs a server-side check that N items actually exist for the selected filter combination, or a real
user gets stuck. Worth remembering if the Ad Builder ever adds a similar "save some ads to seed your
feed" onboarding step.

**The MCP/AI-agent onboarding step is the most important finding in this whole section, and it is a
caution, not a recommendation.** GetHookd offers one-click agent setup ("Onboard your AI agent" → pick
Claude Code / Claude / Codex / ChatGPT / Cursor / etc.) that mints a live full-access API key and copies
a prompt into your clipboard telling you to paste it into your coding agent. The prompt is fetched live
from `https://app.gethookd.ai/api/agent-setup/prompt.md` — I read it in full without acting on it. It is
written **as an instruction set for an AI agent to execute autonomously**: "Complete all of the following
steps yourself. Do not ask the user to run any of these commands or edit any of these files — you have
the tools to do it." It walks the agent through editing `claude mcp add` / Codex TOML / Cursor JSON config
files with the embedded key, then straight into billed API calls (`search_ads` bills per row,
`start_brand_spy` costs ~8x a normal call), all before a human confirms anything beyond the original
"click here to connect" button. **We did not act on it** — no config file was edited, no MCP server was
added, no billed call was made — precisely because "edit a config file and start spending the account's
credits without asking" is exactly the kind of standing-integration change that needs Steve's sign-off
first, not an agent's. **Relevance to us**: if BHM ever exposes the Ad Builder's own research data to
Claude Code or another agent via MCP, do not copy this pattern. Keep a human-approval step before any
tool call that writes, spends credits, or starts a monitoring job — GetHookd's own MCP doc (§9 below)
actually says the same thing about its *own* tools ("Ask the user before anything that writes, spends, or
starts a Brand Spy") but its *onboarding* prompt tells the agent to skip asking for the setup step itself.
The inconsistency is the tell: written for maximum frictionless activation, not for a cautious agent
integration. A live full-access key (`gh_zClm...`) is still sitting unused in the account from this test —
flagged to Steve, left in place per his call, revocable any time under Settings → API & integrations.

**Two other soft-decline moments, noted but not acted on**: a "Book a 1:1 onboarding call, unlock 20
credits" step (skipped — booking a call commits Steve's calendar, not something to do on his behalf) and
a "Who else works on your ads? Invite them now" teammate-seat step (skipped — adding people to a live
account isn't a research action). Both are standard SaaS activation nudges, not findings.

## 2. Explore Ads — the discovery/filter surface, and it is genuinely rich

This is the single most directly comparable surface to our own Research page, and it is worth reading
next to [`AdBuilder-Research-Inspiration-CreativeHub-Brief.md`](AdBuilder-Research-Inspiration-CreativeHub-Brief.md),
which already flagged our "coarse 7-tag taxonomy" and "pull-oriented discovery" as the two real gaps
after the Adnova review. GetHookd is a second, independent data point confirming both gaps are real and
showing a concrete shape to close them with:

- **Corpus**: "429,900 of 13,316,398 active ads" shown on a filtered view; ~5-6M ads / 400K+ brands per
  their own MCP docs. Free-text search across keyword or brand name, not just fixed vertical tabs.
- **Filter surface — 20+ independent dimensions**, all combinable: Country, EU transparency, Estimated
  spend, Performance (a "Winning/Optimized" preset tier, not a raw number), Ad Rank, Limit ads per brand,
  Ad format, CTA Type, Static ad style, Status, **Niche (a real 33-category taxonomy, not 7 tags — see
  below)**, Page Type, **Technology** (landing-page tech stack — WordPress/Shopify/Checkout Champ/etc.,
  auto-detected per ad), Run time, Language, Channels, Start date, Creative usage, Brand active ads, Min
  ad copy length, Video length, Hide brands. A "Spied Brands only" toggle scopes the whole feed to brands
  you're actively monitoring (see §5).
- **The niche taxonomy specifically** (full list, captured live): Fashion, Health/Wellness, Home/Garden,
  Beauty, Tech, Supplements, Food/Drink, Sports/Outdoors, Accessories, Automotive, Jewelry/Watches, Pets,
  Entertainment, Kids/Baby, Skincare, Travel, Medical, Business/Professional, Info, App/Software, Service
  Business, Book/Publishing, Other, Finance, Real Estate, Games, Charity/NFP, **Insurance**, Media/News,
  Alcohol, Subscription Box, CBD/Cannabis, Government — 33 total, each with a live brand count (Insurance:
  873 brands; Real Estate: 1,742; Finance: 1,885; Service Business: 3,090; Medical: 3,812). Four of these
  map directly onto BHM verticals (Insurance→DIN, Real Estate→Homewise, Service Business→THS, Finance→
  adjacent). **This is a directly reusable taxonomy shape** — richer and more standard than our current
  seven manual angle tags, and unlike Adnova's proprietary rank/spend signals, a niche taxonomy is not a
  defensible moat to avoid copying, it's just good information architecture.
- **Ad card metadata, at a glance, before opening a single ad**: run dates + days-active, a 1-5 star
  "performance" rating with a directional trend arrow, a comment/engagement count, and (on hover, no
  click needed) a lightweight Brand Spy preview card — active-ad count, estimated spend, new-ads-this-week
  delta — for any brand, without first spying it. That hover-preview pattern (intel before commitment) is
  a nice, cheap-to-borrow UX idea independent of whether we ever build our own brand-monitoring dashboard.

**Net read**: GetHookd's discovery surface is what our Research page should look like once the
Adnova-review recommendations actually ship. It does not do anything conceptually new beyond what the
Adnova review already asked for — it is useful mainly as a second confirmation that the specific gaps
already identified (taxonomy depth, board/collection saving, brand-following) are real, not idiosyncratic
to one competitor's design choice.

### 2b. Explore → "Brands" — a separate ranked brand directory

`Explore` has an `Ads | Brands` tab at the top that is easy to miss — it's not just a filter on the same
ad feed, it's a **different object entirely**: a searchable, ranked directory of brands (not individual
ads). Searching "insurance" returned a paginated (40 pages) table of every advertiser matching the query,
sorted by active-ad count — Health Insurance Comparison (4,190 ads), QuickGuarding Insurance (4,046),
Smart Insurance (3,853), BestMoney.com - Car Insurance (2,567), Australian Seniors Insurance Agency
(2,096), and so on — each with a one-click "Spy" action inline. This is a genuinely different research
entry point from the ad-first Explore feed: instead of "show me ads about X," it answers "who are the
biggest active advertisers in X, ranked by scale" — a faster way to find who's actually worth watching in
a vertical before drilling into their individual creative. **Relevance to us**: a "top advertisers in this
niche, ranked by active-ad count" view is a cheap addition on top of whatever ad-level scrape data we
already store — it's just a `GROUP BY brand` over data we may already have, not a new data source.

## 3. Ad detail panel — "how competitor ads are displayed for review"

This is Steve's second explicit priority, and it's worth walking through what a single ad's detail view
actually contains, since a card grid alone (what our Research page has today) is not the same job as a
detail view built for review. Opening an ad (Paw Guardian, a dental-spray video ad) surfaced:

- **Left pane**: the actual video/image inline (playable, not a link out), a "Download media" action, the
  **full ad copy text** as typed by the advertiser (not truncated), a "Copy" button, a "View all" toggle
  (multiple copy variants the advertiser is running against the same creative), the headline, and the
  landing-page URL with a "see details" link.
- **Right pane — four tabs**:
  - **Overview**: Ad ID (linkable to Meta's own transparency page), date saved, active-period in days,
    niche, page type, **platform breakdown** (Facebook, Instagram, Audience Network, Messenger, Threads —
    not just "Meta"), CTA type, display format, landing-page URL, and **auto-detected technology stack**
    split by category (CMS: WordPress 82%; E-commerce: Shopify) — this is inferred from crawling the
    actual landing page, not advertiser-reported.
  - **AI Script**: on-demand, credit-gated (see §6) — deconstructs the ad's transcript into Hook / Body /
    Call-to-Action and, given your own product's name/audience/description, generates a new script in
    the same structural pattern (tested live, see §6).
  - **Transcription**: the ad's spoken/on-screen video text, machine-transcribed (their MCP docs confirm
    this is the `transcribe_ad` tool, async, polled).
  - **Comments**: (not populated on the ad tested — presumably surfaces public engagement/comments where
    available).
- **Top bar**: "Spy brand" (adds to the full Brand Spy dashboard — see §5, with a live count of credits
  it'll cost), "Visit shop" (the advertiser's actual storefront/site), Save (to Swipe File, with a
  folder-picker dropdown), share, download, external-link, and a "..." overflow menu.

**Net read**: this is a genuinely well-built single-ad review surface — closer to Adnova's Creative Hub
concept (§3 of the earlier brief) than to a simple modal, but purpose-built for *competitor* ads rather
than *our own* generated variants. The tech-stack detection and multi-platform breakdown are the two
pieces our current ad detail view (whatever it currently shows) most likely doesn't have, and both are
cheap, valuable, and don't require any AI: tech-stack detection is a one-time crawl-and-pattern-match per
landing-page domain (same category of work as our existing Chrome-capture/brand-scrape pipeline), and
platform breakdown is just reading Meta Ad Library's own placement data more completely than we
currently surface it.

## 4. Swipe File(s) — two distinct features, both confirm "boards" is table stakes

**Swipe File (singular, personal)**: `Discover Ads → Swipe File` is GetHookd's saved-ads home — a
filterable grid (same 20+ filters as Explore) of everything *you've* saved, split into "My Ads" and
"Brands" sub-tabs, sortable (Latest added, etc.), with a **Folders & Boards** sidebar for organizing
collections (a "Default Folder" exists out of the box, and you can create more). This is the third
independent product (after Adnova's boards and RyzeAI's asset library framing) confirming that "flat
sidebar of saved ads" — our current state per the Adnova review — is the one pattern nobody else ships.
**Worth treating as settled, not still an open question**: build folders/boards on the Research page's
saved-ads list next time it's touched.

One real inconsistency worth flagging rather than treating as gospel: **ads saved during the onboarding
quiz did not appear in the Swipe File for several seconds after navigating there** (page showed "0 total
ads" before a background sync caught up to the 5 saves made during onboarding). Not a data-loss bug —
they did appear — but it's a reminder that "save now, appear elsewhere immediately" needs an actual
optimistic-UI or fast-poll guarantee if we ever build a similar save-during-onboarding flow; a naive
implementation can look broken for several seconds.

**Swipe Files (plural, staff-curated) — a completely different feature, easy to miss because the name is
one letter off from the one above.** `Discover Ads → Swipe Files` is "Curated Collections of Top-Performing
Ads" — a library of **staff-picked theme collections**, each a named bundle of ads around a specific
creative pattern rather than a vertical: "NATIVE IMAGES + LONG FORM COPY" (546 ads), "AI & CGI Ads That
Actually Convert" (279), "Advertorials & Presell Pages That Print Money" (280), "Winning Ads — Top 50 DTC
Brands" (2,702), "VSLs" (158), "AI UGC + Doctor Avatars — Health & Wellness" (283), "Static Ads That
Outperform Video" (226), "Shock & Gross Ads That Print 💰(4-5 🏆Winners)" (357) — 23 pages of these.
Each collection shows a curator avatar, last-updated date, and a **"Copy" count** — how many other users
have cloned that entire collection into their own workspace (134 for the top one) — as a social-proof
signal, plus a share action. **Relevance to us**: this is a distinct layer above raw search — hand-curated
"here's what X pattern actually looks like across dozens of proven examples" collections, organized by
*tactic* (native, UGC, advertorial, shock-value) rather than by *vertical* or *brand*. Nothing in the
Adnova review had an equivalent. Worth a look as a lightweight addition once boards/folders exist: a
handful of BHM-curated "here are our best examples of X angle" collections (Steve or Joel hand-picking,
not AI-curated) would give new hires or a second media buyer the same fast-onboarding value this feature
is clearly built for, without needing GetHookd's scale to do it.

## 5. Brand Spy — tested live with a real spy, and it's a full dashboard, not just a hover card

§2's hover-preview card undersells this feature badly — spying a real brand (Tesco Insurance, 2 credits,
confirmed via a "this will cost 2 credits... once confirmed, we'll start tracking this brand's ads
indefinitely, until you decide to remove it" dialog) opens a genuinely comprehensive per-brand dashboard:

- **Ad format mix**: Images / Videos / Carousels / No media / Hidden-by-Meta, as counts and % of total
  (Tesco Insurance: 155 carousels = 58.94% of 263 total formats — note formats can exceed ad count since
  one ad can carry multiple format tags, called out explicitly elsewhere in their own docs).
- **"Ads Launched Over Time"**: a monthly bar chart (3M/6M/ALL toggle) plus a trailing trend line ("262
  Launched Ads, -83.0%" — a launch-velocity signal, not just a raw count).
- **"Most used landings"**: a table of the brand's top landing-page URLs by current-ad count and % of
  current, each with a preview action.
- **"Most used hooks"**: a **"Generate Hooks" button** — a second, brand-level AI extraction distinct from
  the single-ad AI Script in §3/§6: this one mines the *pattern across the whole brand's ad history* for
  its most common opening hooks, not just one ad's script.
- **"Active Ad Trends"**: a daily active-ad-count line chart (7D/30D/90D toggle, Format/Page-type
  breakdown, a "Show added/removed" toggle, and CSV export) — explicitly labeled **"Backfill — daily
  snapshots start once Brand Spy is tracking"**, i.e. history before you started spying is backfilled once
  from whatever data they already have, but true day-by-day granularity only accrues forward from the
  moment you spy a brand.
- **"Top 10 ads by performance score"**: a ranked creative gallery for that one brand specifically.

**Relevance to us**: this is the single richest feature in the entire product, and a much stronger
argument for building brand-monitoring than the hover-preview alone suggested in §2. The concrete,
buildable subset — without needing GetHookd's own scrape infrastructure — is the **daily
active-ad-count snapshot + format-mix + top-landing-page tracking for a small, curated list of BHM's
actual named competitors** (RealEstateAgents.com competitors for Homewise, THS's home-services
competitors, DIN's insurance competitors), fed by a scheduled re-scrape of our existing Chrome-capture/
brand-scrape pipeline rather than a new data source. The "Generate Hooks" (brand-level pattern mining
across many ads, not one) is the more novel idea worth a lower-priority look — it's a different AI job
than the single-ad Hook/Body/CTA breakdown in §6, and would need enough saved ads per competitor to be
worth running.

## 6. AI Script — tested live, Hook/Body/CTA structural generation

Ran to completion, not just read about: opened the Paw Guardian dental-spray video ad's "AI Script" tab,
clicked "Generate AI Script" (**cost: 5 of 10 trial credits** — half the entire trial budget for one
action, confirmed via a second confirmation dialog before charging), which created a new "Video Scripts"
brief pre-linked to that ad as its "Inspiration." From there, filling in a *different* brand's product
details (Company: TrustedHomeService; Product: "Free home repair quote matching"; Target Audience: "US
homeowners needing a repair or service quote"; a one-line description) and clicking "Generate AI Script"
a second time produced, with no additional credit charge shown:

- **Hook** — source: *"We kept seeing this weird dental spray that apparently turns dog teeth from this,
  to this."* → generated: *"We kept seeing this free service that instantly connects homeowners to top
  local repair pros—curious how it works?"*
- **Body** — source: a full first-person "I tried it myself, was skeptical, it worked" paragraph about
  the dog's breath/teeth → generated: a beat-for-beat structural mirror about a homeowner's peeling
  paint/leaking roof, ending on the same "I'm just so thankful/grateful... I 100% recommend this" close.
- **Call to Action** — source: *"And right now, they're offering 50% off, plus free shipping."* →
  generated: *"Get your free home repair quote today and connect with trusted local pros—quick, easy, and
  totally worth it!"*

**Quality read**: text renders cleanly, is on-brief for the inputs given, and the Hook/Body/CTA
segmentation (each with its own regenerate/edit/copy icon, independently) is a genuinely useful
interaction pattern — Joel could keep a winning Hook and only regenerate the Body, for instance. **The
honest caveat**: at creativity level 9/14 ("Creative, but still on point"), the output is a very close
structural paraphrase of the source ad — same sentence rhythm, same rhetorical beats, nouns swapped. That
is either a feature (fast, proven-structure copy) or a risk (derivative-feeling, close to the source
ad's actual language) depending on how it's used; it is not the kind of divergent "inspired by, not
copied from" creative a human copywriter would produce from the same brief. Worth knowing going in, not
a reason to dismiss the pattern.

**Relevance to us**: the Hook/Body/CTA-as-independently-regeneratable-units pattern is the most concrete,
buildable idea in this whole review for our own "Build from this ad" → Ad Remix handoff, which today
(per the Research/Inspiration brief) hands the whole ad over as one blob of competitor context. Breaking
a saved ad's copy into Hook/Body/CTA once, storing it as three fields rather than one string, and letting
each regenerate independently is a UI/data-model change, not a new AI capability — we already have a
copy-generation model in the pipeline.

## 7. Clone Ads — static image variation, tested live

Ran to completion: picked a saved COUNTRY Financial sweepstakes banner ("Enter for Your Chance to Win!")
as the single inspiration, typed one line of brief text ("Rebuild this as a home-repair quote-matching ad
for TrustedHomeService. Same sweepstakes/giveaway energy, US homeowners audience."), left model on **Nano
Banana 2** (their default, priced per-variation), aspect ratio Square 1:1, and requested 4 variations —
**quoted cost 4 credits, confirmed before charging**.

Result, ~15 seconds of generation: four coherent "Ultimate Home Makeover Giveaway" static banners, each
with a correctly-rendered, legible **invented TrustedHomeService logo** (shield + house icon + wordmark),
correct body copy ("Find local pros. Get free quotes. Build your dream home." / "U.S. Homeowners Only.
Terms Apply."), a "WINNER" ribbon tag, and a real aerial-suburb photo background — genuinely
production-plausible output, on par with or better than the RyzeAI creative-generation test (§6 of the
RyzeAI review), and materially faster (~15s vs. RyzeAI's ~4 min end-to-end). Text rendering had zero
garbling across all four variants, which is the single most common failure mode for AI ad-image
generation and the thing a template screenshot can never prove.

**A credit-ledger jump, run down and confirmed, not left as a guess**: trial credits went from 10 → 5
(after the AI Script generation) → **15** after this 4-credit image generation, i.e. a net +10 on an
action that should have net -4. Checked the "Earn credits" panel directly rather than assuming: it lists
a fixed task list — **"Save your first ad" (+5), "Clone your first ad" (+10), "Connect AI Agent" (+50),
"Book onboarding call" (+20)** — and the first two had just been completed by this session's own actions.
**Confirmed cause, not a billing bug**: gamified onboarding-milestone bonuses, tracked separately from
the credit balance the UI shows blended together. **Relevance to us**: if the Ad Builder's own
credit/usage-based features (kie.ai generation costs, etc.) ever get a visible "credits remaining"
counter, keep bonus/gamified credit grants **clearly separated** from paid-usage debits in the ledger — a
single blended number that can jump up from an action that should cost money is confusing to audit even
once you know the real cause.

## 8. Image Ad Templates & Funnel Templates — the Canva/Shopify lock-in

**Image Ad Templates**: a category-filtered gallery (Supplements, Beauty, Accessories, Health, Other) of
pre-built static creative layouts, each with a single action: **"Edit on Canva."** There is no in-app
editor — GetHookd generates or curates the layout, then hands the actual editing off entirely to Canva.

**Funnel Templates**: a richer, better-tagged gallery — landing-page angle patterns (Listicle, 3rd Party
Reviews, Breaking News, Founder Story, Personal Story) cross-tagged by visual format (Story Related
Image, Product in Use, Before & After, Comparison, The After/Before Image, Video), each with a usage
count (e.g., "Toaster" — a Listicle "Top X" format — 1,142 uses) as a social-proof signal. Opening one
confirms: **"To use this funnel template, you'll customize and launch it in your Shopify store with
GemPages."** Locked to Shopify + GemPages, full stop — not usable for a WordPress-on-AWS stack like ours
without a from-scratch rebuild of the visual, which defeats the point of a template.

**Relevance to us**: the Shopify/Canva handoffs themselves are not reusable — wrong stack, wrong tool.
**The angle-pattern taxonomy is the reusable part, independent of the delivery mechanism**: "Listicle /
3rd-Party-Reviews / Breaking-News / Founder-Story / Personal-Story" cross-tagged by visual format is a
cleaner, more structured version of the same idea behind BHM's own
`BHM-Funnel-Differentiation-Playbook.md` — worth a side-by-side read next time that playbook is updated,
purely for the taxonomy shape, not the templates themselves.

## 8b. Shops — a separate 144K-store Shopify-intelligence product, not applicable

`Discover Ads → Shops` (marked "NEW") is a whole separate research surface from ad research: a directory
of **144,151 Shopify stores**, filterable by Shopify Plan, origin/visitor country, niche, language,
currency, shop-created date, monthly traffic, traffic growth, active-ads growth, product count, active
Meta ads, Trustpilot rating, theme, installed apps, and detected pixels — essentially a Shopify-store
spy tool (comparable to standalone tools like Sell The Trend or Koala Inspector) bolted onto the same
platform. A single row (Fashion Nova) showed 2,524 products, 4.3★/194.8K Trustpilot reviews, 39.1M
monthly traffic (-1.7% growth), and 918 active Meta ads (+34.6% growth) in one glance. **Relevance to
us: none.** This entire surface assumes the thing you're researching is an e-commerce Shopify storefront
— BHM's owned properties are lead-gen/content funnels on WordPress, not Shopify stores, and BHM's
competitors in insurance/real-estate/home-services are not Shopify merchants either. Documented for
completeness since it's a major, easy-to-miss feature area (its own filter set, its own corpus size), not
because it changes any recommendation below.

## 9. Analyze Ads dashboard, API & AI Agent, pricing

**Analyze Ads → Dashboard**: a self-reported ROI layer ("Hello, ssun 👋" / Money saved / Time saved /
ROI%) broken out by activity type (Saved Ads, Followed Brands, Transcriptions, AI Scripts, Ad Templates)
plus a **Recent searches log with team-member attribution** (who searched what, when) — a genuinely
useful pattern for a shared team workspace, not applicable to a single-operator tool but worth
remembering if BHM's Ad Builder ever gets more than one active researcher.

**API & AI Agent**: same MCP setup flow as onboarding (§1), plus a separate REST API tab (same
bearer-token auth, `/api/v1/*`). Per their own published MCP docs (read directly, not just summarized):
~50 tools when connected, billing is **per-row for list/search calls, flat-per-record for a single
lookup, free for a defined allowlist** (`get_ad`, `get_brand`, `search_brands`, `get_top_ads`,
`list_swipe_file`, taxonomy lookups, `get_user_profile`), and `start_brand_spy` costs roughly 8x a normal
call — consistent with the 2-credit UI price observed live in §5 (the API path is materially more
expensive for the same action). Media/logo URLs returned by the API **expire 24 hours after the
response**, with `share_url` as the durable link and free re-fetch (`get_ad`/`get_brand`) to mint new
URLs on demand — a sane pattern worth remembering if we ever build a similar signed-URL scheme ourselves.

**Pricing** (Team plan, the tier this trial account is on): $79/mo billed monthly, or $52.42/mo billed
annually ($629/yr, "save $319 a year") — 400 credits/mo (4,800/yr), 5 team seats, API & MCP included on
both tiers. Not directly relevant to an internal BHM tool (we're not buying this), but useful context for
reading the credit costs in §6-7 against a real monthly allowance: 400 credits/mo means the single
AI-Script generation tested here (5 credits) is a small fraction of a paid month's budget, even though it
was half the 10-credit trial.

## 10. Recommendation — ranked, concrete

1. **Ship the richer niche/filter taxonomy on Research — build this.** The Adnova review already asked
   for this; GetHookd is independent confirmation with a concrete, ready-to-copy shape: a ~30-value niche
   taxonomy (not 7 tags) plus filter dimensions we're currently missing entirely — CTA type, static ad
   style, page type, **auto-detected landing-page tech stack**, min ad copy length, video length. None of
   this requires new AI; it's crawl-and-classify work adjacent to what our existing brand-scrape/Chrome-
   capture pipeline already does.
2. **Boards/Folders for saved Research ads — build this.** Fourth independent confirmation (Adnova,
   RyzeAI's asset framing, GetHookd's Swipe File, GetHookd's separate curated Swipe Files) that a flat
   sidebar is the outlier, not the norm.
3. **Break "Build from this ad" copy into Hook / Body / CTA as three independently-regeneratable
   fields, not one blob — build this alongside Ad Remix's next iteration.** The single most concrete,
   low-lift idea in this review: same generation model we already have, different data shape and UI, and
   it directly targets the workflow Joel already does manually (keep the hook that's working, only
   rewrite the CTA).
4. **A lightweight brand-monitoring snapshot for a short, named list of BHM's real competitors — worth
   scoping.** Daily active-ad-count + format-mix + top-landing-page tracking, fed by a scheduled re-run of
   our existing scrape pipeline rather than new infrastructure. Directly modeled on §5's Brand Spy
   dashboard, scoped down to what's cheap: skip the brand-level "Generate Hooks" AI mining and the
   234K-brand discovery leaderboard, keep the daily snapshot + trend chart.
5. **Auto-detect and display landing-page tech stack + full platform breakdown (FB/IG/AN/Messenger/
   Threads, not just "Meta") on saved competitor ads — worth a look, medium priority.** Cheap, no AI
   required, and directly serves Steve's "how we display competitor ads for review" priority: two data
   points our current ad-detail view most likely doesn't surface today.
6. **A handful of hand-curated "best examples of X angle" collections (BHM-picked, not AI-curated) —
   worth a look, lower priority.** Modeled on §4's staff-curated Swipe Files: a fast onboarding/reference
   tool for a new media buyer, cheap once boards/folders (#2) exist.
7. **Funnel angle taxonomy (Listicle/3rd-Party-Reviews/Breaking-News/Founder-Story/Personal-Story x
   visual format) — worth a look, lower priority, taxonomy only.** Cross-reference against
   `BHM-Funnel-Differentiation-Playbook.md` next update; do not adopt the Shopify/GemPages delivery
   mechanism, only the naming/structure.

**Explicitly not recommended:** the Shops Shopify-store-intelligence surface (§8b — wrong business model
entirely, BHM isn't researching e-commerce competitors); the Canva/Shopify+GemPages creative-delivery
handoffs (wrong stack — our in-house generation is already faster per the RyzeAI review's timing
comparison); the credit-based trial/gamification/upsell machinery (booking-call bonus, invite-teammate
bonus, "Earn credits" task list) — not applicable to a single-operator internal tool; team-seat management
and the "Recent searches by team member" attribution log — same reason, revisit only if the Ad Builder
ever gets a second active researcher; the 234,690-brand "trending brands" discovery leaderboard in
Brand Spy — a defensible-scale data moat, not a cheap fix, same category as Adnova's corpus size; and,
most importantly, **the MCP agent-onboarding pattern of instructing an agent to act autonomously, mint a
live key, and start spending credits without asking the user** (§1) — if BHM ever exposes Ad Builder data
via MCP, the human-approval gate stays, full stop, regardless of activation friction.

## 11. What this review confirms GetHookd is *not* a threat to

Zero Meta OAuth, zero publish/schedule mechanism, zero bulk-ad-creation UI anywhere in the product (§0).
Every creative surface (Clone Ads, Video Scripts, Image Ad Templates, Funnel Templates) ends at "here is
an asset or a script" and hands off to Canva, GemPages, or nothing at all — the advertiser still needs a
separate launcher. **This means GetHookd users are, structurally, prospective Ad Builder users** (or
users of some other launcher) for the other half of their workflow — it competes with our Research page
and Ad Remix's creative-generation step, not with the Ad Builder as a whole. Worth remembering the next
time "should we worry about GetHookd" comes up: the honest answer is no, not as a launcher; yes, their
research/discovery UX (including a genuinely strong brand-monitoring dashboard, §5) is currently ahead of
ours on taxonomy depth and saved-ad organization, both of which are cheap, well-understood fixes, not a
moat — the actual moats (the 13M-ad / 400K-brand / 144K-shop corpus itself, and the 234K-brand trending
leaderboard) are exactly the parts of this review marked "not recommended."

## 12. September 24, 2026 — commercial-insurance seed pull (trial exhausted)

This is a one-time, operator-led corpus pull from the active GetHookd trial, intended to seed BHM's
Research experience rather than establish a paid GetHookd dependency. Six high-relevance brands were
tracked. The source's `Winning` / `Growing` labels are directional creative-discovery signals, **not**
verified conversion or profitability claims.

| Brand | Current ads observed | Highest-value pattern captured |
| --- | ---: | --- |
| Compare Commercial Insurance Quotes | 125 | Segment-specific rate-relief: LLC owners, trucking/DOT, general liability, commercial property, NEMT. Repeated promise: compare in about two minutes. |
| Progressive Truck Insurance | 60 | Trucking coverage proof: up to $2M primary liability, quote in as little as 8 minutes, roadside/cargo, and ELD-led savings. |
| Hiscox Insurance | 167 | Trust plus low-friction purchase: America's leading small-business insurer, 600K businesses, easy claims, policy online in minutes. |
| biBerk Business Insurance | 120 | Landing-page segmentation is the insight: general business, contractors, and trucking have distinct paid-social paths and campaign labels. |
| Simply Business US | 139 | Simple savings prompt: “Could you be getting business insurance for less?” paired with a quick-quote CTA. Snapshot is dated Aug. 9 and should be treated as historical. |
| GEICO / Root / Progressive | 889 / 264 / 1,490 | Auto benchmark: authority + savings (GEICO), switching/save-up-to-$109 per month (Root), and distinct landing-page families for savings, name-your-price, and comparison (Progressive). |

### Cross-brand conclusion

The durable commercial pattern is not headline novelty. It is a clear audience-to-landing-page match,
then one of three evidence forms: **lower rate**, **fast quote**, or **credible protection/trust**.
The most repeatable BHM seed angles are therefore:

1. `segment + same coverage / lower rate` — e.g. LLC owners, contractors, trucking, NEMT.
2. `speed + low-friction quote` — use only supportable time claims; competitors cluster around 2–8 minutes.
3. `coverage proof + operational reassurance` — liability limits, roadside/cargo, claims support, and
   business-count proof where substantiated.

### Recommended product follow-through

Build a small one-time **external-research importer** for the existing Research page, not a recurring
GetHookd integration: paste or upload normalized rows for `source`, `brand`, `vertical`, `segment`,
`headline`, `primary_text`, `cta`, `landing_url`, `format`, `first_seen`, and `source_signal`. Display
`source_signal` as directional and keep its label separate from BHM performance. That gives Joel a
durable, searchable commercial-insurance seed library after the trial ends, with no API key, subscription,
or monitoring cost.

## 13. September 24, 2026 — final scoped source capture

The remaining trial balance was used only where the result added a distinct, usable pattern to the agreed
scope: commercial insurance, home services (gutters first; roofing/windows adjacent), and auto-insurance
aggregators. These are **source signals**, not BHM revenue, profit, or proof that a specific claim may be
used. Preserve the structure and the audience/offer fit; create original claims and creative.

| Source | Scope | Signal observed | Reusable research takeaway |
| --- | --- | --- | --- |
| SmartFinancial | Commercial insurance | 15 current ads; all current traffic routed to a commercial fast-quote page. Its leading contractor hook was: "Contractors, if you don't have insurance, you don't get paid." | Start with the operational consequence, then offer comparison/availability—not a generic "buy insurance" message. |
| Compare Commercial Insurance Quotes | Commercial insurance | 125 current ads; strong segment families for LLC, trucking/DOT, GL, property, and NEMT; compare-in-minutes proposition. | Build segment-specific ad/landing pairs, each with a coverage question and a fast, bounded quote promise. |
| Rescue Roofing Houston | Home services / roofing | 146 current ads, 470 total; 60% video. 98% of current ads drive to one roof-replacement landing page. Winning family: "50-Year Warranty" plus "Full Roof Replacement For $7,000!" | A single concrete offer, proof asset/warranty, and a tightly focused landing page can support substantial creative iteration. Do not reuse unsupported pricing or warranty claims. |
| Rain Gutter Pros | Home services / gutters | 18 current ads, primarily carousel. Winning offer: free proof/estimate, licensed/insured/5-star proof, and damage-avoidance framing. | For gutters, lead with a visible homeowner problem and free inspection/estimate; stack local credibility before the form. |
| Insurify | Auto-insurance aggregator | 286 current / 2,394 total; 53% carousel, 24% video. A large portion of the live set concentrates on a single car-insurance route. | The aggregator advantage is breadth of creative around a disciplined destination/funnel, not a carrier brand claim. |
| OTTO Insurance | Auto-insurance aggregator | 496 current / 7,188 total; 71% carousel. Auto routes use multiple affiliate IDs against the same destination family. Several long-running winners use no-down-payment / overpayment relief. | Preserve attribution and partner-route structure from day one; test affordability and comparison angles, but substantiate eligibility/pricing claims. |
| SmarterAuto | Auto-insurance aggregator | 285 current / 3,003 total; 79% video. 73% of active traffic routes to one `best-match-auto-insurance` funnel, with CTA and state-title variants (e.g., “Could Massachusetts drivers actually save on auto insurance?”). Leading hooks are concrete household/usage triggers: low daily mileage and two-car households. | Use one core matching funnel with controlled CTA/state wrappers. Segment the hook around a verifiable driver condition instead of emulating a carrier’s broad brand promise. |
| HomeBuddy.com | Home services / gutter lead generation | 698 current / 53,234 total; 67% static, 28% video. Winning gutter family has run 86 days: “Here’s The Cost To Cover 150 Feet Of Gutters In 1 Day,” framed as no-cleaning, home-value protection, local pricing, and 410K+ homeowner social proof. | The relevant insight is not the brand—it's a price-framed gutter-guard offer, homeowner-value proof, and a tracked marketplace route. Validate every pricing, installation, and proof claim independently. |
| RigCover.com | Commercial-insurance aggregator | Direct Meta source (page ID `61585543093855`) reveals deep segment-specific live creative: security firms, tree services, rideshare, owner-operators, dump trucks, charter buses, mobile mechanics, and religious organizations. Common promise: compare 50–100+ carriers in about two minutes, then connect to an agent. | RigCover is a primary commercial reference. Its strongest reusable structure is `specific business type → operational risk or lost-income consequence → comparison market mechanism → fast quote`. Do not reuse its dollar, carrier-count, or customer-count claims without proof. |

### What stays out of the library

- **RigCover** is now resolved through its exact Meta page ID (`61585543093855`) and is queued in
  GetHookd Brand Spy. Its initial data fetch was still in progress at capture time; the live Meta source
  supplied the usable creative and routing evidence above.
- **HomeBuddy / LeafFilter** is now resolved as `HomeBuddy.com` through page ID `927136097325358` and
  actively tracked in GetHookd. Its landing routes retain Meta campaign/ad-set/ad/placement macros—an
  unusually clear example of the attribution fields our own future home-services paths should preserve.
- Carrier-led auto ads (GEICO, Root, Progressive) are retained only as market context; they must not drive
  BHM's own angle selection. Insurify and OTTO are the primary aggregator references.
- A two-credit pull for “My Affordable Trucker Insurance” was excluded after inspection: it routes to
  trucker life-insurance content, not commercial trucking insurance. It adds no scoped library item.
- Next Insurance (Meta page ID `1582973568662187`) was tracked but its GetHookd snapshot showed zero
  active ads and no active landing pages. Keep it as an inactive reference only; it should not seed the
  current commercial creative library.

### Final operating recommendation

Use this one-time corpus to populate the new external importer after it is deployed, then keep the library
fresh through a lightweight weekly operator routine: save 3–5 newly observed ads per active vertical,
record the source and observed date, label any platform score as directional, and retire stale entries
rather than implying they remain live. No GetHookd API, stored credential, or recurring vendor cost is
required.
