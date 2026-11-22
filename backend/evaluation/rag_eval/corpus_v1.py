"""Builders, manifest and checks for the v1 evaluation corpus (the Marrowdale documents).

    python -m evaluation.rag_eval.corpus_v1 --write      # (re)write evaluation/corpus/v1/ and the manifest
    python -m evaluation.rag_eval.corpus_v1 --check      # rebuild in memory, compare, run every check
    python -m evaluation.rag_eval.corpus_v1 --report     # format and chunk-count table
    python -m evaluation.rag_eval.corpus_v1 --google declined   # record the Owner's decision on exports

Nothing here calls a model, an embedding service, Google or the network. The content descriptions are in
``corpus_v1_content.py``; the five older generated files stay in ``messy_fixtures.py`` unchanged.

The manifest (``corpus/v1_manifest.json``) freezes the whole committed corpus: the 19 new files, the five
generated Office and PDF files, the 22 synthetic text files and any Google exports the Owner pinned. The
33 public PDFs are not committed; their own manifest is referenced by checksum. Two digests are kept apart
on purpose: the **corpus version** hashes the file bytes (it changes only when a document changes), while
each file's **text digest** hashes what the product's readers extract (it changes when a reader changes,
which is a visible event, not a new corpus).
"""

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
from reportlab.lib.units import cm  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
)

from . import corpus_v1_content as content
from .corpus import CORPUS_DIR, sha256_file, synthetic_files
from .messy_fixtures import (
    STAMP,
    Slide,
    Table_,
    _fixed_zip,
    _furniture,
    _pdf_table,
    _styles,
    manifest_entries,
    truth_text,
)
from .text import contains

GENERATOR_VERSION = "1"
V1_DIR = CORPUS_DIR / "v1"
GOOGLE_DIR = CORPUS_DIR / "google"
MANIFEST = CORPUS_DIR / "v1_manifest.json"
SOURCES = {"generated", "public", "Google export"}
GROUPS = {"synthetic", "messy", "v1", "google"}
MIN_CANARIES = 3
MIN_LONG_CHUNKS = 4
GOOGLE_STATUS = {"pending", "pinned", "declined"}

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Blocks = content.Blocks


# ---- ground truth text ------------------------------------------------------------------------------------


def _table_lines(table: Table_) -> list[str]:
    return [" | ".join(row) for row in (table.header, *table.rows)]


def blocks_text(blocks: Blocks) -> str:
    """Everything a reader of the document would see, from the description only."""
    lines: list[str] = []
    for kind, payload in blocks:
        if kind in {"h1", "h2", "h3", "p"}:
            lines.append(str(payload))
        elif kind == "bullets":
            lines += list(payload)
        elif kind in {"table", "table_plain"}:
            lines += _table_lines(payload)
        elif kind == "columns":
            for heading, body in payload:
                lines += [heading, body]
    return "\n".join(lines)


def deck_text(slides: tuple[Slide, ...]) -> str:
    lines: list[str] = []
    for slide in slides:
        lines += [slide.title, *slide.bullets]
        if slide.table:
            lines += _table_lines(slide.table)
        for extra in (slide.textbox, slide.notes):
            if extra:
                lines.append(extra)
    return "\n".join(lines)


def sheets_text(sheets: list[content.Sheet]) -> str:
    lines: list[str] = []
    for name, rows in sheets:
        lines.append(name)
        for row in rows:
            cells = [c.cached if isinstance(c, content.Formula) else c for c in row]
            if cells:
                lines.append(" | ".join(str(c) for c in cells))
    return "\n".join(lines)


# ---- deterministic builders -------------------------------------------------------------------------------


def build_docx(blocks: Blocks, title: str) -> bytes:
    doc = Document()
    props = doc.core_properties
    props.author = props.last_modified_by = content.COMPANY
    props.created = props.modified = STAMP
    props.title = title
    for kind, payload in blocks:
        if kind in {"h1", "h2", "h3"}:
            doc.add_heading(str(payload), level=int(kind[1]))
        elif kind == "p":
            doc.add_paragraph(str(payload))
        elif kind == "bullets":
            for item in payload:
                doc.add_paragraph(item, style="List Bullet")
        elif kind in {"table", "table_plain"}:
            table: Table_ = payload
            grid = doc.add_table(rows=1 + len(table.rows), cols=len(table.header))
            grid.style = "Table Grid"
            for c, text in enumerate(table.header):
                grid.cell(0, c).text = text
            for r, row in enumerate(table.rows, start=1):
                for c, text in enumerate(row):
                    grid.cell(r, c).text = text
    buffer = io.BytesIO()
    doc.save(buffer)
    return _fixed_zip(buffer.getvalue())


