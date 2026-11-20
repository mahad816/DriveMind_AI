"""Deterministic test documents with tables, slides, notes, sheets and page furniture.

    python -m evaluation.rag_eval.messy_fixtures            # (re)write evaluation/corpus/messy/
    python -m evaluation.rag_eval.messy_fixtures --check    # regenerate in memory and compare bytes

The company-style synthetic corpus is all plain ``.txt``, so file readers for DOCX, PPTX, XLSX and
PDF tables were never exercised. These five files are in the same Larkspur Systems story, with
new facts that do not contradict the existing files:

* ``customer_rollout_plan.docx``  headings, bullets, two tables, a paragraph after a table
* ``board_update_q3.pptx``        titles, bullets, a table, a free text box and **speaker notes**
* ``sales_2026.xlsx``             two sheets (orders, targets)
* ``invoice_0457.pdf``            two pages, running header and footer, ruled tables
* ``annual_report_2025.pdf``      six pages, running header and page numbers, a borderless table,
                                  a ruled table and a two-column page

Each file is built from a plain description of its content in this module. The same description is the
independent **ground truth** (``truth_text``): it is used to check the question set without trusting
the product's readers, and to check what a reader returns. Output is byte-for-byte reproducible
(fixed dates, fixed zip timestamps, ReportLab ``invariant``).
"""

import argparse
import hashlib
import io
import json
import re
import sys
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    FrameBreak,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

MESSY_DIR = Path(__file__).resolve().parents[1] / "corpus" / "messy"
MANIFEST = Path(__file__).resolve().parents[1] / "corpus" / "messy_manifest.json"
STAMP = datetime(2026, 10, 1, 9, 0, 0)  # every embedded date
ZIP_STAMP = (2026, 10, 1, 9, 0, 0)

Row = tuple[str, ...]


@dataclass(frozen=True)
class Table_:
    header: Row
    rows: tuple[Row, ...]


# ---- content: the single description each file is built from --------------------------------------

ROLLOUT_PACKAGES = Table_(
    ("Package", "Clinics", "Setup fee (USD)", "Go-live (weeks)"),
    (
        ("Pilot", "1", "1,200", "2"),
        ("Regional", "5", "4,500", "4"),
        ("Network", "20", "14,000", "8"),
    ),
)
ROLLOUT_OWNERS = Table_(
    ("Task", "Owner", "Due"),
    (
        ("Data import from the old system", "Priya Nair", "Week 1"),
        ("Calendar configuration", "Marcus Webb", "Week 2"),
        ("Staff training", "Nadia Rahman", "Week 3"),
    ),
)
# (kind, payload): h1/h2 = heading text, p = paragraph, bullets = list of strings, table = Table_
ROLLOUT_DOC: tuple[tuple[str, object], ...] = (
    ("h1", "Customer rollout packages"),
    (
        "p",
        "This plan describes how Larkspur Systems rolls out the scheduler to new clinic customers.",
    ),
    ("h2", "Packages"),
    ("table", ROLLOUT_PACKAGES),
    ("p", "Setup fees are invoiced once, at contract signature."),
    ("h2", "Training"),
    (
        "bullets",
        [
            "Each training session lasts 90 minutes.",
            "Sessions are held on Wednesdays.",
            "The Pilot package includes 2 sessions, the Regional package 4 sessions "
            "and the Network package 1 session per clinic.",
        ],
    ),
    ("h2", "Responsibilities"),
    ("table", ROLLOUT_OWNERS),
)


@dataclass(frozen=True)
class Slide:
    title: str
    bullets: tuple[str, ...] = ()
    table: Table_ | None = None
    textbox: str | None = None
    notes: str | None = None


