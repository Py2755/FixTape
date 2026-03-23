from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_handoff(
    output_path: Path,
    session: dict[str, Any],
    events: list[dict[str, Any]],
    parsed_artifacts: dict[str, Any] | None = None,
) -> None:
    notes = [event for event in events if event["type"] == "note_added"]
    commands = [event for event in events if event["type"] == "command_ran"]
    attachments = [event for event in events if event["type"] == "artifact_attached"]
    refs = session.get("refs") or []

    repro_commands = [item for item in commands if item.get("repro")]
    recent_notes = notes[-3:]
    recent_commands = commands[-5:]

    lines: list[str] = []
    lines.append(f"# Handoff: {session['title']}")
    lines.append("")
    lines.append("## TL;DR")
    lines.append(f"- Verdict: `{session.get('verdict') or 'n/a'}`")
    lines.append(f"- Session ID: `{session['id']}`")
    if session.get("final_summary"):
        lines.append(f"- Closing summary: {session['final_summary']}")
    else:
        lines.append("- Closing summary: n/a")
    lines.append("")

    lines.append("## Related Refs")
    if refs:
        for ref in refs:
            lines.append(f"- `{ref}`")
    else:
        lines.append("- No refs linked.")
    lines.append("")

    lines.append("## Where To Start")
    lines.append("- Read `SUMMARY.md` for the full debugging narrative.")
    if repro_commands:
        lines.append("- Start with the reproducible commands in `REPRO_SCRIPT`.")
    if attachments:
        lines.append("- Check the attached evidence under `session/artifacts/`.")
    lines.append("")

    lines.append("## Key Notes")
    if recent_notes:
        for note in recent_notes:
            lines.append(f"- `{note['timestamp']}` {note['text']}")
    else:
        lines.append("- No notes captured.")
    lines.append("")

    lines.append("## Most Relevant Commands")
    if repro_commands:
        for command in repro_commands[:3]:
            lines.append(f"- repro `{command['command']}`")
    elif recent_commands:
        for command in recent_commands[:3]:
            lines.append(f"- `{command['command']}`")
    else:
        lines.append("- No commands captured.")
    lines.append("")

    lines.append("## Attached Evidence")
    if attachments:
        for item in attachments[:5]:
            lines.append(f"- `{item['kind']}` -> `{Path(item['stored_path']).name}`")
    else:
        lines.append("- No attached evidence.")
    lines.append("")

    lines.append("## Parsed Failure Signals")
    if parsed_artifacts and parsed_artifacts.get("top_signals"):
        for signal in parsed_artifacts["top_signals"]:
            lines.append(f"- {signal}")
        if parsed_artifacts.get("exception_types"):
            lines.append(f"- Exception types: {', '.join(parsed_artifacts['exception_types'])}")
        if parsed_artifacts.get("file_hints"):
            lines.append(f"- File hints: {', '.join(parsed_artifacts['file_hints'])}")
    else:
        lines.append("- No parsed failure signals detected.")
    lines.append("")

    lines.append("## Suggested Next Steps")
    if session.get("verdict") == "fixed":
        lines.append("- Turn the repro path into a regression test.")
        lines.append("- Link the fix commit or ticket to this bundle.")
    else:
        lines.append("- Continue from the latest summary and unresolved evidence.")
        lines.append("- Add the next blocking question before handing off.")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
