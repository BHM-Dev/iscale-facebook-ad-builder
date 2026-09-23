# Adnova Competitive Research — Second Pass

Second-angle review of the live Adnova trial workspace on 2026-09-16. Scope intentionally excludes
the launcher discoverability, ad-level naming, and angle/template findings already covered in
`CODEX_BRIEF.md` and `AdBuilder-Adnova-Competitive-Research.md`.

## Executive summary

Adnova is not materially ahead of us on AI copy generation or automatic brand-kit application. Its
meaningful advantages are workflow infrastructure around the creative: a dedicated Creative Hub with
asset versioning and threaded visual review, plus a first-class draft-before-launch model. Its
analytics product may be broader than our current performance surfaces, but the live trial could not
prove that because the workspace has no connected ad account.

Recommendation: do not retain Adnova solely for copy or launcher functionality. Keep only if the team
would value a standalone creative-review/DAM layer or if connecting a real account demonstrates
analytics/reporting capabilities that materially improve Joel's iteration decisions.

## Findings by area

### 1. Analytics / reporting

**Observed live:** `/app/analytics` stops at an onboarding screen asking the user to link Facebook or
TikTok ad accounts. No CPL, ROAS, spend, winning-ad, or comparison report was available in the trial
workspace. This is an account-setup limitation, not evidence that the product lacks analytics.

**Documented capability:** Adnova's Analytics API supports ad-level or grouped insights, prior-period
comparisons, platform metrics, computed ROAS, custom metrics, and custom conversions. Its public plan
comparison also advertises top-performing reports, comparison reports, Adnova Scores, custom tags,
metric builders, and shareable report snapshots.

**Comparison:** This could exceed our current Dashboard / Copy Library / P&L workflow in reporting
breadth, especially for creative-level comparison and shareable snapshots. It does not yet prove a
better answer to BHM's core question—RPU, CPL, phone rate, acceptance, and qualified-vs-DQ economics—
because those are not native Adnova concepts in the observed product.

**Recommendation: needs Steve's call.** Only pursue a paid continuation for analytics after linking a
representative Meta account and verifying one real Joel workflow: identify a winning ad, compare it to
a prior period, and translate the result into the next iteration.

### 2. Copy / creative generation

**Observed live:** Adnova exposes Default Ad Copy settings and an Ad Copy Templates area. Templates
can be created blank, loaded from existing ads, or imported by CSV. Default fields include primary
text, headline, description, CTA, web link, display link, phone number, custom product/store listing
ID, and UTM parameters. No AI copywriter, awareness-stage diagnosis, avatar voice system, or prompt
editor was visible in the launcher workspace.

**Documented capability:** Bulk-launch documentation says a saved copy template can be applied across
multiple ads with variables/customization. Launch payloads support primary-text and headline
variations, but this is structured reuse rather than generation.

**Comparison:** Our Gemini-based Eugene Schwartz framework, vertical voice matching, and Copy Library
few-shot workflow are stronger for generating new lead-gen copy. Adnova's manual template/import
pattern is useful as an optional operational convenience, but it is not a reason to replace our copy
pipeline.

**Recommendation: skip for now.** Consider only a lightweight “save this winning copy as reusable
template” workflow if Joel asks for it.

### 3. Collaboration / approval

**Observed live:** The trial had no launch drafts to inspect, but the launcher clearly exposes a
centralized Launch Drafts surface.

**Documented capability:** Adnova's API lets a system create a draft without sending anything to Meta;
a person can review it in the Adnova dashboard, edit it, and launch it later. Drafts are listable,
retrievable, replaceable, and removed after launch. The API also supports asynchronous launch status
polling and idempotency keys.

Creative Hub supports threaded comments on a specific file version, replies/resolution, video-timestamp
anchors, and on-screen annotations.

**Comparison:** This is a real workflow gap for us. We have previews and generated-ad storage, but no
durable “ready for review → approved → launched” state or reviewer comments attached to a creative.
For BHM's current single-media-buyer workflow, it is not launch-critical; for agency/client review it
would remove handoffs through Slack and screenshots.

**Recommendation: adopt directionally, phase 2.** Start with a lightweight internal approval state
and reviewer note on generated ads; do not build a full DAM/commenting system until multiple reviewers
or clients are regularly involved.

### 4. Asset / brand management

**Observed live:** The launcher Creatives page is a centralized asset table with launch status, uploader,
dimensions, size, boards, tags, custom fields, and extension filters. Workspace settings expose custom
fields and product-organized tags. The trial workspace had no custom fields or tags configured.

**Documented capability:** Creative Hub provides boards, asset search, tags, versioning, visual
annotations, threaded feedback, and upload-to-launch handoff via stable file IDs.

