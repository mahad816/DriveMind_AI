"""Freeze manifest and amendment log for the M1 question set.

``datasets/m1_freeze.json`` holds the SHA-256 of every frozen case file, the corpus version id, the pool mapping
and, for the sealed held-out file, only its checksum and counts per gate group. ``datasets/m1_amendments.json``
is the log of every change made to a frozen file after it was frozen: date, case ids, reason, checksum before and
after. ``check`` fails when a file differs from the manifest, when the manifest and the log disagree, or when a
case file exists that the manifest does not list. The only way to change a frozen file is ``amend``, which
writes the log entry and the new checksum together.

    uv run python -m evaluation.rag_eval.freeze check
    uv run python -m evaluation.rag_eval.freeze write                         # first manifest only
    uv run python -m evaluation.rag_eval.freeze amend FILE --reason TEXT [--cases ID ...] [--kind correction]
    uv run python -m evaluation.rag_eval.freeze add FILE --reason TEXT        # register a new case file
    uv run python -m evaluation.rag_eval.freeze seal-held-out --reason TEXT   # record the sealed file's checksum

A held-out amendment records no case ids unless the case moved to the development pool: the log is committed.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .corpus import CORPUS_DIR
from .dataset import DATA
from .pools import FREEZE_MANIFEST, HELD_OUT_ENV, LEGACY_FILES, POOLS, held_out_path, pool_of

AMENDMENT_LOG = DATA / "m1_amendments.json"
HELD_OUT_KEY = "held_out"
KINDS = {"correction", "addition", "move_to_development"}
SHA = re.compile(r"[0-9a-f]{64}")
PREFIX = re.compile(r"[0-9a-f]{6,63}")
CASE_FILE_PATTERNS = ("rag_v2_*.json", "rag_v3_*.json", "m1_*cases*.json")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_version() -> str:
    return str(json.loads((CORPUS_DIR / "v1_manifest.json").read_text())["corpus_version"])


def describe(path: Path) -> dict[str, Any]:
    """Checksum and case counts of one case file."""
    cases = json.loads(path.read_text())["cases"]
    by_pool = Counter(pool_of(c) for c in cases)
    return {
        "sha256": sha256_of(path),
        "cases": len(cases),
        "by_pool": dict(sorted(by_pool.items())),
    }


def registered(path: Path) -> dict[str, Any]:
    """Manifest entry for a file entering the freeze: ``frozen_sha256`` is the anchor no tool moves again."""
    node = describe(path)
    return {"frozen_sha256": node["sha256"], **node}


def build_manifest(names: Sequence[str] = LEGACY_FILES, root: Path = DATA) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "corpus_version": corpus_version(),
        "pools": dict(POOLS),
        "files": {name: registered(root / name) for name in names},
        HELD_OUT_KEY: {
            "env": HELD_OUT_ENV,
            "frozen_sha256": None,
            "sha256": None,
            "cases": 0,
            "gate_group_counts": {},
            "injection_documents": [],
        },
    }


def _read(path: Path) -> Any:
    return json.loads(path.read_text())


def _write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=1, ensure_ascii=False) + "\n")


def _entry_problems(index: int, entry: Mapping[str, Any], known: set[str]) -> list[str]:
    tag = f"amendment {index + 1}"
    problems = []
    try:
        date.fromisoformat(str(entry.get("date")))
    except ValueError:
        problems.append(f"{tag}: date must be an ISO date")
    if entry.get("file") not in known:
        problems.append(f"{tag}: unknown file {entry.get('file')!r}")
    if entry.get("phase") not in {"history", "post_freeze"}:
        problems.append(f"{tag}: phase must be history or post_freeze")
    if entry.get("kind") not in KINDS:
        problems.append(f"{tag}: kind must be one of {sorted(KINDS)}")
    if not str(entry.get("reason") or "").strip():
        problems.append(f"{tag}: a reason is required")
    if not isinstance(entry.get("case_ids"), list):
        problems.append(f"{tag}: case_ids must be a list")
    if not SHA.fullmatch(str(entry.get("sha256_after"))):
        problems.append(f"{tag}: sha256_after must be a full SHA-256")
    before, prefix = entry.get("sha256_before"), entry.get("sha256_before_prefix")
    if before is not None and not SHA.fullmatch(str(before)):
        problems.append(f"{tag}: sha256_before must be a full SHA-256 or null")
    if before is None and prefix is not None and not PREFIX.fullmatch(str(prefix)):
        problems.append(f"{tag}: sha256_before_prefix must be lowercase hex")
    return problems


def check_chain(manifest: Mapping[str, Any], log: Sequence[Mapping[str, Any]]) -> list[str]:
    """The log must explain every difference between a file's frozen checksum and its current one.

    ``phase: history`` entries are earlier corrections recorded from the results history: they chain to each
    other and end at ``frozen_sha256``. ``phase: post_freeze`` entries start from ``frozen_sha256`` (a file
    registered after the freeze starts with its ``addition`` entry) and each ``before`` is the previous
    ``after``; the last ``after`` must be the manifest's current checksum. A manifest edited to match a changed
    file, with no log entry, fails here.
    """
    known = {*manifest["files"], HELD_OUT_KEY}
    problems = [p for i, e in enumerate(log) for p in _entry_problems(i, e, known)]
    for name in sorted(known):
        node = manifest[HELD_OUT_KEY] if name == HELD_OUT_KEY else manifest["files"][name]
        entries = [e for e in log if e.get("file") == name]
        history = [e for e in entries if e.get("phase") == "history"]
        later = [e for e in entries if e.get("phase") == "post_freeze"]
        for earlier, next_ in zip(history, history[1:], strict=False):
            if next_.get("sha256_before") != earlier.get("sha256_after"):
                problems.append(f"{name}: history chain broken at {next_['date']}")
        if history and history[-1].get("sha256_after") != node["frozen_sha256"]:
            problems.append(f"{name}: the history does not end at the frozen checksum")
        expected = node["frozen_sha256"]
        for entry in later:
            if entry.get("kind") == "addition" and entry.get("sha256_before") is None:
                if entry.get("sha256_after") != node["frozen_sha256"]:
                    problems.append(f"{name}: the addition entry is not the frozen checksum")
            elif entry.get("sha256_before") != expected:
                problems.append(
                    f"{name}: amendment of {entry['date']} does not start from the previous checksum"
                )
            expected = entry.get("sha256_after")
        if node["sha256"] != expected:
            problems.append(f"{name}: the manifest checksum has no amendment entry behind it")
    return problems


def check(
    manifest: Mapping[str, Any],
    log: Sequence[Mapping[str, Any]],
    root: Path = DATA,
    held_out_file: Path | None = None,
) -> list[str]:
    """Problems with the freeze (empty = intact). Needs no key, no network and no held-out file."""
    problems = []
    if manifest["corpus_version"] != corpus_version():
        problems.append(
            f"corpus version is {corpus_version()}, the freeze says {manifest['corpus_version']}"
        )
    if manifest["pools"] != POOLS:
        problems.append("pool mapping differs from pools.POOLS")
    for name, recorded in manifest["files"].items():
        path = root / name
        if not path.exists():
            problems.append(f"{name}: frozen file is missing")
        elif sha256_of(path) != recorded["sha256"]:
            problems.append(
                f"{name}: changed since it was frozen; record it with `freeze amend {name} --reason ...`"
            )
        elif describe(path)["cases"] != recorded["cases"]:
            problems.append(f"{name}: case count differs from the manifest")
    listed = set(manifest["files"])
    for pattern in CASE_FILE_PATTERNS:
        problems += [
            f"{p.name}: case file not in the freeze; register it with `freeze add`"
            for p in sorted(root.glob(pattern))
            if p.name not in listed
        ]
    problems += check_chain(manifest, log)
    held = manifest[HELD_OUT_KEY]
    if held_out_file is not None:
        if held["sha256"] is None:
            problems.append("a held-out file is present but the freeze records no checksum for it")
        elif sha256_of(held_out_file) != held["sha256"]:
            problems.append(
                "the held-out file changed since it was sealed; record it with `freeze amend held_out`"
            )
    return problems


def _manifest_sha(manifest: Mapping[str, Any], name: str) -> str | None:
    node = manifest[HELD_OUT_KEY] if name == HELD_OUT_KEY else manifest["files"].get(name)
    return None if node is None else node["sha256"]


def _record(
    manifest: dict[str, Any],
    log: list[dict[str, Any]],
    name: str,
    path: Path,
    *,
    reason: str,
    case_ids: Sequence[str],
    kind: str,
    today: date,
) -> None:
    before, after = _manifest_sha(manifest, name), sha256_of(path)
    if before == after:
        raise ValueError(f"{name} has not changed since it was frozen; nothing to record")
    if not reason.strip():
        raise ValueError("a reason is required")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    log.append(
        {
            "date": today.isoformat(),
            "file": name,
            "phase": "post_freeze",
            "kind": kind,
            "case_ids": list(case_ids),
            "reason": reason.strip(),
            "sha256_before": before,
            "sha256_after": after,
        }
    )


def amend(
    name: str,
    *,
    reason: str,
    case_ids: Sequence[str] = (),
    kind: str = "correction",
    today: date | None = None,
    root: Path = DATA,
    manifest_path: Path = FREEZE_MANIFEST,
    log_path: Path = AMENDMENT_LOG,
) -> None:
    """Record a deliberate change to a frozen case file: log entry and new checksum together."""
    manifest, log = _read(manifest_path), _read(log_path)
    if name not in manifest["files"]:
        raise ValueError(f"{name} is not a frozen file (use `freeze add` for a new case file)")
    path = root / name
    _record(
        manifest,
        log,
        name,
        path,
        reason=reason,
        case_ids=case_ids,
        kind=kind,
        today=today or datetime.now(UTC).date(),
    )
    manifest["files"][name] = {**manifest["files"][name], **describe(path)}
    _write(manifest_path, manifest)
    _write(log_path, log)


def add_file(
    name: str,
    *,
    reason: str,
    today: date | None = None,
    root: Path = DATA,
    manifest_path: Path = FREEZE_MANIFEST,
    log_path: Path = AMENDMENT_LOG,
) -> None:
    """Register a new case file in the freeze, logged as an addition (a file added after the freeze)."""
    manifest, log = _read(manifest_path), _read(log_path)
    if name in manifest["files"]:
        raise ValueError(f"{name} is already frozen")
    path = root / name
    cases = _read(path)["cases"]
    _record(
        manifest,
        log,
        name,
        path,
        reason=reason,
        case_ids=[c["id"] for c in cases],
        kind="addition",
        today=today or datetime.now(UTC).date(),
    )
    manifest["files"][name] = registered(path)
    _write(manifest_path, manifest)
    _write(log_path, log)


def held_out_counts(path: Path) -> dict[str, Any]:
    """Counts per gate group and the injection documents of the sealed file: counts and corpus paths only."""
    from .coverage import count_cases, injection_documents

    cases = _read(path)["cases"]
    return {
        "cases": len(cases),
        "gate_group_counts": dict(sorted(count_cases(cases).items())),
        "injection_documents": injection_documents(cases),
    }


def seal_held_out(
    path: Path,
    *,
    reason: str,
    today: date | None = None,
    manifest_path: Path = FREEZE_MANIFEST,
    log_path: Path = AMENDMENT_LOG,
) -> None:
    """Record the sealed file's checksum and counts. The first call is the seal; a later call is an amendment.
    The log entry never lists the file's case ids."""
    manifest, log = _read(manifest_path), _read(log_path)
    kind = "addition" if manifest[HELD_OUT_KEY]["sha256"] is None else "correction"
    _record(
        manifest,
        log,
        HELD_OUT_KEY,
        path,
        reason=reason,
        case_ids=[],
        kind=kind,
        today=today or datetime.now(UTC).date(),
    )
    node = manifest[HELD_OUT_KEY]
    node.update(sha256=sha256_of(path), **held_out_counts(path))
    node["frozen_sha256"] = node["frozen_sha256"] or node["sha256"]
    _write(manifest_path, manifest)
    _write(log_path, log)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["check", "write", "amend", "add", "seal-held-out"])
    parser.add_argument("file", nargs="?")
    parser.add_argument("--reason")
    parser.add_argument("--cases", nargs="*", default=[])
    parser.add_argument("--kind", default="correction", choices=sorted(KINDS))
    args = parser.parse_args(argv)
    if args.command == "check":
        problems = check(
            _read(FREEZE_MANIFEST), _read(AMENDMENT_LOG), held_out_file=held_out_path()
        )
        print(f"freeze: {len(problems)} problem(s)")
        for line in problems:
            print(" ", line)
        return 1 if problems else 0
    if args.command == "write":
        if FREEZE_MANIFEST.exists():
            raise SystemExit("the freeze manifest exists; change a frozen file with `amend`")
        _write(FREEZE_MANIFEST, build_manifest())
        _write(AMENDMENT_LOG, []) if not AMENDMENT_LOG.exists() else None
        return 0
    if not args.reason:
        parser.error("--reason is required")
    if args.command == "seal-held-out":
        path = held_out_path()
        if path is None:
            parser.error(f"set {HELD_OUT_ENV}")
        seal_held_out(path, reason=args.reason)
    elif not args.file:
        parser.error("a case file name is required")
    elif args.command == "amend":
        amend(args.file, reason=args.reason, case_ids=args.cases, kind=args.kind)
    else:
        add_file(args.file, reason=args.reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
