# Codex Brief — Drive Copy Contract + Drift Indicator

Repo: `BHM-Dev/iscale-facebook-ad-builder` · branch `develop` · written 2026-10-02
Read first: `CLAUDE.md` (Codex Quick Reference, never-push list). **Codex commits locally; Claude Code reviews + pushes.**

---

## 1. Executive summary

**Problem.** `backend/app/services/drive_sync_service.py` is 4,233 lines / 114 methods and took 78 commits in September. Most are "support one more copy-document layout" (Painting handoffs, README handoffs, Markdown handoffs, inline video manifests, 4x5 placements…). The creative team writes copy files in whatever shape the package needs, and the parser chases them. Separately, nothing compared Drive to the database, so on 2026-10-02 36 CA-PROVEN files sat in Drive with no `drive_assets` row for a day and nobody (including the sync) knew. Root cause unknown; logs are wiped on every deploy.

**Solution (MVP, two parts, no rewrite).**
- **A. One canonical copy format + validator.** Bless the format already proven on CA-PROVEN (the "Final Handoff Manifest — Launcher Copy Map"). Ship a template, a pure validator, a paste-and-check endpoint/UI, and per-package `source_kind` telemetry so we can retire legacy parsers on data, not opinion.
- **B. Drift indicator + persistent sync-run log.** Show "Drive N · Library N · checked X ago" where Joel/Abel work, and store every sync run in the database instead of container stdout.

**Economics.** Every parser patch is dev time plus a window where Joel/Abel can't launch a creative (Abel's 2026-10-01 report: tasks "missing or missing copy"). Part A stops the format treadmill; Part B turns "someone noticed on Slack" into "the screen says so".

**Explicitly out of scope:** splitting the 4k-line class, deleting legacy parsers (Phase 2, after telemetry), changing how media is pairing-matched.

---

## 2. The canonical format (Part A)

Already supported by `_parse_handoff_manifest` (`drive_sync_service.py` ~L3902). Reference example = `CA-PROVEN-HANDOFF-MANIFEST.txt` (Drive folder `1OKFpd90RRk8bp8O987zrteZSNoAiQFAu`). Shape:

```
PACKAGE: <Vertical> | <Package name>
FINAL HANDOFF MANIFEST — LAUNCHER COPY MAP

Meta Button
Get Quote                      <- must normalize to a Meta CTA (see CTA_OPTIONS in AdCreativeStep.jsx)

==================================================

## CA-PROVEN-01-H1             <- copy id, unique within file

PRIMARY TEXT
<multi-line>

HEADLINE
<one line>

DESCRIPTION
<one line, optional>

4X5 VIDEO
<exact filename>               <- one line per placement present
9X16 VIDEO
<exact filename>

==================================================
## CA-PROVEN-01-IMG ... (1X1 IMAGE / 9X16 IMAGE blocks the same way)
```

