from __future__ import annotations

import os
from pathlib import Path


def generate_repro_script(output_path: Path, events: list[dict[str, object]]) -> None:
    commands = [
        str(event["command"])
        for event in events
        if event["type"] == "command_ran" and event.get("repro") and event.get("exit_code") == 0
    ]

    if os.name == "nt":
        lines = [
            "Set-StrictMode -Version Latest",
            "$ErrorActionPreference = 'Stop'",
            "",
        ]
        lines.extend(commands or ["# No reproducible commands were marked in this session."])
    else:
        lines = [
            "#!/usr/bin/env bash",
            "set -euo pipefail",
            "",
        ]
        lines.extend(commands or ["# No reproducible commands were marked in this session."])

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
