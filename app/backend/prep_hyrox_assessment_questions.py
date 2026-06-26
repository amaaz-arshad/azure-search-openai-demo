"""Generate ``approaches/chatbots/hyrox_assessment/questions.py`` from the L2 question bank.

Source of truth: ``hyrox-files/HYROX_L2_QuestionBank_Final.xlsx`` (master tab ``Module 1``,
which actually lists all 52 questions across the 13 modules M1..M10). The per-module tabs in
that workbook are superseded drafts and are intentionally ignored.

Run from the repo root with the backend venv (no third-party deps — uses only the stdlib, since
an ``.xlsx`` is a zip of XML)::

    python app/backend/prep_hyrox_assessment_questions.py
    python app/backend/prep_hyrox_assessment_questions.py path/to/QuestionBank.xlsx

It re-writes ``questions.py`` (data + helpers) in full, so the result is reproducible. The grader
scores one point per key point capped at ``max_pts``; this generator asserts ``len(key_points) ==
max_pts`` for every question and that each module's question points sum to the workbook's
"Max Modul points" column, failing loudly on any mismatch.
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_XLSX = REPO_ROOT / "hyrox-files" / "HYROX_L2_QuestionBank_Final.xlsx"
OUTPUT = Path(__file__).resolve().parent / "approaches" / "chatbots" / "hyrox_assessment" / "questions.py"
MASTER_SHEET = "Module 1"

# Column layout of the master tab (1-based): Q-ID, Question, Primary Answer, Alternative Answer,
# Key Points (Must Be Mentioned), Max Pts, Max Modul points.
COL_QID, COL_QUESTION, COL_PRIMARY, COL_ALT, COL_KEYPOINTS, COL_MAXPTS, COL_MODPTS = 1, 2, 3, 4, 5, 6, 7


def col_index(cell_ref: str) -> int:
    match = re.match(r"[A-Z]+", cell_ref or "")
    letters = match.group() if match else ""
    idx = 0
    for c in letters:
        idx = idx * 26 + (ord(c) - 64)
    return idx


def load_master_rows(xlsx_path: Path) -> list[dict[int, str]]:
    """Return the master sheet as a list of {col_index: value} dicts (data rows only)."""
    z = zipfile.ZipFile(xlsx_path)
    shared = ET.fromstring(z.read("xl/sharedStrings.xml"))
    strings = ["".join(t.text or "" for t in si.iter(f"{NS}t")) for si in shared.findall(f"{NS}si")]

    workbook = ET.fromstring(z.read("xl/workbook.xml"))
    name_to_rid = {s.get("name"): s.get(f"{REL_NS}id") for s in workbook.findall(f"{NS}sheets/{NS}sheet")}
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {r.get("Id"): r.get("Target") for r in rels}
    if MASTER_SHEET not in name_to_rid:
        raise SystemExit(f"Master sheet {MASTER_SHEET!r} not found; tabs are {list(name_to_rid)}")
    target = rid_to_target.get(name_to_rid[MASTER_SHEET]) or ""
    target = target if target.startswith("xl/") else "xl/" + target
    sheet = ET.fromstring(z.read(target))

    def cell_value(c: ET.Element) -> str:
        t = c.get("t")
        v = c.find(f"{NS}v")
        if t == "s":
            return strings[int(v.text)] if v is not None and v.text else ""
        if t == "inlineStr":
            is_ = c.find(f"{NS}is")
            return "".join(x.text or "" for x in is_.iter(f"{NS}t")) if is_ is not None else ""
        return v.text if v is not None and v.text else ""

    rows: list[dict[int, str]] = []
    sheet_data = sheet.find(f"{NS}sheetData")
    for row in sheet_data.findall(f"{NS}row") if sheet_data is not None else []:
        cells = {col_index(c.get("r") or ""): cell_value(c) for c in row.findall(f"{NS}c")}
        rows.append(cells)
    return rows


def parse_key_points(raw: str) -> list[str]:
    """Split the '• '-bulleted, newline-separated Key Points cell into a clean list."""
    out: list[str] = []
    for line in re.split(r"[\r\n]+", raw or ""):
        cleaned = line.strip().lstrip("••-–—").strip()
        if cleaned:
            out.append(cleaned)
    return out


def module_of_qid(qid: str) -> str:
    """'M7.1-Q03' -> 'M7.1'."""
    return qid.split("-", 1)[0].strip()


def build_questions(rows: list[dict[int, str]]) -> tuple[list[dict], list[str], dict[str, int]]:
    questions: list[dict] = []
    module_order: list[str] = []
    module_col_points: dict[str, int] = {}
    number = 0
    for cells in rows:
        qid = (cells.get(COL_QID) or "").strip()
        if not qid or qid == "Q-ID":
            continue
        number += 1
        module = module_of_qid(qid)
        if module not in module_order:
            module_order.append(module)
        key_points = parse_key_points(cells.get(COL_KEYPOINTS, ""))
        max_pts = int((cells.get(COL_MAXPTS) or "0").strip())
        if len(key_points) != max_pts:
            raise SystemExit(f"{qid}: {len(key_points)} key points but max_pts={max_pts} (must be equal)")
        mod_pts_raw = (cells.get(COL_MODPTS) or "").strip()
        if mod_pts_raw:
            module_col_points[module] = int(mod_pts_raw)
        questions.append(
            {
                "number": number,
                "module": module,
                "qid": qid,
                "question": (cells.get(COL_QUESTION) or "").strip(),
                "primary_answer": (cells.get(COL_PRIMARY) or "").strip(),
                "alternative_answer": (cells.get(COL_ALT) or "").strip(),
                "key_points": key_points,
                "max_pts": max_pts,
            }
        )
    # Verify each module's question points sum to the workbook's "Max Modul points" column.
    for module in module_order:
        summed = sum(q["max_pts"] for q in questions if q["module"] == module)
        declared = module_col_points.get(module)
        if declared is not None and declared != summed:
            raise SystemExit(f"{module}: question points sum to {summed} but column says {declared}")
    return questions, module_order, module_col_points


def render_questions_py(questions: list[dict], module_order: list[str]) -> str:
    lines: list[str] = []
    lines.append(HEADER)
    lines.append("QUESTIONS: list[AssessmentQuestion] = [")
    for q in questions:
        lines.append("    {")
        lines.append(f'        "number": {q["number"]},')
        lines.append(f'        "module": {q["module"]!r},')
        lines.append(f'        "qid": {q["qid"]!r},')
        lines.append(f'        "question": {q["question"]!r},')
        lines.append(f'        "primary_answer": {q["primary_answer"]!r},')
        lines.append(f'        "alternative_answer": {q["alternative_answer"]!r},')
        lines.append('        "key_points": [')
        for kp in q["key_points"]:
            lines.append(f"            {kp!r},")
        lines.append("        ],")
        lines.append(f'        "max_pts": {q["max_pts"]},')
        lines.append("    },")
    lines.append("]")
    lines.append("")
    lines.append("# Module keys in fixed assessment order (M1..M10, with M7 split into 7.1-7.4).")
    lines.append("MODULES: list[str] = [")
    for m in module_order:
        lines.append(f"    {m!r},")
    lines.append("]")
    lines.append("")
    lines.append(FOOTER)
    return "\n".join(lines) + "\n"


HEADER = '''"""HYROX Level 2 "Managing Performance" Coach Assessment — question bank.