def build_deck(slides: tuple[Slide, ...], title: str) -> bytes:
    prs = Presentation()
    prs.core_properties.author = prs.core_properties.last_modified_by = content.COMPANY
    prs.core_properties.created = prs.core_properties.modified = STAMP
    prs.core_properties.title = title
    for index, spec in enumerate(slides):
        if index == 0:
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = spec.title
            slide.placeholders[1].text_frame.text = spec.bullets[0]
        elif spec.table:
            slide = prs.slides.add_slide(prs.slide_layouts[5])
            slide.shapes.title.text = spec.title
            rows, cols = 1 + len(spec.table.rows), len(spec.table.header)
            grid = slide.shapes.add_table(
                rows, cols, Inches(0.7), Inches(2.0), Inches(8.6), Inches(2.4)
            ).table
            for c, text in enumerate(spec.table.header):
                grid.cell(0, c).text = text
            for r, row in enumerate(spec.table.rows, start=1):
                for c, text in enumerate(row):
                    grid.cell(r, c).text = text
        else:
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = spec.title
            frame = slide.placeholders[1].text_frame
            frame.text = spec.bullets[0]
            for bullet in spec.bullets[1:]:
                frame.add_paragraph().text = bullet
        if spec.textbox:
            box = slide.shapes.add_textbox(Inches(0.7), Inches(5.8), Inches(8.0), Inches(0.6))
            box.text_frame.text = spec.textbox
        if spec.notes:
            slide.notes_slide.notes_text_frame.text = spec.notes
    buffer = io.BytesIO()
    prs.save(buffer)
    return _fixed_zip(buffer.getvalue())


_EMPTY_VALUE = re.compile(
    rb"(<c r=\"([A-Z]+[0-9]+)\"[^>]*><f>[^<]*</f>)<v\s*/>|(<c r=\"([A-Z]+[0-9]+)\"[^>]*><f>[^<]*</f>)<v></v>"
)


def _write_cached_values(sheet_xml: bytes, cached: Mapping[str, float | int]) -> bytes:
    """Put Excel's last-calculated value after each formula, as a real Excel-saved file has it.

    openpyxl writes formulas with an empty value, and the product's reader (correctly) shows a formula
    that was never calculated as empty. A file saved by Excel always carries the value.
    """

    def put(match: re.Match[bytes]) -> bytes:
        head = match.group(1) or match.group(3)
        ref = (match.group(2) or match.group(4)).decode()
        return head + f"<v>{cached[ref]}</v>".encode()

    return _EMPTY_VALUE.sub(put, sheet_xml)


