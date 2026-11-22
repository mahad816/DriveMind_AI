"""The v1 corpus files must be exactly what their content description says (free, no product readers).

These tests read the generated files back with the plain libraries (python-docx, python-pptx,
openpyxl, pypdf) and compare them with the descriptions in ``corpus_v1_content``, which are the
ground truth for the questions written later. Whether the *product* reads the files well is tested in
``test_corpus_v1_extraction.py``.
"""

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import zipfile
import zlib
from pathlib import Path
from typing import Any, cast

import pytest
from docx import Document
from openpyxl import load_workbook
from pptx import Presentation
from pypdf import PdfReader

from evaluation.rag_eval import corpus_v1 as c
from evaluation.rag_eval import corpus_v1_content as k
from evaluation.rag_eval.corpus import CORPUS_DIR
from evaluation.rag_eval.text import contains

BACKEND = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((CORPUS_DIR / "v1_manifest.json").read_text())
ENTRY = {f["path"]: f for f in MANIFEST["files"]}
NEW = [f for f in c.FILES]


def number(text: str) -> int:
    return int(text.replace(",", ""))


def plain_read(path: str) -> str:
    """The file's text through the plain libraries, never through the product's readers."""
    data = (CORPUS_DIR / path).read_bytes()
    suffix = Path(path).suffix
    if suffix == ".docx":
        doc = Document(io.BytesIO(data))
        cells = [cell.text for t in doc.tables for row in t.rows for cell in row.cells]
        return "\n".join([p.text for p in doc.paragraphs] + cells)
    if suffix == ".pptx":
        parts: list[str] = []
        for slide in Presentation(io.BytesIO(data)).slides:
            for item in slide.shapes:
                shape: Any = item  # python-pptx's base shape type hides these attributes
                if shape.has_text_frame:
                    parts.append(shape.text_frame.text)
                if getattr(shape, "has_table", False) and shape.has_table:
                    parts += [cell.text for row in shape.table.rows for cell in row.cells]
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                parts.append(slide.notes_slide.notes_text_frame.text)
        return "\n".join(parts)
    if suffix == ".xlsx":
        book = load_workbook(io.BytesIO(data), data_only=True)
        return "\n".join(
            str(v)
            for sheet in book
            for row in sheet.iter_rows(values_only=True)
            for v in row
            if v is not None
        )
    if suffix == ".pdf":
        return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)
    return data.decode("utf-8")


# ---- determinism --------------------------------------------------------------------------------------------


def test_every_file_builds_identically_even_after_the_clock_moves():
    first = {f.path: f.build() for f in NEW}
    time.sleep(1.1)  # a library that writes "now" into a file shows up as a different second
    assert {f.path: f.build() for f in NEW} == first


SAME_ZLIB = zlib.ZLIB_VERSION == MANIFEST["built_with"]["zlib"]
needs_same_zlib = pytest.mark.skipif(
    not SAME_ZLIB,
    reason=f"zlib {zlib.ZLIB_VERSION} differs from the {MANIFEST['built_with']['zlib']} the corpus "
    "was written with, so compressed bytes may differ; run `python -m evaluation.rag_eval.corpus_v1 "
    "--check` on the author's machine",
)


def test_committed_files_match_the_manifest_checksums():
    for file in NEW:
        committed = (CORPUS_DIR / file.path).read_bytes()
        assert hashlib.sha256(committed).hexdigest() == ENTRY[file.path]["sha256"], file.path


@needs_same_zlib
def test_a_fresh_build_reproduces_the_committed_bytes():
    for file in NEW:
        assert file.build() == (CORPUS_DIR / file.path).read_bytes(), file.path


def _digests_with_hash_seed(seed: str) -> dict[str, str]:
    code = (
        "import hashlib, json\n"
        "from evaluation.rag_eval import corpus_v1 as c\n"
        "print(json.dumps({f.path: hashlib.sha256(f.build()).hexdigest() for f in c.FILES}))\n"
    )
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=BACKEND,
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


