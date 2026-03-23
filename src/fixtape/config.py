from __future__ import annotations

import os
from pathlib import Path

from fixtape.git_tools import get_repo_root
from fixtape.utils import ensure_dir


def resolve_workspace_root(cwd: Path | None = None) -> Path:
    current = (cwd or Path.cwd()).resolve()
    repo_root = get_repo_root(current)
    return repo_root or current


def resolve_store_root(cwd: Path | None = None) -> Path:
    override = os.environ.get("FIXTAPE_HOME")
    if override:
        return ensure_dir(Path(override).expanduser().resolve())
    return ensure_dir(resolve_workspace_root(cwd) / ".fixtape")


def active_session_pointer(cwd: Path | None = None) -> Path:
    return resolve_store_root(cwd) / "active-session.json"


def last_session_pointer(cwd: Path | None = None) -> Path:
    return resolve_store_root(cwd) / "last-session.json"


def session_index_path(cwd: Path | None = None) -> Path:
    return resolve_store_root(cwd) / "session-index.json"


def sessions_root(cwd: Path | None = None) -> Path:
    return ensure_dir(resolve_store_root(cwd) / "sessions")
