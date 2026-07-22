"""Tests for orient_sheets — orientation-detection contact sheets (no OCR).

Self-contained: synthesises page PNGs with Pillow, so no dataset is required.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.orient_sheets import (
    SHEETS_DIRNAME,
    SHEETS_INDEX_NAME,
    _cell_size,
    build_orient_sheets,
)


def _mk_pages(png_dir: Path, stem: str, n: int, size=(900, 1200)) -> None:
    png_dir.mkdir(parents=True, exist_ok=True)
    for p in range(1, n + 1):
        Image.new("RGB", size, "white").save(png_dir / f"{stem}_p{p:02d}.png")


def test_single_sheet_for_small_case(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    _mk_pages(cache_root / "9" / "png", "CERT_A", 3)

    summary = build_orient_sheets("9", cache_root)
    assert summary["n_sheets"] == 1
    assert summary["stems"] == {"CERT_A": 3}

    sheets_dir = cache_root / "9" / SHEETS_DIRNAME
    assert (sheets_dir / "CERT_A__sheet01.png").exists()

    index = json.loads((sheets_dir / SHEETS_INDEX_NAME).read_text(encoding="utf-8"))
    assert index["case_id"] == "9"
    assert index["sheets"][0]["pages"] == [1, 2, 3]
    assert index["sheets"][0]["stem"] == "CERT_A"


def test_pages_chunked_into_multiple_sheets(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    # 14 pages with a 3x4 grid -> 12 + 2 = 2 sheets
    _mk_pages(cache_root / "9" / "png", "CERT_B", 14)

    summary = build_orient_sheets("9", cache_root)
    assert summary["n_sheets"] == 2

    index = json.loads(
        (cache_root / "9" / SHEETS_DIRNAME / SHEETS_INDEX_NAME).read_text(encoding="utf-8")
    )
    pages_by_sheet = [s["pages"] for s in index["sheets"]]
    assert pages_by_sheet == [list(range(1, 13)), [13, 14]]


def test_sheet_geometry_and_landscape_pages_fit(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    png_dir = cache_root / "9" / "png"
    _mk_pages(png_dir, "CERT_C", 1, size=(900, 1200))       # portrait
    Image.new("RGB", (1200, 900), "white").save(png_dir / "CERT_C_p02.png")  # landscape

    build_orient_sheets("9", cache_root, cols=3, rows=4, thumb_long=360)
    sheet = Image.open(cache_root / "9" / SHEETS_DIRNAME / "CERT_C__sheet01.png")
    cell_w, cell_h = _cell_size(360)
    assert sheet.size[0] == 3 * cell_w
    assert sheet.size[1] > 4 * cell_h  # + header


def test_multi_stem_case_gets_separate_sheets(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    png_dir = cache_root / "9" / "png"
    _mk_pages(png_dir, "CERT_A", 2)
    for p in (1, 2):
        Image.new("RGB", (900, 1200), "white").save(png_dir / f"CERT_B_p{p:02d}.png")

    summary = build_orient_sheets("9", cache_root)
    assert summary["n_sheets"] == 2
    names = sorted(
        p.name for p in (cache_root / "9" / SHEETS_DIRNAME).glob("*__sheet*.png")
    )
    assert names == ["CERT_A__sheet01.png", "CERT_B__sheet01.png"]


def test_hundred_plus_pages_included(tmp_path: Path):
    """3-digit pages must appear in the inventory (review finding: the old
    [0-9][0-9] glob silently dropped pages >= 100)."""
    cache_root = tmp_path / ".cache"
    png_dir = cache_root / "9" / "png"
    png_dir.mkdir(parents=True)
    for p in (99, 100, 101):
        Image.new("RGB", (300, 400), "white").save(png_dir / f"CERT_A_p{p:02d}.png")

    summary = build_orient_sheets("9", cache_root)
    assert summary["stems"] == {"CERT_A": 3}
    index = json.loads(
        (cache_root / "9" / SHEETS_DIRNAME / SHEETS_INDEX_NAME).read_text(encoding="utf-8")
    )
    assert index["sheets"][0]["pages"] == [99, 100, 101]


def test_regeneration_drops_stale_sheets(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    _mk_pages(cache_root / "9" / "png", "CERT_A", 14)  # -> 2 sheets
    build_orient_sheets("9", cache_root)

    # Shrink to 3 pages -> 1 sheet; sheet02 must disappear on regeneration.
    for p in range(4, 15):
        (cache_root / "9" / "png" / f"CERT_A_p{p:02d}.png").unlink()
    summary = build_orient_sheets("9", cache_root)
    assert summary["n_sheets"] == 1
    names = sorted(p.name for p in (cache_root / "9" / SHEETS_DIRNAME).glob("*__sheet*.png"))
    assert names == ["CERT_A__sheet01.png"]


def test_missing_pngs_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        build_orient_sheets("9", tmp_path / ".cache")


def test_classify_sheets_dirname_writes_to_separate_dir(tmp_path: Path):
    """T-3: sheets_dirname='classify' writes to classify/ and never touches
    orient/ — the default-path behaviour (orient/) is unchanged."""
    cache_root = tmp_path / ".cache"
    _mk_pages(cache_root / "9" / "png", "CERT_A", 3)

    summary = build_orient_sheets("9", cache_root, sheets_dirname="classify")
    classify_dir = cache_root / "9" / "classify"
    assert (classify_dir / "CERT_A__sheet01.png").exists()
    assert (classify_dir / SHEETS_INDEX_NAME).exists()
    # Default orient/ dir was not created by the classify build.
    assert not (cache_root / "9" / SHEETS_DIRNAME).exists()
    assert classify_dir.name in summary["sheets_dir"]


def test_default_dirname_still_orient(tmp_path: Path):
    """T-3: omitting sheets_dirname keeps the byte-identical orient/ path."""
    cache_root = tmp_path / ".cache"
    _mk_pages(cache_root / "9" / "png", "CERT_A", 2)
    build_orient_sheets("9", cache_root)
    assert (cache_root / "9" / SHEETS_DIRNAME / "CERT_A__sheet01.png").exists()
    assert not (cache_root / "9" / "classify").exists()


def test_no_ocr_import():
    """Guard: sheet composition imports no OCR/text library (C1)."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "orient_sheets.py"
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
    assert not (imported & forbidden), f"orient_sheets imports forbidden: {imported & forbidden}"
