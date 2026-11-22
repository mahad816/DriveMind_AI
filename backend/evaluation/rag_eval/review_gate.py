"""The Owner-review gate for the sealed held-out pool (M1-07-F, closes blocker B-1).

A paid run that measures held-out cases must not start on a pool the Owner has not reviewed, or on a pool that
changed after the review. The review state is one small file beside the sealed file, outside the repository:

    <sealed file stem>.review-attestation.json

It records the sealed file's SHA-256, the freeze manifest's ``held_out`` checksum, the review sheet's SHA-256 and
three counts (reviewed, correct, gold wrong). It holds no case id, question, answer or anchor.

    attest-review SHEET     the only writer. Reads the Owner's review sheet and writes the attestation. Refuses
                            unless: the Owner confirms at an interactive terminal by typing a fixed phrase; the
                            sheet lies outside the repository; the freeze checksum equals the sealed file's; every
                            sheet case is in the sealed file and matches it; each case has exactly one box
                            ticked; at least ``MIN_REVIEWED`` cases are reviewed; none is "gold wrong".
    require_review(...)     the check ``pools.load_held_out`` runs by default: the attestation must exist, be
                            well formed, equal the sealed file's current hash and equal the freeze checksum.

Any amendment of the sealed file changes its hash and so ends the approval; no bookkeeping is needed. Free
commands (validate, coverage, review-sheet, freeze check) pass ``require_review=False`` and never need it.

Limits (also in docs/guides/EVALUATION.md): the attestation is a plain file. It stops an accident, a stale
approval and a normal run that never touches it; it does not stop someone who can write files on the Owner's
machine and chooses to forge it. It records review only, never approval of spend.
"""

import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

MIN_REVIEWED = 30
VERSION = 1
CONFIRM_PHRASE = "I HAVE REVIEWED THE SHEET AS THE OWNER"
SUFFIX = ".review-attestation.json"
FIELDS = {
    "version",
    "sealed_sha256",
    "freeze_held_out_sha256",
    "sheet_sha256",
    "reviewed",
    "correct",
    "gold_wrong",
    "attested_at",
}
TICKED = frozenset("xX✓✔")
HEADER = re.compile(r"^## (\d+)\. (\S+) \((.+)\)\s*$")
BOXES = re.compile(r"^- \[(.)\] correct\s+- \[(.)\] gold wrong")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class Terminal(Protocol):
    def isatty(self) -> bool: ...


class ReviewRequired(RuntimeError):
    """A paid held-out run was asked for without a current, matching Owner review attestation."""


class ReviewRefused(ValueError):
    """The attestation could not be written; the message names a rule, never a case."""


def attestation_path(sealed: Path) -> Path:
    return sealed.with_name(sealed.stem + SUFFIX)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_checksum(manifest_path: Path) -> str | None:
    try:
        node = json.loads(manifest_path.read_text()).get("held_out") or {}
    except (OSError, ValueError, AttributeError):
        return None
    value = node.get("sha256") if isinstance(node, dict) else None
    return value if isinstance(value, str) else None


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def require_review(sealed: Path, manifest_path: Path) -> dict[str, Any]:
    """Return the attestation when it is valid for the sealed file as it is now; otherwise raise ReviewRequired."""
    where = attestation_path(sealed)
    hint = " Run the free checks; paid held-out work waits for the Owner's `pools attest-review`."
    if not where.is_file():
        raise ReviewRequired("no Owner review attestation beside the sealed file." + hint)
    try:
        record = json.loads(where.read_text())
    except (OSError, ValueError):
        raise ReviewRequired("the review attestation is unreadable." + hint) from None
    if not isinstance(record, dict) or set(record) != FIELDS or record["version"] != VERSION:
        raise ReviewRequired("the review attestation is malformed." + hint)
    shas = ("sealed_sha256", "freeze_held_out_sha256", "sheet_sha256")
    counts = ("reviewed", "correct", "gold_wrong")
    if not all(isinstance(record[k], str) and HEX64.match(record[k]) for k in shas) or not all(
        _is_count(record[k]) for k in counts
    ):
        raise ReviewRequired("the review attestation is malformed." + hint)
    if (
        record["reviewed"] < MIN_REVIEWED
        or record["gold_wrong"] != 0
        or record["correct"] != record["reviewed"]
    ):
        raise ReviewRequired("the review attestation does not describe a completed review." + hint)
    actual = sha256_file(sealed)
    if record["sealed_sha256"] != actual:
        raise ReviewRequired("the sealed file changed since the review was attested." + hint)
    frozen = freeze_checksum(manifest_path)
    if frozen != actual or record["freeze_held_out_sha256"] != frozen:
        raise ReviewRequired("the freeze checksum does not match the attested sealed file." + hint)
    return record


# --- reading the Owner's sheet -----------------------------------------------------------------------


def parse_sheet(text: str) -> list[dict[str, Any]]:
    """One entry per case block: id, behaviour, content lines before the boxes, and the boxes found."""
    blocks: list[dict[str, Any]] = []
    for line in text.splitlines():
        header = HEADER.match(line)
        if header:
            blocks.append(
                {"id": header[2], "behavior": header[3], "body": [], "boxes": [], "done": False}
            )
        elif blocks:
            current = blocks[-1]
            box = BOXES.match(line)
            if box:
                current["boxes"].append((box[1] in TICKED, box[2] in TICKED))
                current["done"] = True
            elif not current["done"]:
                current["body"].append(line)
    return blocks