BOARD_SLIDES: tuple[Slide, ...] = (
    Slide("Q3 2026 Board Update", bullets=("Prepared by Elena Costa, CEO",)),
    Slide(
        "Highlights",
        bullets=(
            "Signed 6 new clinics in Q3",
            "Support tickets closed: 412",
            "Demo requests received: 87",
        ),
    ),
    Slide(
        "Pipeline by region",
        table=Table_(
            ("Region", "Clinics signed", "Pipeline (USD)"),
            (
                ("Portugal", "4", "38,000"),
                ("Spain", "2", "21,500"),
                ("Germany", "0", "12,000"),
            ),
        ),
    ),
    Slide(
        "Decisions",
        bullets=("Second QA engineer", "Support rota review"),
        textbox="Next board review: January 2027",
        notes=(
            "Board decision (14 October 2026): approve hiring a second QA engineer in Q4 "
            "with a budget of 55,000 USD."
        ),
    ),
)

ORDERS = Table_(
    ("Order ID", "Clinic", "Region", "Amount (USD)", "Status"),
    (
        ("SO-101", "Clinica Sao Bento", "Portugal", "4500", "Delivered"),
        ("SO-102", "Clinica Mira", "Portugal", "1200", "Delivered"),
        ("SO-103", "Madrid Salud", "Spain", "4500", "Pending"),
        ("SO-104", "Sevilla Medica", "Spain", "14000", "Delivered"),
        ("SO-105", "Porto Care", "Portugal", "1200", "Pending"),
        ("SO-106", "Berlin Praxis", "Germany", "4500", "Cancelled"),
        ("SO-107", "Lisbon Dental", "Portugal", "14000", "Delivered"),
        ("SO-108", "Valencia Clinic", "Spain", "1200", "Delivered"),
    ),
)
TARGETS = Table_(
    ("Region", "2026 target (USD)"),
    (("Portugal", "60000"), ("Spain", "45000"), ("Germany", "20000")),
)
SALES_SHEETS: tuple[tuple[str, Table_], ...] = (("Orders", ORDERS), ("Targets", TARGETS))

INVOICE_HEADER = "Larkspur Systems | Invoice INV-0457"
INVOICE_ITEMS = Table_(
    ("Description", "Qty", "Unit price (USD)", "Amount (USD)"),
    (
        ("Regional rollout package", "1", "4,500.00", "4,500.00"),
        ("Extra training session", "2", "350.00", "700.00"),
        ("SMS bundle (1,000 messages)", "3", "40.00", "120.00"),
    ),
)
INVOICE_TOTALS = Table_(
    ("Summary", "Amount (USD)"),
    (("Subtotal", "5,320.00"), ("VAT (23%)", "1,223.60"), ("Total due", "6,543.60")),
)
INVOICE_PAGE1 = (
    ("h1", "Invoice INV-0457"),
    ("p", "Billed to: Clinica Sao Bento"),
    ("p", "Issue date: 12 October 2026"),
    ("table", INVOICE_ITEMS),
    ("table", INVOICE_TOTALS),
)
INVOICE_PAGE2 = (
    ("h1", "Payment terms"),
    ("p", "Payment is due within 30 days of the issue date."),
    ("p", "Late payments incur a fee of 1.5 percent per month."),
    ("p", "Quote reference INV-0457 on every bank transfer."),
)

REPORT_HEADER = "LARKSPUR SYSTEMS - ANNUAL REPORT 2025"
FINANCIALS = Table_(
    ("Metric", "2024", "2025"),
    (
        ("Revenue (USD)", "1,210,000", "1,840,000"),
        ("Operating costs (USD)", "1,150,000", "1,520,000"),
        ("Clinics served at year end", "38", "61"),
    ),
)
CLINICS_BY_COUNTRY = Table_(
    ("Country", "Clinics 2024", "Clinics 2025"),
    (("Portugal", "24", "36"), ("Spain", "10", "17"), ("Germany", "4", "8")),
)
OPS_LEFT = (
    "Support",
    "The support team answered 91 percent of tickets within 4 hours in 2025.",
)
OPS_RIGHT = (
    "Reliability",
    "There were 6 planned maintenance windows in 2025, each under 30 minutes.",
)
# one entry per page: list of (kind, payload); "columns" marks the two-column page
REPORT_PAGES: tuple[tuple[tuple[str, object], ...], ...] = (
    (
        ("h1", "Annual report 2025"),
        (
            "p",
            "Dear shareholders, 2025 was a year of steady growth. Larkspur ended the year with "
            "11 employees and 61 clinics as customers.",
        ),
    ),
    (
        ("h1", "Financial summary"),
        ("table_plain", FINANCIALS),
        ("p", "All amounts are in US dollars and are unaudited."),
    ),
    (("h1", "Customers by country"), ("table", CLINICS_BY_COUNTRY)),
    (("h1", "Operations review"), ("columns", (OPS_LEFT, OPS_RIGHT))),
    (("h1", "Outlook"), ("p", "In 2026 we will keep growth steady and focus on reliability.")),
    (
        ("h1", "About this report"),
        ("p", "This report covers the period 1 January to 31 December 2025."),
    ),
)


