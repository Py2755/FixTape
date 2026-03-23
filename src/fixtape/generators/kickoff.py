from __future__ import annotations

from pathlib import Path
from typing import Any


def generate_incident_kickoff(output_path: Path, payload: dict[str, Any]) -> None:
    lines = [
        f"# Incident Kickoff: {payload['title']}",
        "",
        "## Triage Input",
        f"- Query: {payload['query']}",
    ]
    if payload.get("playbook"):
        lines.append(f"- Suggested playbook: `{payload['playbook']['label']}`")
    if payload.get("recipe"):
        lines.append(f"- Suggested recipe bucket: `{payload['recipe']['label']}`")
    lines.append("")

    lines.append("## Recommended First Move")
    lines.append(f"- {payload.get('starter_step') or 'Capture the next smallest verified fact.'}")
    if payload.get("entry_point"):
        lines.append(f"- Entry point: `{payload['entry_point']}`")
    if payload.get("repro_command"):
        lines.append(f"- Repro command: `{payload['repro_command']}`")
    lines.append("")

    lines.append("## Capture First")
    if payload.get("artifact_kinds"):
        for artifact in payload["artifact_kinds"]:
            lines.append(f"- `{artifact}`")
    else:
        lines.append("- No repeated artifact guidance yet.")
    lines.append("")

    lines.append("## Areas To Check")
    if payload.get("areas"):
        for area in payload["areas"]:
            lines.append(f"- `{area}`")
    else:
        lines.append("- No repeated hotspot area yet.")
    lines.append("")

    lines.append("## Similar Sessions")
    if payload.get("sessions"):
        for session in payload["sessions"]:
            lines.append(
                f"- `{session['id']}` score={session['score']} verdict={session['verdict']} title={session['title']}"
            )
    else:
        lines.append("- No historical sessions matched strongly.")
    lines.append("")

    lines.append("## Why These Suggestions")
    if payload.get("reasons"):
        for reason in payload["reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- Historical context is still sparse for this query.")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