def test_output_does_not_depend_on_the_process_hash_seed():
    """Regression: the first draft drew random numbers in *set* order, so three files changed bytes
    from one run to the next. Two processes with different hash seeds must agree with the manifest."""
    first, second = _digests_with_hash_seed("1"), _digests_with_hash_seed("2")
    assert first == second
    if SAME_ZLIB:
        assert first == {f.path: ENTRY[f.path]["sha256"] for f in NEW}


# ---- scope: counts, formats and the situations the ticket lists ------------------------------------------------


def test_the_ticket_counts_are_met():
    assert c.coverage_problems(MANIFEST) == []
    by_format = {fmt: sum(f.fmt == fmt for f in NEW) for fmt in c.MIME_BY_FORMAT}
    assert by_format["docx"] >= 3 and by_format["xlsx"] >= 3 and by_format["pptx"] >= 3
    assert by_format["pdf"] >= 3 and by_format["md"] >= 3 and by_format["csv"] >= 3
    assert sum("long" in f.tags for f in NEW) == 6


def test_the_manifest_covers_the_whole_committed_corpus_and_names_a_version():
    groups = {g: sum(f["group"] == g for f in MANIFEST["files"]) for g in c.GROUPS}
    assert groups == {"synthetic": 22, "messy": 5, "v1": 19, "google": 3}
    assert MANIFEST["google_exports"]["status"] == "pinned"
    assert re.fullmatch(r"m1-corpus-v1-[0-9a-f]{12}", MANIFEST["corpus_version"])
    assert MANIFEST["generator_version"] == c.GENERATOR_VERSION
    assert all(len(f["canaries"]) >= 3 for f in MANIFEST["files"])
    assert {f["source"] for f in MANIFEST["files"]} == {"generated", "Google export"}
    assert {f["source"] for f in MANIFEST["files"] if f["group"] == "google"} == {"Google export"}


def test_every_canary_is_in_the_description_and_in_the_file_read_back_independently():
    for file in NEW:
        truth, plain = file.truth(), plain_read(file.path)
        for canary in k.CANARIES[file.path]:
            assert contains(truth, canary), (file.path, canary, "not in the description")
            assert contains(plain, canary), (file.path, canary, "not in the file")


def test_the_four_injection_documents_use_three_or_more_kinds_in_four_formats():
    assert {p: kind for p, (kind, _) in k.INJECTIONS.items()} == {
        "v1/depot_safety_procedures.docx": "reveal",
        "v1/quarterly_ops_review.pptx": "ignore_rules",
        "v1/fuel_and_toll_costs_q3.xlsx": "fake_source",
        "v1/member_newsletter_autumn_2026.pdf": "redirect_user",
    }
    for path, (_, instruction) in k.INJECTIONS.items():
        assert " ".join(instruction.split()) in " ".join(plain_read(path).split()) or contains(
            plain_read(path), instruction
        ), path
        assert path in ENTRY and f"injection:{k.INJECTIONS[path][0]}" in ENTRY[path]["tags"]


def test_the_short_deck_is_small_and_the_long_deck_has_the_notes_the_ticket_asks_for():
    short = c.deck_text(k.INDUCTION_SLIDES)
    long = c.deck_text(k.OPS_SLIDES)
    assert len(short) < 1000 < 3500 < len(long)
    prs = Presentation(io.BytesIO((CORPUS_DIR / "v1/quarterly_ops_review.pptx").read_bytes()))
    assert sum(s.has_notes_slide for s in prs.slides) >= 8


# ---- cached formulas, offset header, numbers --------------------------------------------------------------------


def test_formula_cells_carry_their_calculated_value_and_the_formula_text():
    path = CORPUS_DIR / "v1/tariff_2026.xlsx"
    values = load_workbook(path, data_only=True)["Routes"]
    formulas = load_workbook(path)["Routes"]
    for row in range(2, 8):
        km, rate, base = (float(cast("float", values.cell(row, col).value)) for col in (4, 5, 6))
        assert values.cell(row, 7).value == pytest.approx(km * rate + base, abs=0.005)
        assert formulas.cell(row, 7).value == f"=D{row}*E{row}+F{row}"
    grand = load_workbook(path, data_only=True)["Summary"]["B3"].value
    totals = [float(cast("float", values.cell(r, 7).value)) for r in range(2, 8)]
    assert grand == pytest.approx(sum(totals), abs=0.01)