def build_xlsx(sheets: list[content.Sheet]) -> bytes:
    workbook = Workbook()
    workbook.properties.creator = workbook.properties.lastModifiedBy = content.COMPANY
    workbook.properties.created = workbook.properties.modified = STAMP
    workbook.remove(workbook.active)
    cached: dict[int, dict[str, float | int]] = {}
    for number, (name, rows) in enumerate(sheets, start=1):
        sheet = workbook.create_sheet(name)
        for r, row in enumerate(rows, start=1):
            for c, value in enumerate(row, start=1):
                cell = sheet.cell(row=r, column=c)
                if isinstance(value, content.Formula):
                    cell.value = "=" + value.expression
                    cached.setdefault(number, {})[cell.coordinate] = value.cached
                else:
                    cell.value = value
    buffer = io.BytesIO()
    workbook.save(buffer)
    if not cached:
        return _fixed_zip(buffer.getvalue())
    patched = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as source,
        zipfile.ZipFile(patched, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            data = source.read(info.filename)
            match = re.fullmatch(r"xl/worksheets/sheet(\d+)\.xml", info.filename)
            if match and int(match.group(1)) in cached:
                data = _write_cached_values(data, cached[int(match.group(1))])
            target.writestr(info, data)
    return _fixed_zip(patched.getvalue())


def build_pdf(blocks: Blocks, title: str, header: str) -> bytes:
    """Multi-page PDF; a ``columns`` block starts a two-column page (like a newsletter)."""
    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, invariant=1, title=title)
    width, height = A4
    margin = 2 * cm
    top = height - 2 * margin - 0.5 * cm
    full = Frame(margin, margin, width - 2 * margin, top, id="full")
    half = (width - 2 * margin - 1 * cm) / 2
    left = Frame(margin, margin, half, top, id="left")
    right = Frame(margin + half + 1 * cm, margin, half, top, id="right")
    furniture = _furniture(header, total=None)
    starts_in_columns = len(blocks) > 1 and blocks[1][0] == "columns"
    templates = [
        PageTemplate(id="single", frames=[full], onPage=furniture),
        PageTemplate(id="double", frames=[left, right], onPage=furniture),
    ]
    doc.addPageTemplates(list(reversed(templates)) if starts_in_columns else templates)
    styles = _styles()
    story: list[Any] = []
    for index, (kind, payload) in enumerate(blocks):
        nxt = blocks[index + 1][0] if index + 1 < len(blocks) else ""
        if kind in {"h1", "h2"} and nxt == "columns" and index > 1:
            story += [NextPageTemplate("double"), PageBreak()]
        if kind in {"h1", "h2", "h3", "p"}:
            style = styles["h2" if kind == "h3" else kind]
            story += [Paragraph(escape(str(payload)), style), Spacer(1, 6)]
        elif kind == "bullets":
            story += [Paragraph("- " + escape(item), styles["p"]) for item in payload]
            story.append(Spacer(1, 6))
        elif kind in {"table", "table_plain"}:
            story += [_pdf_table(payload, ruled=kind == "table"), Spacer(1, 14)]
        elif kind == "columns":
            for heading, body in payload:
                story += [
                    Paragraph(escape(heading), styles["h2"]),
                    Paragraph(escape(body), styles["p"]),
                ]
            if index + 1 < len(blocks):
                story += [NextPageTemplate("single"), PageBreak()]
    doc.build(story)
    return buffer.getvalue()


# ---- the registry -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class V1File:
    name: str
    fmt: str
    build: Callable[[], bytes]
    truth: Callable[[], str]
    tags: tuple[str, ...] = ()

    @property
    def path(self) -> str:
        return f"v1/{self.name}"


def _text(value: str) -> tuple[Callable[[], bytes], Callable[[], str]]:
    return (lambda: value.encode("utf-8")), (lambda: value)


def _doc(
    name: str, fmt: str, blocks: Callable[[], Blocks], title: str, tags: tuple[str, ...]
) -> V1File:
    if fmt == "docx":
        return V1File(
            name, fmt, lambda: build_docx(blocks(), title), lambda: blocks_text(blocks()), tags
        )
    header = f"{content.COMPANY.upper()} - {title.upper()}"
    return V1File(
        name,
        fmt,
        lambda: build_pdf(blocks(), title, header),
        lambda: blocks_text(blocks()),
        tags,
    )


def _deck(name: str, slides: tuple[Slide, ...], title: str, tags: tuple[str, ...]) -> V1File:
    return V1File(name, "pptx", lambda: build_deck(slides, title), lambda: deck_text(slides), tags)


def _book(name: str, sheets: Callable[[], list[content.Sheet]], tags: tuple[str, ...]) -> V1File:
    return V1File(name, "xlsx", lambda: build_xlsx(sheets()), lambda: sheets_text(sheets()), tags)


def _plain(name: str, fmt: str, value: Callable[[], str], tags: tuple[str, ...]) -> V1File:
    return V1File(name, fmt, lambda: value().encode("utf-8"), value, tags)


