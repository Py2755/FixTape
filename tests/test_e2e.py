"""End-to-end test covering the full FixTape session lifecycle.

start → note → capture → attach → snapshot → finish → show → search → digest → export
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fixtape.cli import main


class EndToEndTests(unittest.TestCase):
    """Full session lifecycle: start → … → export."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.env_patch = patch.dict(os.environ, {"FIXTAPE_HOME": str(self.workspace / ".fixtape-home")}, clear=False)
        self.cwd_patch = patch("pathlib.Path.cwd", return_value=self.workspace)
        self.env_patch.start()
        self.cwd_patch.start()

    def tearDown(self) -> None:
        self.cwd_patch.stop()
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                code = main(argv)
            except SystemExit as exc:
                code = int(exc.code)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_full_session_lifecycle(self) -> None:
        # Prepare sample artifacts
        payload_file = self.workspace / "failing_event.json"
        payload_file.write_text('{"event_id": "evt_123", "retry": true}\n', encoding="utf-8")

        trace_file = self.workspace / "traceback.txt"
        trace_file.write_text(
            "Traceback (most recent call last):\n"
            '  File "billing/webhook.py", line 42, in handle_event\n'
            "    charge = process_payment(event)\n"
            '  File "billing/payments.py", line 88, in process_payment\n'
            "    raise DuplicateChargeError('Idempotency key reused')\n"
            "billing.errors.DuplicateChargeError: Idempotency key reused\n",
            encoding="utf-8",
        )

        log_file = self.workspace / "server.log"
        log_file.write_text(
            "2025-03-27 10:01:33 ERROR billing.webhook: duplicate charge detected event_id=evt_123\n"
            "2025-03-27 10:01:34 WARN billing.retry: idempotency key collision key=idem_abc\n",
            encoding="utf-8",
        )

        # 1. Start session
        code, out, _ = self.run_cli(["start", "billing webhook duplicates charges"])
        self.assertEqual(code, 0)
        self.assertIn("Started FixTape session", out)

        # 2. Check status
        code, out, _ = self.run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertIn("billing webhook duplicates charges", out)
        self.assertIn("Notes: 0", out)

        # 3. Add notes
        code, out, _ = self.run_cli(["note", "Can reproduce only with retry header present"])
        self.assertEqual(code, 0)
        self.assertIn("Note captured", out)

        code, _, _ = self.run_cli(["note", "Root cause: idempotency key ignored on retry path"])
        self.assertEqual(code, 0)

        # 4. Capture a command (outside session → goes to buffer, promoted if session active)
        code, out, _ = self.run_cli(["capture", "--", "python", "-c", "print('test passed')"])
        self.assertEqual(code, 0)
        self.assertIn("Recorded command", out)

        # 5. Attach artifacts
        code, out, _ = self.run_cli(["attach", "trace", str(trace_file)])
        self.assertEqual(code, 0)
        self.assertIn("Attached artifact", out)

        code, out, _ = self.run_cli(["attach", "payload", str(payload_file)])
        self.assertEqual(code, 0)
        self.assertIn("Attached artifact", out)

        code, out, _ = self.run_cli(["attach", "log", str(log_file)])
        self.assertEqual(code, 0)
        self.assertIn("Attached artifact", out)

        # 6. Link refs
        code, out, _ = self.run_cli(["link", "ticket", "PAY-456"])
        self.assertEqual(code, 0)
        self.assertIn("Linked ref", out)

        # 7. Check status again — counts should have increased
        code, out, _ = self.run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Notes: 2", out)
        self.assertIn("Artifacts: 3", out)

        # 8. Check refs
        code, out, _ = self.run_cli(["refs"])
        self.assertEqual(code, 0)
        self.assertIn("ticket:PAY-456", out)

        # 9. Finish session
        code, out, _ = self.run_cli([
            "finish",
            "--verdict", "fixed",
            "--summary", "Retry path now respects idempotency keys",
            "--ref", "commit:abc123",
        ])
        self.assertEqual(code, 0)
        self.assertIn("Session finished", out)
        self.assertIn("debug-summary.md", out)

        # 10. Show finished session
        code, out, _ = self.run_cli(["show"])
        self.assertEqual(code, 0)
        self.assertIn("billing webhook duplicates charges", out)
        self.assertIn("fixed", out)

        # 11. Digest
        code, out, _ = self.run_cli(["digest"])
        self.assertEqual(code, 0)
        self.assertIn("Session digest", out)

        # 12. Search
        code, out, _ = self.run_cli(["search", "idempotency"])
        self.assertEqual(code, 0)
        self.assertIn("billing webhook duplicates charges", out)

        code, out, _ = self.run_cli(["search", "DuplicateChargeError", "--field", "signals"])
        self.assertEqual(code, 0)
        # Should find the exception type from parsed artifacts
        self.assertIn("billing webhook", out)

        # 13. List sessions
        code, out, _ = self.run_cli(["list"])
        self.assertEqual(code, 0)
        self.assertIn("fixed", out)

        # 14. Export
        export_path = self.workspace / "handoff.zip"
        code, out, _ = self.run_cli(["export", str(export_path)])
        self.assertEqual(code, 0)
        self.assertIn("Session exported", out)
        self.assertTrue(export_path.exists())

        # Verify zip contents
        with zipfile.ZipFile(export_path, "r") as archive:
            names = archive.namelist()
            # Should contain top-level handoff files
            has_handoff = any("HANDOFF.md" in name for name in names)
            has_summary = any("SUMMARY.md" in name for name in names)
            has_metadata = any("metadata.json" in name for name in names)
            has_session = any("session/session.json" in name for name in names)
            self.assertTrue(has_handoff, f"HANDOFF.md not found in {names}")
            self.assertTrue(has_summary, f"SUMMARY.md not found in {names}")
            self.assertTrue(has_metadata, f"metadata.json not found in {names}")
            self.assertTrue(has_session, f"session.json not found in {names}")

            # Verify metadata.json content
            metadata_name = next(name for name in names if "metadata.json" in name)
            metadata = json.loads(archive.read(metadata_name))
            self.assertEqual(metadata["title"], "billing webhook duplicates charges")
            self.assertEqual(metadata["verdict"], "fixed")
            self.assertIn("ticket:PAY-456", metadata["refs"])
            self.assertIn("commit:abc123", metadata["refs"])
            self.assertEqual(metadata["artifact_count"], 3)
            self.assertEqual(metadata["note_count"], 2)

        # 15. Verify generated files exist on disk
        fixtape_dir = self.workspace / ".fixtape-home"
        sessions_dir = fixtape_dir / "sessions"
        session_dirs = list(sessions_dir.iterdir())
        self.assertEqual(len(session_dirs), 1)

        generated_dir = session_dirs[0] / "generated"
        self.assertTrue((generated_dir / "debug-summary.md").exists())
        self.assertTrue((generated_dir / "handoff.md").exists())
        self.assertTrue((generated_dir / "parsed-artifacts.json").exists())
        self.assertTrue((generated_dir / "session-digest.json").exists())
        self.assertTrue((generated_dir / "session-digest.md").exists())
        self.assertTrue((generated_dir / "regression-draft.json").exists())
        self.assertTrue((generated_dir / "timeline.json").exists())

        # Verify parsed artifacts detected the traceback
        parsed = json.loads((generated_dir / "parsed-artifacts.json").read_text(encoding="utf-8"))
        self.assertIsInstance(parsed, dict)
        exception_types = parsed.get("exception_types", [])
        self.assertTrue(
            any("DuplicateChargeError" in et for et in exception_types),
            f"DuplicateChargeError not found in parsed artifacts: {exception_types}",
        )
