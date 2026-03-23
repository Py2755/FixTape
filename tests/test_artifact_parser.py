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
