from __future__ import annotations

import subprocess
from pathlib import Path

from fixtape.models import GitState


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )


def get_repo_root(cwd: Path) -> Path | None:
    result = _git(["rev-parse", "--show-toplevel"], cwd)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def collect_git_state(cwd: Path) -> GitState | None:
    repo_root = get_repo_root(cwd)
    if repo_root is None:
        return None

    branch_result = _git(["branch", "--show-current"], repo_root)
    head_result = _git(["rev-parse", "HEAD"], repo_root)
    status_result = _git(["status", "--short"], repo_root)

    status_lines = [line.rstrip() for line in status_result.stdout.splitlines() if line.strip()]
    changed_files = []
    for line in status_lines:
        if len(line) > 3:
            changed_files.append(line[3:].strip())

    return GitState(
        repo_root=str(repo_root),
        branch=branch_result.stdout.strip() or None,
        head=head_result.stdout.strip() or None,
        dirty=bool(status_lines),
        status_short=status_lines,
        changed_files=changed_files,
    )


def write_diff_snapshots(repo_root: Path, target_dir: Path, prefix: str) -> tuple[str | None, str | None]:
    working_path = target_dir / f"{prefix}_working.diff"
    staged_path = target_dir / f"{prefix}_staged.diff"

    working = _git(["diff", "--binary"], repo_root)
    staged = _git(["diff", "--cached", "--binary"], repo_root)

    working_file = None
    staged_file = None

    if working.stdout:
        working_path.write_text(working.stdout, encoding="utf-8")
        working_file = working_path.name

    if staged.stdout:
        staged_path.write_text(staged.stdout, encoding="utf-8")
        staged_file = staged_path.name

    return working_file, staged_file
