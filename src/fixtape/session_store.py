from __future__ import annotations

import platform
import re
import zipfile
import json
from pathlib import Path
from typing import Any

from fixtape.config import (
    active_session_pointer,
    last_session_pointer,
    resolve_workspace_root,
    session_index_path,
    sessions_root,
)
from fixtape.events import append_event, load_events
from fixtape.git_tools import collect_git_state, write_diff_snapshots
from fixtape.indexer import build_session_index_entry, load_index, write_index
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
        self.index_path = session_index_path(self.cwd)
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
        self._sync_session_index(session_dir)
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
        self._sync_session_index(session_dir)

    def add_command_event(self, event: dict[str, Any]) -> None:
        _, session_dir = self.load_session()
        append_event(session_dir / "events.jsonl", event)
        self._sync_session_index(session_dir)

    def add_artifact_event(self, event: dict[str, Any]) -> None:
        _, session_dir = self.load_session()
        append_event(session_dir / "events.jsonl", event)
        self._sync_session_index(session_dir)

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
        self._sync_session_index(session_dir)
        return event

    def finalize_session(
        self,
        verdict: str,
        summary: str | None = None,
        refs: list[str] | None = None,
    ) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
        session, session_dir = self.load_session()
        final_git_state = collect_git_state(self.cwd)
        session["finished_at"] = iso_now()
        session["verdict"] = verdict
        session["final_summary"] = summary
        merged_refs = list(dict.fromkeys([*(session.get("refs") or []), *(refs or [])]))
        session["refs"] = merged_refs
        session["final_git_state"] = final_git_state.to_dict() if final_git_state else None
        self.update_session(session_dir, session)

        append_event(
            session_dir / "events.jsonl",
            {
                "type": "session_finished",
                "timestamp": iso_now(),
                "verdict": verdict,
                "summary": summary,
                "refs": merged_refs,
            },
        )
        events = self.load_events(session_dir)
        write_json(self.last_pointer_path, {"session_id": session["id"], "session_dir": str(session_dir)})
        if self.pointer_path.exists():
            self.pointer_path.unlink()
        self._sync_session_index(session_dir)
        return session, session_dir, events

    def export_session(self, destination: Path) -> Path:
        try:
            session_dir = self.get_active_session_dir()
        except NoActiveSessionError:
            session_dir = self.get_last_session_dir()
        session, _ = self.load_session_from_dir(session_dir)
        events = self.load_events(session_dir)
        destination = destination.resolve()
        ensure_dir(destination.parent)
        bundle_root = f"fixtape-handoff-{session['id']}"
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            generated_dir = session_dir / "generated"
            script_name = "repro.ps1" if (generated_dir / "repro.ps1").exists() else "repro.sh"
            top_level_files = [
                (generated_dir / "handoff.md", "HANDOFF.md"),
                (generated_dir / "debug-summary.md", "SUMMARY.md"),
                (generated_dir / script_name, "REPRO_SCRIPT"),
                (generated_dir / "regression-test.todo.md", "REGRESSION_TEST_TODO.md"),
            ]
            for source_path, alias in top_level_files:
                if source_path.exists():
                    archive.write(source_path, arcname=f"{bundle_root}/{alias}")

            metadata = {
                "session_id": session["id"],
                "title": session["title"],
                "verdict": session.get("verdict"),
                "created_at": session.get("created_at"),
                "finished_at": session.get("finished_at"),
                "refs": session.get("refs") or [],
                "workspace_root": session.get("workspace_root"),
                "repo_root": session.get("repo_root"),
                "artifact_count": sum(1 for item in events if item["type"] == "artifact_attached"),
                "command_count": sum(1 for item in events if item["type"] == "command_ran"),
                "note_count": sum(1 for item in events if item["type"] == "note_added"),
            }
            archive.writestr(
                f"{bundle_root}/metadata.json",
                json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            )
            for file_path in session_dir.rglob("*"):
                if file_path.is_file():
                    archive.write(file_path, arcname=f"{bundle_root}/session/{file_path.relative_to(session_dir)}")
        return destination

    def list_sessions(self, limit: int = 10) -> list[dict[str, Any]]:
        sessions = self._load_indexed_sessions()
        if not sessions:
            self.reindex_sessions()
            sessions = self._load_indexed_sessions()
        return sessions[:limit]

    def search_sessions(self, query: str, fields: set[str] | None = None, limit: int = 10) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        active_fields = fields or {"title", "summary", "notes", "commands", "artifacts"}
        query_terms = [term for term in re.split(r"\s+", needle) if term]

        matches: list[dict[str, Any]] = []
        indexed_sessions = self._load_indexed_sessions()
        if not indexed_sessions:
            self.reindex_sessions()
            indexed_sessions = self._load_indexed_sessions()

        for session in indexed_sessions:
            hit_fields: list[str] = []
            snippets: list[str] = []
            score = 0

            title = str(session.get("title") or "")
            summary = str(session.get("summary") or "")
            if "title" in active_fields:
                field_score = self._score_text_match(title, needle, query_terms, base_weight=80)
                if field_score:
                    hit_fields.append("title")
                    snippets.append(self._make_snippet("title", title, needle))
                    score += field_score
            if "summary" in active_fields and summary:
                field_score = self._score_text_match(summary, needle, query_terms, base_weight=60)
                if field_score:
                    hit_fields.append("summary")
                    snippets.append(self._make_snippet("summary", summary, needle))
                    score += field_score

            for text in session.get("notes", []):
                if "notes" in active_fields:
                    field_score = self._score_text_match(text, needle, query_terms, base_weight=35)
                    if field_score:
                        hit_fields.append("note")
                        snippets.append(self._make_snippet("note", text, needle))
                        score += field_score
            for command in session.get("commands", []):
                if "commands" in active_fields:
                    field_score = self._score_text_match(command, needle, query_terms, base_weight=25)
                    if field_score:
                        hit_fields.append("command")
                        snippets.append(self._make_snippet("command", command, needle))
                        score += field_score
            for source_path in session.get("artifacts", []):
                if "artifacts" in active_fields:
                    field_score = self._score_text_match(source_path, needle, query_terms, base_weight=15)
                    if field_score:
                        hit_fields.append("artifact")
                        snippets.append(self._make_snippet("artifact", source_path, needle))
                        score += field_score

            if hit_fields and score > 0:
                unique_fields = list(dict.fromkeys(hit_fields))
                unique_snippets = list(dict.fromkeys(snippets))
                matches.append(
                    {
                        "session": session,
                        "hit_fields": unique_fields,
                        "snippets": unique_snippets[:3],
                        "score": score,
                    }
                )

        matches.sort(key=lambda item: (item["score"], item["session"].get("created_at", "")), reverse=True)
        return matches[:limit]

    def reindex_sessions(self) -> int:
        entries: list[dict[str, Any]] = []
        for session_file in self.sessions_dir.glob("*/session.json"):
            session_dir = session_file.parent
            session = read_json(session_file)
            if not session:
                continue
            events = self.load_events(session_dir)
            entry = build_session_index_entry(session, events, session_dir)
            entries.append(entry)
        write_index(self.index_path, entries)
        return len(entries)

    def _load_indexed_sessions(self) -> list[dict[str, Any]]:
        index = load_index(self.index_path)
        active_session_id = None
        pointer = read_json(self.pointer_path)
        if pointer:
            active_session_id = pointer.get("session_id")

        sessions: list[dict[str, Any]] = []
        for entry in index.get("sessions", []):
            session_copy = dict(entry)
            session_copy["is_active"] = session_copy.get("id") == active_session_id
            sessions.append(session_copy)
        sessions.sort(key=lambda item: (item.get("is_active", False), item.get("created_at", "")), reverse=True)
        return sessions

    def _sync_session_index(self, session_dir: Path) -> None:
        session, _ = self.load_session_from_dir(session_dir)
        events = self.load_events(session_dir)
        entry = build_session_index_entry(session, events, session_dir)
        index = load_index(self.index_path)
        entries = [item for item in index.get("sessions", []) if item.get("id") != session["id"]]
        entries.append(entry)
        write_index(self.index_path, entries)

    def _score_text_match(self, text: str, needle: str, query_terms: list[str], base_weight: int) -> int:
        haystack = text.lower()
        if needle not in haystack and not any(term in haystack for term in query_terms):
            return 0

        score = 0
        if needle in haystack:
            score += base_weight
            if haystack == needle:
                score += 80
            elif haystack.startswith(needle):
                score += 35
            elif re.search(rf"\b{re.escape(needle)}\b", haystack):
                score += 25

        matched_terms = 0
        for term in query_terms:
            if term in haystack:
                matched_terms += 1
                score += 8
                if re.search(rf"\b{re.escape(term)}\b", haystack):
                    score += 4

        if query_terms and matched_terms == len(query_terms):
            score += 12

        return score

    def _make_snippet(self, label: str, text: str, needle: str, radius: int = 42) -> str:
        lowered = text.lower()
        index = lowered.find(needle)
        if index == -1:
            for term in [part for part in needle.split() if part]:
                index = lowered.find(term)
                if index != -1:
                    needle = term
                    break

        if index == -1:
            compact = " ".join(text.split())
            compact = compact[: (radius * 2)]
            return f"[{label}] {compact}"

        start = max(0, index - radius)
        end = min(len(text), index + len(needle) + radius)
        snippet = text[start:end].strip()
        snippet = " ".join(snippet.split())
        if start > 0:
            snippet = f"...{snippet}"
        if end < len(text):
            snippet = f"{snippet}..."
        return f"[{label}] {snippet}"