FILES: tuple[V1File, ...] = (
    _doc(
        "driver_handbook.docx",
        "docx",
        content.driver_handbook,
        "Driver handbook",
        ("long", "same_name:Sam Kerrigan", "bullets", "table"),
    ),
    _doc(
        "customs_and_border_guide.docx",
        "docx",
        content.customs_guide,
        "Customs and border guide",
        ("long", "table"),
    ),
    _doc(
        "depot_safety_procedures.docx",
        "docx",
        content.safety_procedures,
        "Depot safety procedures",
        ("injection:reveal", "bullets", "table"),
    ),
    _book(
        "fleet_register.xlsx",
        content.fleet_sheets,
        ("multi_sheet", "header_not_row_one", "numeric_columns", "same_name:Pioneer"),
    ),
    _book(
        "tariff_2026.xlsx",
        content.tariff_sheets,
        ("multi_sheet", "cached_formulas", "supersedes:v1/tariff_2025.csv", "same_name:Pioneer"),
    ),
    _book(
        "fuel_and_toll_costs_q3.xlsx",
        content.fuel_sheets,
        ("multi_sheet", "numeric_columns", "injection:fake_source"),
    ),
    _deck(
        "depot_induction.pptx",
        content.INDUCTION_SLIDES,
        "Depot induction",
        ("short_deck", "notes", "textbox"),
    ),
    _deck(
        "quarterly_ops_review.pptx",
        content.OPS_SLIDES,
        "Q3 2026 operations review",
        ("long_deck", "notes", "textbox", "table", "injection:ignore_rules"),
    ),
    _deck(
        "network_expansion_plan.pptx",
        content.EXPANSION_SLIDES,
        "Network expansion plan",
        ("mid_deck", "notes", "textbox", "table"),
    ),
    _doc(
        "cold_chain_operations_manual.pdf",
        "pdf",
        content.cold_chain_manual,
        "Cold chain operations manual",
        ("long", "multi_page", "ruled_table"),
    ),
    _doc(
        "marrowdale_annual_report_2025.pdf",
        "pdf",
        content.annual_report,
        "Annual report 2025",
        ("long", "multi_page", "two_columns", "borderless_table", "ruled_table"),
    ),
    _doc(
        "member_newsletter_autumn_2026.pdf",
        "pdf",
        content.newsletter,
        "Member newsletter Autumn 2026",
        ("two_columns", "injection:redirect_user"),
    ),
    _plain(
        "fleet_maintenance_policy_v1.md",
        "md",
        lambda: content.maintenance_policy(1),
        ("superseded_by:v1/fleet_maintenance_policy_v2.md",),
    ),
    _plain(
        "fleet_maintenance_policy_v2.md",
        "md",
        lambda: content.maintenance_policy(2),
        ("supersedes:v1/fleet_maintenance_policy_v1.md",),
    ),
    _plain("depot_systems_runbook.md", "md", content.runbook, ("long", "code_blocks")),
    _plain(
        "tariff_2025.csv",
        "csv",
        content.tariff_2025_csv,
        ("superseded_by:v1/tariff_2026.xlsx", "same_name:Pioneer"),
    ),
    _plain("incident_log_2026.csv", "csv", content.incident_log_csv, ("numeric_columns",)),
    _plain(
        "customer_accounts.csv", "csv", content.customer_accounts_csv, ("same_name:Sam Kerrigan",)
    ),
    _plain("cooperative_bylaws.txt", "txt", content.bylaws, ("long",)),
)
BY_PATH = {f.path: f for f in FILES}
MIME_BY_FORMAT = {
    "docx": DOCX_MIME,
    "pptx": PPTX_MIME,
    "xlsx": XLSX_MIME,
    "pdf": "application/pdf",
    "md": "text/markdown",
    "csv": "text/csv",
    "txt": "text/plain",
}


def google_names() -> list[str]:
    return sorted(content.GOOGLE_SOURCES)


# ---- text access and digests ------------------------------------------------------------------------------


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chunk_count(text: str) -> int:
    from app.ingestion.chunking import chunk_text

    return len(chunk_text(text))


def extract_file(path: str, root: Path = CORPUS_DIR) -> str:
    """Text of one corpus file exactly as the product's own reader returns it, read from ``root``."""
    from app.ingestion.extractors.bootstrap import register_builtin_extractors
    from app.ingestion.extractors.registry import get_extractor

    from .corpus import MIME

    register_builtin_extractors()
    mime = MIME[Path(path).suffix.lower()]
    return (
        get_extractor(mime)
        .extract((root / path).read_bytes(), mime_type=mime, filename=Path(path).name)
        .text
    )


