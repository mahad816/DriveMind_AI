"""Tests for .claude/hooks/guard.py. Run: python3 -I .claude/hooks/test_guard.py  (no network, no keys, no repo data)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

GUARD = str(Path(__file__).with_name("guard.py"))
SEALED = os.path.expanduser("~/.drivemind-eval-sealed")


def run(tool: str, tool_input: dict, *, private: bool = False) -> int:
    env = {k: v for k, v in os.environ.items() if k != "DRIVEMIND_PRIVATE_REVIEW"}
    if private:
        env["DRIVEMIND_PRIVATE_REVIEW"] = "1"
    payload = json.dumps({"tool_name": tool, "tool_input": tool_input})
    return subprocess.run(
        [sys.executable, GUARD], input=payload, text=True, capture_output=True, env=env
    ).returncode


def bash(command: str, **kw: bool) -> int:
    return run("Bash", {"command": command}, **kw)


class SealedRule(unittest.TestCase):
    def test_read_sealed_file_blocked(self) -> None:
        self.assertEqual(run("Read", {"file_path": f"{SEALED}/m1_held_out_cases.json"}), 2)

    def test_read_with_tilde_blocked(self) -> None:
        self.assertEqual(run("Read", {"file_path": "~/.drivemind-eval-sealed/anything"}), 2)

    def test_grep_into_sealed_blocked(self) -> None:
        self.assertEqual(run("Grep", {"pattern": "x", "path": SEALED}), 2)

    def test_grep_from_home_ancestor_blocked(self) -> None:
        self.assertEqual(run("Grep", {"pattern": "x", "path": os.path.expanduser("~")}), 2)

    def test_glob_pattern_blocked(self) -> None:
        self.assertEqual(run("Glob", {"pattern": "~/.drivemind-eval-sealed/*"}), 2)

    def test_glob_prefix_blocked(self) -> None:
        self.assertEqual(run("Glob", {"pattern": "~/.drivemind-e*"}), 2)

    def test_bash_cat_blocked(self) -> None:
        self.assertEqual(bash("cat ~/.drivemind-eval-sealed/m1_held_out_cases.json"), 2)

    def test_bash_by_filename_blocked(self) -> None:
        self.assertEqual(bash("find / -name m1_held_out_cases.json"), 2)

    def test_private_review_env_allows(self) -> None:
        self.assertEqual(
            run("Read", {"file_path": f"{SEALED}/m1_held_out_cases.json"}, private=True), 0
        )

    def test_ordinary_repo_reads_allowed(self) -> None:
        self.assertEqual(run("Read", {"file_path": "/Users/x/Developer/DriveMind_AI/AGENTS.md"}), 0)
        self.assertEqual(run("Grep", {"pattern": "held_out", "path": "backend/evaluation"}), 0)
        self.assertEqual(bash("git status"), 0)

    def test_invalid_json_fails_closed(self) -> None:
        proc = subprocess.run(
            [sys.executable, GUARD], input="not json", text=True, capture_output=True
        )
        self.assertEqual(proc.returncode, 2)

    def test_unexpected_shape_fails_closed(self) -> None:
        for payload in ('["Bash"]', '{"tool_name": "Bash", "tool_input": "ls"}'):
            proc = subprocess.run(
                [sys.executable, GUARD], input=payload, text=True, capture_output=True
            )
            self.assertEqual(proc.returncode, 2, payload)


if __name__ == "__main__":
    unittest.main(verbosity=1)