def _expected_body(case: Mapping[str, Any]) -> list[str]:
    from .pools import render_review_sheet

    lines = render_review_sheet([case]).splitlines()
    start = next(i for i, ln in enumerate(lines) if HEADER.match(ln))
    return [ln for ln in lines[start + 1 :] if not BOXES.match(ln)]


def _strip(lines: Sequence[str]) -> list[str]:
    out = [ln.rstrip() for ln in lines]
    while out and not out[-1]:
        out.pop()
    return out


def check_sheet(text: str, cases: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Counts for a sheet that is complete and corresponds to ``cases``; raises ReviewRefused otherwise."""
    blocks = parse_sheet(text)
    if not blocks:
        raise ReviewRefused("the sheet has no review entries")
    by_id = {str(c.get("id")): c for c in cases}
    seen: set[str] = set()
    for position, block in enumerate(blocks, start=1):
        if block["id"] in seen:
            raise ReviewRefused(f"sheet entry {position} repeats an earlier case (duplicate)")
        seen.add(block["id"])
        case = by_id.get(block["id"])
        if (
            case is None
            or block["behavior"] != case.get("expected_behavior")
            or _strip(block["body"]) != _strip(_expected_body(case))
        ):
            raise ReviewRefused(f"sheet entry {position} does not correspond to the sealed file")
    correct = wrong = 0
    for position, block in enumerate(blocks, start=1):
        if len(block["boxes"]) != 1 or sum(block["boxes"][0]) != 1:
            raise ReviewRefused(f"sheet entry {position} must have exactly one box ticked")
        correct += block["boxes"][0][0]
        wrong += block["boxes"][0][1]
    if len(blocks) < MIN_REVIEWED:
        raise ReviewRefused(
            f"the sheet reviews {len(blocks)} cases; at least {MIN_REVIEWED} are required"
        )
    if wrong:
        raise ReviewRefused(
            f"{wrong} case(s) are marked gold wrong: correct them through `freeze seal-held-out`, then review again"
        )
    return {"reviewed": len(blocks), "correct": correct, "gold_wrong": wrong}


def write_attestation(
    sheet: Path,
    sealed: Path,
    *,
    manifest_path: Path,
    owner_confirmed: bool,
) -> dict[str, Any]:
    """Create the attestation from the Owner's sheet. ``owner_confirmed`` must be True, and only
    ``attest_command`` (an interactive terminal) sets it; nothing in an evaluation run calls this."""
    from .pools import REPO_ROOT

    if not owner_confirmed:
        raise ReviewRefused("the Owner must confirm the review at a terminal; nothing was written")
    target = sheet.expanduser().resolve()
    if target == REPO_ROOT or REPO_ROOT in target.parents:
        raise ReviewRefused(
            "the review sheet holds held-out text and must lie outside the repository"
        )
    if not target.is_file():
        raise ReviewRefused("the review sheet file does not exist")
    actual = sha256_file(sealed)
    frozen = freeze_checksum(manifest_path)
    if frozen != actual:
        raise ReviewRefused(
            "the freeze checksum does not match the sealed file; seal or amend it first"
        )
    cases = json.loads(sealed.read_text())["cases"]
    counts = check_sheet(target.read_text(), cases)
    record = {
        "version": VERSION,
        "sealed_sha256": actual,
        "freeze_held_out_sha256": frozen,
        "sheet_sha256": sha256_file(target),
        **counts,
        "attested_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    where = attestation_path(sealed)
    scratch = where.with_name(where.name + ".tmp")
    fd = os.open(scratch, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(record, indent=1) + "\n")
    os.replace(scratch, where)
    return record


def attest_command(
    sheet: Path,
    sealed: Path | None,
    manifest_path: Path,
    *,
    stdin: Terminal | None = None,
    ask: Callable[[str], str] = input,
) -> int:
    """`pools attest-review SHEET`: the Owner's explicit act. Needs an interactive terminal and a typed phrase,
    so a script, a pipe or an agent running a shell command cannot supply it."""
    stream = stdin if stdin is not None else sys.stdin
    if not stream.isatty():
        print(
            "attest-review needs an interactive terminal: the Owner runs it, not a script or an agent."
        )
        return 2
    if sealed is None:
        print("Set DRIVEMIND_EVAL_HELDOUT_FILE to the sealed case file first.")
        return 2
    print(
        "This records that YOU reviewed the held-out review sheet. It does not approve any spend."
    )
    if ask(f"Type exactly '{CONFIRM_PHRASE}' to continue: ").strip() != CONFIRM_PHRASE:
        print("Not confirmed; nothing was written.")
        return 1
    try:
        record = write_attestation(sheet, sealed, manifest_path=manifest_path, owner_confirmed=True)
    except ReviewRefused as exc:
        print(f"Refused: {exc}")
        return 1
    print(
        f"Attestation written beside the sealed file: {record['reviewed']} reviewed, "
        f"{record['correct']} correct, {record['gold_wrong']} gold wrong."
    )
    return 0
