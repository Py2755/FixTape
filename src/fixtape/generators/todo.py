from __future__ import annotations

from pathlib import Path


def generate_regression_todo(
    output_path: Path,
    session: dict[str, object],
    events: list[dict[str, object]],
) -> None:
    last_note = None
    for event in reversed(events):
        if event["type"] == "note_added":
            last_note = event["text"]
            break

    lines = [
        f"# Regression Test TODO: {session['title']}",
        "",
        "## Failing scenario",
        "- Describe the exact user or system behavior that failed.",
        "",
        "## Expected fixed behavior",
        "- Describe the behavior that should now remain stable.",
        "",
        "## Candidate reproduction entry point",
        "- Reference the most relevant command or script from this FixTape session.",
        "",
        "## Notes",
        f"- Last debugging note: {last_note or 'n/a'}",
        f"- Verdict: {session.get('verdict') or 'n/a'}",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")