# ---- ground truth ------------------------------------------------------------------------------------


def _table_lines(table: Table_) -> list[str]:
    return [" | ".join(row) for row in (table.header, *table.rows)]


def _blocks_text(blocks: tuple[tuple[str, object], ...]) -> list[str]:
    lines: list[str] = []
    for kind, payload in blocks:
        if kind in {"h1", "h2", "p"}:
            lines.append(str(payload))
        elif kind == "bullets":
            lines += list(payload)  # type: ignore[call-overload]
        elif kind in {"table", "table_plain"}:
            lines += _table_lines(payload)  # type: ignore[arg-type]
        elif kind == "columns":
            for heading, body in payload:  # type: ignore[attr-defined]
                lines += [heading, body]
    return lines


def truth_text(name: str) -> str:
    """Everything a person reading the file would see, from the content description only.

    Running headers, footers and page numbers are page furniture, not content, so they are absent.
    """
    if name == "customer_rollout_plan.docx":
        lines = _blocks_text(ROLLOUT_DOC)
    elif name == "board_update_q3.pptx":
        lines = []
        for slide in BOARD_SLIDES:
            lines += [slide.title, *slide.bullets]
            if slide.table:
                lines += _table_lines(slide.table)
            if slide.textbox:
                lines.append(slide.textbox)
            if slide.notes:
                lines.append(slide.notes)
    elif name == "sales_2026.xlsx":
        lines = []
        for sheet, table in SALES_SHEETS:
            lines += [sheet, *_table_lines(table)]
    elif name == "invoice_0457.pdf":
        lines = _blocks_text(INVOICE_PAGE1) + _blocks_text(INVOICE_PAGE2)
    elif name == "annual_report_2025.pdf":
        lines = [line for page in REPORT_PAGES for line in _blocks_text(page)]
    else:
        raise KeyError(name)
    return "\n".join(lines)


# ---- deterministic builders -----------------------------------------------------------------------------


_MODIFIED = re.compile(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)")


def _fixed_zip(data: bytes) -> bytes:
    """Rewrite a zip container so the bytes do not depend on the clock.

    Entry timestamps are fixed, and the document's "modified" date is pinned: openpyxl overwrites it
    with the current time on every save.
    """
    stamp = STAMP.strftime("%Y-%m-%dT%H:%M:%SZ").encode()
    out = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(data)) as source,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target,
    ):
        for info in source.infolist():
            clone = zipfile.ZipInfo(info.filename, date_time=ZIP_STAMP)
            clone.compress_type = zipfile.ZIP_DEFLATED
            clone.external_attr = info.external_attr
            content = source.read(info.filename)
            if info.filename == "docProps/core.xml":
                content = _MODIFIED.sub(rb"\g<1>" + stamp + rb"\g<2>", content)
            target.writestr(clone, content)
    return out.getvalue()