def extract_all(root: Path = CORPUS_DIR, paths: list[str] | None = None) -> dict[str, str]:
    """Text of every manifest file as the product's readers return it."""
    chosen = paths if paths is not None else [e["path"] for e in _entries_on_disk(root)]
    return {path: extract_file(path, root) for path in chosen}


def derived_canaries(text: str, count: int = MIN_CANARIES) -> list[str]:
    """Three distinctive tokens (digits first, then long words) from the *independent* source text.

    Used for the older files, whose facts were not written with canaries in mind. The rule is fixed, so
    the choice is reproducible; it only has to find strings the reader must keep.
    """
    tokens = [t.strip(".,;:()|*#`\"'") for t in re.split(r"\s+", text)]
    with_digit = sorted(
        {t for t in tokens if len(t) >= 5 and any(c.isdigit() for c in t)},
        key=lambda t: (-len(t), t),
    )
    words = sorted({t for t in tokens if len(t) >= 9 and t.isalpha()}, key=lambda t: (-len(t), t))
    return (with_digit + words)[:count]


# ---- manifest ---------------------------------------------------------------------------------------------


def _fmt(path: str) -> str:
    return Path(path).suffix.lstrip(".").lower()


def _entries_on_disk(root: Path = CORPUS_DIR) -> list[dict[str, Any]]:
    """Minimal entries (path, group) of every committed corpus file, for text extraction."""
    entries: list[dict[str, Any]] = [
        {"path": f.path, "group": "synthetic"} for f in synthetic_files()
    ]
    entries += [{"path": f"messy/{n}", "group": "messy"} for n in sorted(manifest_entries())]
    entries += [{"path": f.path, "group": "v1"} for f in FILES]
    entries += [
        {"path": name, "group": "google"} for name in google_names() if (root / name).exists()
    ]
    return entries


def corpus_version(files: list[dict[str, Any]], public_manifest_sha: str) -> str:
    lines = sorted(f"{f['path']}\t{f['sha256']}" for f in files)
    lines.append(f"public\t{public_manifest_sha}")
    return "m1-corpus-v1-" + hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]


def _previous_google_status() -> str:
    if MANIFEST.exists():
        return str(
            json.loads(MANIFEST.read_text()).get("google_exports", {}).get("status", "pending")
        )
    return "pending"


def build_manifest(*, root: Path = CORPUS_DIR, google_status: str | None = None) -> dict[str, Any]:
    present = [n for n in google_names() if (root / n).exists()]
    if present and len(present) != len(google_names()):
        raise ValueError(f"Google exports must be all three or none; found {present}")
    texts = extract_all(root)
    entries: list[dict[str, Any]] = []
    for entry in _entries_on_disk(root):
        path, group = entry["path"], entry["group"]
        data = (root / path).read_bytes()
        text = texts[path]
        if group == "v1":
            canaries = list(content.CANARIES[path])
            tags = list(BY_PATH[path].tags)
            source, generator = "generated", GENERATOR_VERSION
        elif group == "google":
            canaries = list(content.GOOGLE_SOURCES[path][1])
            tags, source, generator = ["google_export"], "Google export", "n/a"
        else:
            independent = truth_text(Path(path).name) if group == "messy" else data.decode("utf-8")
            canaries = derived_canaries(independent)
            tags, source = ["canaries_derived"], "generated"
            generator = "messy_fixtures" if group == "messy" else "authored"
        entries.append(
            {
                "path": path,
                "kind": _fmt(path),
                "group": group,
                "source": source,
                "generator_version": generator,
                "sha256": hashlib.sha256(data).hexdigest(),
                "text_sha256": text_digest(text),
                "chars": len(text),
                "chunks": chunk_count(text),
                "canaries": canaries,
                "tags": tags,
            }
        )
    entries.sort(key=lambda e: e["path"])
    public_sha = sha256_file(CORPUS_DIR / "public_manifest.json")
    status = google_status or ("pinned" if present else _previous_google_status())
    if present:
        status = "pinned"
    elif status == "pinned":
        status = "pending"
    return {
        "schema_version": 1,
        "corpus_version": corpus_version(entries, public_sha),
        "generator_version": GENERATOR_VERSION,
        # ZIP-based files (DOCX, PPTX, XLSX) are compressed by zlib, whose output can differ between
        # builds. Rebuilding is only expected to reproduce the committed bytes where this matches.
        "built_with": {"zlib": zlib.ZLIB_VERSION},
        "public_manifest_sha256": public_sha,
        "google_exports": {"status": status, "expected": google_names()},
        "files": entries,
    }


