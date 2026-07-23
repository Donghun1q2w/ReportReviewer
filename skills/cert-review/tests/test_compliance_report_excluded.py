"""T-7: compliance_report renders the Phase 1.6 excluded-documents block.

Self-contained: builds a synthetic review.json under tmp_path, renders the xlsx,
and reads it back with openpyxl (Korean read-back). No dataset required.
"""

from __future__ import annotations

import json
from pathlib import Path

import openpyxl

from scripts.compliance_report import build_compliance_report


def _base_review() -> dict:
    return {
        "case_id": "PU",
        "po_number": "PU-1",
        "mps_files": ["mps_a.pdf"],
        "code_edition_note": "",
        "materials": [
            {
                "item_name": "Seamless Pipe",
                "heat_no": "N100",
                "grade_cert": "A106 Gr.B",
                "grade_spec": "SA-106-B",
                "size": "48.3 x 7.14",
                "qty": "10",
                "verdict": "PASS",
                "chemistry": [], "mechanical": [], "heat_treatment": [],
                "nde": [], "doc_checks": [],
            }
        ],
        "findings": [],
    }


def _read_summary_rows(xlsx: Path) -> list[list]:
    wb = openpyxl.load_workbook(xlsx)
    ws = wb["검토 총괄"]
    return [[c.value for c in row] for row in ws.iter_rows()]


def test_excluded_documents_block_rendered(tmp_path: Path):
    review = _base_review()
    review["excluded_documents"] = [
        {
            "stem": "certA",
            "doc_type": "MTC_RAW_MATERIAL",
            "doc_type_ko": "원자재 성적서(동봉 Mill Cert)",
            "pages": [30, 31],
            "page_range": "p.30-31",
            "note": "제외됨: 원자재 성적서(동봉 Mill Cert) — 완제품 성적서가 아닌 동봉 문서로 분류되어 비교 검토에서 제외",
        },
        {
            "stem": "certA",
            "doc_type": "NDE_REPORT",
            "doc_type_ko": "비파괴검사 보고서(동봉)",
            "pages": [55],
            "page_range": "p.55",
            "note": "제외됨: 비파괴검사 보고서(동봉) — 완제품 성적서가 아닌 동봉 문서로 분류되어 비교 검토에서 제외",
        },
    ]
    review_path = tmp_path / "PU_review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    out = build_compliance_report(review_path, tmp_path / "out.xlsx")
    rows = _read_summary_rows(out)
    flat = [str(c) for row in rows for c in row if c is not None]

    # Header block present + Korean intact (read-back).
    assert any("검토 제외 문서" in c for c in flat)
    assert any("원자재 성적서(동봉 Mill Cert)" in c for c in flat)
    assert any("비파괴검사 보고서(동봉)" in c for c in flat)
    assert any(c == "제외됨" for c in flat)
    assert any("p.30-31" in c for c in flat)
    # No mojibake signatures in the read-back.
    assert not any("�" in c or "占" in c for c in flat)


def test_no_excluded_documents_field_is_backward_compatible(tmp_path: Path):
    """A legacy review.json without the field renders with no exclusion block
    and does not crash."""
    review = _base_review()  # no excluded_documents key
    review_path = tmp_path / "PU_review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    out = build_compliance_report(review_path, tmp_path / "out.xlsx")
    rows = _read_summary_rows(out)
    flat = [str(c) for row in rows for c in row if c is not None]
    assert not any("검토 제외 문서" in c for c in flat)
    assert any("Seamless Pipe" in c for c in flat)  # material still rendered


def test_excluded_documents_related_heat_column_rendered(tmp_path: Path):
    """T-4 (기준 20): related identifiers render a '관련 Heat/품목' cell; heat is
    preferred over PO, and Korean reads back intact."""
    review = _base_review()
    review["excluded_documents"] = [
        {
            "stem": "certA", "doc_type": "NDE_REPORT",
            "doc_type_ko": "비파괴검사 보고서(동봉)",
            "pages": [22], "page_range": "p.22",
            "note": "제외됨: 비파괴검사 보고서(동봉) — 동봉 문서로 분류되어 제외",
            "related_heat_nos": ["14328912", "23215117"],
            "related_po_items": [], "related_confidence": "high",
        },
        {
            "stem": "certA", "doc_type": "PMI_REPORT",
            "doc_type_ko": "PMI 보고서(동봉)",
            "pages": [23], "page_range": "p.23",
            "note": "제외됨: PMI 보고서(동봉) — 동봉 문서로 분류되어 제외",
            "related_heat_nos": [], "related_po_items": ["PU2601565-039"],
            "related_confidence": "high",
        },
    ]
    review_path = tmp_path / "PU_review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    out = build_compliance_report(review_path, tmp_path / "out.xlsx")
    rows = _read_summary_rows(out)
    flat = [str(c) for row in rows for c in row if c is not None]

    # heat preferred over PO.
    assert any("관련 Heat/품목: 14328912, 23215117" in c for c in flat)
    # PO-only report falls back to PO items.
    assert any("관련 Heat/품목: PU2601565-039" in c for c in flat)
    assert not any("�" in c or "占" in c for c in flat)


def test_excluded_documents_missing_related_renders_unknown(tmp_path: Path):
    """A record with no related fields (legacy merge) renders '확인 불가'."""
    review = _base_review()
    review["excluded_documents"] = [
        {
            "stem": "certA", "doc_type": "MTC_RAW_MATERIAL",
            "doc_type_ko": "원자재 성적서(동봉 Mill Cert)",
            "pages": [30], "page_range": "p.30",
            "note": "제외됨: 원자재 성적서(동봉 Mill Cert) — 동봉 문서로 분류되어 제외",
        },
    ]
    review_path = tmp_path / "PU_review.json"
    review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    out = build_compliance_report(review_path, tmp_path / "out.xlsx")
    rows = _read_summary_rows(out)
    flat = [str(c) for row in rows for c in row if c is not None]
    assert any("관련 Heat/품목: 확인 불가" in c for c in flat)
