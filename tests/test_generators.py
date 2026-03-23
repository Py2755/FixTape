from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fixtape.generators.repro import generate_repro_script
from fixtape.generators.summary import generate_summary
from fixtape.generators.todo import generate_regression_todo


class GeneratorTests(unittest.TestCase):
    def test_generators_create_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = {
                "id": "session-1",
                "title": "demo",
                "created_at": "2026-03-23T00:00:00+00:00",
                "finished_at": "2026-03-23T00:10:00+00:00",
                "workspace_root": str(root),
                "shell": "powershell",
                "verdict": "fixed",
                "initial_git_state": None,
                "final_git_state": None,
            }
            events = [
                {"type": "note_added", "timestamp": "t1", "text": "first note"},
                {"type": "command_ran", "timestamp": "t2", "command": "python -V", "exit_code": 0, "repro": True},
            ]

            summary_path = root / "debug-summary.md"
            repro_path = root / "repro.ps1"
            todo_path = root / "regression-test.todo.md"

            generate_summary(summary_path, session, events)
            generate_repro_script(repro_path, events)
            generate_regression_todo(todo_path, session, events)

            self.assertTrue(summary_path.exists())
            self.assertTrue(repro_path.exists())
            self.assertTrue(todo_path.exists())
