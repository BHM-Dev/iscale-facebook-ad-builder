"""Regression tests for the local pre-push migration guard."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from check_alembic_heads import validate_migration_graph


def write_migration(directory, name, revision, down_revision):
    (directory / name).write_text(
        f'revision = "{revision}"\ndown_revision = {down_revision!r}\n', encoding="utf-8"
    )


def test_guard_rejects_duplicate_revision_ids(tmp_path):
    write_migration(tmp_path, "a_first.py", "abc123", None)
    write_migration(tmp_path, "b_duplicate.py", "abc123", None)
    _, errors = validate_migration_graph(str(tmp_path))
    assert any("duplicate revision abc123" in error for error in errors)


def test_guard_rejects_missing_parent(tmp_path):
    write_migration(tmp_path, "a_child.py", "child", "missing")
    _, errors = validate_migration_graph(str(tmp_path))
    assert "missing down_revision target: missing" in errors


def test_guard_accepts_single_linear_chain(tmp_path):
    write_migration(tmp_path, "a_base.py", "base", None)
    write_migration(tmp_path, "b_head.py", "head", "base")
    heads, errors = validate_migration_graph(str(tmp_path))
    assert errors == []
    assert heads == {"head": "b_head.py"}
