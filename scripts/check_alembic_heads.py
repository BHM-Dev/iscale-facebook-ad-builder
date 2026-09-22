#!/usr/bin/env python3
"""
Alembic migration chain validator.

Scans backend/alembic/versions/ and checks whether the migration graph
has exactly one head.  Outputs JSON consumed by the Claude Code PreToolUse
hook so a git push is blocked immediately when the chain is branched.

Exit codes:
  0 — single head, chain is linear, push is safe
  1 — multiple heads found, push blocked

Usage (standalone):
  python3 scripts/check_alembic_heads.py

Usage (Claude Code hook — reads nothing from stdin, just exits + prints):
  Already wired up via .claude/settings.json PreToolUse hook.
"""

import json
import os
import re
import sys

# Resolve versions dir relative to this script's location so the check works
# regardless of what directory Claude Code is launched from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSIONS_DIR = os.path.join(SCRIPT_DIR, "..", "backend", "alembic", "versions")


def validate_migration_graph(versions_dir: str) -> tuple[dict[str, str], list[str]]:
    """Return heads and fatal graph errors for a migration directory.

    Alembic itself can obscure a duplicate ``revision`` assignment because a
    dict-like revision map keeps only one of the files. Detect it here before
    it becomes an ambiguous deploy-time migration graph.
    """
    revisions: dict[str, str] = {}
    down_refs: set[str] = set()     # all IDs referenced as down_revision
    errors: list[str] = []

    for fname in sorted(os.listdir(versions_dir)):
        if not fname.endswith(".py"):
            continue
        path = os.path.join(versions_dir, fname)
        try:
            content = open(path).read()
        except OSError:
            continue

        # Alembic-generated files may use either `revision =` or the typed
        # `revision: str =` form. The guard must understand both.
        rev_match = re.search(r"^revision(?:\s*:\s*[^=]+)?\s*=\s*['\"](\w+)['\"]", content, re.M)
        # down_revision can be None, a single string, or a tuple/list (merge migration)
        down_match = re.search(
            r"^down_revision(?:\s*:\s*[^=]+)?\s*=\s*([^\n]+)", content, re.M
        )

        if not rev_match:
            errors.append(f"{fname}: missing revision assignment")
            continue
        revision = rev_match.group(1)
        if revision in revisions:
            errors.append(f"duplicate revision {revision}: {revisions[revision]} and {fname}")
        else:
            revisions[revision] = fname

        if down_match:
            raw = down_match.group(1).strip()
            # Extract all quoted revision IDs from the value
            for r in re.findall(r"['\"](\w+)['\"]", raw):
                down_refs.add(r)

    missing_parents = sorted(down_refs - set(revisions))
    errors.extend(f"missing down_revision target: {revision}" for revision in missing_parents)
    return {r: revisions[r] for r in revisions if r not in down_refs}, errors


def main() -> None:
    if not os.path.isdir(VERSIONS_DIR):
        # Can't find versions dir — don't block, just warn
        sys.stderr.write(f"check_alembic_heads: versions dir not found at {VERSIONS_DIR}\n")
        sys.exit(0)

    heads, errors = validate_migration_graph(VERSIONS_DIR)

    if errors:
        message = "🚨 Alembic migration graph is invalid — push blocked.\n\n" + "\n".join(f"  • {error}" for error in errors)
        print(json.dumps({"continue": False, "stopReason": message}))
        sys.exit(1)

    if len(heads) <= 1:
        # Single head (or no migrations at all) — chain is healthy
        sys.exit(0)

    head_list = "\n".join(f"  • {r}  ({f})" for r, f in heads.items())
    message = (
        f"🚨 Alembic migration chain has {len(heads)} heads — push blocked.\n\n"
        f"Heads found:\n{head_list}\n\n"
        "This is what broke login last time. Fix before pushing:\n"
        "  Update the down_revision of the newest migration to point to the\n"
        "  correct parent (whichever head is currently at the end of the chain).\n\n"
        "Quick check: grep -h '^revision\\|^down_revision' backend/alembic/versions/*.py"
    )

    # Output the Claude Code hook JSON that blocks the push
    print(json.dumps({"continue": False, "stopReason": message}))
    sys.exit(1)


if __name__ == "__main__":
    main()
