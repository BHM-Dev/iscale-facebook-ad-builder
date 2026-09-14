# Ad Builder — RyzeAI Competitive Research

Live walkthrough 2026-09-14: signed up for a real RyzeAI trial (`getbusinesscoverage.com`, connected to the
real `RHO - Commercial Insurance` Meta account) and went through onboarding + explored the product surface
end to end. Goal: find what RyzeAI does differently from how the Ad Builder is built, not just describe it.

## 1. What RyzeAI actually is

Not a campaign-builder wizard like Birch/AdEspresso/the Ad Builder. It's an agentic platform where **every
surface — SEO issues, keywords, AI-search-visibility prompts, pSEO articles, backlinks/press mentions, and
paid ad campaigns — is exposed as a typed object** (`list/get/create/update/delete` + named actions like
`launch`/`pause`/`publish`) that both its own agent and the client's chat interface operate on. The chat UI
is the primary interface; "Analytics," "Campaigns," etc. in the left nav are views onto the same object
store, not a separate system.

## 2. Onboarding — chat-driven, adaptive, ends in a real deliverable

- Conversational start: how'd you find us → site URL → auto-scraped site summary ("is this you?") → which
  ad platforms you use → connect (OAuth) → optional native Claude/MCP connector ("Add Ryze in Claude — same
  accounts, same data") → optional team invites. Every step skippable.
- **Live data pull happens before calibration, not after.** The moment Meta Ads was connected, it had
  already pulled real numbers ($38,039 spend / 44 campaigns / 30 days) before asking a single calibration
  question.
- **Calibration questions are genuinely adaptive**, not a fixed form — picking "profit after ad cost and
  rejected leads" as the ranking method triggered follow-ups specific to insurance lead-gen economics (CRM
  matching, same-day vs multi-day lead acceptance, payout variance by buyer) that a generic form never
  would have asked. Every answer got compressed into a one-sentence declarative rule and written into a
  per-workspace `memory` object live, during onboarding, not after.
- **A visible, resumable agent todo list** (`Write todos` tool call) drives the whole flow: Review account →
  Capture goals/rules → Set up recurring checks → Deliver first finding. When the user declined the final
  step, the todo item's own text updated to *"Skip the first account review at your request"* — it
  accurately described what happened, not a generic "done."
- **The first real deliverable is a chart with an honest caveat**, not a vanity number: "Current active
  groups: provisional efficiency... Raw submissions, not accepted leads" — plus a written refusal to call
  anything profitable until CRM data is connected.
- **Scheduling a recurring check is itself a natural-language task**, not a config object: the created
  `agent_run` cron job's `payload.task` field is a full English brief — *"Do not recommend a winner from raw
  form submissions alone; if CRM data is unavailable, report the blocker and limit findings to advertising
  delivery"* — readable and auditable by a human, re-interpreted fresh by an LLM every time it runs (monthly,
  timezone-aware, email notification).

## 3. Product surface (left nav, once past onboarding)

`Home` (onboarding checklist + a literal approvals inbox: *"Nothing waiting — new findings from your agent
will land here for your decision"*) · `AI Marketer` chat (New chat / History / Schedules / Templates /
Reports) · `Integrations` · `Brand` (a single stored brand profile: description, voice, style passport,
writing style — reused across every content-generation surface) · `Analytics` (Web Analytics, Ads
Performance, Search Performance [locked], AI Visibility [locked — GEO/brand-mention tracking across
ChatGPT/Claude/Gemini/Perplexity]) · `Ads` (Campaigns, My Creatives, Ad Templates, Competitor Ads) · `SEO`
[locked] · `A/B Testing` [locked].

- **"Campaigns" here means agent-managed, not manually-built.** Empty state: *"Create one and the agent sets
  it up, launches it and reviews it daily."* You describe a mandate in chat (budget, goal, accounts, landing
  page) and the agent builds + launches it end-to-end — a fundamentally different operating model from the
  Ad Builder, where Joel always drives creation himself with AI assistance.
