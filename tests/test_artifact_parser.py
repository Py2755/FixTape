from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fixtape.artifact_parser import build_parsed_artifacts


class ArtifactParserTests(unittest.TestCase):
    def test_python_traceback_signal_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "traceback.txt"
            trace_path.write_text(
                "Traceback (most recent call last):\n"
                "  File \"worker.py\", line 42, in run\n"
                "    raise RuntimeError('broken')\n"
                "RuntimeError: broken\n",
                encoding="utf-8",
            )

            events = [
                {
                    "type": "artifact_attached",
                    "kind": "trace",
                    "stored_path": str(trace_path),
                }
            ]

            parsed = build_parsed_artifacts(events)
            self.assertEqual(parsed["artifact_count"], 1)
            self.assertGreaterEqual(parsed["signal_count"], 1)
            self.assertIn("RuntimeError: broken", parsed["top_signals"][0])
            self.assertIn("RuntimeError", parsed["exception_types"])
            self.assertTrue(any("worker.py" in item for item in parsed["file_hints"]))
            self.assertTrue(parsed["fingerprints"])

    def test_http_and_sql_signals_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_path = root / "server.log"
            log_path.write_text(
                "POST /api/payments failed with HTTP 503 Service Unavailable\n"
                "SQLSTATE[23505]: duplicate key value violates unique constraint\n",
                encoding="utf-8",
            )

            events = [
                {
                    "type": "artifact_attached",
                    "kind": "log",
                    "stored_path": str(log_path),
                }
            ]

            parsed = build_parsed_artifacts(events)
            self.assertIn(503, parsed["status_codes"])
            self.assertIn("http_failure", parsed["families"])
            self.assertIn("sql_failure", parsed["families"])

    def test_java_stack_signal_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            trace_path = root / "java-stack.txt"
            trace_path.write_text(
                "java.lang.IllegalStateException: boom\n"
                "\tat com.example.jobs.Worker.run(Worker.java:42)\n"
                "\tat com.example.Main.main(Main.java:10)\n",
                encoding="utf-8",
            )

            events = [
                {
                    "type": "artifact_attached",
                    "kind": "trace",
                    "stored_path": str(trace_path),
                }
            ]

            parsed = build_parsed_artifacts(events)
            self.assertIn("java.lang.IllegalStateException", parsed["exception_types"])
            self.assertTrue(any("Worker.java" in item for item in parsed["file_hints"]))
