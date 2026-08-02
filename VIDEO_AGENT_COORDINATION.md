# Video Agent Coordination Ledger

This file is the handoff layer between Claude, Codex, Steven, and Joel.

Neither agent should rely on chat history as the source of truth. Before working on auto-insurance video production, read this file and append an update when done.

## Current Objective

Build a repeatable auto-insurance video production system that can approach Arcads-style UGC quality:

```text
competitor research -> guidance -> cheap video drafts -> Joel review -> final candidates -> Meta-ready creative
```

## Ownership Lanes

| Owner | Lane |
|---|---|
| Claude | Facebook Ad Library scrape quality, competitor pattern extraction, script guidance, visual-reference notes |
| Codex | video harness, cost/speed controls, caching, assembly, QA tooling, app integration |
| Joel | creative usefulness review, paid-social launch judgment |
| Steven | final product direction and budget guardrails |

## Standing Workflow

1. Claude updates `AutoInsurance-VideoCreative-Guidance.md` and/or drops scrape payloads.
2. Claude appends a dated note in `Claude Updates`.
3. Codex reads this file, then updates the harness/app/docs.
4. Codex appends a dated note in `Codex Updates`.
5. Joel reviews `VIDEO_PRODUCTION_JOEL_WALKTHROUGH.md` plus review pages.
6. Steven decides whether to generate more, ship app changes, or adjust direction.

Before starting a video-production session, either agent can run:

```bash
python3 backend/scripts/video_coordination_check.py
```

That prints watched file timestamps, git status, open handoffs, and the latest agent updates.

## Claude Update Format

```markdown
### YYYY-MM-DD HH:MM AST — Claude

Changed:
- 

New competitor findings:
- 

Recommended script/prompt changes:
- 

Files touched:
- 

Needs from Codex:
- 
```

## Codex Update Format

```markdown
### YYYY-MM-DD HH:MM AST — Codex

Changed:
- 

Validation:
- 

Cost/speed impact:
- 

Files touched:
- 

Needs from Claude:
- 
```

## Open Handoff Items

- Improve Chrome/Facebook Ad Library capture so video/media assets map to exact Library IDs.
- After Claude produces clean mapped examples, convert the top patterns into a harness config override instead of editing defaults every time.
- Add a simple in-app Review Pack view after Joel validates the local review-page flow.

## Codex Updates

### 2026-08-01 — Codex

Changed:
- Added `draft`, `contender`, and `final` cost modes to `backend/scripts/video_finetuning_harness.py`.
- Added TTS caching and local clip reuse so reruns avoid unnecessary Kie spend.
- Added stricter auto-insurance prompt constraints from `AutoInsurance-VideoCreative-Guidance.md`.
- Added `VIDEO_PRODUCTION_JOEL_WALKTHROUGH.md`.
- Added a planned-credit cap before live Kie generation.
- Added Joel feedback controls and JSON export to review pages.
- Fixed review findings: missing `hashlib` import, reused clips in assembly, executable assembly commands, and TTS cache mutation.

Validation:
- Python compile, mode dry-runs, review generation, plan-only assembly, and cost-cap smoke pass.

Cost/speed impact:
- `draft` mode tests 2 talking-head clips per cast with no B-roll.
- `contender` mode tests 4 talking-head clips per cast with no B-roll.
- `final` mode is reserved for full talking-head + B-roll candidates.
- Live generation defaults to a 350-credit planned-spend cap; `contender` and `final` require an intentional higher cap or override.

Needs from Claude:
- Clean per-ad media/video mapping from the current Facebook Ad Library page.
- Updated top competitor patterns from the latest scrape.

## Claude Updates

### 2026-08-02 08:xx AST — Claude

Changed:
- Wrote `AutoInsurance-VideoCreative-Guidance.md` from 23 legacy saved ads plus a fresh 34-ad live Ad Library scrape (`q=auto insurance cheap`, US, active, sorted by impressions).
- Pushed the Ad Library Import feature (`/research/ad-library-import`, migration, capture snippet, Research.jsx modal) that had been sitting unpushed — it's now live in production and the 34 fresh ads are imported and browsable under Research > Auto Insurance.
- Reviewed and pushed Codex's two follow-up passes on that feature (snippet brand-name extraction, content-hash collision fix, unmapped-video-count fix).
- Reviewed Codex's video-agent package (this commit) for money-safety before pushing: confirmed `video_finetuning_harness.py`'s planned-credit cap aborts before any live Kie call, no per-mode bypass, caching can't mask real spend.

New competitor findings:
- Top hook patterns: overpay callout, hidden-thing curiosity, long-tenure surprise narrative, geo-localized urgency, concrete before/after dollar number. Full detail in the guidance doc.
- Several saved/scraped ads were off-vertical or low-quality (cloaked lookalike-character text, injury-lawyer lead gen, body shops, car auctions) — filtered out before both the guidance doc and the fresh import; see the guidance doc's keep/ignore table.

Recommended script/prompt changes:
- 30 UGC scripts (8-15 sec, hook→reveal→CTA) already in the guidance doc, ready for harness prompt use.
- Reject/redo rubric for AI video artifacts (garbled text, wrong steering wheel, fake phone UI, bad lip sync, actor/voice mismatch) is in the guidance doc — worth wiring into the harness's own review-page QA if not already covered.

Files touched:
- `AutoInsurance-VideoCreative-Guidance.md` (new)
- `backend/app/api/v1/research.py`, `backend/app/models.py`, `backend/app/schemas/research.py`, `frontend/src/pages/Research.jsx`, `backend/alembic/versions/v0r8s4t5u7q3_*.py`, `backend/scripts/ad_library_*` (Ad Library Import feature, separate from video harness)

Needs from Codex:
- `video_bakeoff_phase0.py` has no credit-spend cap at all (no `--max-planned-credits`, no pre-flight abort) — bounded only by a hardcoded clip list (~700-930 credits worst case). Add the same cap pattern from `video_finetuning_harness.py` before anyone runs it live with `--yes`.
