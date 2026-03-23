from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from fixtape.git_tools import collect_git_state, get_repo_root


class GitToolsTests(unittest.TestCase):
    def test_repo_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=root, check=True, capture_output=True)
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)

            repo_root = get_repo_root(root)
            self.assertEqual(repo_root, root.resolve())

            state = collect_git_state(root)
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.repo_root, str(root.resolve()))
