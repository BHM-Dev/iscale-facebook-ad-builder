#!/usr/bin/env python3
"""Print a compact video-production handoff status for Codex/Claude."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WATCH_FILES = [
    "VIDEO_AGENT_COORDINATION.md",
    "AutoInsurance-VideoCreative-Guidance.md",
    "VIDEO_PRODUCTION_JOEL_WALKTHROUGH.md",
    "backend/scripts/video_finetuning_harness.py",
    "backend/scripts/video_assembly_harness.py",
]


def git_status() -> str:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return f"git status unavailable: {exc}"
    return result.stdout.strip() or "clean"


def modified_time(path: Path) -> str:
    if not path.exists():
        return "missing"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")


def tail_section(path: Path, marker: str, max_lines: int = 40) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    try:
        start = lines.index(marker) + 1
    except ValueError:
        return []
    collected = []
    for line in lines[start:]:
        if line.startswith("## ") and collected:
            break
        collected.append(line)
    return collected[-max_lines:]


def main() -> int:
    print("Video production coordination check")
    print(f"Repo: {ROOT}")
    print("")
    print("Watched files")
    for rel in WATCH_FILES:
        print(f"- {rel}: {modified_time(ROOT / rel)}")
    print("")
    print("Git status")
    print(git_status())
    print("")
    ledger = ROOT / "VIDEO_AGENT_COORDINATION.md"
    for marker in ("## Open Handoff Items", "## Codex Updates", "## Claude Updates"):
        section = tail_section(ledger, marker)
        if not section:
            continue
        print(marker.replace("## ", ""))
        for line in section:
            print(line)
        print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
