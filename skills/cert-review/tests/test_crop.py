"""crop command regression tests.

Unit tests cover the fractional-bbox parsing/validation and the fraction->pixel
conversion (no rendering). One integration test renders a tiny synthetic PDF and
asserts the crop file lands at the expected slugged path with the right size.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from scripts.crop import bbox_to_pixels, crop_region, parse_bbox, resolve_stem

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"


# --- parse_bbox -------------------------------------------------------------

def test_parse_bbox_ok():
    assert parse_bbox("0.0,0.1,0.5,0.6") == (0.0, 0.1, 0.5, 0.6)


def test_parse_bbox_wrong_count():
    with pytest.raises(ValueError):
        parse_bbox("0.0,0.1,0.5")


def test_parse_bbox_non_numeric():
    with pytest.raises(ValueError):
        parse_bbox("a,b,c,d")


def test_parse_bbox_out_of_range():
    with pytest.raises(ValueError):
        parse_bbox("0.0,0.0,1.5,0.5")


def test_parse_bbox_degenerate():
    with pytest.raises(ValueError):
        parse_bbox("0.5,0.0,0.5,1.0")  # x1 == x0


# --- bbox_to_pixels ---------------------------------------------------------

def test_bbox_to_pixels_basic():
    # full image
    assert bbox_to_pixels((0.0, 0.0, 1.0, 1.0), 1000, 800) == (0, 0, 1000, 800)
    # top-left quarter
    assert bbox_to_pixels((0.0, 0.0, 0.5, 0.5), 1000, 800) == (0, 0, 500, 400)
    # centre band
    assert bbox_to_pixels((0.25, 0.5, 0.75, 0.6), 1000, 800) == (250, 400, 750, 480)


def test_bbox_to_pixels_min_one_pixel():
    # A vanishingly thin slice still yields at least 1px width/height.
    left, top, right, bottom = bbox_to_pixels((0.999, 0.999, 1.0, 1.0), 100, 100)
    assert right > left and bottom > top


# --- resolve_stem + crop_region ---------------------------------------------

def _write_pdf(path: Path, pages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    with open(path, "wb") as fh:
        writer.write(fh)


def test_resolve_stem_prefix_match(tmp_path: Path):
    work = tmp_path / "work"
    _write_pdf(work / CERT_CLEANUP_DIRNAME / "9" / "ABC-long-name.pdf", 1)
    p = resolve_stem("9", "ABC", work)
    assert p.stem == "ABC-long-name"


def test_resolve_stem_ambiguous(tmp_path: Path):
    work = tmp_path / "work"
    _write_pdf(work / CERT_CLEANUP_DIRNAME / "9" / "ABC-one.pdf", 1)
    _write_pdf(work / CERT_CLEANUP_DIRNAME / "9" / "ABC-two.pdf", 1)
    with pytest.raises(ValueError, match="ambiguous"):
        resolve_stem("9", "ABC", work)


def test_crop_region_writes_slugged_png(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _write_pdf(work / CERT_CLEANUP_DIRNAME / "9" / "certA.pdf", 2)

    out = crop_region("9", "certA", 1, "0.00,0.00,0.50,0.25", work, cache, dpi=72)
    assert out.exists()
    assert out.name == "certA_p01_0.00x0.00-0.50x0.25.png"
    assert out.parent == (cache / "9" / "crops").resolve()

    from PIL import Image
    im = Image.open(out)
    # page is 200x300 pt at 72 dpi -> 200x300 px; half width, quarter height.
    assert im.size == (100, 75)


def test_crop_region_page_out_of_range(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _write_pdf(work / CERT_CLEANUP_DIRNAME / "9" / "certA.pdf", 1)
    with pytest.raises(ValueError, match="out of range"):
        crop_region("9", "certA", 5, "0,0,1,1", work, cache, dpi=72)