**Rules the validator enforces** (each is an `error` unless marked `warn`):
1. File name matches `*HANDOFF-MANIFEST*.txt` (case-insensitive) — `warn` if only a legacy name matched.
2. `PACKAGE:` header present.
3. A `Meta Button` value that normalizes to a Meta CTA (or a per-block override — **don't invent one; confirm with Steve, see §8**).
4. ≥1 block; every block has a unique `## <id>`, non-empty `PRIMARY TEXT` and `HEADLINE`; `DESCRIPTION` missing = `warn`.
5. Every block lists ≥1 placement filename; filenames contain no path separators.
6. Every listed filename exists in the package folder in Drive (checked in sync/endpoint when a folder is known; skipped for paste-only validation) — missing = `error`, extra media with no block = `warn`.
7. Placement pairs make sense: a block has Feed (1X1 or 4X5) and Stories (9X16) of the same media type, else `warn`.
8. Emoji / all-caps lines inside PRIMARY TEXT must **not** truncate it (existing known trap — see `_COPY_FIELD_STOP_LABELS` comment). Fixture test required.

**Do not** duplicate parsing. The validator wraps the existing parser output plus a structural line-scan; it returns the same `entries` the sync would use, so "valid" means "will import".

---

## 3. Part A — deliverables

| # | Deliverable | Where | Owner |
|---|---|---|---|
| A1 | Pure function `validate_handoff_manifest(text, *, folder_media_names=None) -> {ok, errors[], warnings[], entries, cta, package}` | new `backend/app/services/drive_manifest_validator.py` | Codex |
| A2 | Unit tests incl. CA-PROVEN-shaped fixture (sanitized copy, ~3 blocks), emoji/all-caps PRIMARY TEXT, missing HEADLINE, duplicate id, bad CTA, missing file, path in filename | `backend/tests/unit/test_drive_manifest_validator.py` | Codex |
| A3 | `POST /api/v1/drive-assets/validate-manifest` (body: `text`, optional `folder_id`) — read-only, returns A1 result | `backend/app/api/v1/drive_assets.py` (existing router) | Codex |
| A4 | Template file for the creative team | `docs/DRIVE_HANDOFF_MANIFEST_TEMPLATE.txt` + 10-line how-to at top | Codex (new file under `docs/` is on the never-push list → Claude Code pushes) |
| A5 | "Check a copy file" paste box on the existing Package Health page: textarea → calls A3 → renders errors/warnings/parsed blocks | `frontend/src/pages/DrivePackageHealth.jsx` | Codex |
| A6 | `source_kind` per package: record which parser produced each package's copy (`handoff_manifest`, `readme_meta_handoff`, `final_launch_brief`, `inline_variant`, `ad_copy_doc`, `category_doc`, `strategy_doc`, `none`) into the package-health snapshot (`drive_health.py` result_packages entries) | `backend/app/api/v1/drive_health.py` — **field already has `copy_source`; extend, don't add a second field** | Codex |
| A7 | During sync/refresh, run the validator on each recognized handoff manifest and attach `manifest_status: ok|warn|error` + first 3 messages to that package's entry in the health snapshot. **Warn-only: never block import in MVP.** | `drive_health.py` (snapshot build), not the import path | Codex |

**Phase 2 (directional, not now):** after ~2 weeks of `source_kind` data, delete parsers for formats with zero packages; make `error` manifests block import with a named reason instead of silent partial copy.

---

## 4. Part B — drift indicator + sync-run log

### B1. Drift numbers (no new Drive walk)
The hourly job (`scheduled_drive_health_snapshot`, `:20`) already walks all of Drive and records `media_count` per package (`drive_health.py` ~L281). Extend the snapshot:
- per package: `library_count` = `COUNT(*) FROM drive_assets WHERE archived = FALSE` whose `folder_path` falls under that package's `path` (match on normalized path; `drive_assets` has no package id — see risk below)
- top level: `drive_media_total`, `library_media_total`, `missing_total` (= sum of `max(media_count − library_count, 0)`), `missing_packages[]` (top 10 with names + counts)

Risk: path normalization (`Commercial Van Insurance/CA-PROVEN | …` in `drive_assets.folder_path` vs. the snapshot's `path`). Write the matcher as its own function with tests against both shapes seen in production (placement subfolders like `1x1 Feed Images`).

### B2. Picker indicator — **Claude Code, not Codex** (`AdCreativeStep.jsx` is a trigger file)
In the Drive Creative Library modal header, one line fed by `GET /drive-health/package-health`: `Drive 1,164 files · Library 1,164 · checked 12 min ago`. Amber + link to Package Health when `missing_total > 0` or snapshot `stale`. Never red; never blocks selection.

### B3. Persistent sync-run log — **migration → Claude Code**
New table `drive_sync_runs` (`has_table()` guard; follow the Alembic rules in `CLAUDE.md`): `id`, `kind` (`incremental|backfill|scoped|reconcile|copy_refresh|health_snapshot`), `started_at`, `finished_at`, `status` (`ok|error|skipped_locked`), `processed`, `created`, `updated`, `archived`, `errors`, `error_summary` (text, ≤500 chars), `triggered_by` (`scheduler|user:<id>`), plus **reserved, always NULL in MVP:** `package_folder_id`, `token_before`, `token_after`, `meta` (JSON text). Written from `scheduled_drive_sync`, `scheduled_drive_reconcile`, and the manual endpoints in `drive_assets.py`. Read endpoint `GET /api/v1/drive-assets/sync-runs?limit=20` and a small table on the Package Health page (Codex can build the UI once the endpoint exists).

---

## 5. Routing (who does what)

| Work | Tool |
|---|---|
| A1, A2, A3, A5, A6, A7, B1 (+ tests) | **Codex** |
| A4 (`docs/` file), migration + model for B3 (`models.py`, `alembic/versions`), B2 (`AdCreativeStep.jsx`), review, push | **Claude Code** |
| Sync-runs table UI on Package Health | Codex, after B3 endpoint lands |

Codex: end with "Edits done — ready for Claude Code 2-agent review + push." Do not edit the four trigger files, `models.py`, `main.py`, or anything under `alembic/versions/`.

---

### File ownership — Codex and Claude Code work in parallel, so stay in your lane

| Owner | Files |
|---|---|
| **Codex** | new `drive_manifest_validator.py` + its tests/fixture; `api/v1/drive_assets.py` (validate endpoint only); `api/v1/drive_health.py` (A6, A7, B1); `frontend/src/pages/DrivePackageHealth.jsx` |
| **Claude Code** | `models.py`, `alembic/versions/*`, `main.py`, new `api/v1/drive_sync_runs.py`, new `services/drive_sync_run_log.py`, `services/drive_sync_service.py`, `AdCreativeStep.jsx`, `docs/` |

Do **not** touch the Claude Code files; if you need a change there, say so in your hand-off. Run `git pull origin develop` before starting and before handing off. Health endpoint actually lives at `GET /api/v1/drive/package-health` (router prefix `/drive`); drift fields you add to the snapshot are read by the picker as `drive_media_total`, `library_media_total`, `missing_total`, `missing_packages` at the top level of that JSON — use exactly those names.

---

## 6. Tracking & analytics

- `source_kind` per package (A6) is the analytics: the adoption metric is "% of packages on `handoff_manifest`".
- Manifest validation results ride the health snapshot (A7) — no new table.
- `drive_sync_runs` (B3) is the audit trail; `error_summary` must not contain secrets (strip env/tokens like existing logging).
- No `session_id` / revenue paths touched. No Everflow or Meta calls added.

---

## 7. Build order

1. **Week 1 (Codex):** A1 → A2 → A3 → A6/A7 → A5. Ship the template (A4) the same day as A3 so the creative team can start validating immediately.
2. **Week 1 (Claude Code, parallel):** B3 migration + endpoint, B1 matcher review.
3. **Week 2:** B2 picker line, sync-runs table UI, then look at `source_kind` data.
4. **Phase 2:** retire dead parsers; consider making `error` manifests block.

"Ready for review" = Part A + B1 + B3. "Phase 2 directional" = parser deletion, blocking on `error`.

---

## 8. Decisions (Steve, 2026-10-02)

1. **Copy-file author: Joel.** He is the user of the template and the paste-box checker; wording in A4/A5 should be media-buyer plain ("fix these 2 lines"), not parser jargon. Tell him where the template lives once A4 ships.
2. **Per-block CTA override: undecided → not built.** MVP is file-level `Meta Button` only. Revisit if a package needs it; the validator must emit a clear error (not silently pick one) if a block contains its own CTA line.
3. **Warn-only for the first two weeks: confirmed.** No import is blocked by the validator.
4. **Sanitized CA-PROVEN fixture (≈3 blocks) may be committed** under `backend/tests/fixtures/`.

## 9. Acceptance

- Pasting the CA-PROVEN manifest into the Package Health checker returns `ok: true` with 18 blocks' worth of entries; deleting one `HEADLINE` returns exactly one error naming the block id.
- A package whose folder holds a file not listed in its manifest shows a `warn`.
- A unit test for B1 with a fake package of 36 Drive media files and 0 library rows yields `missing_total == 36` and lists that package first in `missing_packages` (fixture only; do not touch production data).
- A second `scheduled_drive_sync` while `reconcile` holds the lock records `skipped_locked`, not `error`.
- `python3 scripts/check_alembic_heads.py` returns one head; backend unit tests pass: `cd backend && DATABASE_URL=postgresql://x:y@localhost/z SECRET_KEY=x python3 -m pytest tests/unit -q`.
