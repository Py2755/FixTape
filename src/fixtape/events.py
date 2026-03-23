from __future__ import annotations

from pathlib import Path
from typing import Any

from fixtape.utils import append_jsonl, read_jsonl


def append_event(path: Path, event: dict[str, Any]) -> None:
    append_jsonl(path, event)


def load_events(path: Path) -> list[dict[str, Any]]:
    return read_jsonl(path)
