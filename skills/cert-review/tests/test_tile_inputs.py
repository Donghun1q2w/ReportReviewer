"""Tests for tile_inputs — overlapping page tiling (image crop only, no OCR).

Self-contained: synthesises page PNGs with Pillow, so no dataset is required.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PIL import Image

from scripts.tile_inputs import tile_bounds, tile_case, tile_image


def test_tile_bounds_2x2_overlap():
    boxes = tile_bounds(2, 2, 0.06)
    assert len(boxes) == 4
    # row/col indices cover the 2x2 grid exactly once
    assert sorted((r, c) for r, c, *_ in boxes) == [(0, 0), (0, 1), (1, 0), (1, 1)]
    # top-left tile starts at origin and overshoots the midline by the overlap
    r, c, x0, y0, x1, y1 = boxes[0]
    assert (x0, y0) == (0.0, 0.0)
    assert abs(x1 - 0.56) < 1e-9 and abs(y1 - 0.56) < 1e-9
    # bottom-right tile ends at 1.0 and starts below the midline by the overlap
    r, c, x0, y0, x1, y1 = boxes[-1]
    assert abs(x0 - 0.44) < 1e-9 and abs(y0 - 0.44) < 1e-9
    assert (x1, y1) == (1.0, 1.0)


def test_tile_image_produces_overlapping_tiles():
    img = Image.new("RGB", (1000, 800), "white")
    tiles = tile_image(img, 2, 2, 0.06)
    assert len(tiles) == 4
    for _, _, t in tiles:
        # each tile ~ (0.56*W) x (0.56*H), larger than a non-overlap quadrant
        assert t.size[0] > 500 and t.size[1] > 400
        assert t.size[0] <= 1000 and t.size[1] <= 800


def test_tile_image_is_legibility_gain():
    # The whole point: a 2x2 tile's long edge is well under the full page's, so
    # it survives Read downsampling with more detail.
    img = Image.new("RGB", (3500, 2500), "white")
    full_long = max(img.size)
    tiles = tile_image(img)
    tile_long = max(max(t.size) for _, _, t in tiles)
    assert tile_long < full_long * 0.65


def test_tile_case_writes_tiles(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    png_dir = cache_root / "99" / "png"
    png_dir.mkdir(parents=True)
    stem = "CERT_A"
    for p in (1, 2):
        Image.new("RGB", (1200, 900), "white").save(png_dir / f"{stem}_p{p:02d}.png")

    summary = tile_case("99", cache_root)
    assert summary["case_id"] == "99"
    assert summary["grid"] == "2x2"
    assert len(summary["certs"]) == 1
    assert summary["certs"][0]["tile_count"] == 8  # 2 pages * 4 tiles

    tiles_dir = cache_root / "99" / "tiles"
    written = sorted(p.name for p in tiles_dir.glob("*.png"))
    assert written == [
        f"{stem}_p01_r0c0.png", f"{stem}_p01_r0c1.png",
        f"{stem}_p01_r1c0.png", f"{stem}_p01_r1c1.png",
        f"{stem}_p02_r0c0.png", f"{stem}_p02_r0c1.png",
        f"{stem}_p02_r1c0.png", f"{stem}_p02_r1c1.png",
    ]


def test_missing_pngs_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        tile_case("99", tmp_path / ".cache")


def test_no_ocr_import():
    """Guard: tiling imports no OCR/text library (C1) — AST so docstrings that
    name forbidden libs don't trip the check."""
    path = Path(__file__).resolve().parent.parent / "scripts" / "tile_inputs.py"
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
    assert not (imported & forbidden), f"tile_inputs imports forbidden: {imported & forbidden}"
