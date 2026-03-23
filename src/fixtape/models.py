from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GitState:
    repo_root: str
    branch: str | None
    head: str | None
    dirty: bool
    status_short: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    working_diff_file: str | None = None
    staged_diff_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SessionRecord:
    id: str
    title: str
    created_at: str
    cwd: str
    workspace_root: str
    shell: str
    platform: str
    tags: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)
    repo_root: str | None = None
    finished_at: str | None = None
    verdict: str | None = None
    final_summary: str | None = None
    initial_git_state: dict[str, Any] | None = None
    final_git_state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
