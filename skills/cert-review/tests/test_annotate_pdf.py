"""annotate_pdf regression tests.

Pure unit tests (colour/verdict mapping, label truncation, placement, the
load_annotations dual gate) always run — they need neither the dataset nor a
font. The render/integration tests need a Hangul TTF (malgun.ttf, or set
CERT_REVIEW_FONT) and are skipped when it is absent so the always-run suite
stays green on non-Windows/font-less environments.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from scripts import annotate_pdf as A
from scripts.annotate_pdf import (
    _hex_to_rgb,
    _label_for,
    _place_label,
    _truncate,
    _verdict_rgb,
    annotate_case,
    load_annotations,
    render_annotated_pdf,
)

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"

_FONT = os.environ.get("CERT_REVIEW_FONT", A.DEFAULT_FONT)
_HAS_FONT = Path(_FONT).exists()
requires_font = pytest.mark.skipif(
    not _HAS_FONT, reason=f"Hangul font not present ({_FONT}); set CERT_REVIEW_FONT"
)

# Report colours (compliance_report constants), alpha-stripped to RGB.
_FAIL_RGB = (255, 199, 206)
_WARN_RGB = (255, 235, 156)
_NA_RGB = (217, 217, 217)


# --------------------------------------------------------------------------- #
# Pure unit tests (always run)
# --------------------------------------------------------------------------- #
def test_hex_to_rgb_strips_alpha_by_position():
    assert _hex_to_rgb("FFFFC7CE") == _FAIL_RGB   # 8-digit ARGB
    assert _hex_to_rgb("#FFC7CE") == _FAIL_RGB     # 6-digit with '#'
    assert _hex_to_rgb("FFC7CE") == _FAIL_RGB      # 6-digit


def test_hex_to_rgb_bad_length():
    with pytest.raises(ValueError):
        _hex_to_rgb("FFF")


def test_verdict_rgb_mapping_and_aliases():
    assert _verdict_rgb("FAIL") == _FAIL_RGB
    assert _verdict_rgb("WARNING") == _WARN_RGB        # alias -> 주의
    assert _verdict_rgb("주의") == _WARN_RGB
    assert _verdict_rgb("확인 불가") == _NA_RGB         # alias -> N/A
    assert _verdict_rgb("N/A") == _NA_RGB
    # PASS (and its aliases) are never annotated
    assert _verdict_rgb("PASS") is None
    assert _verdict_rgb("합격") is None


def test_truncate_korean_caps_at_50_codepoints():
    out = _truncate("가" * 60)
    assert len(out) == 50
    assert out.endswith("…")
    assert _truncate("짧은 라벨") == "짧은 라벨"  # under limit unchanged


def test_truncate_collapses_whitespace():
    assert _truncate("주의:   열처리\n온도  미기재") == "주의: 열처리 온도 미기재"


def test_label_for_explicit_and_auto():
    assert _label_for({"verdict": "FAIL", "label": "P 0.024 > 0.02"}) == "P 0.024 > 0.02"
    assert _label_for({"verdict": "주의", "source_ref": "chemistry/P"}) == "주의: chemistry/P"
    assert _label_for({"verdict": "N/A"}) == "N/A"  # no ref -> bare verdict


def test_place_label_clamps_into_page():
    # box near the top -> label would clip above, must flip below and stay in page
    x, y = _place_label((10, 0, 50, 20), tw=120, th=18, page_w=200, page_h=300, placed=[])
    assert 0 <= x <= 200 - 120
    assert 0 <= y <= 300 - 18


def test_place_label_avoids_overlap():
    placed = [(0, 0, 200, 40)]  # occupies the top band
    x, y = _place_label((10, 50, 60, 70), tw=80, th=18, page_w=400, page_h=400, placed=placed)
    rect = (x - 2, y - 2, x + 80 + 2, y + 18 + 2)
    assert not A._rects_overlap(rect, placed[0])


# --------------------------------------------------------------------------- #
# load_annotations dual gate (always run)
# --------------------------------------------------------------------------- #
def _write_annotations(path: Path, records: list[dict], case_id: str = "9") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"case_id": case_id, "annotations": records}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_annotations_dual_gate(tmp_path: Path):
    p = tmp_path / "9_annotations.json"
    _write_annotations(
        p,
        [
            {"stem": "s", "page": 1, "bbox": [0.1, 0.1, 0.5, 0.2], "verdict": "FAIL", "label": "ok"},
            {"stem": "s", "page": 1, "bbox": [0, 0, 0.3, 0.3], "verdict": "합격"},       # PASS excluded
            {"stem": "s", "page": True, "bbox": [0, 0, 0.3, 0.3], "verdict": "주의"},     # bool page
            {"stem": "s", "page": 2, "bbox": "oops", "verdict": "N/A"},                   # bad bbox
            {"stem": "s", "page": 0, "bbox": [0, 0, 0.3, 0.3], "verdict": "FAIL"},        # page < 1
        ],
    )
    anns, skips = load_annotations(p)
    assert len(anns) == 1 and anns[0].verdict == "FAIL"
    assert skips.get("pass_or_other_excluded") == 1
    assert skips.get("bad_page") == 2          # bool + page 0
    assert skips.get("bad_bbox") == 1


def test_load_annotations_empty_is_backward_compatible(tmp_path: Path):
    p = tmp_path / "9_annotations.json"
    p.write_text(json.dumps({"case_id": "9"}), encoding="utf-8")  # no annotations key
    anns, skips = load_annotations(p)
    assert anns == [] and skips == {}


# --------------------------------------------------------------------------- #
# C1: no forbidden (OCR) imports in the module
# --------------------------------------------------------------------------- #
def test_no_forbidden_imports():
    forbidden = {"fitz", "pymupdf", "pdfplumber", "pdfminer", "pytesseract", "easyocr",
                 "paddleocr", "openai", "anthropic"}
    src = Path(A.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert forbidden.isdisjoint(names), f"forbidden import: {forbidden & names}"


# --------------------------------------------------------------------------- #
# Render / integration (require a Hangul font)
# --------------------------------------------------------------------------- #
def _write_pdf(path: Path, pages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=400, height=300)
    with open(path, "wb") as fh:
        writer.write(fh)


def _render_first_page(pdf_path: Path, dpi: int = 100):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        img = doc[0].render(scale=dpi / 72.0).to_pil().convert("RGB")
    finally:
        doc.close()
    return img


def _has_color(img, target, tol=25, step=2) -> bool:
    px = img.load()
    w, h = img.size
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y][:3]
            if abs(r - target[0]) <= tol and abs(g - target[1]) <= tol and abs(b - target[2]) <= tol:
                return True
    return False


@requires_font
def test_render_draws_box_with_report_colour(tmp_path: Path):
    src = tmp_path / "c.pdf"
    _write_pdf(src, 1)
    ann = A.Annotation(stem="c", page=1, bbox=(0.2, 0.2, 0.8, 0.6), verdict="FAIL", label="FAIL: 한글 라벨")
    out = tmp_path / "c_annotated.pdf"
    out_path, drawn, pages, oob = render_annotated_pdf(src, {1: [ann]}, out, dpi=100, font_path=_FONT)
    assert drawn == 1 and pages == 1 and oob == 0 and out_path.exists()
    img = _render_first_page(out_path)
    assert _has_color(img, _FAIL_RGB), "FAIL outline/label colour not found within tolerance"


@requires_font
def test_render_copy_through_preserves_unannotated_page(tmp_path: Path):
    src = tmp_path / "c.pdf"
    _write_pdf(src, 2)  # 2 blank pages
    ann = A.Annotation(stem="c", page=1, bbox=(0.1, 0.1, 0.5, 0.4), verdict="주의", label="주의")
    out = tmp_path / "c_annotated.pdf"
    _, drawn, pages, oob = render_annotated_pdf(src, {1: [ann]}, out, dpi=100, font_path=_FONT)
    assert drawn == 1 and pages == 2 and oob == 0

    reader = PdfReader(str(out))
    assert len(reader.pages) == 2

    def has_xobject(page) -> bool:
        res = page.get("/Resources")
        return bool(res and res.get("/XObject"))

    assert has_xobject(reader.pages[0]), "annotated page should be rasterised (image XObject)"
    assert not has_xobject(reader.pages[1]), "unannotated page should be preserved verbatim"


@requires_font
def test_annotate_case_routes_and_guards_pages(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _write_pdf(cert_root / "9" / "certA.pdf", 2)
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [
            {"stem": "certA", "page": 1, "bbox": [0.1, 0.1, 0.5, 0.3], "verdict": "FAIL", "label": "FAIL: 화학"},
            {"stem": "certA", "page": 99, "bbox": [0.1, 0.1, 0.5, 0.3], "verdict": "주의", "label": "주의: 범위초과"},  # oob
        ],
        case_id="9",
    )
    out_dir = tmp_path / "out"
    summary = annotate_case(
        case_id="9", work_dir=work, cache_root=tmp_path, cert_dir=cert_root,
        out_dir=out_dir, annotations_path=ann_path, dpi=100, font_path=_FONT,
    )
    assert summary["n_pdfs"] == 1
    assert summary["boxes_drawn"] == 1            # oob page not drawn
    assert summary["rows_skipped"] == 1           # oob counted
    out_pdf = out_dir / "certA_annotated.pdf"
    assert out_pdf.exists()
    assert len(PdfReader(str(out_pdf)).pages) == 2  # page count preserved


@requires_font
def test_annotate_case_multi_pdf_stem_routing(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _write_pdf(cert_root / "4" / "certA.pdf", 1)
    _write_pdf(cert_root / "4" / "certB.pdf", 1)
    ann_path = tmp_path / "4_annotations.json"
    _write_annotations(
        ann_path,
        [
            {"stem": "certA", "page": 1, "bbox": [0.1, 0.1, 0.5, 0.3], "verdict": "FAIL", "label": "A"},
            {"stem": "certB", "page": 1, "bbox": [0.1, 0.1, 0.5, 0.3], "verdict": "N/A", "label": "B"},
            {"page": 1, "bbox": [0.1, 0.1, 0.5, 0.3], "verdict": "주의", "label": "no-stem"},  # 2 PDFs -> unresolved
        ],
        case_id="4",
    )
    summary = annotate_case(
        case_id="4", work_dir=work, cache_root=tmp_path, cert_dir=cert_root,
        out_dir=tmp_path / "out", annotations_path=ann_path, dpi=100, font_path=_FONT,
    )
    assert summary["n_pdfs"] == 2
    assert summary["boxes_drawn"] == 2
    assert summary["rows_skipped"] == 1  # no-stem row unresolved (case has 2 PDFs)


def test_annotate_case_missing_annotations_raises(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _write_pdf(cert_root / "9" / "certA.pdf", 1)
    with pytest.raises(FileNotFoundError):
        annotate_case(
            case_id="9", work_dir=work, cache_root=tmp_path, cert_dir=cert_root,
            annotations_path=tmp_path / "nope.json",
        )


@requires_font
def test_render_rotations_emit_upright_page(tmp_path: Path):
    """A page align-inputs rotated is burned in the aligned (upright) space."""
    src = tmp_path / "c.pdf"
    _write_pdf(src, 1)  # 400x300 (landscape source)
    ann = A.Annotation(stem="c", page=1, bbox=(0.2, 0.2, 0.8, 0.6), verdict="FAIL", label="FAIL")
    out = tmp_path / "c_annotated.pdf"
    render_annotated_pdf(src, {1: [ann]}, out, dpi=100, font_path=_FONT, rotations={1: 90})

    page = PdfReader(str(out)).pages[0]
    assert float(page.mediabox.height) > float(page.mediabox.width), (
        "burned page must be emitted in the rotated (aligned) orientation"
    )


@requires_font
def test_annotate_case_consumes_alignment_record(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _write_pdf(cert_root / "9" / "certA.pdf", 1)  # 400x300 landscape
    case_cache = tmp_path / "9"
    case_cache.mkdir(parents=True)
    (case_cache / "certA_alignment.json").write_text(
        json.dumps({"applied": {"1": 90}}), encoding="utf-8"
    )
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": [0.1, 0.1, 0.5, 0.3], "verdict": "FAIL", "label": "F"}],
        case_id="9",
    )
    summary = annotate_case(
        case_id="9", work_dir=work, cache_root=tmp_path, cert_dir=cert_root,
        out_dir=tmp_path / "out", annotations_path=ann_path, dpi=100, font_path=_FONT,
    )
    assert summary["boxes_drawn"] == 1
    page = PdfReader(str(tmp_path / "out" / "certA_annotated.pdf")).pages[0]
    assert float(page.mediabox.height) > float(page.mediabox.width)
