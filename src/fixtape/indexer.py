from __future__ import annotations

from pathlib import Path
from typing import Any

from fixtape.utils import iso_now, read_json, write_json


def build_session_index_entry(
    session: dict[str, Any],
    events: list[dict[str, Any]],
    session_dir: Path,
) -> dict[str, Any]:
    notes = [str(event.get("text") or "") for event in events if event["type"] == "note_added"]
    commands = [str(event.get("command") or "") for event in events if event["type"] == "command_ran"]
    artifacts = [str(event.get("source_path") or event.get("stored_path") or "") for event in events if event["type"] == "artifact_attached"]

    return {
        "id": session["id"],
        "title": session["title"],
        "created_at": session.get("created_at"),
        "finished_at": session.get("finished_at"),
        "verdict": session.get("verdict"),
        "refs": session.get("refs") or [],
        "session_dir": str(session_dir),
        "summary": session.get("final_summary") or "",
        "notes": notes[:25],
        "commands": commands[:25],
        "artifacts": artifacts[:25],
        "note_count": len(notes),
        "command_count": len(commands),
        "artifact_count": len(artifacts),
        "indexed_at": iso_now(),
    }


def load_index(index_path: Path) -> dict[str, Any]:
    index = read_json(index_path)
    if not index:
        return {"version": 1, "updated_at": None, "sessions": []}
    if "sessions" not in index:
        index["sessions"] = []
    if "version" not in index:
        index["version"] = 1
    return index


def write_index(index_path: Path, sessions: list[dict[str, Any]]) -> None:
    payload = {
        "version": 1,
        "updated_at": iso_now(),
        "sessions": sorted(sessions, key=lambda item: item.get("created_at", ""), reverse=True),
    }
    write_json(index_path, payload)
