"""Checks on .claude/settings.json: valid JSON, paid-command ask rules, secret-file deny rules.

Run: python3 -I .claude/hooks/test_settings.py

The wildcard is simulated with fnmatch (`*` matches any text, including spaces, as the Claude Code
permissions page documents). This is a simulation of the matcher, not the matcher itself: it cannot
show that a prompt appears in a given permission mode.
"""

import fnmatch
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SETTINGS = json.loads((ROOT / ".claude" / "settings.json").read_text())
EVAL = ROOT / "backend" / "evaluation"

# Every executable evaluation module that can make paid provider calls, with its invocation module path.
PAID = {
    "rag_eval.cli": "evaluation.rag_eval.cli run --cap 1",
    "rag_eval.retrieval_probe": "evaluation.rag_eval.retrieval_probe --cap 1",
    "rag_eval.first_step_probe": "evaluation.rag_eval.first_step_probe --cap 1",
    "rag_eval.planted_claims": "evaluation.rag_eval.planted_claims --cap 1",
    "rag_eval.ragbench_check": "evaluation.rag_eval.ragbench_check --cap 1",
    "intent_eval": "evaluation.intent_eval --execute",
    "agent_smoke_runner": "evaluation.agent_smoke_runner --execute",
    "runner": "evaluation.runner --execute-gold",
    "conversation_runner": "evaluation.conversation_runner --execute-conversation",
}
# Executable modules reviewed and judged free (no provider call). A new entry point must be added to PAID or here.
FREE = {
    "rag_eval.corpus_v1", "rag_eval.coverage", "rag_eval.fetch_public", "rag_eval.freeze",
    "rag_eval.index_verify", "rag_eval.messy_fixtures", "rag_eval.pools",
}  # fmt: skip


def asks(command: str) -> bool:
    return any(
        fnmatch.fnmatchcase(command, r[len("Bash(") : -1])
        for r in SETTINGS["permissions"]["ask"]
        if r.startswith("Bash(")
    )


def denies_read(path: str) -> bool:
    # gitignore-style `**/name` matches the name at any depth; `*` inside a name matches any text.
    rel = path.lstrip("/")
    for r in SETTINGS["permissions"]["deny"]:
        if r.startswith("Read(**/"):
            pattern = r[len("Read(**/") : -1]
            if fnmatch.fnmatchcase(rel.rsplit("/", 1)[-1], pattern):
                return True
    return False


class PaidCommandRules(unittest.TestCase):
    def test_every_entry_point_is_classified(self) -> None:
        found = set()
        for f in EVAL.rglob("*.py"):
            if "__pycache__" in f.parts or '__name__ == "__main__"' not in f.read_text():
                continue
            found.add(".".join(f.relative_to(EVAL).with_suffix("").parts))
        self.assertEqual(found - set(PAID) - FREE, set(), "classify new entry points")
        self.assertEqual((set(PAID) | FREE) - found, set(), "classified module no longer exists")

    def test_module_and_path_invocations_prompt(self) -> None:
        for name, args in PAID.items():
            for prefix in ("uv run python -m ", "python3 -m ", "cd backend && uv run python -m "):
                self.assertTrue(asks(prefix + args), f"module form not covered: {name}")
            path = "backend/evaluation/" + name.replace(".", "/") + ".py"
            self.assertTrue(asks(f"python {path} --cap 1"), f"path form not covered: {name}")

    def test_reading_or_linting_paid_modules_does_not_prompt(self) -> None:
        for cmd in (
            "git diff backend/evaluation/intent_eval.py",
            "cat backend/evaluation/runner.py",
            "uv run ruff check evaluation/conversation_runner.py",
            "grep -n main backend/evaluation/rag_eval/cli.py",
        ):
            self.assertFalse(asks(cmd), cmd)

    def test_free_commands_do_not_match_by_accident(self) -> None:
        for mod in FREE:
            self.assertFalse(asks(f"uv run python -m evaluation.{mod} --help"), mod)


class SecretFileRules(unittest.TestCase):
    def test_secret_names_denied_at_any_depth(self) -> None:
        for p in (
            "/x/.env", "/x/backend/.env", "/x/frontend/.env.local", "/x/a/b/.env.production",
            "/x/credentials.json", "/x/a/token.json", "/x/a/key.pem",
        ):  # fmt: skip
            self.assertTrue(denies_read(p), p)

    def test_ordinary_files_not_denied(self) -> None:
        for p in ("/x/AGENTS.md", "/x/backend/pyproject.toml", "/x/environment.md"):
            self.assertFalse(denies_read(p), p)


class Structure(unittest.TestCase):
    def test_push_and_destructive_rules_present(self) -> None:
        deny = SETTINGS["permissions"]["deny"]
        for rule in ("Bash(git push *)", "Bash(git reset --hard*)", "Bash(railway *)"):
            self.assertIn(rule, deny)
        self.assertIn("Bash(git commit*)", SETTINGS["permissions"]["ask"])

    def test_guard_hook_registered(self) -> None:
        cmds = [h["command"] for g in SETTINGS["hooks"]["PreToolUse"] for h in g["hooks"]]
        self.assertTrue(any("hooks/guard.py" in c for c in cmds))
        self.assertTrue(re.search(r"Bash", SETTINGS["hooks"]["PreToolUse"][0]["matcher"]))


if __name__ == "__main__":
    unittest.main()
