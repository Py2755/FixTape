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
        self.assertIn("function ftdoctor", out)
        self.assertIn("function ftsuggest", out)
        self.assertIn("fixtape capture", out)
        self.assertIn("suggest-start --shell-notify", out)

    def test_doctor_and_start_include_last_import_buffered_history(self) -> None:
        for index in range(2):
            code, _, _ = self.run_cli(
                [
                    "record-shell-command",
                    "--command",
                    f"pytest tests/test_retry.py -k duplicate_{index}",
                    "--exit-code",
                    "1",
                    "--shell",
                    "powershell",
                    "--cwd",
                    str(self.workspace),
                ]
            )
            self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["doctor", "--window", "40m"])
        self.assertEqual(code, 0)
        self.assertIn("Buffered commands: 2", out)
        self.assertIn("duplicate_1", out)

        code, out, _ = self.run_cli(["start", "late start retry", "--include-last", "40m"])
        self.assertEqual(code, 0)
        self.assertIn("Imported buffered commands: 2", out)

        code, out, _ = self.run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertIn("Commands: 2", out)

    def test_capture_records_output_and_promotes_it_into_session(self) -> None:
        code, out, err = self.run_cli(
            [
                "capture",
                sys.executable,
                "-c",
                "import sys; print('prebuffer hello'); print('prebuffer err', file=sys.stderr)",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("prebuffer hello", out)
        self.assertIn("prebuffer err", err)

        code, out, _ = self.run_cli(["start", "capture import", "--include-last", "40m"])
        self.assertEqual(code, 0)
        self.assertIn("Imported buffered commands: 1", out)

        sessions_root = self.workspace / ".fixtape-home" / "sessions"
        session_dir = next(sessions_root.iterdir())
        events = (session_dir / "events.jsonl").read_text(encoding="utf-8")
        self.assertIn("pre_session_imported", events)
        self.assertIn("prebuffer hello", (session_dir / "commands" / "command_001_stdout.txt").read_text(encoding="utf-8"))
        self.assertIn("prebuffer err", (session_dir / "commands" / "command_001_stderr.txt").read_text(encoding="utf-8"))

    def test_finish_can_include_recent_buffer_after_late_start(self) -> None:
        code, _, _ = self.run_cli(
            [
                "record-shell-command",
                "--command",
                "python replay.py --case duplicate",
                "--exit-code",
                "1",
                "--shell",
                "powershell",
                "--cwd",
                str(self.workspace),
            ]
        )
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "finish import"])
        self.assertEqual(code, 0)
        code, out, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "done", "--include-last", "40m"])
        self.assertEqual(code, 0)
        self.assertIn("Included buffered commands from the last 40m.", out)

        code, out, _ = self.run_cli(["search", "replay.py", "--field", "commands"])
        self.assertEqual(code, 0)
        self.assertIn("finish import", out)

    def test_suggest_start_detects_failure_burst_and_trace_signal(self) -> None:
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

        code, _, _ = self.run_cli(
            [
                "capture",
                sys.executable,
                "-c",
                "import sys; print('Traceback (most recent call last):', file=sys.stderr); print('RuntimeError: duplicate charge', file=sys.stderr); sys.exit(1)",
            ]
        )
        self.assertEqual(code, 1)

        code, out, _ = self.run_cli(["suggest-start", "--window", "20m", "--cooldown", "15m"])
        self.assertEqual(code, 0)
        self.assertIn("Suggested FixTape session start:", out)
        self.assertIn("Kickoff:", out)
        self.assertIn("--include-last 20m", out)

        code, out, _ = self.run_cli(["doctor", "--window", "20m"])
        self.assertEqual(code, 0)
        self.assertIn("Suggestion:", out)
        self.assertIn("kickoff:", out.lower())

    def test_shell_notify_suppresses_duplicate_start_suggestions(self) -> None:
        for command in (
            "pytest tests/test_billing.py -k duplicate",
            "pytest tests/test_billing.py -k duplicate --maxfail=1",
        ):
            code, _, _ = self.run_cli(
                [
                    "record-shell-command",
                    "--command",
                    command,
                    "--exit-code",
                    "1",
                    "--shell",
                    "powershell",
                    "--cwd",
                    str(self.workspace),
                ]
            )
            self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["suggest-start", "--shell-notify", "--window", "20m", "--cooldown", "15m"])
        self.assertEqual(code, 0)
        self.assertIn("FixTape: recent failure burst detected.", out)

        code, out, _ = self.run_cli(["suggest-start", "--shell-notify", "--window", "20m", "--cooldown", "15m"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "")

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

    def test_similar_and_patterns_use_cross_session_failure_signals(self) -> None:
        trace_one = self.workspace / "trace-one.txt"
        trace_two = self.workspace / "trace-two.txt"
        trace_one.write_text(
            "Traceback (most recent call last):\n"
            "  File \"worker.py\", line 42, in run\n"
            "    raise RuntimeError('broken')\n"
            "RuntimeError: broken\n",
            encoding="utf-8",
        )
        trace_two.write_text(
            "Traceback (most recent call last):\n"
            "  File \"worker.py\", line 57, in run\n"
            "    raise RuntimeError('broken')\n"
            "RuntimeError: broken\n",
            encoding="utf-8",
        )

        code, _, _ = self.run_cli(["start", "worker crash one"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_one)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "done"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "worker crash two"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "needs follow-up"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["similar"])
        self.assertEqual(code, 0)
        self.assertIn("worker crash one", out)
        self.assertIn("shared failure fingerprint", out)

        code, out, _ = self.run_cli(["patterns"])
        self.assertEqual(code, 0)
        self.assertIn("RuntimeError: broken", out)
        self.assertIn("worker crash one", out)

    def test_search_can_hit_signal_fields(self) -> None:
        trace_file = self.workspace / "node-trace.txt"
        trace_file.write_text(
            "TypeError: Cannot read properties of undefined (reading 'id')\n"
            "    at retry (billing.js:17:3)\n"
            "    at processPayment (billing.js:41:9)\n",
            encoding="utf-8",
        )

        code, _, _ = self.run_cli(["start", "node crash"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_file)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "done"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["search", "TypeError", "--field", "signals"])
        self.assertEqual(code, 0)
        self.assertIn("node crash", out)

    def test_clusters_and_hotspots_group_related_sessions(self) -> None:
        worker_trace_one = self.workspace / "worker-one.txt"
        worker_trace_two = self.workspace / "worker-two.txt"
        http_log = self.workspace / "gateway.log"
        http_log_two = self.workspace / "gateway-two.log"

        worker_trace_one.write_text(
            "Traceback (most recent call last):\n"
            "  File \"worker.py\", line 42, in run\n"
            "    raise RuntimeError('broken')\n"
            "RuntimeError: broken\n",
            encoding="utf-8",
        )
        worker_trace_two.write_text(
            "Traceback (most recent call last):\n"
            "  File \"worker.py\", line 78, in run\n"
            "    raise RuntimeError('broken')\n"
            "RuntimeError: broken\n",
            encoding="utf-8",
        )
        http_log.write_text(
            "POST /api/payments failed with HTTP 503 Service Unavailable\n"
            "TypeError: gateway exploded\n"
            "    at charge (gateway.js:14:2)\n",
            encoding="utf-8",
        )
        http_log_two.write_text(
            "status=503 upstream timeout during POST /api/payments\n"
            "TypeError: gateway exploded again\n"
            "    at charge (gateway.js:22:2)\n",
            encoding="utf-8",
        )

        code, _, _ = self.run_cli(["start", "worker crash alpha"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(worker_trace_one)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "needs worker fix"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "worker crash beta"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(worker_trace_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "unresolved", "--summary", "still broken"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "gateway 503 burst"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "log", str(http_log)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "needs-more-data", "--summary", "gateway instability"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "gateway 503 retry storm"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "log", str(http_log_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "gateway still unstable"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["clusters"])
        self.assertEqual(code, 0)
        self.assertIn("worker crash", out)
        self.assertIn("python_exception", out)

        code, out, _ = self.run_cli(["hotspots", "--kind", "file"])
        self.assertEqual(code, 0)
        self.assertIn("worker.py", out)
        self.assertIn("2 sessions", out)

        code, out, _ = self.run_cli(["hotspots", "--kind", "status"])
        self.assertEqual(code, 0)
        self.assertIn("HTTP 503", out)

    def test_digest_and_lenses_surface_compact_history(self) -> None:
        trace_one = self.workspace / "digest-trace-one.txt"
        trace_two = self.workspace / "digest-trace-two.txt"
        trace_one.write_text(
            "Traceback (most recent call last):\n"
            "  File \"billing.py\", line 12, in charge\n"
            "    raise ValueError('duplicate payment')\n"
            "ValueError: duplicate payment\n",
            encoding="utf-8",
        )
        trace_two.write_text(
            "Traceback (most recent call last):\n"
            "  File \"billing.py\", line 14, in charge\n"
            "    raise ValueError('duplicate payment')\n"
            "ValueError: duplicate payment\n",
            encoding="utf-8",
        )

        code, _, _ = self.run_cli(["start", "billing duplicate one"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_one)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "retry path duplicates payment"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "billing duplicate two"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "needs-more-data", "--summary", "retry path duplicates payment"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["digest"])
        self.assertEqual(code, 0)
        self.assertIn("Root-cause hint", out)
        self.assertIn("billing.py", out)

        code, out, _ = self.run_cli(["lenses"])
        self.assertEqual(code, 0)
        self.assertIn("Family lenses:", out)
        self.assertIn("python_exception", out)
        self.assertIn("Area lenses:", out)
        self.assertIn("billing.py", out)
        self.assertIn("Digest lenses:", out)

    def test_regressions_and_outcomes_surface_team_memory(self) -> None:
        trace_one = self.workspace / "reg-one.txt"
        trace_two = self.workspace / "reg-two.txt"
        trace_three = self.workspace / "reg-three.txt"
        for path in (trace_one, trace_two, trace_three):
            path.write_text(
                "Traceback (most recent call last):\n"
                "  File \"checkout.py\", line 21, in charge\n"
                "    raise RuntimeError('idempotency missed')\n"
                "RuntimeError: idempotency missed\n",
                encoding="utf-8",
            )

        code, _, _ = self.run_cli(["start", "checkout duplicate alpha"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_one)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('checkout duplicate repro')"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "fixed", "--summary", "idempotency missed on retry path"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "checkout duplicate beta"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('checkout duplicate repro')"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "idempotency missed on retry path"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "checkout duplicate gamma"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_three)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "needs-more-data", "--summary", "idempotency missed on retry path"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["regressions"])
        self.assertEqual(code, 0)
        self.assertIn("checkout.py", out)
        self.assertIn("test_checkout_duplicate", out)

        code, out, _ = self.run_cli(["outcomes"])
        self.assertEqual(code, 0)
        self.assertIn("Totals:", out)
        self.assertIn("python_exception", out)
        self.assertIn("fixed=", out)

    def test_playbooks_and_recipes_surface_repeatable_guidance(self) -> None:
        trace_one = self.workspace / "recipe-one.txt"
        trace_two = self.workspace / "recipe-two.txt"
        for path in (trace_one, trace_two):
            path.write_text(
                "Traceback (most recent call last):\n"
                "  File \"checkout.py\", line 31, in charge\n"
                "    raise RuntimeError('idempotency missed')\n"
                "RuntimeError: idempotency missed\n",
                encoding="utf-8",
            )

        code, _, _ = self.run_cli(["start", "checkout recipe alpha"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_one)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('recipe repro')"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "idempotency missed on checkout retry"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "checkout recipe beta"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('recipe repro')"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "needs-more-data", "--summary", "idempotency missed on checkout retry"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["playbooks"])
        self.assertEqual(code, 0)
        self.assertIn("python_exception", out)
        self.assertIn("checkout.py", out)
        self.assertIn("artifacts:", out)

        code, out, _ = self.run_cli(["recipes"])
        self.assertEqual(code, 0)
        self.assertIn("RuntimeError: idempotency missed", out)
        self.assertIn("recipe repro", out)
        self.assertIn("checkout recipe", out)

    def test_triage_and_kickoff_surface_best_historical_start(self) -> None:
        trace_one = self.workspace / "triage-one.txt"
        trace_two = self.workspace / "triage-two.txt"
        for path in (trace_one, trace_two):
            path.write_text(
                "Traceback (most recent call last):\n"
                "  File \"payments.py\", line 41, in process\n"
                "    raise RuntimeError('retry storm')\n"
                "RuntimeError: retry storm\n",
                encoding="utf-8",
            )

        code, _, _ = self.run_cli(["start", "payments retry alpha"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_one)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('retry repro')"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "handoff", "--summary", "retry storm in payments processor"])
        self.assertEqual(code, 0)

        code, _, _ = self.run_cli(["start", "payments retry beta"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["attach", "trace", str(trace_two)])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["run", "--repro", "python", "-c", "print('retry repro')"])
        self.assertEqual(code, 0)
        code, _, _ = self.run_cli(["finish", "--verdict", "needs-more-data", "--summary", "retry storm in payments processor"])
        self.assertEqual(code, 0)

        code, out, _ = self.run_cli(["triage", "retry storm payments"])
        self.assertEqual(code, 0)
        self.assertIn("Recommended first move", out)
        self.assertIn("payments.py", out)
        self.assertIn("retry repro", out)

        code, out, _ = self.run_cli(["kickoff", "payments retry gamma", "--query", "retry storm payments"])
        self.assertEqual(code, 0)
        self.assertIn("Kickoff bundle", out)
        self.assertIn("Recommended first move", out)

        sessions_root = self.workspace / ".fixtape-home" / "sessions"
        session_dirs = sorted(sessions_root.iterdir())
        kickoff_dir = session_dirs[-1] / "generated"
        self.assertTrue((kickoff_dir / "incident-kickoff.md").exists())
        kickoff_text = (kickoff_dir / "incident-kickoff.md").read_text(encoding="utf-8")
        self.assertIn("retry storm payments", kickoff_text)
        self.assertIn("retry repro", kickoff_text)
