"""Tests for scripts.doctype — Phase 1.6 classification support (no OCR).

Fully self-contained: synthesises page PNGs (Pillow) and doctype sidecars under
tmp_path, so these tests carry no dataset coupling.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.doctype import (
    DOC_TYPES,
    EXCLUDED_DOC_TYPES,
    INCLUDED_DOC_TYPES,
    check_doctype_case,
    compress_pages,
    doctype_path,
    excluded_documents_for_case,
    excluded_pages_map,
    load_doctype,
)


def _mk_pngs(png_dir: Path, stem: str, pages: list[int]) -> None:
    png_dir.mkdir(parents=True, exist_ok=True)
    for p in pages:
        Image.new("RGB", (60, 80), "white").save(png_dir / f"{stem}_p{p:02d}.png")


def _write_doctype(case_cache: Path, stem: str, pages: dict[int, str],
                   uncertain: list[int] | None = None) -> None:
    case_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "stem": stem,
        "pages": {str(p): t for p, t in pages.items()},
        "uncertain_pages": uncertain or [],
    }
    (case_cache / f"{stem}_doctype.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# T-1: excluded_pages_map / compress_pages / excluded_documents_for_case
# ---------------------------------------------------------------------------

def test_taxonomy_partition_is_consistent():
    assert INCLUDED_DOC_TYPES == frozenset({"MTC_FINISHED", "UNKNOWN"})
    assert INCLUDED_DOC_TYPES.isdisjoint(EXCLUDED_DOC_TYPES)
    assert INCLUDED_DOC_TYPES | EXCLUDED_DOC_TYPES == frozenset(DOC_TYPES)
    assert len(DOC_TYPES) == 13


def test_excluded_pages_map_absent_sidecar_is_empty(tmp_path):
    case = tmp_path / "9"
    case.mkdir()
    assert excluded_pages_map(case, "certA") == {}
    assert load_doctype(case, "certA") is None


def test_excluded_pages_map_only_excluded_labels(tmp_path):
    case = tmp_path / "9"
    _write_doctype(case, "certA", {
        1: "MTC_FINISHED",     # included
        2: "UNKNOWN",          # included
        3: "MTC_RAW_MATERIAL", # excluded
        4: "NDE_REPORT",       # excluded
    })
    m = excluded_pages_map(case, "certA")
    assert m == {3: "MTC_RAW_MATERIAL", 4: "NDE_REPORT"}


def test_excluded_pages_map_unknown_label_treated_as_included(tmp_path):
    case = tmp_path / "9"
    _write_doctype(case, "certA", {1: "TOTALLY_MADE_UP", 2: "PMI_REPORT"})
    # Unknown label falls back to "included" (skipped); only the known excluded.
    assert excluded_pages_map(case, "certA") == {2: "PMI_REPORT"}


def test_excluded_pages_map_invalid_json_is_empty(tmp_path):
    case = tmp_path / "9"
    case.mkdir()
    doctype_path(case, "certA").write_text("{not json", encoding="utf-8")
    assert excluded_pages_map(case, "certA") == {}


def test_compress_pages_ranges():
    assert compress_pages([30, 31, 55]) == "p.30-31, p.55"
    assert compress_pages([1, 2, 3, 10, 12, 13, 14]) == "p.1-3, p.10, p.12-14"
    assert compress_pages([7]) == "p.7"
    assert compress_pages([]) == ""
    # unsorted + duplicates collapse
    assert compress_pages([5, 4, 4, 6]) == "p.4-6"


def test_excluded_documents_groups_runs_and_sorts(tmp_path):
    case = tmp_path / "9"
    # Two runs on one stem: raw material p.30-31, then NDE p.55.
    _write_doctype(case, "certA", {
        1: "MTC_FINISHED", 30: "MTC_RAW_MATERIAL", 31: "MTC_RAW_MATERIAL",
        55: "NDE_REPORT",
    })
    docs = excluded_documents_for_case(case)
    assert [d["doc_type"] for d in docs] == ["MTC_RAW_MATERIAL", "NDE_REPORT"]
    assert docs[0]["pages"] == [30, 31]
    assert docs[0]["page_range"] == "p.30-31"
    assert docs[0]["doc_type_ko"] == "원자재 성적서(동봉 Mill Cert)"
    assert docs[0]["stem"] == "certA"
    assert "제외됨" in docs[0]["note"]
    assert docs[1]["pages"] == [55]


def test_excluded_documents_breaks_run_on_type_change(tmp_path):
    case = tmp_path / "9"
    # Adjacent excluded pages of DIFFERENT type stay separate documents.
    _write_doctype(case, "certA", {
        10: "MTC_RAW_MATERIAL", 11: "NDE_REPORT",
    })
    docs = excluded_documents_for_case(case)
    assert [d["doc_type"] for d in docs] == ["MTC_RAW_MATERIAL", "NDE_REPORT"]
    assert docs[0]["pages"] == [10]
    assert docs[1]["pages"] == [11]


def test_excluded_documents_multi_stem_sorted(tmp_path):
    case = tmp_path / "9"
    _write_doctype(case, "certB", {5: "PMI_REPORT"})
    _write_doctype(case, "certA", {2: "HEAT_TREATMENT_CHART"})
    docs = excluded_documents_for_case(case)
    # sorted by (stem, first page)
    assert [d["stem"] for d in docs] == ["certA", "certB"]


def test_excluded_documents_empty_when_no_sidecar(tmp_path):
    case = tmp_path / "9"
    case.mkdir()
    assert excluded_documents_for_case(case) == []


# ---------------------------------------------------------------------------
# T-2: check_doctype_case gate matrix
# ---------------------------------------------------------------------------

def test_check_normal_mixed_ok(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2, 3, 4])
    _write_doctype(case_cache, "certA", {
        1: "MTC_FINISHED", 2: "MTC_FINISHED",
        3: "MTC_RAW_MATERIAL", 4: "NDE_REPORT",
    })
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is True
    assert summary["uncovered_stems"] == []
    s = summary["stems"][0]
    assert s["included"] == 2
    assert s["excluded"] == 2
    assert s["by_type"] == {"MTC_RAW_MATERIAL": 1, "NDE_REPORT": 1}


def test_check_stem_without_sidecar_uncovered(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2])
    _mk_pngs(case_cache / "png", "certB", [1, 2])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "MTC_FINISHED"})
    # certB has no doctype sidecar.
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is False
    assert summary["uncovered_stems"] == ["certB"]


def test_check_gap_fails(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2, 3])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "MTC_FINISHED"})
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is False
    assert any("without a doctype label" in i for i in summary["stems"][0]["issues"])


def test_check_extra_fails(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2])
    _write_doctype(case_cache, "certA", {
        1: "MTC_FINISHED", 2: "MTC_FINISHED", 9: "NDE_REPORT",
    })
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is False
    assert any("extra" in i for i in summary["stems"][0]["issues"])


def test_check_invalid_label_fails(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "BOGUS_LABEL"})
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is False
    assert any("invalid doctype labels" in i for i in summary["stems"][0]["issues"])


def test_check_all_non_mtc_fails_with_human_message(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2, 3, 4])
    _write_doctype(case_cache, "certA", {
        1: "MTC_RAW_MATERIAL", 2: "MTC_RAW_MATERIAL",
        3: "NDE_REPORT", 4: "NDE_REPORT",
    })
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is False
    assert any("사람 확인 필요" in i for i in summary["stems"][0]["issues"])


def test_check_high_exclusion_ratio_warns_but_passes(tmp_path):
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    # 7/10 excluded (>60%) but at least one included -> WARNING, exit ok.
    _mk_pngs(case_cache / "png", "certA", list(range(1, 11)))
    pages = {1: "MTC_FINISHED", 2: "MTC_FINISHED", 3: "MTC_FINISHED"}
    for p in range(4, 11):
        pages[p] = "MTC_RAW_MATERIAL"
    _write_doctype(case_cache, "certA", pages)
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is True
    assert summary["stems"][0]["warnings"]
    assert summary["warnings"]


def test_check_enclosed_at_page_one(tmp_path):
    """E3: an enclosed non-MTC block at the FIRST page is position-independent."""
    cache = tmp_path / ".cache"
    case_cache = cache / "PU"
    _mk_pngs(case_cache / "png", "certA", [1, 2, 3])
    _write_doctype(case_cache, "certA", {
        1: "MTC_RAW_MATERIAL", 2: "MTC_FINISHED", 3: "MTC_FINISHED",
    })
    summary = check_doctype_case("PU", cache)
    assert summary["ok"] is True
    docs = excluded_documents_for_case(case_cache)
    assert docs[0]["pages"] == [1]
    assert docs[0]["doc_type"] == "MTC_RAW_MATERIAL"


def test_check_missing_pngs_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        check_doctype_case("PU", tmp_path / ".cache")


# ---------------------------------------------------------------------------
# T-8 companion: C1 no-OCR import guard for the new module
# ---------------------------------------------------------------------------

def test_no_ocr_import():
    path = Path(__file__).resolve().parent.parent / "scripts" / "doctype.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "pytesseract", "tesserocr", "easyocr", "paddleocr", "doctr", "kraken",
        "fitz", "pymupdf", "pdfplumber", "pdfminer", "cv2", "openai", "anthropic",
    }
    assert not (imported & forbidden), f"doctype imports forbidden: {imported & forbidden}"
