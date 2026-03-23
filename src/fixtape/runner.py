from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from fixtape.utils import shell_join


def capture_command(args: list[str], cwd: Path) -> dict[str, object]:
    completed = subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        encoding="utf-8",
    )

    stdout_text = completed.stdout or ""
    stderr_text = completed.stderr or ""
    return {
        "command": shell_join(args),
        "args": args,
        "exit_code": completed.returncode,
        "stdout_text": stdout_text,
        "stderr_text": stderr_text,
        "stdout_sha256": hashlib.sha256(stdout_text.encode("utf-8")).hexdigest(),
        "stderr_sha256": hashlib.sha256(stderr_text.encode("utf-8")).hexdigest(),
    }


def run_command(
    args: list[str],
    cwd: Path,
    stdout_path: Path,
    stderr_path: Path,
) -> dict[str, object]:
    result = capture_command(args, cwd)
    stdout_text = str(result["stdout_text"])
    stderr_text = str(result["stderr_text"])

    stdout_path.write_text(stdout_text, encoding="utf-8")
    stderr_path.write_text(stderr_text, encoding="utf-8")

    return {
        "command": result["command"],
        "args": args,
        "exit_code": result["exit_code"],
        "stdout_file": str(stdout_path),
        "stderr_file": str(stderr_path),
        "stdout_sha256": result["stdout_sha256"],
        "stderr_sha256": result["stderr_sha256"],
    }