def build_docx() -> bytes:
    doc = Document()
    props = doc.core_properties
    props.author = props.last_modified_by = "Larkspur Systems"
    props.created = props.modified = STAMP
    props.title = "Customer rollout packages"
    for kind, payload in ROLLOUT_DOC:
        if kind in {"h1", "h2"}:
            doc.add_heading(str(payload), level=1 if kind == "h1" else 2)
        elif kind == "p":
            doc.add_paragraph(str(payload))
        elif kind == "bullets":
            for item in payload:  # type: ignore[attr-defined]
                doc.add_paragraph(item, style="List Bullet")
        elif kind == "table":
            table: Table_ = payload  # type: ignore[assignment]
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


def build_pptx() -> bytes:
    prs = Presentation()
    prs.core_properties.author = prs.core_properties.last_modified_by = "Larkspur Systems"
    prs.core_properties.created = prs.core_properties.modified = STAMP
    prs.core_properties.title = "Q3 2026 Board Update"
    for index, spec in enumerate(BOARD_SLIDES):
        if index == 0:
            slide = prs.slides.add_slide(prs.slide_layouts[0])
            slide.shapes.title.text = spec.title  # type: ignore[union-attr]
            slide.placeholders[1].text_frame.text = spec.bullets[0]  # type: ignore[attr-defined]
        elif spec.table:
            slide = prs.slides.add_slide(prs.slide_layouts[5])  # title only
            slide.shapes.title.text = spec.title  # type: ignore[union-attr]
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
            slide = prs.slides.add_slide(prs.slide_layouts[1])  # title and content
            slide.shapes.title.text = spec.title  # type: ignore[union-attr]
            frame = slide.placeholders[1].text_frame  # type: ignore[attr-defined]
            frame.text = spec.bullets[0]
            for bullet in spec.bullets[1:]:
                frame.add_paragraph().text = bullet
        if spec.textbox:
            box = slide.shapes.add_textbox(Inches(0.7), Inches(5.8), Inches(8.0), Inches(0.6))
            box.text_frame.text = spec.textbox
        if spec.notes:
            slide.notes_slide.notes_text_frame.text = spec.notes  # type: ignore[union-attr]
    buffer = io.BytesIO()
    prs.save(buffer)
    return _fixed_zip(buffer.getvalue())


def build_xlsx() -> bytes:
    workbook = Workbook()
    workbook.properties.creator = workbook.properties.lastModifiedBy = "Larkspur Systems"
    workbook.properties.created = workbook.properties.modified = STAMP
    workbook.remove(workbook.active)  # type: ignore[arg-type]
    for name, table in SALES_SHEETS:
        sheet = workbook.create_sheet(name)
        sheet.append(list(table.header))
        for row in table.rows:
            sheet.append([int(v) if v.isdigit() else v for v in row])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return _fixed_zip(buffer.getvalue())


def _styles() -> dict[str, ParagraphStyle]:
    sheet = getSampleStyleSheet()
    styles = {"h1": sheet["Heading1"], "p": sheet["BodyText"], "h2": sheet["Heading2"]}
    return {key: style for key, style in styles.items() if isinstance(style, ParagraphStyle)}


def _pdf_table(table: Table_, *, ruled: bool, widths: list[float] | None = None) -> Table:
    grid = Table([list(table.header), *map(list, table.rows)], colWidths=widths)
    style = [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 10)]
    if ruled:
        style += [
            ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ]
    grid.setStyle(TableStyle(style))
    return grid


def _flowables(blocks: tuple[tuple[str, object], ...]) -> list:
    styles = _styles()
    out: list = []
    for kind, payload in blocks:
        if kind in {"h1", "h2", "p"}:
            out += [Paragraph(str(payload), styles[kind]), Spacer(1, 6)]
        elif kind in {"table", "table_plain"}:
            out += [_pdf_table(payload, ruled=kind == "table"), Spacer(1, 14)]  # type: ignore[arg-type]
    return out


def _furniture(header: str, total: int | None) -> Callable:
    def draw(canvas, doc) -> None:  # noqa: ANN001
        canvas.saveState()
        canvas.setFont("Helvetica", 9)
        canvas.drawString(2 * cm, A4[1] - 1.2 * cm, header)
        number = canvas.getPageNumber()
        canvas.drawCentredString(
            A4[0] / 2, 1.0 * cm, f"Page {number} of {total}" if total else str(number)
        )
        canvas.restoreState()

    return draw