AUTO-GENERATED by ``app/backend/prep_hyrox_assessment_questions.py`` from
``hyrox-files/HYROX_L2_QuestionBank_Final.xlsx`` (master tab "Module 1"). Do not edit by hand —
re-run the generator. This is the single source of truth for the assessment rubric and is compiled
into the system prompt at import time by sampleprompt.py, so the grader always has the exact rubric
for the asked question on every (stateless) turn. Do NOT index this into Azure Search.

The 52 questions are grouped into 13 modules (M1..M6, M7.1..M7.4, M8..M10), asked in order. Each
module is scored separately at an 80% threshold; the per-key-point verdict drives scoring (one point
per key point, capped at ``max_pts``; ``len(key_points) == max_pts`` for every question).

Each question dict:
  number              int    1..52, fixed module/ask order; the id used in [[SCORE]]/[[ASKED]] markers
  module              str    module key, e.g. "M7.1"
  qid                 str    client display id, e.g. "M7.1-Q03" (audit/logging only)
  question            str    the prompt shown to the learner
  primary_answer      str    full model answer (reference only; never revealed early)
  alternative_answer  str    an accepted alternative phrasing (reference only; grading aid)
  key_points          list   each entry = 1 semantic point the learner must supply (1 point each)
  max_pts             int    cap for this question (== len(key_points))
