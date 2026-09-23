# Codex Brief — `53d0095`'s next-line guard regresses both real Auto Dealer copy files

## Status

`53d0095` ("Guard handoff parser against non-ID labels") is committed locally, not pushed. It
correctly fixes the `Batch 3`/`Phase 2` false-positive repro from the previous brief — verified,
that part works. But re-running the same live-production validation the previous brief required
(not just the new unit tests, which are all synthetic) finds a real regression:

```
TOTAL_EXTRA: 0   TOTAL_MISSING: 10
```

Both `auto-dealerships-compliance-set.txt` and `auto-dealerships-claim-denial-set.txt` (the copy
files for the 2 real Auto Dealer packages) now parse to **zero blocks each** — they were 5/5 before
this commit. Every other of the 8 real handoff manifests/copy-file pairs is still clean.

## Root cause

The new guard in `_extract_handoff_copy_id` (`drive_sync_service.py`) requires the **immediate**
next non-blank line after a bare, nothing-following ID to look like a recognized field label
(`_looks_like_handoff_structure`). The real production copy file has an extra line the synthetic
unit test (`test_copy_file_keeps_auto_dealer_headline_out_of_image_fields`, from the prior commit)
didn't include:

```
AD DEALER CR 00
CONTROL RECREATION
Dealer Operations Review

PRIMARY TEXT
You run an auto dealership...
```

`AD DEALER CR 00`'s immediate next line is `CONTROL RECREATION` — a plain-text concept-name label,
not `PRIMARY TEXT`/`HEADLINE`/etc. and not itself a valid ID (no digits) — so
`_looks_like_handoff_structure` returns `False` and the real heading gets rejected outright,
producing zero parsed entries for the whole file.

Pull the real file yourself to confirm (same SSH/docker pattern as before):
```bash
ssh -i ~/.ssh/id_ed25519 ubuntu@adbuilder.velocitymx.io "docker exec ad-builder-api python -c \"
from app.database import SessionLocal
from app.services.drive_sync_service import DriveSyncService
db = SessionLocal()
svc = DriveSyncService(db)
drive = svc._client()
for f in svc._initial_folder_walk(drive):
    if f.get('name') == 'auto-dealerships-compliance-set.txt':
        print(svc._download_text_file(f['id'])[:600])
db.close()
\""
```

## Fix direction

The lookahead is too narrow — it only tolerates the label appearing on the *very next* line, but a
real heading can have 1+ plain description/title lines before the recognized structure resumes
(this repo's own naming style: an ID, then a human-readable concept title, then a blank line, then
the actual field labels). Widen the lookahead to skip past a small number of plain non-blank lines
(cap it — don't scan unboundedly, or a genuinely bare non-ID line deep in body prose could start
matching structure that belongs to something else entirely) before giving up. Verify against the
real Welders and both Florist/Barber Shops copy files too — they may or may not have this same
"concept line" pattern; don't assume Auto Dealer is the only one affected.

Whatever bound you pick, justify it against the real data, not a guess — check how many non-blank
lines actually separate a bare ID from its first recognized field label across all 8 real packages'
copy files and manifests, and set the cap to comfortably cover the real maximum you find (with some
margin), not the exact number.

## Verification requirement — same as last time, don't skip it

Unit tests passing is not sufcient — the last regression happened precisely because the new tests
were synthetic and didn't match real content. Before reporting back:

1. Re-run the full live-production validation (fetch all 8 real manifests + every copy file they
   reference, parse both, and confirm **zero extra, zero missing** across all of them — same method
   as the previous two rounds, live via SSH/docker exec against the real Drive content, not
   hand-written test fixtures).
2. Re-run the `Batch 3`/`Phase 2` repro tests to confirm this fix doesn't reopen the previous gap.
3. Add a regression test using the REAL Auto Dealer structure (ID → concept title line → blank line
   → `PRIMARY TEXT`) so this exact shape can't silently regress a third time.

## Hand-off

Same as before:

> "Edits done — ready for Claude Code 2-agent review + push."

Claude Code will re-run the live validation independently before pushing regardless of what you
report — this has caught two real gaps in two rounds now, so treat "passes my tests" as necessary
but not sufficient.
