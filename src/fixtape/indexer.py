from __future__ import annotations

from pathlib import Path
from typing import Any

from fixtape.artifact_parser import build_parsed_artifacts
from fixtape.generators.digest import build_session_digest
from fixtape.generators.todo import build_regression_draft
from fixtape.utils import iso_now, read_json, write_json


def build_session_index_entry(
    session: dict[str, Any],
    events: list[dict[str, Any]],
    session_dir: Path,
) -> dict[str, Any]:
    notes = [str(event.get("text") or "") for event in events if event["type"] == "note_added"]
    commands = [str(event.get("command") or "") for event in events if event["type"] == "command_ran"]
    artifacts = [str(event.get("source_path") or event.get("stored_path") or "") for event in events if event["type"] == "artifact_attached"]
    artifact_kinds = [str(event.get("kind") or "") for event in events if event["type"] == "artifact_attached" and event.get("kind")]
    parsed_artifacts = _load_or_build_parsed_artifacts(session_dir, events)
    digest = _load_or_build_digest(session_dir, session, events, parsed_artifacts)
    regression_draft = _load_or_build_regression_draft(session_dir, session, events)

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
        "artifact_kinds": list(dict.fromkeys(artifact_kinds))[:12],
        "signal_headlines": parsed_artifacts.get("top_signals") or [],
        "signal_fingerprints": parsed_artifacts.get("fingerprints") or [],
        "signal_exception_types": parsed_artifacts.get("exception_types") or [],
        "signal_families": parsed_artifacts.get("families") or [],
        "signal_status_codes": parsed_artifacts.get("status_codes") or [],
        "signal_file_hints": parsed_artifacts.get("file_hints") or [],
        "digest_summary": digest.get("summary_line") or "",
        "digest_root_cause": digest.get("root_cause_hint") or "",
        "digest_likely_area": digest.get("likely_area") or "",
        "digest_next_step": digest.get("next_step") or "",
        "digest_failure_family": digest.get("failure_family") or "",
        "regression_test_name": regression_draft.get("suggested_test_name") or "",
        "regression_entry_point": regression_draft.get("candidate_test_entry_point") or "",
        "regression_expected_behavior": regression_draft.get("expected_fixed_behavior") or "",
        "regression_fixture_candidates": regression_draft.get("fixture_candidates") or [],
        "regression_repro_commands": regression_draft.get("repro_commands") or [],
        "regression_failing_commands": regression_draft.get("failing_commands") or [],
        "note_count": len(notes),
        "command_count": len(commands),
        "artifact_count": len(artifacts),
        "indexed_at": iso_now(),
    }


def _load_or_build_parsed_artifacts(session_dir: Path, events: list[dict[str, Any]]) -> dict[str, Any]:
    generated_path = session_dir / "generated" / "parsed-artifacts.json"
    stored = read_json(generated_path)
    if stored:
        return stored
    return build_parsed_artifacts(events)


def _load_or_build_digest(
    session_dir: Path,
    session: dict[str, Any],
    events: list[dict[str, Any]],
    parsed_artifacts: dict[str, Any],
) -> dict[str, Any]:
    generated_path = session_dir / "generated" / "session-digest.json"
    stored = read_json(generated_path)
    if stored:
        return stored
    return build_session_digest(session, events, parsed_artifacts)


def _load_or_build_regression_draft(
    session_dir: Path,
    session: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    generated_path = session_dir / "generated" / "regression-draft.json"
    stored = read_json(generated_path)
    if stored:
        return stored
    return build_regression_draft(session, events)


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