"""

from typing import Optional, TypedDict


class AssessmentQuestion(TypedDict):
    number: int
    module: str
    qid: str
    question: str
    primary_answer: str
    alternative_answer: str
    key_points: list[str]
    max_pts: int

'''


FOOTER = '''TOTAL_QUESTIONS = len(QUESTIONS)
TOTAL_MAX_POINTS = sum(q["max_pts"] for q in QUESTIONS)

# Index by question number for O(1) lookups by the backend state engine (results.py).
QUESTIONS_BY_NUMBER: dict[int, AssessmentQuestion] = {q["number"]: q for q in QUESTIONS}

# Ordered question numbers per module, and each module's maximum points.
MODULE_QUESTIONS: dict[str, list[int]] = {m: [q["number"] for q in QUESTIONS if q["module"] == m] for m in MODULES}
MODULE_MAX_POINTS: dict[str, int] = {
    m: sum(QUESTIONS_BY_NUMBER[n]["max_pts"] for n in nums) for m, nums in MODULE_QUESTIONS.items()
}


def get_question(number: int) -> Optional[AssessmentQuestion]:
    """Return the question with this 1..52 number, or None if unknown."""
    return QUESTIONS_BY_NUMBER.get(number)


def key_point_count(number: int) -> int:
    """How many required key points question ``number`` has (== expected length of the per-point verdict)."""
    q = QUESTIONS_BY_NUMBER.get(number)
    return len(q["key_points"]) if q else 0


def max_points(number: int) -> int:
    """The point cap for question ``number`` (0 if unknown)."""
    q = QUESTIONS_BY_NUMBER.get(number)
    return q["max_pts"] if q else 0


def module_of(number: int) -> str:
    """The module key for question ``number`` ("" if unknown)."""
    q = QUESTIONS_BY_NUMBER.get(number)
    return q["module"] if q else ""


def module_label(module_key: str) -> str:
    """'M7.1' -> 'Module 7.1' (learner-facing module heading)."""
    return "Module " + module_key.lstrip("M") if module_key else ""


def module_questions(module_key: str) -> list[int]:
    """Ordered question numbers in ``module_key`` (empty if unknown)."""
    return list(MODULE_QUESTIONS.get(module_key, []))


def module_max_points(module_key: str) -> int:
    """Maximum points available in ``module_key`` (0 if unknown)."""
    return MODULE_MAX_POINTS.get(module_key, 0)


def module_index(module_key: str) -> int:
    """0-based position of ``module_key`` in the fixed order (-1 if unknown)."""
    return MODULES.index(module_key) if module_key in MODULES else -1


def is_last_module(module_key: str) -> bool:
    """True when ``module_key`` is the final module of the assessment."""
    return bool(MODULES) and module_key == MODULES[-1]


def next_module(module_key: str) -> Optional[str]:
    """The module after ``module_key`` in fixed order, or None if it is the last/unknown."""
    idx = module_index(module_key)
    if idx < 0 or idx + 1 >= len(MODULES):
        return None
    return MODULES[idx + 1]'''


def main() -> None:
    xlsx_path = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DEFAULT_XLSX
    if not xlsx_path.exists():
        raise SystemExit(f"Workbook not found: {xlsx_path}")
    rows = load_master_rows(xlsx_path)
    questions, module_order, module_col_points = build_questions(rows)
    OUTPUT.write_text(render_questions_py(questions, module_order), encoding="utf-8")
    total_pts = sum(q["max_pts"] for q in questions)
    print(f"Wrote {OUTPUT.relative_to(REPO_ROOT)}")
    print(f"  {len(questions)} questions, {len(module_order)} modules, {total_pts} points total")
    for m in module_order:
        nums = [q["number"] for q in questions if q["module"] == m]
        pts = sum(q["max_pts"] for q in questions if q["module"] == m)
        print(f"  {m:6} {len(nums)} questions, {pts} pts")


if __name__ == "__main__":
    main()
