"""extract_csv_seeds.py — one-shot seed extractor for chemistry_limits and mechanical_limits CSVs.

Parses ASME SEC II Part A markdown files (already OCR'd) to extract chemical
composition and mechanical property tables, then writes two seed CSVs with full
provenance (source_file, anchor, snippet) per row.

CLI:
    cd plugin/cert-review-skill
    python -m scripts._bootstrap.extract_csv_seeds \\
        --work-dir "D:\\...\\1. Standard Inspection" \\
        --out data/_seeds
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path bootstrap: resolve scripts/ package relative to this file
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent          # scripts/_bootstrap/
_PKG  = _HERE.parent                              # scripts/
_PLUGIN = _PKG.parent                             # plugin/cert-review-skill/
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG.parent))          # add plugin/ so "scripts." works

from scripts.source_validator import validate_csv_row  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEC2_DIR = Path(
    "ref_code/output_sec2_pta_1of2/ASME_SEC_II_PTA_1of2_2023"
)

# Priority-ordered list of (md_relative_path, spec_tag)
PRIORITY_FILES: list[tuple[str, str]] = [
    ("SA-105_SA-105M.md", "SA-105"),
    ("SA-106_SA-106M.md", "SA-106"),
    ("SA-182_SA-182M.md", "SA-182"),
    ("SA-234_SA-234M.md", "SA-234"),
    ("SA-335_SA-335M.md", "SA-335"),
]

# Elements we recognise in chemical tables (ordered for matching)
_ELEMENTS = [
    "Carbon", "Manganese", "Phosphorus", "Sulfur", "Silicon",
    "Chromium", "Molybdenum", "Nickel", "Vanadium", "Niobium",
    "Columbium", "Nitrogen", "Aluminum", "Tungsten", "Boron",
    "Titanium", "Zirconium", "Copper",
]

# Canonical element name mapping
_ELEM_CANON: dict[str, str] = {
    "Carbon": "C", "Manganese": "Mn", "Phosphorus": "P", "Sulfur": "S",
    "Silicon": "Si", "Chromium": "Cr", "Molybdenum": "Mo", "Nickel": "Ni",
    "Vanadium": "V", "Niobium": "Nb", "Columbium": "Nb",
    "Nitrogen": "N", "Aluminum": "Al", "Tungsten": "W", "Boron": "B",
    "Titanium": "Ti", "Zirconium": "Zr", "Copper": "Cu",
}

# Mechanical property labels we care about
_MECH_LABELS = [
    ("Tensile strength", "UTS", "ksi [MPa]"),
    ("Yield strength", "YS", "ksi [MPa]"),
    ("Elongation", "El", "%"),
]

# value patterns
_RANGE_RE  = re.compile(r"(\d+\.?\d*)\s*[–\-–]\s*(\d+\.?\d*)")
_MAX_RE    = re.compile(r"(\d+\.?\d*)\s+max", re.IGNORECASE)
_MIN_RE    = re.compile(r"(\d+\.?\d*)\s+min", re.IGNORECASE)
_SINGLE_RE = re.compile(r"^(\d+\.?\d*)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_md(path: Path) -> str:
    for enc in ("utf-8", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return ""


def _parse_value(raw: str) -> tuple[str, str]:
    """Return (min, max) strings from a raw cell value. Empty string = no req."""
    raw = raw.strip().strip("…").strip()
    if raw in ("", "…", "..."):
        return ("", "")
    m = _RANGE_RE.search(raw)
    if m:
        return (m.group(1), m.group(2))
    m = _MAX_RE.search(raw)
    if m:
        return ("", m.group(1))
    m = _MIN_RE.search(raw)
    if m:
        return (m.group(1), "")
    m = _SINGLE_RE.match(raw.split()[0]) if raw.split() else None
    if m:
        # bare number without qualifier → treat as max (common for P, S, C single values)
        return ("", m.group(1))
    return ("", "")


def _rel_path(md_path: Path, work_dir: Path) -> str:
    try:
        return md_path.relative_to(work_dir).as_posix()
    except ValueError:
        return md_path.as_posix()


# ---------------------------------------------------------------------------
# SA-335 parser — multi-grade pipe spec with column-per-grade table
# ---------------------------------------------------------------------------

def _parse_sa335(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    """Parse SA-335 TABLE 1 Chemical Requirements (one row per grade)."""
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    # Find TABLE 1 block
    tbl1_match = re.search(r"\*\*TABLE 1 Chemical Requirements\*\*", text)
    if not tbl1_match:
        print(f"[WARN] SA-335: TABLE 1 header not found", file=sys.stderr)
        return rows

    tbl_start = tbl1_match.start()
    # Extract up to 150 lines after TABLE 1 header
    chunk = text[tbl_start:tbl_start + 8000]
    lines = chunk.splitlines()

    # Each grade is a '| GradeX | ...' row. Column layout:
    # Grade | UNS | Carbon | Manganese | Phosphorus max | Sulfur max | Silicon | Chromium | Molybdenum | Others
    col_map = {
        2: "C", 3: "Mn", 4: "P", 5: "S", 6: "Si", 7: "Cr", 8: "Mo",
    }

    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # cells[0] is empty (before first |), cells[-1] is empty (after last |)
        cells = cells[1:-1]
        if len(cells) < 9:
            continue
        grade_raw = cells[0].strip()
        # Skip header rows and separator rows
        if not grade_raw or grade_raw.startswith("---") or grade_raw.startswith("Grade") \
                or grade_raw.startswith("UNS") or grade_raw == "Composition, %":
            continue
        # Normalise grade: "P91 Type 1" → "P91"
        grade = re.sub(r"\s*(Type\s*\d+|Class\s*\d+).*", "", grade_raw).strip()
        grade = re.sub(r"\s+", "", grade)  # remove spaces

        for col_idx, elem in col_map.items():
            if col_idx >= len(cells):
                continue
            cell_val = cells[col_idx].strip()
            lo, hi = _parse_value(cell_val)
            if not lo and not hi:
                continue
            # Analysis type — SA-335 only lists heat analysis in TABLE 1
            analysis = "Heat"
            # snippet = exact cell text
            snippet = cell_val
            if not snippet or snippet in ("…", "..."):
                continue
            # Verify snippet is actually in file text
            if snippet not in text:
                # try normalised
                snippet_norm = re.sub(r"\s+", " ", snippet)
                if snippet_norm not in re.sub(r"\s+", " ", text):
                    print(f"[WARN] SA-335 grade={grade} elem={elem} snippet not in file: {snippet!r}", file=sys.stderr)
                    continue
                snippet = snippet_norm
            anchor = f"Table1#Grade={grade}#Element={elem}"
            rows.append({
                "grade": grade,
                "element": elem,
                "analysis": analysis,
                "min": lo,
                "max": hi,
                "source_file": src,
                "anchor": anchor,
                "snippet": snippet,
            })

    return rows


# ---------------------------------------------------------------------------
# SA-106 parser — simple single-spec table with Grade A/B/C columns
# ---------------------------------------------------------------------------

def _parse_sa106(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    # TABLE 1 is a 4-column table: Element | Grade A | Grade B | Grade C
    tbl_match = re.search(r"\*\*TABLE 1 Chemical Requirements\*\*", text)
    if not tbl_match:
        print("[WARN] SA-106: TABLE 1 Chemical Requirements not found", file=sys.stderr)
        return rows

    chunk = text[tbl_match.start():tbl_match.start() + 3000]
    lines = chunk.splitlines()

    grades = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if len(cells) < 2:
            continue
        # Header row has "Grade A", "Grade B", "Grade C"
        if "Grade A" in cells[1] if len(cells) > 1 else False:
            grades = [c.strip() for c in cells[1:] if c.strip() and not c.startswith("---")]
            continue
        if not grades:
            if cells[0] in ("", "---") or "---" in cells[0]:
                continue
            # Try to detect header from first meaningful row
        if cells[0].startswith("---"):
            continue
        elem_raw = cells[0]
        if not elem_raw or elem_raw.startswith("---"):
            continue

        # Map element label to symbol
        elem_sym = None
        for full, sym in _ELEM_CANON.items():
            if full.lower() in elem_raw.lower():
                elem_sym = sym
                break
        if not elem_sym:
            continue

        for gi, grade in enumerate(grades):
            ci = gi + 1
            if ci >= len(cells):
                continue
            cell_val = cells[ci].strip()
            lo, hi = _parse_value(cell_val)
            if not lo and not hi:
                continue
            snippet = cell_val
            if snippet not in text:
                continue
            grade_clean = re.sub(r"Grade\s*", "", grade).strip()
            anchor = f"Table1#Grade={grade_clean}#Element={elem_sym}"
            rows.append({
                "grade": f"SA-106-{grade_clean}",
                "element": elem_sym,
                "analysis": "Heat",
                "min": lo,
                "max": hi,
                "source_file": src,
                "anchor": anchor,
                "snippet": snippet,
            })

    return rows


# ---------------------------------------------------------------------------
# SA-105 parser — single grade, simple element table
# ---------------------------------------------------------------------------

def _parse_sa105(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    tbl_match = re.search(r"TABLE 1 Chemical Requirements", text)
    if not tbl_match:
        print("[WARN] SA-105: TABLE 1 not found", file=sys.stderr)
        return rows

    chunk = text[tbl_match.start():tbl_match.start() + 2000]
    lines = chunk.splitlines()

    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if len(cells) < 2:
            continue
        if cells[0].startswith("---") or cells[0] in ("Element", ""):
            continue
        elem_raw = cells[0]
        elem_sym = None
        for full, sym in _ELEM_CANON.items():
            if full.lower() in elem_raw.lower():
                elem_sym = sym
                break
        if not elem_sym:
            continue
        cell_val = cells[1].strip() if len(cells) > 1 else ""
        lo, hi = _parse_value(cell_val)
        if not lo and not hi:
            continue
        # Remove footnote superscripts from snippet lookup
        snippet = cell_val
        snippet_clean = re.sub(r"[A-Za-z]$", "", snippet).strip()
        actual_snippet = snippet if snippet in text else snippet_clean if snippet_clean in text else None
        if not actual_snippet:
            print(f"[WARN] SA-105 elem={elem_sym} snippet not found: {snippet!r}", file=sys.stderr)
            continue
        anchor = f"Table1#Grade=SA-105#Element={elem_sym}"
        rows.append({
            "grade": "SA-105",
            "element": elem_sym,
            "analysis": "Heat",
            "min": lo,
            "max": hi,
            "source_file": src,
            "anchor": anchor,
            "snippet": actual_snippet,
        })

    return rows


# ---------------------------------------------------------------------------
# SA-182 parser — multi-grade forging spec, TABLE 1 alloy section rows
# ---------------------------------------------------------------------------

def _parse_sa182(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    """Parse SA-182 TABLE 2 (alloy steel chemical) rows that are present."""
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    # Column layout from TABLE 2 header (page 271+):
    # Grade | UNS | Carbon | Manganese | Phosphorus | Sulfur | Silicon | Nickel | Chromium | Molybdenum | Niobium | Titanium | Other
    col_map = {2: "C", 3: "Mn", 4: "P", 5: "S", 6: "Si", 7: "Ni", 8: "Cr", 9: "Mo"}

    # Grades of interest
    target_grades_re = re.compile(
        r"^F\s*(11|12|22|91|92|9|5|911|23|24)\b", re.IGNORECASE
    )

    lines = text.splitlines()
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if len(cells) < 5:
            continue
        grade_raw = cells[0].strip()
        if not grade_raw or grade_raw.startswith("---"):
            continue
        if not target_grades_re.match(grade_raw):
            continue

        # Normalise: "F 22 Class 1" → "F22CL1"
        grade = re.sub(r"\s+Class\s*", "CL", grade_raw)
        grade = re.sub(r"\s+", "", grade)

        for col_idx, elem in col_map.items():
            if col_idx >= len(cells):
                continue
            cell_val = cells[col_idx].strip()
            if cell_val in ("", "…", "..."):
                continue
            lo, hi = _parse_value(cell_val)
            if not lo and not hi:
                continue
            snippet = cell_val
            if snippet not in text:
                snippet_norm = re.sub(r"\s+", " ", snippet)
                if snippet_norm not in re.sub(r"\s+", " ", text):
                    print(f"[WARN] SA-182 grade={grade} elem={elem} snippet not found: {snippet!r}", file=sys.stderr)
                    continue
                snippet = snippet_norm
            anchor = f"Table1#Grade={grade}#Element={elem}"
            rows.append({
                "grade": grade,
                "element": elem,
                "analysis": "Heat",
                "min": lo,
                "max": hi,
                "source_file": src,
                "anchor": anchor,
                "snippet": snippet,
            })

    return rows


# ---------------------------------------------------------------------------
# SA-234 parser — pipe fittings chemical TABLE 1
# ---------------------------------------------------------------------------

def _parse_sa234(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    # TABLE 1 col layout:
    # Grade | Carbon | Manganese | Phosphorus | Sulfur | Silicon | Chromium | Molybdenum | Nickel | Copper | Others
    col_map = {1: "C", 2: "Mn", 3: "P", 4: "S", 5: "Si", 6: "Cr", 7: "Mo", 8: "Ni"}

    target_grades = {
        "WPB", "WPC", "WP1", "WP11CL1", "WP11CL2", "WP11CL3",
        "WP22CL1", "WP22CL3", "WP5CL1", "WP5CL2", "WP9CL1",
        "WP91Type1", "WP91Type2", "WP92", "WP911",
    }

    lines = text.splitlines()
    in_table = False
    for line in lines:
        if "TABLE 1 Chemical Requirements" in line:
            in_table = True
            continue
        if in_table and line.startswith("##"):
            in_table = False
            break
        if not in_table:
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if len(cells) < 5:
            continue
        grade_raw = cells[0].strip()
        if not grade_raw or grade_raw.startswith("---") or grade_raw.startswith("Grade"):
            continue

        # Normalise grade label
        grade = re.sub(r"\s*CL\s*", "CL", grade_raw)
        grade = re.sub(r",.*$", "", grade)  # drop "WP22 CL1, WP22 CL3" after comma
        grade = re.sub(r"\s+", "", grade)
        grade = re.sub(r"Type\s*", "Type", grade)

        for col_idx, elem in col_map.items():
            if col_idx >= len(cells):
                continue
            cell_val = cells[col_idx].strip()
            if cell_val in ("", "…", "..."):
                continue
            lo, hi = _parse_value(cell_val)
            if not lo and not hi:
                continue
            snippet = cell_val
            if snippet not in text:
                sn = re.sub(r"\s+", " ", snippet)
                if sn not in re.sub(r"\s+", " ", text):
                    print(f"[WARN] SA-234 grade={grade} elem={elem} snippet not found: {snippet!r}", file=sys.stderr)
                    continue
                snippet = sn
            anchor = f"Table1#Grade={grade}#Element={elem}"
            rows.append({
                "grade": grade,
                "element": elem,
                "analysis": "Heat",
                "min": lo,
                "max": hi,
                "source_file": src,
                "anchor": anchor,
                "snippet": snippet,
            })

    return rows


# ---------------------------------------------------------------------------
# Mechanical parser — SA-335 TABLE 3 Tensile Requirements (grade-per-column)
# ---------------------------------------------------------------------------

def _parse_sa335_mech(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    tbl_match = re.search(r"\*\*TABLE 3 Tensile Requirements\*\*", text)
    if not tbl_match:
        print("[WARN] SA-335: TABLE 3 Tensile Requirements not found", file=sys.stderr)
        return rows

    chunk = text[tbl_match.start():tbl_match.start() + 3000]
    lines = chunk.splitlines()

    # First non-separator table row is grade header
    grade_cols: list[str] = []
    prop_state: list[tuple[str, str]] = []  # (property_code, unit)
    # Parse state machine
    # Expect: header row -> separator -> data rows
    header_found = False
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if all(c.startswith("---") for c in cells if c):
            continue
        if not header_found:
            # First row with grade names
            if "P1" in line or "P91" in line or "P22" in line:
                grade_cols = []
                for c in cells[1:]:
                    # cells[0] is property label column
                    gc = c.strip()
                    if gc:
                        grade_cols.append(gc)
                header_found = True
            continue

        prop_raw = cells[0].strip() if cells else ""
        if not prop_raw:
            continue

        prop_code = None
        unit = ""
        if re.search(r"Tensile strength", prop_raw, re.IGNORECASE):
            prop_code = "UTS"
            unit = "ksi"
        elif re.search(r"Yield strength", prop_raw, re.IGNORECASE):
            prop_code = "YS"
            unit = "ksi"
        elif re.search(r"ksi", prop_raw):
            # continuation ksi row
            if prop_state:
                prop_code, unit = prop_state[-1]
                unit = "ksi"
        elif re.search(r"MPa", prop_raw):
            if prop_state:
                prop_code = prop_state[-1][0]
                unit = "MPa"
        else:
            prop_state = []
            continue

        if prop_code:
            prop_state = [(prop_code, unit)]

        for gi, grade_label in enumerate(grade_cols):
            ci = gi + 1
            if ci >= len(cells):
                continue
            cell_val = cells[ci].strip()
            if not cell_val or cell_val in ("…", "..."):
                continue
            lo, hi = _parse_value(cell_val)
            if not lo and not hi:
                try:
                    float(cell_val.split()[0])
                    lo = ""
                    hi = ""
                    val_min = cell_val.split()[0]
                    lo = val_min
                except Exception:
                    continue
            # The min value for tensile/yield is the "min" spec
            if not lo:
                lo = hi
                hi = ""
            snippet = cell_val
            if snippet not in text:
                continue
            # Grade normalisation: "P1, P2" → first grade
            for gpart in re.split(r"[,/]", grade_label):
                g = gpart.strip().replace(" ", "")
                if not g:
                    continue
                anchor = f"Table3#Grade={g}#Property={prop_code}#{unit}"
                rows.append({
                    "grade": g,
                    "property": prop_code,
                    "unit": unit,
                    "min": lo,
                    "max": "",
                    "source_file": src,
                    "anchor": anchor,
                    "snippet": snippet,
                })

    return rows


# ---------------------------------------------------------------------------
# SA-106 mechanical — TABLE 2
# ---------------------------------------------------------------------------

def _parse_sa106_mech(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    tbl_match = re.search(r"\*\*TABLE 2 Tensile Requirements\*\*", text)
    if not tbl_match:
        print("[WARN] SA-106: TABLE 2 Tensile Requirements not found", file=sys.stderr)
        return rows

    chunk = text[tbl_match.start():tbl_match.start() + 2000]
    lines = chunk.splitlines()

    grades: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if all(c.startswith("---") for c in cells if c):
            continue
        # Header row
        if not grades and "Grade A" in line:
            grades = [c.strip() for c in cells[1:] if c.strip() and not c.startswith("---")]
            continue
        if not grades:
            continue

        prop_raw = cells[0].strip() if cells else ""
        prop_code = None
        unit = "ksi"
        if re.search(r"Tensile strength.*min", prop_raw, re.IGNORECASE):
            prop_code = "UTS"
        elif re.search(r"Yield strength.*min", prop_raw, re.IGNORECASE):
            prop_code = "YS"
        elif re.search(r"Elongation.*2 in.*min", prop_raw, re.IGNORECASE):
            prop_code = "El"
            unit = "%"
        else:
            continue

        for gi, grade_label in enumerate(grades):
            ci = gi + 1
            if ci >= len(cells):
                continue
            cell_val = cells[ci].strip()
            if not cell_val:
                continue
            # Extract numeric from e.g. "48 000 [330]" or "35" or "30"
            nums = re.findall(r"\d[\d\s]*(?:\[\d+\])?", cell_val)
            if not nums:
                continue
            # Take ksi value (before bracket)
            raw_ksi = nums[0].split("[")[0].replace(" ", "").strip()
            if not raw_ksi:
                continue
            snippet = cell_val
            if snippet not in text:
                continue
            grade_clean = re.sub(r"Grade\s*", "", grade_label).strip()
            anchor = f"Table2#Grade={grade_clean}#Property={prop_code}#{unit}"
            rows.append({
                "grade": f"SA-106-{grade_clean}",
                "property": prop_code,
                "unit": unit,
                "min": raw_ksi,
                "max": "",
                "source_file": src,
                "anchor": anchor,
                "snippet": snippet,
            })

    return rows


# ---------------------------------------------------------------------------
# SA-234 mechanical — TABLE 2
# ---------------------------------------------------------------------------

def _parse_sa234_mech(text: str, md_path: Path, work_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    src = _rel_path(md_path, work_dir)

    tbl_match = re.search(r"\*\*TABLE 2 Tensile Requirements\*\*", text)
    if not tbl_match:
        print("[WARN] SA-234: TABLE 2 Tensile Requirements not found", file=sys.stderr)
        return rows

    chunk = text[tbl_match.start():tbl_match.start() + 3000]
    lines = chunk.splitlines()

    grades: list[str] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")][1:-1]
        if all(c.startswith("---") for c in cells if c):
            continue
        # Header: first row with grade labels
        if not grades and ("WPB" in line or "WPC" in line):
            grades = [c.strip() for c in cells[1:] if c.strip() and not c.startswith("---")]
            continue
        if not grades:
            continue

        prop_raw = cells[0].strip() if cells else ""
        prop_code = None
        unit = "ksi"
        if re.search(r"Tensile strength.*min", prop_raw, re.IGNORECASE):
            prop_code = "UTS"
        elif re.search(r"Yield strength.*min", prop_raw, re.IGNORECASE):
            prop_code = "YS"
        elif re.search(r"Elongation.*min.*%.*Long", prop_raw, re.IGNORECASE):
            prop_code = "El"
            unit = "%"
        else:
            continue

        for gi, grade_label in enumerate(grades):
            ci = gi + 1
            if ci >= len(cells):
                continue
            cell_val = cells[ci].strip()
            if not cell_val or cell_val in ("…", "..."):
                continue
            # Extract first number
            m = re.search(r"(\d+)", cell_val)
            if not m:
                continue
            snippet = cell_val
            if snippet not in text:
                continue
            grade_clean = re.sub(r"\s+", "", grade_label)
            anchor = f"Table2#Grade={grade_clean}#Property={prop_code}#{unit}"
            rows.append({
                "grade": grade_clean,
                "property": prop_code,
                "unit": unit,
                "min": m.group(1),
                "max": "",
                "source_file": src,
                "anchor": anchor,
                "snippet": snippet,
            })

    return rows


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_CHEM_PARSERS = {
    "SA-105": _parse_sa105,
    "SA-106": _parse_sa106,
    "SA-182": _parse_sa182,
    "SA-234": _parse_sa234,
    "SA-335": _parse_sa335,
}

_MECH_PARSERS = {
    "SA-106": _parse_sa106_mech,
    "SA-234": _parse_sa234_mech,
    "SA-335": _parse_sa335_mech,
}

# CSV column headers
_CHEM_HEADERS = ["grade", "element", "analysis", "min", "max",
                 "source_file", "anchor", "snippet"]
_MECH_HEADERS = ["grade", "property", "unit", "min", "max",
                 "source_file", "anchor", "snippet"]


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------

def _validate_rows(rows: list[dict[str, Any]], work_dir: Path, label: str) -> list[dict[str, Any]]:
    valid = []
    for i, row in enumerate(rows, 1):
        res = validate_csv_row(row, work_dir, row_id=f"{label}:row{i}")
        if res.ok:
            valid.append(row)
        else:
            print(f"[DROP] {label} row {i} failed validation: {res.reason}", file=sys.stderr)
    return valid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed CSV extractor for ASME SEC II PTA chemistry/mechanical tables")
    parser.add_argument("--work-dir", required=True, help="Working directory (contains ref_code/)")
    parser.add_argument("--out", default="data/_seeds", help="Output directory for seed CSVs")
    args = parser.parse_args()

    work_dir = Path(args.work_dir).resolve()
    out_dir = (_PLUGIN / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_chem: list[dict[str, Any]] = []
    all_mech: list[dict[str, Any]] = []

    for rel_fname, spec_tag in PRIORITY_FILES:
        md_path = work_dir / SEC2_DIR / rel_fname
        if not md_path.exists():
            print(f"[SKIP] {md_path} does not exist", file=sys.stderr)
            continue

        print(f"[INFO] Parsing {spec_tag} from {md_path.name}", file=sys.stderr)
        text = _read_md(md_path)
        if not text:
            print(f"[WARN] Could not read {md_path}", file=sys.stderr)
            continue

        if spec_tag in _CHEM_PARSERS:
            try:
                chem_rows = _CHEM_PARSERS[spec_tag](text, md_path, work_dir)
                print(f"  chem rows (raw): {len(chem_rows)}", file=sys.stderr)
                all_chem.extend(chem_rows)
            except Exception as exc:
                print(f"[ERROR] Chem parser {spec_tag} failed: {exc}", file=sys.stderr)

        if spec_tag in _MECH_PARSERS:
            try:
                mech_rows = _MECH_PARSERS[spec_tag](text, md_path, work_dir)
                print(f"  mech rows (raw): {len(mech_rows)}", file=sys.stderr)
                all_mech.extend(mech_rows)
            except Exception as exc:
                print(f"[ERROR] Mech parser {spec_tag} failed: {exc}", file=sys.stderr)

    # Validate
    print(f"\n[INFO] Validating {len(all_chem)} chem rows...", file=sys.stderr)
    valid_chem = _validate_rows(all_chem, work_dir, "chemistry")
    print(f"[INFO] Validated: {len(valid_chem)} / {len(all_chem)}", file=sys.stderr)

    print(f"[INFO] Validating {len(all_mech)} mech rows...", file=sys.stderr)
    valid_mech = _validate_rows(all_mech, work_dir, "mechanical")
    print(f"[INFO] Validated: {len(valid_mech)} / {len(all_mech)}", file=sys.stderr)

    # Write CSVs
    chem_path = out_dir / "chemistry_limits_seed.csv"
    mech_path = out_dir / "mechanical_limits_seed.csv"

    with open(chem_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_CHEM_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(valid_chem)

    with open(mech_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_MECH_HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(valid_mech)

    print(f"\n[DONE] chemistry_limits_seed.csv: {len(valid_chem)} rows -> {chem_path}", file=sys.stderr)
    print(f"[DONE] mechanical_limits_seed.csv: {len(valid_mech)} rows -> {mech_path}", file=sys.stderr)

    if len(valid_chem) < 30:
        print(f"[WARN] chemistry rows ({len(valid_chem)}) below 30 target", file=sys.stderr)
    if len(valid_mech) < 10:
        print(f"[WARN] mechanical rows ({len(valid_mech)}) below 10 target", file=sys.stderr)


if __name__ == "__main__":
    main()