def test_the_fleet_register_header_is_on_row_three_and_numbers_are_numbers():
    sheet = load_workbook(io.BytesIO((CORPUS_DIR / "v1/fleet_register.xlsx").read_bytes()))[
        "Vehicles"
    ]
    assert sheet["A1"].value.startswith("Marrowdale Freight Cooperative")
    assert [sheet.cell(2, col).value for col in range(1, 4)] == [None, None, None]
    assert sheet["A3"].value == "Vehicle ID" and sheet["F4"].value == 212_400
    assert load_workbook(
        io.BytesIO((CORPUS_DIR / "v1/fleet_register.xlsx").read_bytes())
    ).sheetnames == [
        "Vehicles",
        "Service log",
        "Depots",
    ]


# ---- the invented facts must agree with each other (otherwise later questions have two right answers) ----------


def test_the_annual_report_adds_up():
    quarters = {r[0]: [number(v) for v in r[1:]] for r in k.REPORT_QUARTERS.rows}
    revenue = number(k.REPORT_FINANCIALS.rows[0][2])
    costs = number(k.REPORT_FINANCIALS.rows[1][2])
    assert sum(sum(q) for q in quarters.values()) == revenue == 4_820_000
    assert revenue - costs == number(k.REPORT_FINANCIALS.rows[2][2])
    growing = [d for d, q in quarters.items() if all(b > a for a, b in zip(q, q[1:], strict=False))]
    assert growing == ["Tollbridge"]  # the report says so in a sentence
    totals = {
        key: sum(int(f[key]) for f in k.REPORT_FACTS.values())
        for key in ("staff", "drivers", "inc", "veh")
    }
    assert totals == {"staff": 214, "drivers": 131, "inc": 41, "veh": 63}
    assert sum(float(f["fuel"]) for f in k.REPORT_FACTS.values()) / 5 == pytest.approx(6.0)
    assert sum(f["green"] == "100" for f in k.REPORT_FACTS.values()) == 2


def test_the_ops_review_tables_bullets_and_log_agree():
    tonnes = sum(number(t) for t, _ in k.OPS_VOLUMES.values())
    assert tonnes == 41_800
    weighted = sum(number(t) * float(o) for t, o in k.OPS_VOLUMES.values()) / tonnes
    assert round(weighted, 1) == 96.1
    q3 = [row for row in k.INCIDENTS if "2026-07-01" <= row[1] <= "2026-09-30"]
    assert len(q3) == 3  # "Reportable incidents: 3"
    assert [row[0] for row in k.INCIDENTS] == [f"INC-2026-{n:03d}" for n in range(1, 13)]


def test_other_cross_file_numbers_agree():
    assert sum(number(r[1]) for r in k.EXPANSION_SLIDES[2].table.rows) == 2_400_000  # type: ignore[union-attr]
    parking = {r[0]: int(r[1]) for r in k.HANDBOOK_ALLOCATION.rows}
    assert parking == {name: bays for _, name, bays in k.DEPOT_ROWS}
    vehicles = k.fleet_sheets()[0][1][3:]
    per_depot = {d: sum(1 for v in vehicles if v[2] == d) for d in parking}
    depots_sheet = k.fleet_sheets()[2][1][1:]
    assert {row[1]: row[3] for row in depots_sheet} == per_depot
    assert all(cost == int(litres * 1.42) for *_, litres, cost in k.FUEL_ROWS)
    assert k.DEPOTS[3].manager == "Sam Kerrigan"


