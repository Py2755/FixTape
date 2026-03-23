from __future__ import annotations

import platform
import zipfile
from pathlib import Path
from typing import Any

from fixtape.config import active_session_pointer, last_session_pointer, resolve_workspace_root, sessions_root
from fixtape.events import append_event, load_events
from fixtape.git_tools import collect_git_state, write_diff_snapshots
from fixtape.models import SessionRecord
from fixtape.utils import detect_shell, ensure_dir, iso_now, read_json, slugify, timestamp_slug, write_json


class FixTapeError(RuntimeError):
    """Base FixTape error."""


class NoActiveSessionError(FixTapeError):
    """Raised when no active session exists."""


class ActiveSessionExistsError(FixTapeError):
    """Raised when another session is already active."""


class SessionStore:
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.workspace_root = resolve_workspace_root(self.cwd)
        self.pointer_path = active_session_pointer(self.cwd)
        self.last_pointer_path = last_session_pointer(self.cwd)
        self.sessions_dir = sessions_root(self.cwd)

    def start_session(self, title: str, tags: list[str] | None = None) -> Path:
        if self.pointer_path.exists():
            raise ActiveSessionExistsError("An active FixTape session already exists.")

        session_id = f"{timestamp_slug()}_{slugify(title)}"
        session_dir = self.sessions_dir / session_id
        ensure_dir(session_dir)
        ensure_dir(session_dir / "commands")
        ensure_dir(session_dir / "artifacts")
        ensure_dir(session_dir / "snapshots")
        ensure_dir(session_dir / "generated")

        git_state = collect_git_state(self.cwd)
        record = SessionRecord(
            id=session_id,
            title=title,
            created_at=iso_now(),
            cwd=str(self.cwd),
            workspace_root=str(self.workspace_root),
            repo_root=git_state.repo_root if git_state else None,
            shell=detect_shell(),
            platform=platform.platform(),
            tags=tags or [],
            initial_git_state=git_state.to_dict() if git_state else None,
        )

        write_json(session_dir / "session.json", record.to_dict())
        (session_dir / "events.jsonl").touch()
        write_json(self.pointer_path, {"session_id": session_id, "session_dir": str(session_dir)})

        append_event(
            session_dir / "events.jsonl",
            {
                "type": "session_started",
                "timestamp": iso_now(),
                "title": title,
                "tags": tags or [],
            },
        )
        return session_dir

    def get_active_session_dir(self) -> Path:
        pointer = read_json(self.pointer_path)
        if not pointer:
            raise NoActiveSessionError("No active FixTape session.")
        return self._resolve_pointer(pointer)

    def _resolve_pointer(self, pointer: dict[str, Any]) -> Path:
        session_dir = Path(pointer["session_dir"]).resolve()
        if not session_dir.exists():
            raise NoActiveSessionError("Active FixTape session pointer is stale.")
        return session_dir

    def get_last_session_dir(self) -> Path:
        pointer = read_json(self.last_pointer_path)
        if not pointer:
            raise NoActiveSessionError("No finished FixTape session is available for export.")
        return self._resolve_pointer(pointer)

    def get_session_dir(self, session_id: str) -> Path:
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            raise FixTapeError(f"FixTape session not found: {session_id}")
        return session_dir

    def load_session(self) -> tuple[dict[str, Any], Path]:
        session_dir = self.get_active_session_dir()
        return self.load_session_from_dir(session_dir)

    def load_session_from_dir(self, session_dir: Path) -> tuple[dict[str, Any], Path]:
        session = read_json(session_dir / "session.json")
        if not session:
            raise NoActiveSessionError("Active FixTape session metadata is missing.")
        return session, session_dir

    def load_session_by_id(self, session_id: str) -> tuple[dict[str, Any], Path]:
        return self.load_session_from_dir(self.get_session_dir(session_id))

    def load_events(self, session_dir: Path) -> list[dict[str, Any]]:
        return load_events(session_dir / "events.jsonl")

    def session_counts(self, session_dir: Path) -> dict[str, int]:
        events = self.load_events(session_dir)
        return {
            "notes": sum(1 for event in events if event["type"] == "note_added"),
            "commands": sum(1 for event in events if event["type"] == "command_ran"),
            "artifacts": sum(1 for event in events if event["type"] == "artifact_attached"),
            "snapshots": sum(1 for event in events if event["type"] == "snapshot_created"),
        }

    def update_session(self, session_dir: Path, session: dict[str, Any]) -> None:
        write_json(session_dir / "session.json", session)

    def add_note(self, text: str) -> None:
        _, session_dir = self.load_session()
        append_event(
            session_dir / "events.jsonl",
            {
                "type": "note_added",
                "timestamp": iso_now(),
                "text": text,
            },
        )

    def add_command_event(self, event: dict[str, Any]) -> None:
        _, session_dir = self.load_session()
        append_event(session_dir / "events.jsonl", event)

    def add_artifact_event(self, event: dict[str, Any]) -> None:
        _, session_dir = self.load_session()
        append_event(session_dir / "events.jsonl", event)

    def create_snapshot(self) -> dict[str, Any]:
        _, session_dir = self.load_session()
        git_state = collect_git_state(self.cwd)
        if git_state is None:
            raise FixTapeError("Current directory is not inside a Git repository.")

        events = self.load_events(session_dir)
        snapshot_index = sum(1 for item in events if item["type"] == "snapshot_created") + 1
        prefix = f"snapshot_{snapshot_index:03d}"
        working_diff_file, staged_diff_file = write_diff_snapshots(
            Path(git_state.repo_root),
            session_dir / "snapshots",
            prefix,
        )
        git_state.working_diff_file = working_diff_file
        git_state.staged_diff_file = staged_diff_file

        event = {
            "type": "snapshot_created",
            "timestamp": iso_now(),
            **git_state.to_dict(),
        }
        append_event(session_dir / "events.jsonl", event)
        return event

    def finalize_session(self, verdict: str, summary: str | None = None) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
        session, session_dir = self.load_session()
        final_git_state = collect_git_state(self.cwd)
        session["finished_at"] = iso_now()
        session["verdict"] = verdict
        session["final_summary"] = summary
        session["final_git_state"] = final_git_state.to_dict() if final_git_state else None
        self.update_session(session_dir, session)

        append_event(
            session_dir / "events.jsonl",
            {
                "type": "session_finished",
                "timestamp": iso_now(),
                "verdict": verdict,
                "summary": summary,
            },
        )
        events = self.load_events(session_dir)
        write_json(self.last_pointer_path, {"session_id": session["id"], "session_dir": str(session_dir)})
        if self.pointer_path.exists():
            self.pointer_path.unlink()
        return session, session_dir, events

    def export_session(self, destination: Path) -> Path:
        try:
            session_dir = self.get_active_session_dir()
        except NoActiveSessionError:
            session_dir = self.get_last_session_dir()
        destination = destination.resolve()
        ensure_dir(destination.parent)
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for file_path in session_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, arcname=str(file_path.relative_to(session_dir.parent)))
        return destination

    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for session_file in self.sessions_dir.glob("*/session.json"):
            session = read_json(session_file)
            if session:
                sessions.append(session)
        sessions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
        return sessions[:limit]

    def search_sessions(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []

        matches: list[dict[str, Any]] = []
        for session in self.list_sessions(limit=10_000):
            session_dir = self.get_session_dir(session["id"])
            events = self.load_events(session_dir)

            hit_fields: list[str] = []
            snippets: list[str] = []

            title = str(session.get("title") or "")
            summary = str(session.get("final_summary") or "")
            if needle in title.lower():
                hit_fields.append("title")
                snippets.append(title)
            if summary and needle in summary.lower():
                hit_fields.append("summary")
                snippets.append(summary)

            for event in events:
                if event["type"] == "note_added":
                    text = str(event.get("text") or "")
                    if needle in text.lower():
                        hit_fields.append("note")
                        snippets.append(text)
                elif event["type"] == "command_ran":
                    command = str(event.get("command") or "")
                    if needle in command.lower():
                        hit_fields.append("command")
                        snippets.append(command)
                elif event["type"] == "artifact_attached":
                    source_path = str(event.get("source_path") or "")
                    if needle in source_path.lower():
                        hit_fields.append("artifact")
                        snippets.append(source_path)

            if hit_fields:
                unique_fields = list(dict.fromkeys(hit_fields))
                unique_snippets = list(dict.fromkeys(snippets))
                matches.append(
                    {
                        "session": session,
                        "hit_fields": unique_fields,
                        "snippets": unique_snippets[:3],
                    }
                )

        matches.sort(key=lambda item: item["session"].get("created_at", ""), reverse=True)
        return matches[:limit]
