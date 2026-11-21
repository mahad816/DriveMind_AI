"""Protective census for the "first stored Google credential" fallbacks (M0 ticket 03, area A2).

Three services (chunking, ingestion, indexing) still resolve ``user_id=None`` to an arbitrary
credential owner (KI-031,
``tests/known_issues/test_ki031_credential_owner_fallback.py``). That is harmless only while no
caller leaves the owner out. These tests read the source (no database, no network) and fail if:

* a production call of a fallback-reaching entry method omits ``user_id`` or passes a literal ``None``;
* ``resolve_active_user`` is called without an owner outside the two demo-only modules;
* a seventh statement selects ``GoogleOAuthToken`` without filtering on its owner column.

Known limits: the entry-method check matches by method name and accepts only a ``user_id=`` keyword
(a positional owner or ``**kwargs`` is not understood; an unrelated class with a same-named method
would be flagged). They are tripwires, not proof: a call that passes a variable which is ``None`` at run time is not
visible to them. The run-time side is covered by the route-dependency tests
(``test_private_read_authorization.py``), the worker's non-UUID guard and the KI-031 guards.
When KI-031 is fixed the third check only gets stricter (its allow-list may shrink, never grow).
"""

import ast
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SCANNED_ROOTS = (BACKEND / "app", BACKEND / "evaluation")

# Entry methods of the services that take an owner. Sync and content now refuse an owner-less call
# (ticket 01); only ingest_files, chunk_documents and build_index still reach a fallback. Kept whole
# as a tripwire.
ENTRY_METHODS = {
    "sync_metadata",
    "get_latest_sync_job",
    "list_synced_files",
    "is_connected",
    "get_pending_counts",
    "fetch_file_content",
    "ingest_files",
    "chunk_documents",
    "build_index",
}

# resolve_active_user() with no owner is the demo identity path: both modules refuse to run
# outside DEMO_MODE (demo/load.py raises first; demo/service.is_ready is only reached behind
# `settings.demo_mode` gates in api/index.py and api/dependencies.py).
DEMO_ONLY_NO_OWNER = {"app/demo/load.py", "app/demo/service.py"}

# The three fallbacks left (ticket 02 closes them) plus the demo "no credentials in storage" check.
KNOWN_UNSCOPED_CREDENTIAL_SELECTS = {
    "app/services/chunking_service.py",
    "app/services/ingestion_service.py",
    "app/services/indexing_service.py",
    "app/demo/service.py",
}

OWNER_FILTER = re.compile(r"GoogleOAuthToken\.user_id\s*==|\.filter_by\(\s*user_id")


def _unscoped_credential_selects(path: Path) -> list[int]:
    """Lines of statements that select GoogleOAuthToken without naming its owner column.

    Looks at whole statements, so ``.first()``, ``.order_by()`` and ``.limit(1)`` variants are all
    seen. A statement is scoped if it filters ``GoogleOAuthToken.user_id ==`` something. Schema
    probes (``select(model).limit(0)``) do not name the model and are not matched.
    """
    source = path.read_text(encoding="utf-8")
    lines: list[int] = []
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.If | ast.While):
            segment = ast.get_source_segment(source, node.test) or ""
        elif isinstance(node, ast.Assign | ast.AnnAssign | ast.Expr | ast.Return):
            segment = ast.get_source_segment(source, node) or ""
        else:
            continue
        if re.search(r"select\(\s*GoogleOAuthToken\b", segment) and not OWNER_FILTER.search(
            segment
        ):
            lines.append(node.lineno)
    return lines


def _python_files() -> list[Path]:
    return sorted(p for root in SCANNED_ROOTS for p in root.rglob("*.py") if ".venv" not in p.parts)


def _relative(path: Path) -> str:
    return path.relative_to(BACKEND).as_posix()


def _calls(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Call):
            yield node


def _is_none(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    if isinstance(call.func, ast.Name):
        return call.func.id
    return None


def test_every_entry_method_call_passes_an_explicit_owner() -> None:
    seen: dict[str, int] = {}
    violations: list[str] = []
    for path in _python_files():
        for call in _calls(path):
            name = _called_name(call)
            if name not in ENTRY_METHODS or not isinstance(call.func, ast.Attribute):
                continue
            seen[name] = seen.get(name, 0) + 1
            owner = next((kw.value for kw in call.keywords if kw.arg == "user_id"), None)
            if owner is None or _is_none(owner):
                violations.append(f"{_relative(path)}:{call.lineno} {name}() has no explicit owner")
    assert not violations, "\n".join(violations)
    # The scan must have found the real callers, or an empty pass would mean nothing.
    assert set(seen) >= {
        "list_synced_files",
        "is_connected",
        "get_pending_counts",
        "fetch_file_content",
        "build_index",
    }, seen


def test_resolve_active_user_without_owner_is_demo_only() -> None:
    owner_less: set[str] = set()
    owned = 0
    for path in _python_files():
        for call in _calls(path):
            if _called_name(call) != "resolve_active_user":
                continue
            owner = call.args[2] if len(call.args) >= 3 else None
            owner = owner or next((kw.value for kw in call.keywords if kw.arg == "user_id"), None)
            has_owner = owner is not None and not _is_none(owner)
            if has_owner:
                owned += 1
            else:
                owner_less.add(_relative(path))
    assert owner_less <= DEMO_ONLY_NO_OWNER, owner_less - DEMO_ONLY_NO_OWNER
    assert owner_less, (
        "scan found no owner-less call at all: the demo modules changed, update this test"
    )
    assert owned >= 3  # drive_sync, drive_content and rag_service pass an owner


def test_no_new_unscoped_credential_select() -> None:
    found = {_relative(path) for path in _python_files() if _unscoped_credential_selects(path)}
    unexpected = found - KNOWN_UNSCOPED_CREDENTIAL_SELECTS
    assert not unexpected, (
        f"new unscoped select of the Google credential model (no owner filter): {sorted(unexpected)}"
    )


@pytest.mark.parametrize("module", sorted(KNOWN_UNSCOPED_CREDENTIAL_SELECTS))
def test_known_fallback_list_is_current(module: str) -> None:
    """Keeps the allow-list honest: a fixed module must be removed from it, not left behind."""
    if not _unscoped_credential_selects(BACKEND / module):
        pytest.fail(f"{module} no longer has the fallback: remove it from the allow-list")
