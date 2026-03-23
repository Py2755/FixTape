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
from fixtape.generators.digest import build_session_digest, normalize_digest_bucket
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

    def find_similar_sessions(self, session_id: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        sessions = self._load_indexed_sessions()
        if not sessions:
            self.reindex_sessions()
            sessions = self._load_indexed_sessions()

        target = None
        if session_id:
            for session in sessions:
                if session.get("id") == session_id:
                    target = session
                    break
            if target is None:
                raise FixTapeError(f"FixTape session not found: {session_id}")
        else:
            try:
                session_dir = self.get_preferred_session_dir()
                session, _ = self.load_session_from_dir(session_dir)
                target = next((item for item in sessions if item.get("id") == session["id"]), None)
            except NoActiveSessionError:
                target = sessions[0] if sessions else None

        if target is None:
            return []

        matches: list[dict[str, Any]] = []
        for candidate in sessions:
            if candidate.get("id") == target.get("id"):
                continue
            score, reasons = self._score_session_similarity(target, candidate)
            if score <= 0:
                continue
            matches.append({"session": candidate, "score": score, "reasons": reasons[:4]})

        matches.sort(key=lambda item: (item["score"], item["session"].get("created_at", "")), reverse=True)
        return matches[:limit]

    def recurring_patterns(self, limit: int = 5) -> list[dict[str, Any]]:
        sessions = self._load_indexed_sessions()
        if not sessions:
            self.reindex_sessions()
            sessions = self._load_indexed_sessions()

        buckets: dict[str, dict[str, Any]] = {}
        for session in sessions:
            seen_in_session: set[str] = set()
            for fingerprint in session.get("signal_fingerprints") or []:
                normalized = str(fingerprint).strip()
                if not normalized or normalized in seen_in_session:
                    continue
                seen_in_session.add(normalized)
                bucket = buckets.setdefault(
                    normalized,
                    {
                        "fingerprint": normalized,
                        "count": 0,
                        "titles": [],
                        "families": set(),
                        "exception_types": set(),
                        "file_hints": set(),
                        "headlines": set(),
                        "session_ids": [],
                    },
                )
                bucket["count"] += 1
                bucket["titles"].append(session.get("title"))
                bucket["session_ids"].append(session.get("id"))
                for family in session.get("signal_families") or []:
                    bucket["families"].add(str(family))
                for exc in session.get("signal_exception_types") or []:
                    bucket["exception_types"].add(str(exc))
                for hint in session.get("signal_file_hints") or []:
                    bucket["file_hints"].add(str(hint))
                for headline in session.get("signal_headlines") or []:
                    bucket["headlines"].add(str(headline))

        patterns: list[dict[str, Any]] = []
        for bucket in buckets.values():
            if bucket["count"] < 2:
                continue
            patterns.append(
                {
                    "fingerprint": bucket["fingerprint"],
                    "count": bucket["count"],
                    "families": sorted(bucket["families"])[:4],
                    "exception_types": sorted(bucket["exception_types"])[:4],
                    "file_hints": sorted(bucket["file_hints"])[:4],
                    "headline": next(iter(bucket["headlines"]), bucket["fingerprint"]),
                    "titles": [title for title in bucket["titles"][:3] if title],
                    "session_ids": bucket["session_ids"][:5],
                }
            )

        patterns.sort(key=lambda item: (item["count"], item["headline"]), reverse=True)
        return patterns[:limit]

    def incident_clusters(self, limit: int = 5, min_size: int = 2) -> list[dict[str, Any]]:
        sessions = self._load_indexed_sessions()
        if not sessions:
            self.reindex_sessions()
            sessions = self._load_indexed_sessions()
        if len(sessions) < min_size:
            return []

        adjacency: dict[str, set[str]] = {str(session["id"]): set() for session in sessions}
        lookup = {str(session["id"]): session for session in sessions}

        for index, left in enumerate(sessions):
            for right in sessions[index + 1 :]:
                score, reasons = self._score_session_similarity(left, right)
                if score < 70 or not reasons:
                    continue
                left_id = str(left["id"])
                right_id = str(right["id"])
                adjacency[left_id].add(right_id)
                adjacency[right_id].add(left_id)

        seen: set[str] = set()
        clusters: list[dict[str, Any]] = []
        for session in sessions:
            session_id = str(session["id"])
            if session_id in seen or not adjacency[session_id]:
                continue
            stack = [session_id]
            component: list[str] = []
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                component.append(current)
                stack.extend(sorted(adjacency[current] - seen))

            if len(component) < min_size:
                continue
            cluster_sessions = [lookup[item] for item in component if item in lookup]
            cluster_sessions.sort(key=lambda item: item.get("created_at", ""), reverse=True)
            clusters.append(self._build_cluster_payload(cluster_sessions))

        clusters.sort(key=lambda item: (item["count"], item["last_seen"]), reverse=True)
        return clusters[:limit]

    def hotspots(self, limit: int = 8, kind: str = "all") -> list[dict[str, Any]]:
        sessions = self._load_indexed_sessions()
        if not sessions:
            self.reindex_sessions()
            sessions = self._load_indexed_sessions()

        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for session in sessions:
            families = list(dict.fromkeys(str(item) for item in (session.get("signal_families") or []) if str(item).strip()))
            exceptions = list(dict.fromkeys(str(item) for item in (session.get("signal_exception_types") or []) if str(item).strip()))
            files = list(dict.fromkeys(str(item) for item in (session.get("signal_file_hints") or []) if str(item).strip()))
            statuses = [f"HTTP {item}" for item in session.get("signal_status_codes") or []]
            fingerprints = list(dict.fromkeys(str(item) for item in (session.get("signal_fingerprints") or []) if str(item).strip()))
            bucket_inputs = {
                "family": families,
                "exception": exceptions,
                "file": files,
                "status": statuses,
                "fingerprint": fingerprints,
            }
            for bucket_kind, values in bucket_inputs.items():
                if kind != "all" and kind != bucket_kind:
                    continue
                for value in values:
                    self._update_hotspot_bucket(buckets, bucket_kind, value, session)

        hotspots = []
        for bucket in buckets.values():
            if bucket["count"] < 2:
                continue
            hotspots.append(
                {
                    "kind": bucket["kind"],
                    "label": bucket["label"],
                    "count": bucket["count"],
                    "open_count": bucket["open_count"],
                    "last_seen": bucket["last_seen"],
                    "families": sorted(bucket["families"])[:4],
                    "examples": bucket["examples"][:3],
                    "headlines": list(bucket["headlines"])[:2],
                    "session_ids": bucket["session_ids"][:5],
                }
            )

        hotspots.sort(
            key=lambda item: (item["count"], item["open_count"], item["last_seen"], item["label"]),
            reverse=True,
        )
        return hotspots[:limit]

    def root_cause_lenses(self, limit: int = 5) -> dict[str, list[dict[str, Any]]]:
        sessions = self._load_indexed_sessions()
        if not sessions:
            self.reindex_sessions()
            sessions = self._load_indexed_sessions()

        family_buckets: dict[str, dict[str, Any]] = {}
        area_buckets: dict[str, dict[str, Any]] = {}
        digest_buckets: dict[str, dict[str, Any]] = {}

        for session in sessions:
            verdict = str(session.get("verdict") or "active")
            next_step = str(session.get("digest_next_step") or "").strip()
            for family in list(dict.fromkeys(str(item) for item in (session.get("signal_families") or []) if str(item).strip())):
                bucket = family_buckets.setdefault(
                    family,
                    {"label": family, "count": 0, "open_count": 0, "next_steps": {}, "examples": []},
                )
                bucket["count"] += 1
                if verdict in {"handoff", "unresolved", "needs-more-data", "active"}:
                    bucket["open_count"] += 1
                if next_step:
                    bucket["next_steps"][next_step] = bucket["next_steps"].get(next_step, 0) + 1
                title = str(session.get("title") or "")
                if title and title not in bucket["examples"]:
                    bucket["examples"].append(title)

            area_label = str(session.get("digest_likely_area") or "").strip()
            if area_label:
                bucket = area_buckets.setdefault(
                    area_label,
                    {"label": area_label, "count": 0, "open_count": 0, "families": set(), "examples": []},
                )
                bucket["count"] += 1
                if verdict in {"handoff", "unresolved", "needs-more-data", "active"}:
                    bucket["open_count"] += 1
                for family in session.get("signal_families") or []:
                    bucket["families"].add(str(family))
                title = str(session.get("title") or "")
                if title and title not in bucket["examples"]:
                    bucket["examples"].append(title)

            digest_label = normalize_digest_bucket(str(session.get("digest_root_cause") or session.get("digest_summary") or ""))
            if digest_label:
                bucket = digest_buckets.setdefault(
                    digest_label,
                    {"label": digest_label, "count": 0, "next_steps": {}, "examples": []},
                )
                bucket["count"] += 1
                if next_step:
                    bucket["next_steps"][next_step] = bucket["next_steps"].get(next_step, 0) + 1
                title = str(session.get("title") or "")
                if title and title not in bucket["examples"]:
                    bucket["examples"].append(title)

        families = []
        for bucket in family_buckets.values():
            if bucket["count"] < 2:
                continue
            families.append(
                {
                    "label": bucket["label"],
                    "count": bucket["count"],
                    "open_count": bucket["open_count"],
                    "next_step": self._top_bucket_value(bucket["next_steps"]) or "capture the next blocking fact",
                    "examples": bucket["examples"][:3],
                }
            )

        areas = []
        for bucket in area_buckets.values():
            if bucket["count"] < 2:
                continue
            areas.append(
                {
                    "label": bucket["label"],
                    "count": bucket["count"],
                    "open_count": bucket["open_count"],
                    "families": sorted(bucket["families"])[:3],
                    "examples": bucket["examples"][:3],
                }
            )

        digests = []
        for bucket in digest_buckets.values():
            if bucket["count"] < 2:
                continue
            digests.append(
                {
                    "label": bucket["label"],
                    "count": bucket["count"],
                    "next_step": self._top_bucket_value(bucket["next_steps"]) or "capture the next blocking fact",
                    "examples": bucket["examples"][:3],
                }
            )

        families.sort(key=lambda item: (item["count"], item["open_count"], item["label"]), reverse=True)
        areas.sort(key=lambda item: (item["count"], item["open_count"], item["label"]), reverse=True)
        digests.sort(key=lambda item: (item["count"], item["label"]), reverse=True)
        return {
            "families": families[:limit],
            "areas": areas[:limit],
            "digests": digests[:limit],
        }

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

    def _score_session_similarity(self, target: dict[str, Any], candidate: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []

        shared_fingerprints = self._shared_values(target.get("signal_fingerprints"), candidate.get("signal_fingerprints"))
        if shared_fingerprints:
            score += 85 * min(2, len(shared_fingerprints))
            reasons.append(f"shared failure fingerprint: {shared_fingerprints[0]}")

        shared_exception_types = self._shared_values(
            target.get("signal_exception_types"),
            candidate.get("signal_exception_types"),
        )
        if shared_exception_types:
            score += 35 * min(2, len(shared_exception_types))
            reasons.append(f"shared exception: {shared_exception_types[0]}")

        shared_file_hints = self._shared_values(target.get("signal_file_hints"), candidate.get("signal_file_hints"))
        if shared_file_hints:
            score += 24 * min(3, len(shared_file_hints))
            reasons.append(f"same failure area: {shared_file_hints[0]}")

        shared_refs = self._shared_values(target.get("refs"), candidate.get("refs"))
        if shared_refs:
            score += 18 * min(3, len(shared_refs))
            reasons.append(f"shared ref: {shared_refs[0]}")

        shared_title_tokens = self._shared_keyword_tokens(target, candidate, ("title", "summary"))
        if shared_title_tokens:
            score += 9 * min(4, len(shared_title_tokens))
            reasons.append(f"shared context: {', '.join(shared_title_tokens[:3])}")

        shared_command_tokens = self._shared_sequence_tokens(target.get("commands"), candidate.get("commands"))
        if shared_command_tokens:
            score += 5 * min(5, len(shared_command_tokens))
            reasons.append(f"similar commands: {', '.join(shared_command_tokens[:3])}")

        if target.get("verdict") and target.get("verdict") == candidate.get("verdict"):
            score += 6

        return score, reasons

    def _build_cluster_payload(self, cluster_sessions: list[dict[str, Any]]) -> dict[str, Any]:
        fingerprints = self._collect_cluster_values(cluster_sessions, "signal_fingerprints")
        families = self._collect_cluster_values(cluster_sessions, "signal_families")
        exceptions = self._collect_cluster_values(cluster_sessions, "signal_exception_types")
        files = self._collect_cluster_values(cluster_sessions, "signal_file_hints")
        refs = self._collect_cluster_values(cluster_sessions, "refs")
        verdicts: dict[str, int] = {}
        open_count = 0
        for session in cluster_sessions:
            verdict = str(session.get("verdict") or "active")
            verdicts[verdict] = verdicts.get(verdict, 0) + 1
            if verdict in {"handoff", "unresolved", "needs-more-data", "active"}:
                open_count += 1

        return {
            "count": len(cluster_sessions),
            "last_seen": max(str(session.get("created_at") or "") for session in cluster_sessions),
            "session_ids": [str(session["id"]) for session in cluster_sessions[:6]],
            "titles": [str(session.get("title") or "") for session in cluster_sessions[:4] if str(session.get("title") or "").strip()],
            "lead": str(cluster_sessions[0].get("title") or cluster_sessions[0].get("id") or "cluster"),
            "fingerprints": fingerprints[:4],
            "families": families[:4],
            "exceptions": exceptions[:4],
            "files": files[:4],
            "refs": refs[:4],
            "open_count": open_count,
            "verdicts": verdicts,
        }

    def _collect_cluster_values(self, sessions: list[dict[str, Any]], field: str) -> list[str]:
        ranked: dict[str, int] = {}
        for session in sessions:
            seen: set[str] = set()
            for value in session.get(field) or []:
                normalized = str(value).strip()
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                ranked[normalized] = ranked.get(normalized, 0) + 1
        return [item for item, _ in sorted(ranked.items(), key=lambda pair: (pair[1], pair[0]), reverse=True)]

    def _update_hotspot_bucket(
        self,
        buckets: dict[tuple[str, str], dict[str, Any]],
        kind: str,
        label: str,
        session: dict[str, Any],
    ) -> None:
        if not label:
            return
        key = (kind, label)
        bucket = buckets.setdefault(
            key,
            {
                "kind": kind,
                "label": label,
                "count": 0,
                "open_count": 0,
                "last_seen": "",
                "families": set(),
                "headlines": [],
                "examples": [],
                "session_ids": [],
            },
        )
        bucket["count"] += 1
        verdict = str(session.get("verdict") or "active")
        if verdict in {"handoff", "unresolved", "needs-more-data", "active"}:
            bucket["open_count"] += 1
        created_at = str(session.get("created_at") or "")
        if created_at > bucket["last_seen"]:
            bucket["last_seen"] = created_at
        bucket["session_ids"].append(str(session.get("id") or ""))
        title = str(session.get("title") or "")
        if title and title not in bucket["examples"]:
            bucket["examples"].append(title)
        for family in session.get("signal_families") or []:
            bucket["families"].add(str(family))
        for headline in session.get("signal_headlines") or []:
            normalized = str(headline).strip()
            if normalized and normalized not in bucket["headlines"]:
                bucket["headlines"].append(normalized)

    def _shared_values(self, left: Any, right: Any) -> list[str]:
        left_values = [str(item) for item in (left or []) if str(item).strip()]
        right_set = {str(item) for item in (right or []) if str(item).strip()}
        return [item for item in left_values if item in right_set]

    def _shared_keyword_tokens(self, left: dict[str, Any], right: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
        left_tokens: set[str] = set()
        right_tokens: set[str] = set()
        for field in fields:
            left_tokens.update(self._tokenize_text(str(left.get(field) or "")))
            right_tokens.update(self._tokenize_text(str(right.get(field) or "")))
        return sorted(left_tokens & right_tokens)

    def _shared_sequence_tokens(self, left: Any, right: Any) -> list[str]:
        left_tokens: set[str] = set()
        right_tokens: set[str] = set()
        for item in left or []:
            left_tokens.update(self._tokenize_text(str(item)))
        for item in right or []:
            right_tokens.update(self._tokenize_text(str(item)))
        return sorted(left_tokens & right_tokens)

    def _tokenize_text(self, text: str) -> set[str]:
        tokens = set(re.findall(r"[a-z0-9_.-]{3,}", text.lower()))
        return {token for token in tokens if token not in {"error", "exception", "failed", "traceback", "command"}}

    def _top_bucket_value(self, values: dict[str, int]) -> str | None:
        if not values:
            return None
        return sorted(values.items(), key=lambda item: (item[1], item[0]), reverse=True)[0][0]
