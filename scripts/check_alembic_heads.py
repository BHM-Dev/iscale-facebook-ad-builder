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

import ast
import json
import os
import sys

# Resolve versions dir relative to this script's location so the check works
# regardless of what directory Claude Code is launched from.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSIONS_DIR = os.path.join(SCRIPT_DIR, "..", "backend", "alembic", "versions")


def _string_literals(node: "ast.AST | None") -> list[str]:
    """Pull revision id string(s) out of a Constant/Tuple/List AST node.

    Handles ``None``, a plain string, and the tuple/list a merge migration
    uses for ``down_revision``. Returns [] for anything else (e.g. a name or
    expression this script doesn't need to understand).
    """
    if node is None:
        return []
    if isinstance(node, ast.Constant):
        return [node.value] if isinstance(node.value, str) else []
    if isinstance(node, (ast.Tuple, ast.List)):
        ids: list[str] = []
        for elt in node.elts:
            ids.extend(_string_literals(elt))
        return ids
    return []


def validate_migration_graph(versions_dir: str) -> tuple[dict[str, str], list[str]]:
    """Return heads and fatal graph errors for a migration directory.

    Parses each file's AST rather than regexing the source text. A regex
    scan of the whole file can match a `revision = "..."`-looking line
    inside a docstring or a trailing comment and silently use the wrong
    id — exactly the class of bug that let a real duplicate-revision
    migration slip through and break production. Reading only the
    top-level `revision`/`down_revision` assignments via ast.parse can't
    be fooled by comments or docstrings, and correctly extracts any string
    value (including hyphenated ids) instead of only `\\w+`.
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

        try:
            tree = ast.parse(content, filename=fname)
        except SyntaxError as exc:
            errors.append(f"{fname}: could not parse ({exc})")
            continue

        revision_id = None
        down_revision_node = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target, value = node.targets[0].id, node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target, value = node.target.id, node.value
            else:
                continue

            if target == "revision":
                ids = _string_literals(value)
                if ids:
                    revision_id = ids[0]
            elif target == "down_revision":
                down_revision_node = value

        if revision_id is None:
            errors.append(f"{fname}: missing revision assignment")
            continue
        if revision_id in revisions:
            errors.append(f"duplicate revision {revision_id}: {revisions[revision_id]} and {fname}")
        else:
            revisions[revision_id] = fname

        down_refs.update(_string_literals(down_revision_node))

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