# ---- validation (every check is deterministic and free) ---------------------------------------------------


def validate_manifest(
    manifest: Mapping[str, Any],
    *,
    root: Path = CORPUS_DIR,
    texts: Mapping[str, str] | None = None,
) -> list[str]:
    """Problems with the manifest and the files it describes (empty = valid). Never writes anything.

    ``texts`` replaces what the product's readers return, by path, so tests can feed a broken reader.
    """
    problems: list[str] = []
    files = list(manifest.get("files", []))
    paths = [f.get("path", "?") for f in files]
    problems += [f"duplicate path {p}" for p in sorted({p for p in paths if paths.count(p) > 1})]
    if manifest.get("google_exports", {}).get("status") not in GOOGLE_STATUS:
        problems.append("google_exports.status must be pending, pinned or declined")
    present: dict[str, str] = {}
    for f in files:
        path = f.get("path", "?")
        for key in ("kind", "group", "source", "generator_version", "sha256", "text_sha256"):
            if not f.get(key):
                problems.append(f"{path}: missing field {key}")
        if f.get("source") not in SOURCES:
            problems.append(f"{path}: unknown source {f.get('source')!r}")
        if f.get("group") not in GROUPS:
            problems.append(f"{path}: unknown group {f.get('group')!r}")
        absolute = root / path
        if not absolute.is_file():
            problems.append(f"{path}: file is missing")
            continue
        if sha256_file(absolute) != f.get("sha256"):
            problems.append(f"{path}: file does not match its recorded SHA-256")
            continue
        present[path] = f.get("group", "")
    for path in sorted(set(_entries_by_path(root)) - set(paths)):
        problems.append(f"{path}: file is in the corpus folders but not in the manifest")
    sums = [f for f in files if f.get("sha256")]
    expected = corpus_version(sums, str(manifest.get("public_manifest_sha256")))
    if manifest.get("corpus_version") != expected:
        problems.append(
            f"corpus_version is {manifest.get('corpus_version')!r}, files give {expected!r}"
        )
    if texts is None:
        texts = extract_all(root, list(present))
    for f in files:
        path = f.get("path", "?")
        if path not in present:
            continue
        text = texts.get(path, "")
        problems += _text_problems(f, text)
    return problems


def _entries_by_path(root: Path) -> list[str]:
    found = [p.relative_to(root).as_posix() for p in (root / "v1").glob("*") if p.is_file()]
    found += [p.relative_to(root).as_posix() for p in (root / "messy").glob("*") if p.is_file()]
    found += [p.relative_to(root).as_posix() for p in (root / "synthetic").glob("*") if p.is_file()]
    found += [p.relative_to(root).as_posix() for p in (root / "google").glob("*") if p.is_file()]
    return found


