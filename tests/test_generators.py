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
from fixtape.generators.digest import build_session_digest, generate_session_digest
from fixtape.generators.summary import generate_summary
from fixtape.generators.todo import build_regression_draft, generate_regression_todo


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
                "final_summary": "retry path now checks idempotency key",
                "refs": ["ticket:PAY-123"],
                "initial_git_state": None,
                "final_git_state": None,
            }
            events = [
                {"type": "note_added", "timestamp": "t1", "text": "first note"},
                {
                    "type": "artifact_attached",
                    "timestamp": "t1",
                    "kind": "payload",
                    "stored_path": str(root / "payload_example.json"),
                },
                {"type": "command_ran", "timestamp": "t2", "command": "python -V", "exit_code": 0, "repro": True},
            ]

            summary_path = root / "debug-summary.md"
            repro_path = root / "repro.ps1"
            todo_path = root / "regression-test.todo.md"
            digest_path = root / "session-digest.md"
            parsed_artifacts = {
                "top_signals": ["RuntimeError: broken"],
                "exception_types": ["RuntimeError"],
                "families": ["python_exception"],
                "file_hints": ["worker.py"],
            }

            generate_summary(summary_path, session, events, parsed_artifacts=parsed_artifacts)
            generate_repro_script(repro_path, events)
            generate_regression_todo(todo_path, session, events)
            draft = build_regression_draft(session, events)
            digest = build_session_digest(session, events, parsed_artifacts=parsed_artifacts)
            generate_session_digest(digest_path, digest)

            self.assertTrue(summary_path.exists())
            self.assertTrue(repro_path.exists())
            self.assertTrue(todo_path.exists())
            self.assertTrue(digest_path.exists())
            self.assertEqual(draft["suggested_test_name"], "test_demo")
            self.assertIn("ticket:PAY-123", draft["refs"])
            self.assertIn("payload_example.json", draft["fixture_candidates"])
            self.assertEqual(digest["likely_area"], "worker.py")
            self.assertIn("idempotency key", digest["root_cause_hint"])