- **Real bug found, not just a feature to admire:** the persisted Ads Performance dashboard showed
  **$0.00 spend / 0 results** for the same 30-day window the chat agent had *just* reported $38,039/44
  campaigns on, live, minutes earlier ("updated 45m ago"). A real gap between the agent's live Meta API
  tool-calls and whatever separately-synced datastore the dashboard reads from — the kind of inconsistency
  that's easy to end up with once "live agent tool call" and "persisted dashboard" are two different data
  paths, which the Ad Builder's Campaign Performance page deliberately avoids (one live query, no separate
  ETL layer to drift out of sync).
- Competitor Ads tool exists but showed an unrelated default/global feed (Malaysian/Australian consumer
  ads) with zero competitors configured — not evaluated further; the Ad Builder's own Research page (live
  Meta Ad Library scraping keyed to configured verticals) is more mature for this specific use case as
  observed.

## 4. What's actually different from the Ad Builder — ranked by relevance to what shipped this session

The Ad Builder's rules engine (Phase 2, this session) is the closest existing analog to compare against.

**1. Reasoning against a live prose brief + accumulated memory, vs. hardcoded thresholds.** The Ad Builder's
auto-pause rules are deterministic Python (`metric > threshold → action`), evaluated identically every 30
minutes. RyzeAI's monthly review re-runs an LLM against a natural-language task plus every memory fact
accumulated for that client — capable of nuance ("don't trust this number until CRM data arrives") a
threshold rule can't express. Real tradeoff, not a free upgrade: this is the "clever, fragile" pattern
Steve's own working-preferences explicitly warn against for BHM ("boring, robust, cron-able ... not
impressive, clever, fragile") — non-deterministic output, real LLM cost on every scheduled run, harder to
predict/audit than a threshold.

**2. A per-client memory the *production system itself* reads.** The Ad Builder has nothing like RyzeAI's
`memory` object, consulted automatically by every future agent run. The closest analog — this Claude Code
session's own memory files — helps the *assistant* across sessions; it's never read by the live app when
auto-pause fires at 3am. Cheapest thing here worth borrowing without going agentic: a short "why this rule
exists" field surfaced to Joel, not consumed by logic.

**3. Approvals as a durable object with a resolution lifecycle — the most directly actionable idea.** The Ad
Builder's rules engine has exactly two modes: no rule (fully manual) or a rule fires automatically (Slack
alert after the fact). The one-time budget-confirm-step at rule *creation* is the closest analog to
RyzeAI's approvals queue, but there's no ongoing "propose a specific evidence-backed change, wait for one
click, execute" tier. Cheap to add — doesn't require any LLM reasoning, just a queue + a UI inbox — and
fits the existing rules-engine architecture without touching its deterministic core.

**4. Client-schedulable natural-language checks vs. one hardcoded 30-minute job.** Steve or Joel can't spin
up their own custom-cadence, custom-brief recurring check today without an engineering session (like the
ones this session ran). RyzeAI lets the client define both the cron and the brief in plain English.

**5. A native Claude/MCP bridge.** Today, the only reason anyone can "ask Claude" about Ad Builder campaigns
is that an engineer (this session) has direct SSH/DB access. RyzeAI exposes the exact tools its own agent
uses to the client's own Claude session directly — nobody has to be an engineer to get that.

**6. Object-model uniformity.** Least directly portable — a full platform-schema rewrite isn't warranted for
an internal Meta-ads tool at this scale — but it's *why* RyzeAI can coherently span SEO + paid + articles +
mentions: one shared CRUD+actions contract across all of it. The Ad Builder is intentionally scoped to Meta
ads and doesn't need this generality.

## 5. Recommendation

**#3 (an approvals queue) is the one worth scoping for real** — it's a rules-engine feature addition, not an
architecture change, doesn't require betting the auto-pause system's reliability on live LLM calls the way
#1 does, and directly closes a real gap (no middle tier between "fully automatic" and "fully manual" once a
rule already exists). #2 is a cheap, low-risk companion to it (a rationale field, not agent memory).
#1/#4/#5 are bigger, riskier bets that trade the Ad Builder's deliberate "boring and robust" bias for
RyzeAI's "clever" one — worth knowing about, not worth building without Steve explicitly choosing that
tradeoff first.
