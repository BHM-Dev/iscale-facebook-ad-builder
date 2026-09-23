# Codex Brief — Drive Package Health report (Ad Builder)

**Repo:** `BHM-Dev/iscale-facebook-ad-builder` · branch off `develop`
**Why now:** A wrong-ad-copy bug was just fixed in `backend/app/services/drive_sync_service.py`
(a creative could inherit a sibling Drive package's headline/primary text/landing page/CTA and
launch to Meta with real spend). The fix makes the sync *refuse* an ambiguous match and flag the
asset. This brief is the preventative half: show the people who own the Drive folders which
packages are structurally ambiguous, once, so the refusals stop happening at the source.

**Do NOT touch these files** (they are Claude Code-only trigger files; a separate task covers them):
`frontend/src/components/AdCreativeStep.jsx`, `frontend/src/components/BulkAdCreation.jsx`,
`frontend/src/lib/facebookApi.js`, `backend/app/services/facebook_service.py`,
`backend/app/services/drive_sync_service.py`, and anything under `backend/alembic/`.

---

## Scope

One read-only endpoint + one simple page. No DB writes, no migration, no new dependency.

### 1. Backend — `GET /api/v1/drive/package-health`

New file `backend/app/api/v1/drive_health.py`, registered in `backend/app/main.py`
alongside the existing v1 routers. Auth: same dependency the other v1 routers use.

Walk the Drive tree once (mirror the pattern in `DriveSyncService._initial_folder_walk`;
instantiate `DriveSyncService(db)` and use its `_client()`, `_list_folder_subtree()`,
`_is_supported_media()` — read-only, do not call any sync or refresh method).

Return, per package folder:

```jsonc
{
  "generated_at": "2026-09-21T16:00:00Z",
  "packages": [
    {
      "folder_id": "…",
      "path": "Commercial Insurance/Barber Shops | Fresh Creative",
      "depth": 3,
      "media_count": 10,
      "has_manifest": true,
      "copy_source": "handoff_manifest",   // handoff_manifest | strategy_doc | category_doc | none
      "issues": ["duplicate_basename_across_packages"]
    }
  ],
  "collisions": [
    { "basename": "ad1-identity-9x16.png", "packages": ["…path…", "…path…"] }
  ]
}
```

Issue codes to detect:
- `no_copy_source` — media present, no manifest and no recognized copy doc anywhere in the subtree.
- `flat_package` — media sitting **directly** in the package root with no `1x1`/`9x16` placement
  subfolders and no manifest. This is the shape that caused the bug.
- `duplicate_basename_across_packages` — a media basename (lowercased) that also exists in another
  package under the same brand.
- `duplicate_basename_within_package` — the same basename twice inside one package subtree. The
  manifest matcher collapses these (last one wins) and the loser silently loses its copy.

Ground truth as of 2026-09-21 to sanity-check against: 8 manifest packages, all at depth 3–4;
18 colliding basenames across packages (e.g. `ad1-identity-9x16.png` in 6 sibling packages,
`contractor.png` / `restaurant.png` in `Broad Testing/Batch 1 - Mixed Niche`); 0 duplicates
*within* a package; 0 media folders directly under the sync root.

### 2. Frontend — `frontend/src/pages/DrivePackageHealth.jsx`

New page + route in `frontend/src/App.jsx`, nav entry in `frontend/src/components/Layout.jsx`.

- One table, one row per package: path, media count, copy source, issue chips.
- Collisions section below: basename → the packages that share it.
- Filter toggle: "only packages with issues".
- Empty state when everything is clean.
- **Use `useToast` for any error — never `alert()`. No `confirm()`.** (see repo CLAUDE.md)
- Match the existing restrained visual style of `Reporting.jsx` / `Dashboard.jsx`. No new UI library.

### 3. Tests

- `backend/tests/unit/test_drive_package_health.py` — stub the Drive client the way
  `backend/tests/unit/test_drive_category_copy.py` does (`DriveSyncService.__new__` plus a fake
  `_list_folder_subtree`); cover each of the four issue codes.
- Run: `cd backend && DATABASE_URL="postgresql://x/y" SECRET_KEY="test" python3 -m pytest tests/unit/test_drive_package_health.py -q`
- The wider unit suite has ~96 pre-existing DB-dependent errors — ignore those, they are not yours.

---

## Constraints

- Read-only. This endpoint must never mutate `drive_assets` or trigger a sync/refresh.
- Cache the walk for ~5 minutes in memory; the Drive API is the slow part and this page will be
  refreshed repeatedly. Do not add Redis.
- Commit locally on a branch. **Do not push** — Claude Code runs the mandatory pre-push agent
  review and does the final `git push origin develop`.

## Out of scope (explicitly)

- Any change to how copy is matched or refused — that logic is done and deployed.
- Renaming anything in Drive, or writing to Drive at all.
- Per-launch nagging in the ad builder flow. This is a standalone report, checked when someone
  wants it, not a blocker in the launch path.
