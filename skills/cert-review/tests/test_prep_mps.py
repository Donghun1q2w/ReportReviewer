"""Tests for prep_mps — render + tile MPS PDFs (no OCR).

Self-contained: builds a tiny multi-page PDF with pypdf, so no dataset needed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scripts.prep_mps import prep_mps_case

MPS_DIRNAME = "standard inspection MPS cleanup data"


def _make_pdf(path: Path, pages: int = 2) -> None:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        w.write(fh)


def test_prep_mps_renders_and_tiles(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / ".cache"
    _make_pdf(work / MPS_DIRNAME / "9" / "MPS_A.pdf", pages=2)
    _make_pdf(work / MPS_DIRNAME / "9" / "MPS_B.pdf", pages=1)

    summary = prep_mps_case("9", work, cache, dpi=100)
    assert summary["case_id"] == "9"
    assert summary["grid"] == "2x2"
    assert len(summary["docs"]) == 2
    # 2-page doc -> 8 tiles, 1-page doc -> 4 tiles
    by_stem = {d["stem"]: d for d in summary["docs"]}
    assert by_stem["MPS_A"]["tile_count"] == 8
    assert by_stem["MPS_B"]["tile_count"] == 4

    tiles = sorted(p.name for p in (cache / "9" / "mps_tiles").glob("*.png"))
    assert "MPS_A_p01_r0c0.png" in tiles
    assert "MPS_A_p02_r1c1.png" in tiles
    assert "MPS_B_p01_r0c1.png" in tiles
    # page PNGs also produced
    assert (cache / "9" / "mps_png" / "MPS_A_p01.png").exists()


def test_missing_mps_folder_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        prep_mps_case("9", tmp_path / "work", tmp_path / ".cache")


def test_no_ocr_import():
    """Guard: prep_mps imports no OCR/text library (C1) — AST check."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "prep_mps.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                imported.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {
        "pytesseract", "easyocr", "paddleocr", "doctr", "fitz", "pymupdf",
        "pdfplumber", "pdfminer", "cv2", "openai", "anthropic",
    }
    assert not (imported & forbidden), f"prep_mps imports forbidden: {imported & forbidden}"
