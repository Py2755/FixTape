from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def build_session_digest(
    session: dict[str, Any],
    events: list[dict[str, Any]],
    parsed_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    notes = [event for event in events if event["type"] == "note_added"]
    commands = [event for event in events if event["type"] == "command_ran"]
    attachments = [event for event in events if event["type"] == "artifact_attached"]
    parsed_artifacts = parsed_artifacts or {}

    top_signal = _first(parsed_artifacts.get("top_signals"))
    exception_type = _first(parsed_artifacts.get("exception_types"))
    failure_family = _first(parsed_artifacts.get("families"))
    likely_area = _first(parsed_artifacts.get("file_hints")) or _derive_area_from_attachments(attachments)
    repro_command = _select_repro_command(commands)
    root_cause_hint = _select_root_cause_hint(session, notes, top_signal)
    next_step = _select_next_step(session.get("verdict"), repro_command, likely_area)
    summary_line = _build_summary_line(session, failure_family, exception_type, likely_area, top_signal)

    return {
        "session_id": session["id"],
        "title": session["title"],
        "verdict": session.get("verdict") or "active",
        "summary_line": summary_line,
        "failure_family": failure_family,
        "exception_type": exception_type,
        "top_signal": top_signal,
        "likely_area": likely_area,
        "root_cause_hint": root_cause_hint,
        "repro_command": repro_command,
        "next_step": next_step,
        "refs": session.get("refs") or [],
        "note_count": len(notes),
        "command_count": len(commands),
        "artifact_count": len(attachments),
    }


def generate_session_digest(output_path: Path, digest: dict[str, Any]) -> None:
    lines = [
        f"# Session Digest: {digest['title']}",
        "",
        "## Snapshot",
        f"- Verdict: `{digest['verdict']}`",
        f"- Summary: {digest['summary_line']}",
    ]
    if digest.get("failure_family"):
        lines.append(f"- Failure family: `{digest['failure_family']}`")
    if digest.get("exception_type"):
        lines.append(f"- Exception: `{digest['exception_type']}`")
    if digest.get("likely_area"):
        lines.append(f"- Likely area: `{digest['likely_area']}`")
    if digest.get("root_cause_hint"):
        lines.append(f"- Root-cause hint: {digest['root_cause_hint']}")
    if digest.get("repro_command"):
        lines.append(f"- Repro command: `{digest['repro_command']}`")
    if digest.get("next_step"):
        lines.append(f"- Next step: {digest['next_step']}")
    if digest.get("refs"):
        lines.append(f"- Refs: {', '.join(digest['refs'])}")
    lines.extend(
        [
            "",
            "## Counts",
            f"- Notes: {digest['note_count']}",
            f"- Commands: {digest['command_count']}",
            f"- Artifacts: {digest['artifact_count']}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _build_summary_line(
    session: dict[str, Any],
    failure_family: str | None,
    exception_type: str | None,
    likely_area: str | None,
    top_signal: str | None,
) -> str:
    if session.get("final_summary"):
        return str(session["final_summary"])

    parts = []
    if exception_type:
        parts.append(exception_type)
    elif failure_family:
        parts.append(failure_family.replace("_", " "))
    if likely_area:
        parts.append(f"around {likely_area}")
    if not parts and top_signal:
        return top_signal
    if not parts:
        return "No closing summary captured."
    return " ".join(parts)


def _select_root_cause_hint(session: dict[str, Any], notes: list[dict[str, Any]], top_signal: str | None) -> str:
    if session.get("final_summary"):
        return str(session["final_summary"])
    for note in reversed(notes):
        text = str(note.get("text") or "").strip()
        if text:
            return text
    return top_signal or "Capture the underlying cause explicitly before closing the session."


def _select_repro_command(commands: list[dict[str, Any]]) -> str | None:
    repro_commands = [str(item.get("command") or "") for item in commands if item.get("repro") and item.get("command")]
    if repro_commands:
        return repro_commands[0]
    failing = [str(item.get("command") or "") for item in commands if item.get("exit_code") not in (0, None) and item.get("command")]
    if failing:
        return failing[0]
    observed = [str(item.get("command") or "") for item in commands if item.get("command")]
    return observed[0] if observed else None


def _select_next_step(verdict: Any, repro_command: str | None, likely_area: str | None) -> str:
    verdict_text = str(verdict or "active")
    if verdict_text == "fixed":
        return "Convert the confirmed fix path into a regression test."
    if verdict_text in {"handoff", "unresolved", "needs-more-data"}:
        if repro_command:
            return f"Re-run and narrow the failure path with `{repro_command}`."
        if likely_area:
            return f"Inspect the failure area around `{likely_area}` and capture the next blocking fact."
        return "Capture one more blocking fact before the next handoff."
    return "Continue the investigation and capture the next smallest verified step."


def _derive_area_from_attachments(attachments: list[dict[str, Any]]) -> str | None:
    for attachment in attachments:
        stored_path = str(attachment.get("stored_path") or "")
        if stored_path:
            return Path(stored_path).name
    return None


def _first(values: Any) -> str | None:
    for value in values or []:
        text = str(value).strip()
        if text:
            return text
    return None


def normalize_digest_bucket(text: str | None) -> str | None:
    if not text:
        return None
    lowered = str(text).lower()
    lowered = re.sub(r"[`'\".,:;(){}\[\]/\\]+", " ", lowered)
    lowered = re.sub(r"\b\d+\b", "#", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered or None