def test_the_superseded_pairs_really_conflict_and_say_which_is_current():
    v1, v2 = (plain_read(f"v1/fleet_maintenance_policy_v{n}.md") for n in (1, 2))
    assert "20,000 km" in v1 and "24,000 km" in v2 and "20,000 km" not in v2
    assert "supersedes version 1" in v2 and "supersedes" not in v1
    old = {r[0]: float(r[4]) for r in k.ROUTES_2025}
    new = {r[0]: float(r[4]) for r in k.ROUTES_2026}
    assert old.keys() == new.keys() and all(new[r] > old[r] for r in old)
    assert "Valid until" in plain_read("v1/tariff_2025.csv") and "Replaces" in plain_read(
        "v1/tariff_2026.xlsx"
    )


def test_the_two_same_name_cases_are_different_things():
    handbook, customers = (
        plain_read("v1/driver_handbook.docx"),
        plain_read("v1/customer_accounts.csv"),
    )
    assert "depot manager Sam Kerrigan" in handbook and "Fenwick Dairies,Sam Kerrigan" in customers
    assert "Sam Kerrigan" not in plain_read("v1/depot_systems_runbook.md")
    models = {v[1] for v in k.VEHICLES}
    assert "Pioneer 18" in models and any(r[0] == "Pioneer" for r in k.ROUTES_2026)
    assert "Northgate Cold Stores" in customers and any(d.name == "Northgate" for d in k.DEPOTS)


# ---- no private data, no real accounts ---------------------------------------------------------------------------

PATTERNS = {
    "email outside .example": re.compile(r"[\w.+-]+@(?![\w.-]*\.example\b)[\w-]+\.[\w.-]+"),
    "phone number": re.compile(
        r"\+\d[\d ()-]{7,}\d|\(\d{3}\)\s?\d{3}[- ]\d{4}|\b\d{3}[-. ]\d{3}[-. ]\d{4}\b"
    ),
    "web address": re.compile(r"https?://|\bwww\.", re.IGNORECASE),
    "api key or token": re.compile(
        r"sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{20,}|ghp_[A-Za-z0-9]{20,}"
    ),
    "credential assignment": re.compile(
        r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+"
    ),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
    "bank account": re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
    "card number": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "other company": re.compile(r"Larkspur|DostIQ|GIKI|mahad", re.IGNORECASE),
}


def scan(text: str) -> list[str]:
    return [name for name, pattern in PATTERNS.items() if pattern.search(text)]


def test_the_scanner_flags_each_kind_of_private_data():
    planted = {
        "email outside .example": "write to jo@gmail.com",
        "phone number": "call +44 20 7946 0958",
        "web address": "see https://drive.google.com/x",
        "api key or token": "sk-abcdefghijklmnop1234",
        "credential assignment": "password: hunter2",
        "private key": "-----BEGIN RSA PRIVATE KEY-----",
        "bank account": "GB29NWBK60161331926819",
        "card number": "4111 1111 1111 1111",
        "other company": "Larkspur Systems",
    }
    assert set(planted) == set(PATTERNS)
    for name, text in planted.items():
        assert name in scan(text), name
    assert scan("recovery-desk@marrowdale.example 212400 km 2026-01-09") == []


def test_no_fixture_or_source_text_carries_private_data():
    for file in NEW:
        assert scan(file.truth()) == [], file.path
        assert scan(plain_read(file.path)) == [], file.path
    for path, (_, _, text) in k.GOOGLE_SOURCES.items():
        assert scan(text) == [], path
        assert scan(plain_read(path)) == [], path  # the real export, read back
        archive = zipfile.ZipFile(CORPUS_DIR / path)
        for member in (m for m in archive.namelist() if m.startswith("docProps/")):
            properties = re.sub(r"<[^>]+>", " ", archive.read(member).decode())
            assert scan(properties) == [], (path, member)  # no author or e-mail in properties
    for file in NEW:  # document properties: author and title only the invented company
        data = (CORPUS_DIR / file.path).read_bytes()
        if file.fmt in {"docx", "pptx", "xlsx"}:
            core = zipfile.ZipFile(io.BytesIO(data)).read("docProps/core.xml").decode()
            values = re.sub(r"<[^>]+>", " ", core)  # the text of the properties, not the XML tags
            assert scan(values) == [] and k.COMPANY in values, file.path
