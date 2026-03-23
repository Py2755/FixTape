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


class FixTapeCliTests(unittest.TestCase):
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

    def test_basic_session_flow(self) -> None:
        input_file = self.workspace / "payload.json"
        input_file.write_text('{"ok": true}\n', encoding="utf-8")
        trace_file = self.workspace / "traceback.txt"
        trace_file.write_text(
            "Traceback (most recent call last):\n"
            "  File \"app.py\", line 10, in <module>\n"
            "    raise ValueError('boom')\n"
            "ValueError: boom\n",
            encoding="utf-8",
        )

        code, out, _ = self.run_cli(["start", "demo bug"])
        self.assertEqual(code, 0)
        self.assertIn("Started FixTape session", out)

        code, _, _ = self.run_cli(["note", "first clue"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('hello fixtape')"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["attach", "payload", str(input_file)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_file)])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(
            ["finish", "--verdict", "fixed", "--summary", "done", "--ref", "ticket:PAY-123", "--ref", "commit:abc123"]
        )
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["list"])
        self.assertEqual(code, 0)
        self.assertIn("demo bug", out)
        self.assertIn("fixed", out)

        code, out, _ = self.run_cli(["show"])
        self.assertEqual(code, 0)
        self.assertIn("Summary:", out)

        code, out, _ = self.run_cli(["search", "clue"])
        self.assertEqual(code, 0)
        self.assertIn("demo bug", out)
        self.assertIn("first clue", out)

        code, out, _ = self.run_cli(["search", "hello fixtape", "--field", "commands"])
        self.assertEqual(code, 0)
        self.assertIn("demo bug", out)

        code, out, _ = self.run_cli(["search", "hello fixtape", "--field", "notes"])
        self.assertEqual(code, 0)
        self.assertIn("No FixTape sessions matched", out)

        archive_path = self.workspace / "fixtape-session.zip"
        code, _, _ = self.run_cli(["export", str(archive_path)])
        self.assertEqual(code, 0)
        self.assertTrue(archive_path.exists())
        with zipfile.ZipFile(archive_path, "r") as archive:
            names = archive.namelist()
            self.assertTrue(any(name.endswith("/HANDOFF.md") for name in names))
            self.assertTrue(any(name.endswith("/metadata.json") for name in names))
            self.assertTrue(any(name.endswith("/session/generated/handoff.md") for name in names))
            handoff_name = next(name for name in names if name.endswith("/HANDOFF.md"))
            metadata_name = next(name for name in names if name.endswith("/metadata.json"))
            handoff_text = archive.read(handoff_name).decode("utf-8")
            metadata_text = archive.read(metadata_name).decode("utf-8")
            self.assertIn("ticket:PAY-123", handoff_text)
            self.assertIn("commit:abc123", metadata_text)

        sessions_root = self.workspace / ".fixtape-home" / "sessions"
        index_path = self.workspace / ".fixtape-home" / "session-index.json"
        sessions = list(sessions_root.iterdir())
        self.assertEqual(len(sessions), 1)
        self.assertTrue(index_path.exists())
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(len(index_payload["sessions"]), 1)
        self.assertEqual(index_payload["sessions"][0]["title"], "demo bug")
        generated = sessions[0] / "generated"
        self.assertTrue((generated / "debug-summary.md").exists())
        self.assertTrue((generated / "regression-test.todo.md").exists())
        self.assertTrue((generated / "regression-draft.json").exists())
        self.assertTrue((generated / "parsed-artifacts.json").exists())
        self.assertTrue((generated / "handoff.md").exists())
        draft = json.loads((generated / "regression-draft.json").read_text(encoding="utf-8"))
        parsed = json.loads((generated / "parsed-artifacts.json").read_text(encoding="utf-8"))
        self.assertEqual(draft["suggested_test_name"], "test_demo_bug")
        self.assertIn("ticket:PAY-123", draft["refs"])
        self.assertGreaterEqual(parsed["signal_count"], 1)

    def test_status_requires_active_session(self) -> None:
        code, _, err = self.run_cli(["status"])
        self.assertEqual(code, 2)
        self.assertIn("No active FixTape session", err)

    def test_shell_init_outputs_helpers(self) -> None:
        code, out, _ = self.run_cli(["shell-init", "powershell"])
        self.assertEqual(code, 0)
        self.assertIn("function ft", out)
        self.assertIn("function ftr", out)
        self.assertIn("function ftenable", out)

    def test_reindex_rebuilds_cross_session_index(self) -> None:
        code, _, _ = self.run_cli(["start", "index me"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["note", "cross session note"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "done"])
        self.assertEqual(code, 0)

        index_path = self.workspace / ".fixtape-home" / "session-index.json"
        if index_path.exists():
            index_path.unlink()

        code, out, _ = self.run_cli(["reindex"])
        self.assertEqual(code, 0)
        self.assertIn("Rebuilt FixTape index", out)
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["sessions"][0]["title"], "index me")

    def test_link_and_refs_commands(self) -> None:
        code, _, _ = self.run_cli(["start", "link me"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["link", "ticket", "PAY-999"])
        self.assertEqual(code, 0)
        self.assertIn("ticket:PAY-999", out)

        code, out, _ = self.run_cli(["refs"])
        self.assertEqual(code, 0)
        self.assertIn("ticket:PAY-999", out)

        code, out, _ = self.run_cli(["search", "PAY-999", "--field", "refs"])
        self.assertEqual(code, 0)
        self.assertIn("link me", out)

    def test_record_shell_command_is_searchable(self) -> None:
        code, _, _ = self.run_cli(["start", "hooked bug"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(
            [
                "record-shell-command",
                "--command",
                "pytest tests/test_billing.py -k duplicate",
                "--exit-code",
                "1",
                "--shell",
                "powershell",
                "--cwd",
                str(self.workspace),
            ]
        )
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["search", "duplicate", "--field", "commands"])
        self.assertEqual(code, 0)
        self.assertIn("hooked bug", out)

    def test_search_ranks_title_above_note_match(self) -> None:
        code, _, _ = self.run_cli(["start", "payment retry idempotency"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "done"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "other billing issue"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["note", "Observed retry idempotency problem during manual test"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "done"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["search", "retry idempotency"])
        self.assertEqual(code, 0)
        lines = [line for line in out.splitlines() if line and not line.startswith("  ")]
        self.assertGreaterEqual(len(lines), 2)
        self.assertIn("payment retry idempotency", lines[0])
