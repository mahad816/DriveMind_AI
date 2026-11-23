#!/usr/bin/env python3
"""PreToolUse guard: keep the sealed held-out store closed to ordinary sessions and subagents.

Reads the hook JSON on stdin; exit 0 = no objection, exit 2 = block (stderr is shown to the model).

Blocks Read/Grep/Glob/Bash calls that name the Owner-local sealed store (``~/.drivemind-eval-sealed``) or its
files, or that search from a directory above it. The Owner opts in for a private review session by starting it
with ``DRIVEMIND_PRIVATE_REVIEW=1`` in the environment.

LIMITS (also in .claude/README.md): this inspects tool arguments and command TEXT. It does not stop a program that
opens the file itself (``python -c``, the eval CLI's own loader), a path built from shell variables or globs
(``ls ~/.drive*``), recursive search from the home directory through Bash, or a symlink made earlier. It is an
accident guard, not a sandbox. History: an allow-list for a read-only reviewer Bash was tried and removed after
three reviews each found new bypasses; the reviewer now has no Bash tool at all.
"""

from __future__ import annotations

import json
import os
import sys

SEALED_DIR = os.path.realpath(os.path.expanduser("~/.drivemind-eval-sealed"))
SEALED_MARKERS = (
    ".drivemind-eval-sealed",
    ".drivemind-",  # also catches a glob such as ".drivemind-e*"
    "m1_held_out_cases",
    "m1_review_sheet_for_owner",
)


def block(reason: str) -> None:
    print(f"BLOCKED by .claude/hooks/guard.py: {reason}", file=sys.stderr)
    sys.exit(2)


def touches_sealed_text(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in SEALED_MARKERS)


def path_hits_sealed(raw: str, search_tool: bool) -> bool:
    if not raw:
        return False
    if touches_sealed_text(raw):
        return True
    resolved = os.path.realpath(os.path.expanduser(raw))
    if resolved == SEALED_DIR or resolved.startswith(SEALED_DIR + os.sep):
        return True
    # A recursive search rooted at an ancestor (for example the home directory) would walk into the store.
    return search_tool and (SEALED_DIR + os.sep).startswith(resolved.rstrip(os.sep) + os.sep)


def check_sealed(tool: str, tool_input: dict) -> None:
    if os.environ.get("DRIVEMIND_PRIVATE_REVIEW") == "1":
        return
    msg = (
        "sealed held-out material is closed to ordinary sessions. The Owner starts an explicit private review "
        "session (DRIVEMIND_PRIVATE_REVIEW=1) for that; do not work around this."
    )
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        if touches_sealed_text(command) or "~/.drivemind" in command:
            block(msg)
        return
    search = tool in {"Grep", "Glob"}
    for key in ("file_path", "path", "pattern"):
        value = tool_input.get(key)
        if isinstance(value, str) and path_hits_sealed(value, search_tool=search and key == "path"):
            block(msg)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        block("hook input was not valid JSON (fail closed).")
    if not isinstance(event, dict) or not isinstance(event.get("tool_input") or {}, dict):
        block("hook input had an unexpected shape (fail closed).")
    tool = event.get("tool_name", "")
    if tool in {"Bash", "Read", "Grep", "Glob"}:
        check_sealed(tool, event.get("tool_input") or {})
    sys.exit(0)


if __name__ == "__main__":
    main()