def _text_problems(entry: Mapping[str, Any], text: str) -> list[str]:
    path = entry["path"]
    problems: list[str] = []
    if not text.strip():
        return [f"{path}: the product's reader returned no text"]
    canaries = list(entry.get("canaries", []))
    if len(set(canaries)) < MIN_CANARIES:
        problems.append(f"{path}: needs at least {MIN_CANARIES} distinct canary strings")
    problems += [
        f"{path}: canary {c!r} not found in the extracted text"
        for c in canaries
        if not contains(text, c)
    ]
    if text_digest(text) != entry.get("text_sha256"):
        problems.append(
            f"{path}: extracted text changed since the manifest was written (a reader change?)"
        )
    if chunk_count(text) != entry.get("chunks"):
        problems.append(
            f"{path}: chunk count is {chunk_count(text)}, manifest has {entry.get('chunks')}"
        )
    tags = entry.get("tags", [])
    if "long" in tags and chunk_count(text) < MIN_LONG_CHUNKS:
        problems.append(f"{path}: long document has only {chunk_count(text)} chunk(s)")
    if "long_deck" in tags and chunk_count(text) < 2:
        problems.append(f"{path}: the longer deck must produce several chunks")
    if "short_deck" in tags and chunk_count(text) != 1:
        problems.append(f"{path}: the short deck must stay a single chunk")
    for tag in tags:
        if tag.startswith("injection:"):
            instruction = content.INJECTIONS.get(path)
            if instruction is None or instruction[0] != tag.split(":", 1)[1]:
                problems.append(f"{path}: injection tag has no matching instruction")
            elif " ".join(instruction[1].split()) not in " ".join(text.split()):
                problems.append(
                    f"{path}: embedded instruction is not verbatim in the extracted text"
                )
    return problems


def coverage_problems(manifest: Mapping[str, Any]) -> list[str]:
    """The ticket's required counts, checked on the manifest's tags and formats."""
    new = [f for f in manifest["files"] if f["group"] == "v1"]
    by_format: dict[str, int] = {}
    for f in new:
        by_format[f["kind"]] = by_format.get(f["kind"], 0) + 1
    required = {"docx": 3, "xlsx": 3, "pptx": 3, "pdf": 3, "md": 3, "csv": 3}
    problems = [
        f"needs {n} {k} files, has {by_format.get(k, 0)}"
        for k, n in required.items()
        if by_format.get(k, 0) < n
    ]
    tags = [t for f in new for t in f["tags"]]
    if sum(f["tags"].count("long") for f in new) < 6:
        problems.append("needs six long documents")
    if sum(t.startswith(("supersedes:", "superseded_by:")) for t in tags) < 4:
        problems.append("needs two superseded pairs")
    names = {t for t in tags if t.startswith("same_name:")}
    if len(names) < 2:
        problems.append("needs two same-name entities across files")
    injected = [f for f in new if any(t.startswith("injection:") for t in f["tags"])]
    kinds = {t for f in injected for t in f["tags"] if t.startswith("injection:")}
    if len(injected) < 3 or len({f["kind"] for f in injected}) < 2 or len(kinds) < 3:
        problems.append("needs three injection documents of different kinds in two formats")
    return problems


# ---- commands ---------------------------------------------------------------------------------------------


def write_all() -> dict[str, Any]:
    V1_DIR.mkdir(parents=True, exist_ok=True)
    for file in FILES:
        (V1_DIR / file.name).write_bytes(file.build())
    manifest = build_manifest()
    MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
    return manifest


def report(manifest: Mapping[str, Any]) -> str:
    rows = ["| path | kind | source | chars | chunks | tags |", "|---|---|---|---:|---:|---|"]
    for f in manifest["files"]:
        if f["group"] in {"v1", "google"}:
            rows.append(
                f"| {f['path']} | {f['kind']} | {f['source']} | {f['chars']:,} | {f['chunks']} | "
                f"{', '.join(f['tags'])} |"
            )
    return "\n".join(rows)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--google", choices=sorted(GOOGLE_STATUS))
    args = parser.parse_args()
    if args.google:
        manifest = build_manifest(google_status=args.google)
        MANIFEST.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n")
        print(f"google_exports.status = {manifest['google_exports']['status']}")
        return
    if args.write:
        manifest = write_all()
        print(f"{manifest['corpus_version']}: {len(manifest['files'])} files")
        return
    manifest = json.loads(MANIFEST.read_text())
    if args.report:
        print(report(manifest))
        return
    problems = validate_manifest(manifest) + coverage_problems(manifest)
    for file in FILES:
        if file.build() != (V1_DIR / file.name).read_bytes():
            problems.append(
                f"{file.path}: rebuilding gives different bytes than the committed file"
            )
    if problems:
        sys.exit("\n".join(problems))
    print(f"{manifest['corpus_version']}: {len(manifest['files'])} files, all checks pass")


if __name__ == "__main__":
    main()
