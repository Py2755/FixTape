from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fixtape.runner import run_command


class RunnerTests(unittest.TestCase):
    def test_run_command_captures_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stdout_path = root / "stdout.txt"
            stderr_path = root / "stderr.txt"
            result = run_command(["python", "-c", "print('runner ok')"], root, stdout_path, stderr_path)

            self.assertEqual(result["exit_code"], 0)
            self.assertTrue(stdout_path.exists())
            self.assertIn("runner ok", stdout_path.read_text(encoding="utf-8"))
