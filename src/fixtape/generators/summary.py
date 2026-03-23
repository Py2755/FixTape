from __future__ import annotations

from pathlib import Path
from typing import Any


def _render_git_state(state: dict[str, Any] | None) -> list[str]:
    if not state:
        return ["- Git: not available"]
    lines = [
        f"- Repo root: `{state.get('repo_root', 'unknown')}`",
        f"- Branch: `{state.get('branch') or 'detached/unknown'}`",
        f"- HEAD: `{state.get('head') or 'unknown'}`",
        f"- Dirty: `{state.get('dirty')}`",
    ]
    changed = state.get("changed_files") or []
    if changed:
        lines.append("- Changed files:")
        lines.extend([f"  - `{item}`" for item in changed])
    return lines


def generate_summary(
    output_path: Path,
    session: dict[str, Any],
    events: list[dict[str, Any]],
    parsed_artifacts: dict[str, Any] | None = None,
) -> None:
    notes = [event for event in events if event["type"] == "note_added"]
    commands = [event for event in events if event["type"] == "command_ran"]
    attachments = [event for event in events if event["type"] == "artifact_attached"]
    snapshots = [event for event in events if event["type"] == "snapshot_created"]

    lines: list[str] = []
    lines.append(f"# {session['title']}")
    lines.append("")
    lines.append("## Session")
    lines.append(f"- Session ID: `{session['id']}`")
    lines.append(f"- Created: `{session['created_at']}`")
    lines.append(f"- Finished: `{session.get('finished_at') or 'active'}`")
    lines.append(f"- Verdict: `{session.get('verdict') or 'n/a'}`")
    lines.append(f"- Workspace: `{session['workspace_root']}`")
    lines.append(f"- Shell: `{session['shell']}`")
    refs = session.get("refs") or []
    if refs:
        lines.append(f"- Refs: {', '.join(refs)}")
    if session.get("final_summary"):
        lines.append(f"- Closing summary: {session['final_summary']}")
    lines.append("")
    lines.append("## Initial Git Context")
    lines.extend(_render_git_state(session.get("initial_git_state")))
    lines.append("")
    lines.append("## Final Git Context")
    lines.extend(_render_git_state(session.get("final_git_state")))
    lines.append("")

    lines.append("## Notes")
    if notes:
        for note in notes:
            lines.append(f"- `{note['timestamp']}` {note['text']}")
    else:
        lines.append("- No notes captured.")
    lines.append("")

    lines.append("## Command Timeline")
    if commands:
        for command in commands:
            capture_source = command.get("captured_via") or "fixtape_run"
            lines.append(
                f"- `{command['timestamp']}` exit={command['exit_code']} repro={command['repro']} via={capture_source} `{command['command']}`"
            )
    else:
        lines.append("- No commands captured.")
    lines.append("")

    lines.append("## Attached Evidence")
    if attachments:
        for item in attachments:
            source_path = item.get("source_path") or "n/a"
            stored_path = item.get("stored_path") or "n/a"
            lines.append(
                f"- `{item['timestamp']}` kind={item['kind']} source=`{source_path}` stored=`{stored_path}`"
            )
    else:
        lines.append("- No artifacts attached.")
    lines.append("")

    lines.append("## Snapshots")
    if snapshots:
        for snapshot in snapshots:
            lines.append(
                f"- `{snapshot['timestamp']}` branch=`{snapshot.get('branch') or 'unknown'}` head=`{snapshot.get('head') or 'unknown'}` dirty=`{snapshot.get('dirty')}`"
            )
    else:
        lines.append("- No snapshots captured.")
    lines.append("")

    lines.append("## Parsed Failure Signals")
    if parsed_artifacts and parsed_artifacts.get("top_signals"):
        for signal in parsed_artifacts["top_signals"]:
            lines.append(f"- {signal}")
        if parsed_artifacts.get("exception_types"):
            lines.append(f"- Exception types: {', '.join(parsed_artifacts['exception_types'])}")
        if parsed_artifacts.get("file_hints"):
            lines.append(f"- File hints: {', '.join(parsed_artifacts['file_hints'])}")
        if parsed_artifacts.get("fingerprints"):
            lines.append(f"- Fingerprints: {', '.join(parsed_artifacts['fingerprints'][:3])}")
    else:
        lines.append("- No parsed failure signals detected.")
    lines.append("")

    lines.append("## Suggested Follow-Up")
    lines.append("- Convert the final reproducible path into a regression test.")
    lines.append("- Link this session to the fixing commit or incident ticket.")
    lines.append("- If the verdict is not `fixed`, capture the next blocking question.")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
