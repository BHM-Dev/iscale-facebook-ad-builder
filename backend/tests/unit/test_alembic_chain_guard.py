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


def test_guard_ignores_lookalike_assignment_in_docstring(tmp_path):
    # A docstring quoting a fake revision line must never be mistaken for
    # the real top-level assignment below it.
    (tmp_path / "a_real.py").write_text(
        '"""\n'
        'Some migration.\n'
        'revision = "WRONGID"\n'
        '"""\n'
        'revision = "bbb222"\n'
        'down_revision = "aaa111"\n',
        encoding="utf-8",
    )
    write_migration(tmp_path, "a_base.py", "aaa111", None)
    heads, errors = validate_migration_graph(str(tmp_path))
    assert errors == []
    assert heads == {"bbb222": "a_real.py"}


def test_guard_accepts_hyphenated_revision_ids(tmp_path):
    write_migration(tmp_path, "a_base.py", "abc-123", None)
    heads, errors = validate_migration_graph(str(tmp_path))
    assert errors == []
    assert heads == {"abc-123": "a_base.py"}


def test_guard_ignores_trailing_comment_on_down_revision_line(tmp_path):
    (tmp_path / "a_base.py").write_text('revision = "aaa111"\ndown_revision = None\n', encoding="utf-8")
    (tmp_path / "b_child.py").write_text(
        'revision = "bbb222"\n'
        'down_revision = "aaa111"  # noqa \'ccc333\' unused\n',
        encoding="utf-8",
    )
    heads, errors = validate_migration_graph(str(tmp_path))
    assert errors == []
    assert heads == {"bbb222": "b_child.py"}


def test_guard_handles_merge_migration_tuple_down_revision(tmp_path):
    write_migration(tmp_path, "a_base.py", "aaa111", None)
    write_migration(tmp_path, "b_base.py", "bbb222", None)
    (tmp_path / "c_merge.py").write_text(
        'revision = "ccc333"\ndown_revision = ("aaa111", "bbb222")\n', encoding="utf-8"
    )
    heads, errors = validate_migration_graph(str(tmp_path))
    assert errors == []
    assert heads == {"ccc333": "c_merge.py"}


def test_guard_reports_unparseable_file(tmp_path):
    (tmp_path / "a_broken.py").write_text("revision = 'unterminated\n", encoding="utf-8")
    _, errors = validate_migration_graph(str(tmp_path))
    assert any("a_broken.py: could not parse" in error for error in errors)


def test_guard_rejects_two_node_cycle(tmp_path):
    # heads = revisions - down_refs alone can't see this: A's down_revision
    # is B and B's down_revision is A, so both are somebody's down_revision
    # and neither is ever excluded from being a "head" by that set-difference
    # -- heads comes back empty, which main() previously read as "0 or 1
    # heads, chain is healthy." A corrupted, cyclic migration graph must be
    # rejected, not silently reported as safe to push.
    write_migration(tmp_path, "a_first.py", "aaa111", "bbb222")
    write_migration(tmp_path, "b_second.py", "bbb222", "aaa111")
    heads, errors = validate_migration_graph(str(tmp_path))
    assert heads == {}
    assert any("cycle detected" in error for error in errors)


def test_guard_rejects_longer_cycle_off_a_valid_branch(tmp_path):
    # A real head (c) exists alongside an unrelated 3-node cycle (x -> y ->
    # z -> x) that isn't reachable from any valid head -- the cycle must
    # still be caught even though a plausible-looking single head is found.
    write_migration(tmp_path, "a_base.py", "aaa", None)
    write_migration(tmp_path, "c_head.py", "ccc", "aaa")
    write_migration(tmp_path, "x.py", "xxx", "zzz")
    write_migration(tmp_path, "y.py", "yyy", "xxx")
    write_migration(tmp_path, "z.py", "zzz", "yyy")
    _, errors = validate_migration_graph(str(tmp_path))
    assert any("cycle detected" in error for error in errors)