**Not confirmed live:** A true brand kit that stores colors, fonts, logos, and automatically applies them
to generated creatives. Public pricing says custom branding, colors, and logos are included in the
Research + Analytics plans, but the exact behavior was not observable from this workspace.

**Comparison:** Adnova is materially stronger as a creative DAM/review system. Our persistent overlay
logo and offer-line behavior is more directly aligned to Joel's lead-gen production needs than generic
branding claims, but our asset metadata and used/unused visibility are thinner.

**Recommendation: adopt selectively.** “Launch status,” asset tags/custom fields, and version history
are the useful pieces. Skip a broad Creative Hub clone unless collaboration demand appears.

### 5. Integrations / automation

**Observed live:** Settings → Integrations listed Slack as the only connected integration, described as
support for sending scheduled reports to Slack. The MCP page showed no active sessions. The API page
offered API-key creation and linked public API documentation; no key was created.

**Documented capability:** Adnova has a public, currently labeled Free BETA API spanning workspace/account
management, analytics, Creative Hub, and Ad Launcher. The launcher API supports asynchronous batches,
status polling, drafts, and idempotent retries. Public docs describe rate limits and versioned endpoints.
No webhook or recurring campaign-launch capability was found in the observed settings or documentation.

**Comparison:** API access and draft/status endpoints are useful integration primitives, but they do not
replace our existing Meta, Drive, RedTrack, Everflow, R2, and internal analytics stack. Slack scheduled
reports are convenient, not differentiated enough to justify another subscription.

**Recommendation: skip as a product purchase; adopt one pattern if needed.** The draft/status/idempotency
model is worth copying into our own launch flow.

### 6. Pricing / tier structure

The live trial showed **6 days 15 hours remaining** and a subscription page with separate products:

| Product | Current monthly price | Included highlights |
|---|---:|---|
| Ad Launcher | $79 for 1 ad account; +$20/account | Unlimited launches, 20 GB storage, static/video/carousel/flexible ads, Drive/Dropbox upload, multi-placement grouping |
| Research + Analytics Plus | $150 | 5 workspaces, 5 users, 5 ad accounts, $250K monthly spend, 30 tracked brands, 500 transcriptions, 20 GB asset storage, 25 templates |
| Research + Analytics Growth | $309 | 10 workspaces, 8 users, 10 ad accounts, $750K monthly spend, 40 tracked brands, 30 GB storage, 50 templates |
| Research + Analytics Pro | $499 | 25 workspaces, 10 users, 25 ad accounts, $1.5M monthly spend, 50 tracked brands, 50 GB storage, unlimited templates |
| Creative Hub | $39 | 100 GB, visual annotations, asset versioning, unlimited feedback, asset tagging |

The live subscription page presents Analytics as an upgrade path from the trial and says the trial
continues all premium features until expiry. The public pricing page also advertises annual billing at
roughly 20% off, plus custom Enterprise plans. Prices and packaging should be rechecked before any
purchase because Adnova's public pages have shown inconsistent historical annual figures.

**Economics for BHM:** The standalone launcher is inexpensive, but it overlaps with a capability we
already operate. The potentially relevant paid bundle is $150/month Plus or $39/month Creative Hub,
but either only makes sense if the team actually uses the analytics or review workflow. There is no
clear economic case to pay for both Adnova and our existing launcher/analytics stack without a proven
incremental decision benefit.

**Recommendation: likely cancel after the Joel check.** Ask Joel whether the discoverability fix
solves his launcher complaint. If yes, cancel unless a real-account analytics test or collaboration
need produces a separate, measurable reason to keep the trial.

## Short decision list

- **Adopt now:** nothing from this pass is urgent enough to interrupt current Ad Builder work.
- **Adopt directionally:** draft-before-launch state, launch-status visibility, asset metadata, and a
  lightweight approval/reviewer-note flow.
- **Validate before paying:** Analytics with a representative connected Meta account.
- **Skip:** Adnova copy generation replacement, generic brand-kit rebuild, Slack-only integration value.

## Sources

- [Adnova live subscription page](https://app.adnova.ai/app/settings?TAB=subscription) — trial and
  in-app pricing observed during this pass.
- [Adnova public pricing](https://www.adnova.ai/pricing) — published plan limits and annual-billing
  context.
- [Adnova Analytics API: Fetch ad insights](https://api-docs.adnova.ai/analytics/postInsights)
- [Adnova Creative Hub API overview](https://api-docs.adnova.ai/creative-hub)
- [Adnova Ad Launcher API overview](https://api-docs.adnova.ai/ad-launcher)
- [Adnova Ad Launcher: Create a draft](https://api-docs.adnova.ai/ad-launcher/createDraft)
- [Adnova Ad Launcher: Create a launch](https://api-docs.adnova.ai/ad-launcher/createLaunch)
