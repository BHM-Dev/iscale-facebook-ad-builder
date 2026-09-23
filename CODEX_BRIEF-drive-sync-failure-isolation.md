# Drive sync: isolate per-file failures so one bad file can't roll back the whole batch

## Problem

`backend/app/services/drive_sync_service.py::_process_file` (line 371) only wraps the
copy-metadata-refresh branch (lines 383-398) in try/except. Everything else in that
function — `_resolve_drive_path`, `_match_brand_id`, the `drive_assets` INSERT/UPDATE,
`_metadata_for_media_file` — has no failure isolation. Every call site
(`sync_once`'s backfill loop line 97-99, the initial-walk replay loop line 123-128,
the incremental changes loop line 149-158) calls `_process_file` with no try/except of
its own either.

Any uncaught exception from one file — a malformed name, an unexpected Drive API
shape, a DB constraint hit, an R2 upload error — propagates to `sync_once`'s outer
`except Exception` (line 167), which does `self.db.rollback()` and re-raises. That
discards every file already processed in that batch and 500s the endpoint, for both
the scheduled incremental sync and Joel's manual "Refresh copy matches" click.

`refresh_copy_metadata()` already does this correctly (per-text-file try/except at
line 219-225, falls back to `_mark_package_copy_unverified` on failure, keeps going).
Apply the same pattern to `_process_file`'s callers.

## Fix

In `sync_once`, wrap each `self._process_file(file_meta, result)` call (all three
call sites: line 98, line 128, line 158) in its own try/except:

```python
try:
    self._process_file(file_meta, result)
except Exception as exc:
    result["errors"] += 1
    logger.warning("Drive sync failed to process %s: %s", file_meta.get("name") or file_meta.get("id"), exc)
    self._mark_package_copy_unverified(file_meta, str(exc))
```

Do NOT remove the outer `except Exception` in `sync_once` (line 167-171) — that still
needs to catch genuine setup failures (advisory lock, Drive client auth, the changes
API call itself) and roll back / alert Slack for those. This only adds isolation
around the per-file work inside the loops.

Check `_mark_package_copy_unverified`'s signature (line 1184) before calling it here —
confirm it degrades gracefully when `file_meta` doesn't resolve to a known package
(e.g. the failure happened in `_resolve_drive_path` before a package was even
identified). If it can't handle an unresolved package safely, guard the call or skip
straight to logging + `result["errors"] += 1` for that case.

## Test to add

`backend/tests/unit/test_drive_category_copy.py` — add a case that feeds `sync_once`
(or `_process_file` directly, whichever the existing test helpers support) a batch of
2+ files where one file's processing raises, and asserts:
- the other file(s) in the batch still get created/updated (i.e. `result["created"]`
  or `result["updated"]` reflects the successful ones)
- `result["errors"]` incremented for the failing one
- `self.db.commit()` at the end of `sync_once` — no rollback of the successful files
- no exception propagates out of `sync_once` for this case

## Also add: endpoint-composition test

Nothing today pins what `POST /drive-assets/sync-now` and
`POST /drive-assets/refresh-copy-metadata` (`backend/app/api/v1/drive_assets.py`)
actually call on `DriveSyncService`, with what arguments. This composition has
changed 5+ times in the last day (`4e6f468` → `a930dda` → `d32b88b` → `6ef0524` →
`b1febbf`) with no test catching any of the swings. Add a thin test (mock/spy
`DriveSyncService.sync_once` and `.refresh_copy_metadata`) asserting:
- `sync-now?backfill=true` calls `sync_once(backfill=True, ...)` — args as currently
  implemented, read the current route before writing the assertion
- `refresh-copy-metadata` calls whatever the current route composes (read
  `backend/app/api/v1/drive_assets.py::refresh_drive_copy_metadata` first — it has
  changed since this brief was written)

This is a regression trip-wire, not a design decision — it just needs to fail loudly
the next time someone reworks this composition without meaning to change behavior.

## Scope

Backend only, no migration, no trigger files. Should qualify for direct Codex push
per CLAUDE.md (no trigger file touched) — but `drive_sync_service.py` backs Joel's
Ad Creative Step Drive copy flow, so if you're unsure, hand off to Claude Code for
the pre-push review rather than guessing.
