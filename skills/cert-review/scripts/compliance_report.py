"""Deterministic compliance-review report (6-sheet Korean Excel).

Input: a structured review JSON (Cert vs MPS vs ref_code/Code comparison) — see
schema below. Unlike report_builder (which renders only findings/violations),
this renders the FULL per-parameter comparison (PASS rows included), which is
what a spec-compliance MTC review report shows.

NO OCR libraries are imported (C1) — openpyxl only.

Review JSON schema
------------------
{
  "case_id": "24",
  "po_number": "PU2501275",                 # optional
  "mps_files": ["1.MPS-SH-ACOR-106_0.pdf"],  # optional
  "code_edition_note": "성적서 2019 vs MPS 2022/2023",  # optional
  "materials": [
    {
      "item_name": "Seamless Pipe",
      "heat_no": "622090314",
      "grade_cert": "A106 Gr.B",            # as printed on the MTC
      "grade_spec": "SA-106-B",             # ordered/spec grade
      "size": "48.3 x 7.14",                # optional
      "qty": 120,                            # optional
      "verdict": "FAIL",                    # PASS | FAIL | 주의 | 조건부 PASS
      "chemistry":      [ {"element","analysis"?, "cert","spec_range","source","verdict","note"?} ],
      "mechanical":     [ {"property","cert","spec","source","verdict","note"?} ],
      "heat_treatment": [ {"stage","cert","spec","source","verdict","note"?} ],
      "nde":            [ {"item","spec"?, "cert"?, "source"?, "verdict","note"?} ],
      "doc_checks":     [ {"page"?, "location","mtc_value","expected","verdict","note"?} ]
    }
  ],
  "findings": [ {"no","severity","category","location","content","action"} ]
}
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

_HEADER_FILL = PatternFill("solid", fgColor="FF4472C4")
_HEADER_FONT = Font(bold=True, color="FFFFFFFF")
_TITLE_FONT = Font(bold=True)
_PASS_FILL = PatternFill("solid", fgColor="FFC6EFCE")
_FAIL_FILL = PatternFill("solid", fgColor="FFFFC7CE")
_WARN_FILL = PatternFill("solid", fgColor="FFFFEB9C")


def _verdict_fill(v: str) -> PatternFill:
    v = (v or "").strip().upper()
    if v == "PASS":
        return _PASS_FILL
    if v == "FAIL":
        return _FAIL_FILL
    if v in ("주의", "WARNING", "조건부 PASS", "조건부PASS"):
        return _WARN_FILL
    # Korean labels arrive non-upper
    raw = (v or "")
    return PatternFill()


def _fill_for(verdict: str) -> PatternFill:
    s = (verdict or "").strip()
    if s.upper() == "PASS":
        return _PASS_FILL
    if s.upper() == "FAIL":
        return _FAIL_FILL
    if s in ("주의", "조건부 PASS", "조건부PASS") or s.upper() == "WARNING":
        return _WARN_FILL
    return PatternFill()


def _title(ws, text: str, ncols: int) -> None:
    ws.merge_cells(f"A1:{get_column_letter(ncols)}1")
    c = ws["A1"]
    c.value = text
    c.font = _TITLE_FONT
    c.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 20


def _meta(ws, row: int, text: str, ncols: int) -> None:
    ws.merge_cells(f"A{row}:{get_column_letter(ncols)}{row}")
    ws.cell(row=row, column=1).value = text


def _header(ws, row: int, headers: list[str], widths: list[float]) -> None:
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i)
        c.value = h
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[row].height = 22


def _mat_label(m: dict) -> str:
    name = m.get("item_name") or "—"
    heat = m.get("heat_no") or ""
    grade = m.get("grade_spec") or m.get("grade_cert") or ""
    tail = ", ".join(x for x in (heat, grade) if x)
    return f"{name}\n({tail})" if tail else name


def _grouped_sheet(wb, sheet, title, headers, widths, materials, key,
                   row_fields) -> None:
    """Build a sheet whose rows come from materials[*][key]; col A merges per material."""
    ws = wb.create_sheet(sheet)
    _title(ws, title, len(headers))
    _header(ws, 3, headers, widths)
    r = 4
    for m in materials:
        rows = m.get(key) or []
        if not rows:
            continue
        start = r
        for row in rows:
            ws.cell(row=r, column=2).value = row.get(row_fields[0], "")
            ws.cell(row=r, column=3).value = row.get("source", "") or row.get("required_by", "")
            ws.cell(row=r, column=4).value = row.get(row_fields[1], "")
            ws.cell(row=r, column=5).value = _fmt(row.get(row_fields[2], ""))
            vc = ws.cell(row=r, column=6)
            vc.value = row.get("verdict", "")
            vc.fill = _fill_for(row.get("verdict", ""))
            ws.cell(row=r, column=7).value = row.get("note", "")
            r += 1
        _merge_label(ws, start, r - 1, _mat_label(m))


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def _merge_label(ws, start: int, end: int, label: str) -> None:
    if end < start:
        return
    if end > start:
        ws.merge_cells(start_row=start, start_column=1, end_row=end, end_column=1)
    ws.cell(row=start, column=1).value = label
    ws.cell(row=start, column=1).alignment = Alignment(wrap_text=True, vertical="center")


def build_compliance_report(review_path: Path, out_path: Path) -> Path:
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    case_id = review.get("case_id", "")
    materials = review.get("materials") or []

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # 1) 검토 총괄
    ws = wb.create_sheet("검토 총괄")
    _title(ws, f"성적서 검토 총괄 — Case {case_id}", 8)
    meta = f"PO: {review.get('po_number','—')}   |   MPS: {', '.join(review.get('mps_files') or []) or '—'}"
    if review.get("code_edition_note"):
        meta += f"   |   Code Edition: {review['code_edition_note']}"
    _meta(ws, 2, meta, 8)
    _header(ws, 4,
            ["S/N", "품명", "재질(발주)", "재질(MTC)", "규격(Size)", "Heat No", "수량", "종합 판정"],
            [6, 20, 16, 16, 18, 16, 8, 16])
    r = 5
    for i, m in enumerate(materials, start=1):
        ws.cell(row=r, column=1).value = f"{i:03d}"
        ws.cell(row=r, column=2).value = m.get("item_name", "")
        ws.cell(row=r, column=3).value = m.get("grade_spec", "")
        ws.cell(row=r, column=4).value = m.get("grade_cert", "")
        ws.cell(row=r, column=5).value = m.get("size", "")
        ws.cell(row=r, column=6).value = m.get("heat_no", "")
        ws.cell(row=r, column=7).value = _fmt(m.get("qty", ""))
        vc = ws.cell(row=r, column=8)
        vc.value = m.get("verdict", "")
        vc.fill = _fill_for(m.get("verdict", ""))
        r += 1

    # 2) 화학성분 검토
    _grouped_sheet(
        wb, "화학성분 검토", "화학성분 검토 (Chemical Composition)",
        ["품명 / Heat", "원소", "규격 출처", "규격 범위", "실측", "판정", "비고"],
        [22, 10, 26, 18, 12, 8, 32],
        materials, "chemistry", ("element", "spec_range", "cert"),
    )
    # 3) 기계적성질 검토
    _grouped_sheet(
        wb, "기계적성질 검토", "기계적 성질 검토 (Mechanical Properties)",
        ["품명 / Heat", "항목", "규격 출처", "규격", "실측", "판정", "비고"],
        [22, 16, 26, 18, 14, 8, 30],
        materials, "mechanical", ("property", "spec", "cert"),
    )
    # 4) 열처리 검토
    _grouped_sheet(
        wb, "열처리 검토", "열처리 검토 (Heat Treatment)",
        ["품명 / Heat", "단계", "규격 출처", "규격 범위", "실측", "판정", "비고"],
        [22, 16, 26, 18, 16, 8, 30],
        materials, "heat_treatment", ("stage", "spec", "cert"),
    )

    # 5) 표기·형식 검토 (doc_checks + nde)
    ws = wb.create_sheet("표기·형식 검토")
    _title(ws, "성적서 표기/형식·NDE 검토 (Document & NDE Check)", 6)
    _header(ws, 3, ["페이지", "검토 위치", "MTC 표기/실측", "마땅한 값/요구", "판정", "비고"],
            [12, 24, 26, 26, 8, 30])
    r = 4
    for m in materials:
        for d in m.get("doc_checks") or []:
            ws.cell(row=r, column=1).value = d.get("page", "")
            ws.cell(row=r, column=2).value = d.get("location", "")
            ws.cell(row=r, column=3).value = _fmt(d.get("mtc_value", ""))
            ws.cell(row=r, column=4).value = _fmt(d.get("expected", ""))
            vc = ws.cell(row=r, column=5)
            vc.value = d.get("verdict", "")
            vc.fill = _fill_for(d.get("verdict", ""))
            ws.cell(row=r, column=6).value = d.get("note", "")
            r += 1
        for n in m.get("nde") or []:
            ws.cell(row=r, column=1).value = ""
            ws.cell(row=r, column=2).value = f"NDE: {n.get('item','')} ({m.get('heat_no','')})"
            ws.cell(row=r, column=3).value = _fmt(n.get("cert", ""))
            ws.cell(row=r, column=4).value = _fmt(n.get("spec", "")) or n.get("source", "")
            vc = ws.cell(row=r, column=5)
            vc.value = n.get("verdict", "")
            vc.fill = _fill_for(n.get("verdict", ""))
            ws.cell(row=r, column=6).value = n.get("note", "")
            r += 1

    # 6) 지적사항 종합
    ws = wb.create_sheet("지적사항 종합")
    _title(ws, "지적사항 종합 (Findings & Recommendations)", 6)
    _header(ws, 3, ["No.", "심각도", "구분", "위치", "내용", "권고 조치"],
            [8, 10, 18, 24, 44, 32])
    r = 4
    for f in review.get("findings") or []:
        ws.cell(row=r, column=1).value = _fmt(f.get("no", ""))
        sc = ws.cell(row=r, column=2)
        sc.value = f.get("severity", "")
        sc.fill = _fill_for(f.get("severity", ""))
        ws.cell(row=r, column=3).value = f.get("category", "")
        ws.cell(row=r, column=4).value = f.get("location", "")
        cc = ws.cell(row=r, column=5)
        cc.value = f.get("content", "")
        cc.alignment = Alignment(wrap_text=True)
        ws.cell(row=r, column=6).value = f.get("action", "")
        r += 1

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))
    return out_path


__all__ = ["build_compliance_report"]