def build_invoice_pdf() -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, invariant=1, title="Invoice INV-0457")
    story = _flowables(INVOICE_PAGE1) + [PageBreak()] + _flowables(INVOICE_PAGE2)
    furniture = _furniture(INVOICE_HEADER, total=2)
    doc.build(story, onFirstPage=furniture, onLaterPages=furniture)
    return buffer.getvalue()


def build_report_pdf() -> bytes:
    buffer = io.BytesIO()
    doc = BaseDocTemplate(buffer, pagesize=A4, invariant=1, title="Annual report 2025")
    width, height = A4
    margin = 2 * cm
    full = Frame(margin, margin, width - 2 * margin, height - 2 * margin - 0.5 * cm, id="full")
    half = (width - 2 * margin - 1 * cm) / 2
    left = Frame(margin, margin, half, height - 2 * margin - 0.5 * cm, id="left")
    right = Frame(margin + half + 1 * cm, margin, half, height - 2 * margin - 0.5 * cm, id="right")
    furniture = _furniture(REPORT_HEADER, total=None)
    doc.addPageTemplates(
        [
            PageTemplate(id="single", frames=[full], onPage=furniture),
            PageTemplate(id="double", frames=[left, right], onPage=furniture),
        ]
    )
    styles = _styles()
    story: list = []
    for index, page in enumerate(REPORT_PAGES):
        columns = next((payload for kind, payload in page if kind == "columns"), None)
        if columns is not None:
            # Two-column page: heading and left column fill the left frame, then the right column.
            (left_head, left_body), (right_head, right_body) = columns  # type: ignore[misc]
            if index:
                story += [NextPageTemplate("double"), PageBreak()]
            story += [
                Paragraph(str(page[0][1]), styles["h1"]),
                Paragraph(left_head, styles["h2"]),
                Paragraph(left_body, styles["p"]),
                FrameBreak(),
                Paragraph(right_head, styles["h2"]),
                Paragraph(right_body, styles["p"]),
                NextPageTemplate("single"),
            ]
        else:
            if index:
                story.append(PageBreak())
            story += _flowables(page)
    doc.build(story)
    return buffer.getvalue()


@dataclass(frozen=True)
class Fixture:
    name: str
    mime_type: str
    build: Callable[[], bytes]
    summary: str = field(default="")


FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        "customer_rollout_plan.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        build_docx,
    ),
    Fixture(
        "board_update_q3.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        build_pptx,
    ),
    Fixture(
        "sales_2026.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        build_xlsx,
    ),
    Fixture("invoice_0457.pdf", "application/pdf", build_invoice_pdf),
    Fixture("annual_report_2025.pdf", "application/pdf", build_report_pdf),
)


def manifest_entries(directory: Path = MESSY_DIR) -> dict[str, str]:
    return {f.name: hashlib.sha256((directory / f.name).read_bytes()).hexdigest() for f in FIXTURES}


def write_all(directory: Path = MESSY_DIR) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    for fixture in FIXTURES:
        (directory / fixture.name).write_bytes(fixture.build())
    return manifest_entries(directory)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="regenerate in memory and compare")
    args = parser.parse_args()
    if args.check:
        recorded = json.loads(MANIFEST.read_text())["files"]
        problems = []
        for fixture in FIXTURES:
            digest = hashlib.sha256(fixture.build()).hexdigest()
            committed = hashlib.sha256((MESSY_DIR / fixture.name).read_bytes()).hexdigest()
            if not digest == committed == recorded.get(fixture.name):
                problems.append(fixture.name)
        if problems:
            sys.exit("differs from the committed files: " + ", ".join(problems))
        print("all fixtures reproduce byte for byte")
        return
    entries = write_all()
    MANIFEST.write_text(json.dumps({"files": entries}, indent=1) + "\n")
    for name, digest in entries.items():
        print(f"{name}  {digest[:12]}")


if __name__ == "__main__":
    main()
