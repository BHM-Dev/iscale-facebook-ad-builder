# Ad Builder — Research Copilot MVP

## 1. Executive summary

Joel should be able to ask a research question in plain English instead of manually translating it into a Meta Ad Library query and then scrolling an unranked result set.

The MVP is an **intent-to-evidence research copilot**. It converts a question such as “show active commercial-insurance ads aimed at truckers that have been running for at least 30 days” into explicit filters, searches BHM’s retained catalog, and explains why every result appeared. It does **not** claim an ad is “best performing” unless BHM has an approved, source-backed performance signal for that exact ad.

Economics: one good natural-language request should replace 10–20 minutes of manual Library filtering and reduce bad creative inspiration choices. The initial version uses the existing library; an explicit follow-on action can request a live Meta capture only when the current corpus is insufficient.

## 2. Flow

```text
Joel asks a question
  → copilot extracts constraints + confirms the plan
  → searches retained BHM research records
  → ranks by disclosed public proxies
  → Joel inspects, saves, or builds from a result
  → optional: Joel approves a live Meta capture when coverage is insufficient
```

## 3. Detailed specification

### Research prompt

- Persistent input in the Research header: `Ask Research`.
- Example prompts are concrete and vertical-aware:
  - “Show current commercial auto ads for owner-operators.”
  - “Find active quote ads that have run 30+ days.”
  - “What creative structures are competitors using for church insurance?”
- The response begins with a visible query plan, not a wall of generated prose:
  - vertical / segments
  - advertiser or brand constraints
  - format / CTA / placement constraints
  - date or runtime constraint
  - selected ranking signals

### Evidence and language rules

- “Best performing” is translated to: **strongest available public proxy**, never a factual performance claim.
- Approved proxies in v1: active/recent status, observed runtime, repeated creative versions, retained visual availability, and BHM’s own manual review.
- Every result has a source label and the exact reasons it matched.
- Unknown data remains unknown. No estimated spend, ROAS, conversions, or “winner” label without a named source that supports it.

### Coverage decision

If the retained catalog cannot answer the question, return a coverage state such as:

> “Only 3 retained commercial-trucking examples match. Expand with a live Meta capture?”

That button opens a pre-filled capture plan but does not scrape or spend credits automatically.

### Initial API contract

`POST /research/copilot/query`

```json
{
  "question": "Show active commercial auto ads for owner-operators running 30+ days",
  "vertical": "Commercial Insurance"
}
```

Response shape:

```json
{
  "query_plan": {
    "segments": ["owner-operators"],
    "format": null,
    "active_only": true,
    "min_running_days": 30,
    "ranking": ["runtime", "creative_versions", "recency"]
  },
  "coverage": { "matched": 8, "sufficient": true },
  "results": [],
  "limitations": ["No Meta performance metrics are available for these public captures."]
}
```

## 4. Routing and decision logic

| Question intent | Deterministic treatment | Do not claim |
|---|---|---|
| “best performing” | Rank available public proxies; explain them | spend, ROAS, conversions, real performance |
| Audience / niche | map to visible copy, segment tag, advertiser, destination | precise audience targeting in Meta |
| “last 30 days” | capture recency and observed start date | full historical Meta delivery |
| No retained results | propose a pre-filled live capture | that no such ads exist |

## 5. Integrations and passthrough

V1 reads `ScrapedAd`, `SavedSearch`, retained BHM R2 media, and the existing taxonomy. It reuses the current `Build from this ad` handoff.

V2 can add a provider adapter for an approved live Meta source. An MCP server is not a prerequisite. If BHM exposes this through an agent/MCP interface later, reads stay free to execute; every scrape, paid query, saved-brand monitor, write, or launch needs explicit operator confirmation.

## 6. Tracking

- `research_copilot_question_submitted`
- `research_copilot_plan_accepted`
- `research_copilot_result_opened`
- `research_copilot_build_started`
- `research_copilot_live_capture_requested`

Primary MVP metric: time from question submitted to first `Build from this ad`, compared with the manual library flow.

## 7. Rollout

### Ready for review — one to two weeks

1. Deterministic query-plan parser for common Joel intents.
2. Existing-catalog search and transparent proxy ranking.
3. Results-with-reasons UI and the coverage gate.
4. Events and a small Joel feedback loop.

### Phase 2 / directional

1. LLM planner with structured JSON validation and fallback to deterministic parsing.
2. Approved live Meta-source adapter with an explicit request confirmation.
3. Brand monitoring, daily snapshots, landing-page tech detection, and transcript extraction.
4. Read-only MCP tool for asking the same question from Claude/Codex.

## 8. Open questions and dependencies

- Which provider, if any, is authorized for live Meta searches and what does each request cost?
- What exact public signals may be called “performance proxies” in Joel’s UI?
- Does BHM want the v1 copilot limited to the three configured research verticals?
- How many low-coverage results should trigger a live-capture suggestion (recommended: fewer than five)?
