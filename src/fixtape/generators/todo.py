from __future__ import annotations

from pathlib import Path
from typing import Any

from fixtape.utils import slugify


def build_regression_draft(
    session: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    notes = [event for event in events if event["type"] == "note_added"]
    commands = [event for event in events if event["type"] == "command_ran"]
    attachments = [event for event in events if event["type"] == "artifact_attached"]

    failing_commands = [event for event in commands if event.get("exit_code") not in (0, None)]
    repro_commands = [event for event in commands if event.get("repro") and event.get("exit_code") == 0]
    payload_artifacts = [event for event in attachments if event.get("kind") in {"payload", "query", "config"}]
    refs = session.get("refs") or []

    first_note = notes[0]["text"] if notes else None
    last_note = notes[-1]["text"] if notes else None
    final_summary = session.get("final_summary")

    candidate_command = None
    if repro_commands:
        candidate_command = repro_commands[0]["command"]
    elif failing_commands:
        candidate_command = failing_commands[0]["command"]
    elif commands:
        candidate_command = commands[0]["command"]

    suggested_test_name = f"test_{slugify(str(session['title'])).replace('-', '_')}"

    assertion_candidates: list[str] = []
    if final_summary:
        assertion_candidates.append(str(final_summary))
    if last_note and last_note != final_summary:
        assertion_candidates.append(str(last_note))
    if first_note and first_note not in assertion_candidates:
        assertion_candidates.append(str(first_note))

    return {
        "title": session["title"],
        "session_id": session["id"],
        "verdict": session.get("verdict"),
        "refs": refs,
        "suggested_test_name": suggested_test_name,
        "failing_scenario": first_note or "Describe the exact user or system behavior that failed.",
        "expected_fixed_behavior": final_summary or last_note or "Describe the behavior that should now remain stable.",
        "candidate_test_entry_point": candidate_command or "Reference the most relevant command or script from this FixTape session.",
        "repro_commands": [event["command"] for event in repro_commands[:3]],
        "failing_commands": [event["command"] for event in failing_commands[:3]],
        "fixture_candidates": [Path(str(event["stored_path"])).name for event in payload_artifacts[:5]],
        "assertion_candidates": assertion_candidates[:3],
        "artifact_count": len(attachments),
        "note_count": len(notes),
        "command_count": len(commands),
    }


def generate_regression_todo(
    output_path: Path,
    session: dict[str, Any],
    events: list[dict[str, Any]],
) -> None:
    draft = build_regression_draft(session, events)

    lines = [
        f"# Regression Test TODO: {session['title']}",
        "",
        "## Suggested test name",
        f"- `{draft['suggested_test_name']}`",
        "",
        "## Failing scenario",
        f"- {draft['failing_scenario']}",
        "",
        "## Expected fixed behavior",
        f"- {draft['expected_fixed_behavior']}",
        "",
        "## Candidate reproduction entry point",
        f"- `{draft['candidate_test_entry_point']}`",
        "",
        "## Candidate fixtures",
    ]
    if draft["fixture_candidates"]:
        lines.extend([f"- `{item}`" for item in draft["fixture_candidates"]])
    else:
        lines.append("- No payload or config artifacts were captured.")

    lines.extend(["", "## Candidate assertions"])
    if draft["assertion_candidates"]:
        lines.extend([f"- {item}" for item in draft["assertion_candidates"]])
    else:
        lines.append("- Add the key behavioral assertion that should never regress.")

    lines.extend(["", "## Repro commands"])
    if draft["repro_commands"]:
        lines.extend([f"- `{item}`" for item in draft["repro_commands"]])
    else:
        lines.append("- No explicit repro commands were marked.")

    lines.extend(["", "## Failing commands observed"])
    if draft["failing_commands"]:
        lines.extend([f"- `{item}`" for item in draft["failing_commands"]])
    else:
        lines.append("- No failing commands were captured.")

    lines.extend(["", "## Linked refs"])
    if draft["refs"]:
        lines.extend([f"- `{item}`" for item in draft["refs"]])
    else:
        lines.append("- No refs linked.")

    lines.extend(
        [
            "",
            "## Notes",
            f"- Verdict: {session.get('verdict') or 'n/a'}",
            f"- Commands captured: {draft['command_count']}",
            f"- Notes captured: {draft['note_count']}",
            f"- Artifacts captured: {draft['artifact_count']}",
            "",
        ]
    )
    output_path.write_text("\n".join(lines), encoding="utf-8")
