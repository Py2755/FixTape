from __future__ import annotations

import platform
import re
import shutil
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
from fixtape.generators.digest import build_session_digest, normalize_digest_bucket
from fixtape.git_tools import collect_git_state, write_diff_snapshots
from fixtape.indexer import build_session_index_entry, load_index, write_index
from fixtape.models import SessionRecord
from fixtape.pre_session import PreSessionRecorder
from fixtape.utils import detect_shell, ensure_dir, iso_now, parse_time_window, read_json, slugify, timestamp_slug, write_json

from fixtape.errors import ActiveSessionExistsError, FixTapeError, NoActiveSessionError  # noqa: F401
from fixtape.intelligence import IntelligenceMixin


class SessionStore(IntelligenceMixin):
    def __init__(self, cwd: Path | None = None) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.workspace_root = resolve_workspace_root(self.cwd)
        self.pointer_path = active_session_pointer(self.cwd)
        self.last_pointer_path = last_session_pointer(self.cwd)
        self.index_path = session_index_path(self.cwd)
        self.sessions_dir = sessions_root(self.cwd)
        self.recorder = PreSessionRecorder(self.cwd)

    def start_session(self, title: str, tags: list[str] | None = None, include_last: str | None = None) -> Path:
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

    def get_preferred_session_dir(self) -> Path:
        try:
            return self.get_active_session_dir()
        except NoActiveSessionError:
            return self.get_last_session_dir()

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

    def resolve_session_for_refs(self, session_id: str | None = None) -> dict[str, Any]:
        if session_id:
            session, _ = self.load_session_by_id(session_id)
            return session
        session_dir = self.get_preferred_session_dir()
        session, _ = self.load_session_from_dir(session_dir)
        return session

    def current_commit_ref(self) -> str:
        git_state = collect_git_state(self.cwd)
        if git_state is None or not git_state.head:
            raise FixTapeError("Current directory is not inside a Git repository with a resolvable HEAD commit.")
        return f"commit:{git_state.head}"

    def add_refs(self, refs: list[str], session_id: str | None = None) -> list[str]:
        session_dir = self.get_session_dir(session_id) if session_id else self.get_preferred_session_dir()
        session, _ = self.load_session_from_dir(session_dir)
        merged_refs = list(dict.fromkeys([*(session.get("refs") or []), *refs]))
        session["refs"] = merged_refs
        self.update_session(session_dir, session)
        append_event(
            session_dir / "events.jsonl",
            {
                "type": "refs_linked",
                "timestamp": iso_now(),
                "refs": refs,
            },
        )
        self._sync_session_index(session_dir)
        return merged_refs

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
        self.add_command_event_to_session_dir(session_dir, event)

    def add_command_event_to_session_dir(self, session_dir: Path, event: dict[str, Any], sync_index: bool = True) -> None:
        append_event(session_dir / "events.jsonl", event)
        if sync_index:
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
        include_last: str | None = None,
    ) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
        session, session_dir = self.load_session()
        if include_last:
            self.include_recent_buffer(session_dir, include_last, source="finish")
            session, _ = self.load_session_from_dir(session_dir)
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

    def recorder_status(self, window: str | None = None) -> dict[str, Any]:
        try:
            has_active_session = self.pointer_path.exists()
            status = self.recorder.status(window=window)
            if has_active_session:
                status["suggestion"] = None
            return status
        except ValueError as exc:
            raise FixTapeError(str(exc)) from exc

    def suggest_session_start(
        self,
        window: str = "20m",
        cooldown: str = "15m",
        mark_seen: bool = False,
    ) -> dict[str, Any] | None:
        try:
            suggestion = self.recorder.suggest_session_start(
                window=window,
                cooldown=cooldown,
                active_session=self.pointer_path.exists(),
                mark_seen=mark_seen,
            )
            if not suggestion:
                return None
            return self._enrich_session_start_suggestion(suggestion)
        except ValueError as exc:
            raise FixTapeError(str(exc)) from exc

    def record_pre_session_command(
        self,
        *,
        command: str,
        exit_code: int,
        shell: str,
        cwd: str | None,
        timestamp: str | None = None,
        duration_ms: float | None = None,
        args: list[str] | None = None,
        repro: bool = False,
        stdout_text: str | None = None,
        stderr_text: str | None = None,
        captured_via: str = "shell_hook",
    ) -> dict[str, Any]:
        event = self.recorder.record_command(
            command=command,
            exit_code=exit_code,
            shell=shell,
            cwd=cwd,
            timestamp=timestamp,
            duration_ms=duration_ms,
            args=args,
            repro=repro,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            captured_via=captured_via,
        )
        return event

    def include_recent_buffer(self, session_dir: Path, window: str, source: str = "promote") -> dict[str, Any]:
        try:
            parse_time_window(window)
        except ValueError as exc:
            raise FixTapeError(str(exc)) from exc
        recent_entries = self.recorder.recent_entries(window=window)
        return self.promote_buffer_entries(session_dir, recent_entries, source=source, window=window)

    def promote_buffer_entry(self, session_dir: Path, entry: dict[str, Any], source: str = "capture") -> dict[str, Any]:
        return self.promote_buffer_entries(session_dir, [entry], source=source)

    def promote_buffer_entries(
        self,
        session_dir: Path,
        entries: list[dict[str, Any]],
        source: str = "promote",
        window: str | None = None,
    ) -> dict[str, Any]:
        session_events = self.load_events(session_dir)
        existing_ids = {
            str(event.get("pre_session_id"))
            for event in session_events
            if event.get("type") == "command_ran" and event.get("pre_session_id")
        }
        imported_events: list[dict[str, Any]] = []
        imported_ids: list[str] = []
        counts = self.session_counts(session_dir)
        next_index = counts["commands"] + 1
        for entry in entries:
            pre_session_id = str(entry.get("pre_session_id") or "")
            if not pre_session_id or pre_session_id in existing_ids:
                continue
            event = self._materialize_pre_session_command(session_dir, entry, next_index)
            next_index += 1
            existing_ids.add(pre_session_id)
            imported_ids.append(pre_session_id)
            imported_events.append(event)

        for event in imported_events:
            self.add_command_event_to_session_dir(session_dir, event, sync_index=False)

        if imported_ids and source not in {"shell_hook", "capture"}:
            payload: dict[str, Any] = {
                "type": "pre_session_imported",
                "timestamp": iso_now(),
                "source": source,
                "count": len(imported_ids),
                "pre_session_ids": imported_ids,
            }
            if window:
                payload["window"] = window
            append_event(session_dir / "events.jsonl", payload)
        self._sync_session_index(session_dir)
        return {"count": len(imported_ids), "window": window, "source": source}

    def _materialize_pre_session_command(self, session_dir: Path, entry: dict[str, Any], index: int) -> dict[str, Any]:
        commands_dir = session_dir / "commands"
        stdout_path = self._copy_buffer_output(entry.get("stdout_file"), commands_dir / f"command_{index:03d}_stdout.txt")
        stderr_path = self._copy_buffer_output(entry.get("stderr_file"), commands_dir / f"command_{index:03d}_stderr.txt")
        return {
            **entry,
            "stdout_file": str(stdout_path) if stdout_path else None,
            "stderr_file": str(stderr_path) if stderr_path else None,
            "promoted_from_buffer": True,
        }

    def _copy_buffer_output(self, source_path: Any, destination: Path) -> Path | None:
        if not source_path:
            return None
        source = Path(str(source_path))
        if not source.exists():
            return None
        ensure_dir(destination.parent)
        shutil.copy2(source, destination)
        return destination

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
        active_fields = fields or {"title", "summary", "notes", "commands", "artifacts", "refs", "signals"}
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
            refs = [str(item) for item in session.get("refs", [])]
            signal_headlines = [str(item) for item in session.get("signal_headlines", [])]
            signal_exception_types = [str(item) for item in session.get("signal_exception_types", [])]
            signal_families = [str(item) for item in session.get("signal_families", [])]
            signal_file_hints = [str(item) for item in session.get("signal_file_hints", [])]
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
            for ref in refs:
                if "refs" in active_fields:
                    field_score = self._score_text_match(ref, needle, query_terms, base_weight=55)
                    if field_score:
                        hit_fields.append("ref")
                        snippets.append(self._make_snippet("ref", ref, needle))
                        score += field_score
            for signal in signal_headlines:
                if "signals" in active_fields:
                    field_score = self._score_text_match(signal, needle, query_terms, base_weight=58)
                    if field_score:
                        hit_fields.append("signal")
                        snippets.append(self._make_snippet("signal", signal, needle))
                        score += field_score
            for exception_type in signal_exception_types:
                if "signals" in active_fields:
                    field_score = self._score_text_match(exception_type, needle, query_terms, base_weight=52)
                    if field_score:
                        hit_fields.append("signal")
                        snippets.append(self._make_snippet("signal", exception_type, needle))
                        score += field_score
            for family in signal_families:
                if "signals" in active_fields:
                    field_score = self._score_text_match(family, needle, query_terms, base_weight=28)
                    if field_score:
                        hit_fields.append("signal")
                        snippets.append(self._make_snippet("signal", family, needle))
                        score += field_score
            for file_hint in signal_file_hints:
                if "signals" in active_fields:
                    field_score = self._score_text_match(file_hint, needle, query_terms, base_weight=25)
                    if field_score:
                        hit_fields.append("signal")
                        snippets.append(self._make_snippet("signal", file_hint, needle))
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

    # --- Index management ---

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

    def refresh_session_index(self, session_dir: Path) -> None:
        self._sync_session_index(session_dir)

    def load_or_build_digest(self, session_dir: Path, session: dict[str, Any] | None = None) -> dict[str, Any]:
        generated_path = session_dir / "generated" / "session-digest.json"
        stored = read_json(generated_path)
        if stored:
            return stored
        resolved_session = session or self.load_session_from_dir(session_dir)[0]
        events = self.load_events(session_dir)
        return build_session_digest(
            resolved_session,
            events,
            parsed_artifacts=read_json(session_dir / "generated" / "parsed-artifacts.json"),
        )

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
