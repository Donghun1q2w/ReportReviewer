"""annotate_pdf regression tests.

Pure unit tests (colour/verdict mapping, label truncation, placement, the
load_annotations dual gate, the coordinate transform, and the static burn-in
regression guards) always run — they need neither the dataset nor a font. The
attach/render integration tests need a Hangul TTF (malgun.ttf, or set
CERT_REVIEW_FONT) because every annotated item carries a FreeText label whose
appearance stream is a real glyph raster; they are skipped when the font is
absent so the always-run suite stays green on non-Windows/font-less hosts.
"""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Text
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    FloatObject,
    NameObject,
    NumberObject,
)

from scripts import annotate_pdf as A
from scripts.annotate_pdf import (
    _hex_to_rgb,
    _label_for,
    _place_label,
    _truncate,
    _verdict_rgb,
    annotate_case,
    load_annotations,
    write_annotated_pdf,
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
# Shared helpers
# --------------------------------------------------------------------------- #
def _make_pdf(
    path: Path,
    pages: int,
    size: tuple[int, int] = (400, 300),
    rotate: int = 0,
    rotate_on_pages_node: bool = False,
    cropbox: tuple[float, float, float, float] | None = None,
) -> None:
    """A real PDF with a distinct content stream per page (so byte-identity bites).

    ``rotate_on_pages_node`` puts /Rotate on the /Pages node only (inherited,
    not on the leaf) — PdfReader flattens it back onto the leaf (F11/F15).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for i in range(pages):
        pg = writer.add_blank_page(width=size[0], height=size[1])
        st = DecodedStreamObject()
        st.set_data(f"q 0 0 1 RG {20 + i} 20 200 100 re S Q".encode("latin-1"))
        pg[NameObject("/Contents")] = writer._add_object(st)
        if rotate and not rotate_on_pages_node:
            pg[NameObject("/Rotate")] = NumberObject(rotate)
        if cropbox is not None:
            pg[NameObject("/CropBox")] = ArrayObject([FloatObject(v) for v in cropbox])
    if rotate and rotate_on_pages_node:
        writer._root_object["/Pages"][NameObject("/Rotate")] = NumberObject(rotate)
    with open(path, "wb") as fh:
        writer.write(fh)


def _attach(
    tmp_path: Path,
    anns_by_page: dict,
    *,
    pages: int = 1,
    rotate: int = 0,
    cropbox: tuple[float, float, float, float] | None = None,
    rotations: dict[int, int] | None = None,
) -> tuple[tuple, Path]:
    """_make_pdf -> write_annotated_pdf; returns (result tuple, output path)."""
    src = tmp_path / "src.pdf"
    _make_pdf(src, pages, rotate=rotate, cropbox=cropbox)
    out = tmp_path / "out.pdf"
    res = write_annotated_pdf(src, anns_by_page, out, rotations=rotations, font_path=_FONT)
    return res, out


def _content_bytes(page) -> bytes:
    c = page.get_contents()
    return c.get_data() if c is not None else b""


def _annots(page) -> list:
    return [a.get_object() for a in (page.get("/Annots") or [])]


def _by_subtype(annots: list, subtype: str):
    return [a for a in annots if str(a.get("/Subtype")) == subtype]


def _square(annots: list):
    return _by_subtype(annots, "/Square")[0]


def _freetext(annots: list):
    return _by_subtype(annots, "/FreeText")[0]


def _imported_top_level(src: str) -> set[str]:
    """Top-level module names imported by ``src`` (import + from-import)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _write_annotations(path: Path, records: list[dict], case_id: str = "9") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"case_id": case_id, "annotations": records}, ensure_ascii=False),
        encoding="utf-8",
    )


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
# T1. Coordinate accuracy (always run — pure geometry)
# --------------------------------------------------------------------------- #
def test_aligned_to_user_frac_all_rotations():
    assert A._aligned_to_user_frac(0.25, 0.25, 0) == (0.25, 0.25)
    assert A._aligned_to_user_frac(0.25, 0.25, 90) == (0.25, 0.75)
    assert A._aligned_to_user_frac(0.25, 0.25, 180) == (0.75, 0.75)
    assert A._aligned_to_user_frac(0.25, 0.25, 270) == (0.75, 0.25)
    with pytest.raises(ValueError):
        A._aligned_to_user_frac(0.5, 0.5, 45)
    # forward (user->aligned) composed with the inverse returns the point
    fwd = {
        0: lambda a, b: (a, b),
        90: lambda a, b: (1 - b, a),
        180: lambda a, b: (1 - a, 1 - b),
        270: lambda a, b: (b, 1 - a),
    }
    for t, f in fwd.items():
        u, v = f(0.3, 0.7)
        assert A._aligned_to_user_frac(u, v, t) == pytest.approx((0.3, 0.7))


def test_aligned_bbox_to_user_rect_literals():
    bbox = (0.25, 0.25, 0.5, 0.5)
    assert list(A.aligned_bbox_to_user_rect(bbox, 0, 0, 400, 300, 0)) == pytest.approx(
        [100, 150, 200, 225], abs=0.01
    )
    assert list(A.aligned_bbox_to_user_rect(bbox, 0, 0, 400, 300, 90)) == pytest.approx(
        [100, 75, 200, 150], abs=0.01
    )
    assert list(A.aligned_bbox_to_user_rect(bbox, 0, 0, 400, 300, 180)) == pytest.approx(
        [200, 75, 300, 150], abs=0.01
    )
    assert list(A.aligned_bbox_to_user_rect(bbox, 0, 0, 400, 300, 270)) == pytest.approx(
        [200, 150, 300, 225], abs=0.01
    )
    # case 46 p1 CropBox offset (F13): crop=(3.96001, 2.88, 599.76, 845.28), T=0
    got = A.aligned_bbox_to_user_rect(
        bbox, 3.96001, 2.88, 599.76 - 3.96001, 845.28 - 2.88, 0
    )
    assert list(got) == pytest.approx([152.91, 424.08, 301.86, 634.68], abs=0.01)


@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations", "expected_rect"),
    [
        pytest.param(90, None, [100, 75, 200, 150], id="R90-A0-T90"),
        pytest.param(0, {1: 90}, [100, 75, 200, 150], id="R0-A90-T90-PU2601233"),
        pytest.param(90, {1: 270}, [100, 150, 200, 225], id="R90-A270-T0-PU2601565"),
    ],
)
def test_rect_matches_metadata_rotation(tmp_path: Path, rotate, rotations, expected_rect):
    ann = A.Annotation(stem="c", page=1, bbox=(0.25, 0.25, 0.5, 0.5), verdict="FAIL", label="F")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate, rotations=rotations)
    sq = _square(_annots(PdfReader(str(out)).pages[0]))
    assert [float(v) for v in sq["/Rect"]] == pytest.approx(expected_rect, abs=0.01)


@requires_font
def test_inherited_rotate_resolved(tmp_path: Path):
    """/Rotate on the /Pages node (inherited) still yields the T=90 /Rect."""
    src = tmp_path / "inh.pdf"
    _make_pdf(src, 1, rotate=90, rotate_on_pages_node=True)
    assert PdfReader(str(src)).pages[0].get("/Rotate") == 90  # PdfReader flattens (F11)
    ann = A.Annotation(stem="c", page=1, bbox=(0.25, 0.25, 0.5, 0.5), verdict="FAIL", label="F")
    out = tmp_path / "inh_out.pdf"
    write_annotated_pdf(src, {1: [ann]}, out, font_path=_FONT)
    sq = _square(_annots(PdfReader(str(out)).pages[0]))
    assert [float(v) for v in sq["/Rect"]] == pytest.approx([100, 75, 200, 150], abs=0.01)


# --------------------------------------------------------------------------- #
# T2. Page integrity
# --------------------------------------------------------------------------- #
@requires_font
def test_all_pages_content_bytes_identical(tmp_path: Path):
    src = tmp_path / "c.pdf"
    _make_pdf(src, 3)  # distinct per-page content
    orig = [_content_bytes(p) for p in PdfReader(str(src)).pages]
    ann = A.Annotation(stem="c", page=2, bbox=(0.1, 0.1, 0.5, 0.4), verdict="주의", label="주의: 확인")
    out = tmp_path / "c_out.pdf"
    write_annotated_pdf(src, {2: [ann]}, out, font_path=_FONT)
    r = PdfReader(str(out))
    assert len(r.pages) == 3
    for i in range(3):
        assert _content_bytes(r.pages[i]) == orig[i]
        assert [float(v) for v in r.pages[i].mediabox] == [0, 0, 400, 300]
        assert r.pages[i].get("/Rotate") in (None, 0)


@requires_font
def test_preexisting_annots_preserved(tmp_path: Path):
    src = tmp_path / "pre.pdf"
    _make_pdf(src, 1)
    w = PdfWriter(clone_from=str(src))
    w.add_annotation(0, Text(text="pre-existing", rect=(10, 10, 30, 30)))
    src2 = tmp_path / "pre_annot.pdf"
    with open(src2, "wb") as fh:
        w.write(fh)
    orig = _content_bytes(PdfReader(str(src2)).pages[0])
    ann = A.Annotation(stem="c", page=1, bbox=(0.2, 0.2, 0.6, 0.5), verdict="FAIL", label="FAIL: 사전주석 보존")
    out = tmp_path / "pre_out.pdf"
    write_annotated_pdf(src2, {1: [ann]}, out, font_path=_FONT)
    annots = _annots(PdfReader(str(out)).pages[0])
    subs = [str(a.get("/Subtype")) for a in annots]
    assert "/Text" in subs          # pre-existing preserved
    assert "/Square" in subs and "/FreeText" in subs  # new appended
    assert _content_bytes(PdfReader(str(out)).pages[0]) == orig


# --------------------------------------------------------------------------- #
# T3. Annotation object fields
# --------------------------------------------------------------------------- #
@requires_font
def test_square_and_freetext_fields(tmp_path: Path):
    anns = [
        A.Annotation("c", 1, (0.10, 0.10, 0.40, 0.30), "주의", "주의: A"),
        A.Annotation("c", 1, (0.50, 0.10, 0.80, 0.30), "N/A", "N/A: B"),
        A.Annotation("c", 1, (0.10, 0.50, 0.40, 0.70), "FAIL", "FAIL: C"),
    ]
    (_, drawn, _, _), out = _attach(tmp_path, {1: anns})
    assert drawn == 3
    annots = _annots(PdfReader(str(out)).pages[0])
    assert len(_by_subtype(annots, "/Square")) == 3
    assert len(_by_subtype(annots, "/Popup")) == 3
    assert len(_by_subtype(annots, "/FreeText")) == 3
    assert len(annots) == 9   # (Square + Popup + FreeText) x 3

    for sq in _by_subtype(annots, "/Square"):
        assert "/IC" not in sq                     # border-only, no fill
        assert len(sq["/C"]) == 3                  # verdict RGB in 0..1
        assert int(sq["/BS"]["/W"]) == 2 and str(sq["/BS"]["/S"]) == "/S"
        assert int(sq["/F"]) == 4
        assert str(sq.get("/T")) == "cert-review"
        assert str(sq.get("/Subj")) in {"주의", "N/A", "FAIL"}
        assert str(sq.get("/NM")).startswith("cert-review-p01-")
        assert "/AP" not in sq                     # Square carries no self /AP (F4)
        assert "/Popup" in sq

    for ft in _by_subtype(annots, "/FreeText"):
        assert str(ft.get("/Contents")).split(":")[0] in {"주의", "N/A", "FAIL"}
        assert str(ft.get("/DA")) == "/Helv 10 Tf 0 g"
        assert int(ft["/F"]) == 4
        assert str(ft.get("/T")) == "cert-review"
        assert str(ft.get("/Subj")) in {"주의", "N/A", "FAIL"}
        assert str(ft.get("/NM")).endswith("-label")
        n = ft["/AP"]["/N"].get_object()
        assert str(n.get("/Subtype")) == "/Form"
        assert "/Popup" not in ft                  # label overlay, no comment popup


@requires_font
def test_pass_injected_directly_yields_no_annotations(tmp_path: Path):
    ann = A.Annotation("c", 1, (0.1, 0.1, 0.4, 0.3), "PASS", "PASS: x")
    (_, drawn, _, _), out = _attach(tmp_path, {1: [ann]})
    assert drawn == 0
    assert _annots(PdfReader(str(out)).pages[0]) == []


@requires_font
@pytest.mark.parametrize(
    ("rotate", "expected_matrix"),
    [
        pytest.param(90, [0, 1, -1, 0, 0, 0], id="T90-has-matrix"),
        pytest.param(0, None, id="T0-no-matrix"),
    ],
)
def test_label_ap_matrix_on_rotated_page(tmp_path: Path, rotate, expected_matrix):
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 회전")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate)
    n = _freetext(_annots(PdfReader(str(out)).pages[0]))["/AP"]["/N"].get_object()
    if expected_matrix is None:
        assert "/Matrix" not in n
    else:
        assert [float(v) for v in n["/Matrix"]] == expected_matrix


# --------------------------------------------------------------------------- #
# T3c. Square <-> Popup bidirectional link
# --------------------------------------------------------------------------- #
@requires_font
def test_square_popup_bidirectional_link(tmp_path: Path):
    anns = [
        A.Annotation("c", 1, (0.1, 0.1, 0.4, 0.3), "FAIL", "FAIL: X"),
        A.Annotation("c", 1, (0.5, 0.5, 0.8, 0.7), "주의", "주의: Y"),
    ]
    _, out = _attach(tmp_path, {1: anns})
    annots = _annots(PdfReader(str(out)).pages[0])
    squares = _by_subtype(annots, "/Square")
    assert len(squares) == 2

    stamps = set()
    for sq in squares:
        pop = sq["/Popup"].get_object()
        assert str(pop.get("/Subtype")) == "/Popup"
        # round-trip: popup's /Parent points back to this Square
        assert str(pop["/Parent"].get_object().get("/NM")) == str(sq.get("/NM"))
        assert pop.get("/Open") in (None, False)    # collapsed popup
        assert "/Contents" not in pop               # empty thread (== reference doc)
        # timestamps: format only, never an exact literal
        assert re.fullmatch(r"D:\d{14}", str(sq.get("/M")))
        assert re.fullmatch(r"D:\d{14}", str(sq.get("/CreationDate")))
        assert str(sq.get("/M")) == str(sq.get("/CreationDate"))
        stamps.add(str(sq.get("/M")))
    assert len(stamps) == 1   # one _pdf_now() per call -> shared stamp


# --------------------------------------------------------------------------- #
# T4. Boundary values
# --------------------------------------------------------------------------- #
@requires_font
def test_full_page_bbox(tmp_path: Path):
    ann = A.Annotation("c", 1, (0.0, 0.0, 1.0, 1.0), "FAIL", "full")
    _, out = _attach(tmp_path, {1: [ann]}, cropbox=(0, 0, 400, 300))
    sq = _square(_annots(PdfReader(str(out)).pages[0]))
    assert [float(v) for v in sq["/Rect"]] == pytest.approx([0, 0, 400, 300], abs=0.01)


@requires_font
def test_label_truncation_flows_to_contents(tmp_path: Path):
    p = tmp_path / "9_annotations.json"
    _write_annotations(p, [{"stem": "c", "page": 1, "bbox": [0.1, 0.1, 0.5, 0.4], "verdict": "FAIL", "label": "가" * 60}])
    anns, _ = load_annotations(p)
    assert len(anns[0].label) == 50 and anns[0].label.endswith("…")
    _, out = _attach(tmp_path, {1: anns})
    sq = _square(_annots(PdfReader(str(out)).pages[0]))
    contents = str(sq.get("/Contents"))
    assert len(contents) == 50 and contents.endswith("…")


@requires_font
@pytest.mark.parametrize(
    ("verdict2", "expected_bundles"),
    [
        pytest.param("FAIL", 1, id="identical-deduped"),
        pytest.param("주의", 2, id="different-verdict-kept"),
    ],
)
def test_same_bbox_dedupe_keyed_on_verdict(tmp_path: Path, verdict2, expected_bundles):
    anns = [
        A.Annotation("c", 1, (0.1, 0.1, 0.5, 0.4), "FAIL", "x"),
        A.Annotation("c", 1, (0.1, 0.1, 0.5, 0.4), verdict2, "x"),
    ]
    (_, drawn, _, _), out = _attach(tmp_path, {1: anns})
    assert drawn == expected_bundles
    assert len(_annots(PdfReader(str(out)).pages[0])) == 3 * expected_bundles


@requires_font
def test_oob_page_counted_not_attached(tmp_path: Path):
    anns_by_page = {
        1: [A.Annotation("c", 1, (0.1, 0.1, 0.5, 0.4), "FAIL", "ok")],
        99: [A.Annotation("c", 99, (0.1, 0.1, 0.5, 0.4), "주의", "oob")],
    }
    (_, drawn, pages, oob), _ = _attach(tmp_path, anns_by_page, pages=2)
    assert drawn == 1 and pages == 2 and oob == 1


@requires_font
def test_annotate_case_routes_and_guards_pages(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _make_pdf(cert_root / "9" / "certA.pdf", 2)
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
        out_dir=out_dir, annotations_path=ann_path, font_path=_FONT,
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
    _make_pdf(cert_root / "4" / "certA.pdf", 1)
    _make_pdf(cert_root / "4" / "certB.pdf", 1)
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
        out_dir=tmp_path / "out", annotations_path=ann_path, font_path=_FONT,
    )
    assert summary["n_pdfs"] == 2
    assert summary["boxes_drawn"] == 2
    assert summary["rows_skipped"] == 1  # no-stem row unresolved (case has 2 PDFs)


def test_annotate_case_missing_annotations_raises(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _make_pdf(cert_root / "9" / "certA.pdf", 1)
    with pytest.raises(FileNotFoundError):
        annotate_case(
            case_id="9", work_dir=work, cache_root=tmp_path, cert_dir=cert_root,
            annotations_path=tmp_path / "nope.json",
        )


@requires_font
def test_annotate_case_consumes_alignment_record(tmp_path: Path):
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    _make_pdf(cert_root / "9" / "certA.pdf", 1)  # 400x300
    case_cache = tmp_path / "9"
    case_cache.mkdir(parents=True)
    (case_cache / "certA_alignment.json").write_text(
        json.dumps({"applied": {"1": 90}}), encoding="utf-8"
    )
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": [0.25, 0.25, 0.5, 0.5], "verdict": "FAIL", "label": "F"}],
        case_id="9",
    )
    summary = annotate_case(
        case_id="9", work_dir=work, cache_root=tmp_path, cert_dir=cert_root,
        out_dir=tmp_path / "out", annotations_path=ann_path, font_path=_FONT,
    )
    assert summary["boxes_drawn"] == 1
    page = PdfReader(str(tmp_path / "out" / "certA_annotated.pdf")).pages[0]
    assert [float(v) for v in page.mediabox] == [0, 0, 400, 300]  # MediaBox unchanged (no raster)
    sq = _square(_annots(page))
    assert [float(v) for v in sq["/Rect"]] == pytest.approx([100, 75, 200, 150], abs=0.01)  # T=90


# --------------------------------------------------------------------------- #
# T5. Deletability
# --------------------------------------------------------------------------- #
@requires_font
def test_delete_annotation_preserves_content(tmp_path: Path):
    src = tmp_path / "c.pdf"
    _make_pdf(src, 1)
    orig = _content_bytes(PdfReader(str(src)).pages[0])
    ann = A.Annotation("c", 1, (0.2, 0.2, 0.6, 0.5), "FAIL", "FAIL: 삭제 테스트")
    out = tmp_path / "c_out.pdf"
    write_annotated_pdf(src, {1: [ann]}, out, font_path=_FONT)
    # drop the FreeText, keep Square + Popup
    w = PdfWriter(clone_from=str(out))
    page0 = w.pages[0]
    arr = page0[NameObject("/Annots")]
    page0[NameObject("/Annots")] = ArrayObject(
        [a for a in arr if a.get_object().get("/Subtype") != "/FreeText"]
    )
    out2 = tmp_path / "c_del.pdf"
    with open(out2, "wb") as fh:
        w.write(fh)
    r = PdfReader(str(out2))
    assert _content_bytes(r.pages[0]) == orig
    subs = [str(a.get("/Subtype")) for a in _annots(r.pages[0])]
    assert "/Square" in subs and "/Popup" in subs and "/FreeText" not in subs


# --------------------------------------------------------------------------- #
# T6. Rendering proxy (require a Hangul font)
# --------------------------------------------------------------------------- #
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


def _dark_pixel_count(img, step=2) -> int:
    px = img.load()
    w, h = img.size
    return sum(
        1 for y in range(0, h, step) for x in range(0, w, step) if sum(px[x, y][:3]) < 250
    )


@requires_font
def test_square_renders_in_pdfium(tmp_path: Path):
    ann = A.Annotation("c", 1, (0.2, 0.2, 0.8, 0.6), "FAIL", "FAIL: 렌더")
    _, out = _attach(tmp_path, {1: [ann]})
    img = _render_first_page(out)
    assert _has_color(img, _FAIL_RGB), "Square border/label colour not found within tolerance"


@requires_font
def test_freetext_label_renders_in_pdfium(tmp_path: Path):
    ann = A.Annotation("c", 1, (0.2, 0.2, 0.8, 0.5), "주의", "주의: 한글 라벨 렌더 확인")
    _, out = _attach(tmp_path, {1: [ann]})
    img = _render_first_page(out)
    assert _has_color(img, _WARN_RGB), "label chip background not rendered"
    assert _dark_pixel_count(img) > 50, "no dark glyph pixels — Korean label not rendered"
    # rotated page: the /AP /Matrix path still renders glyphs (Popup is invisible)
    rot_dir = tmp_path / "rot"
    rot_dir.mkdir()
    _, out2 = _attach(rot_dir, {1: [ann]}, rotate=90)
    assert _dark_pixel_count(_render_first_page(out2)) > 50, "rotated label not rendered"


# --------------------------------------------------------------------------- #
# T7. Static regression (always run — no font, no dataset)
# --------------------------------------------------------------------------- #
def test_no_forbidden_imports():
    forbidden = {"fitz", "pymupdf", "pdfplumber", "pdfminer", "pytesseract", "easyocr",
                 "paddleocr", "openai", "anthropic"}
    names = _imported_top_level(Path(A.__file__).read_text(encoding="utf-8"))
    assert forbidden.isdisjoint(names), f"forbidden import: {forbidden & names}"


def test_no_burnin_symbols():
    src = Path(A.__file__).read_text(encoding="utf-8")
    assert "pypdfium2" not in _imported_top_level(src)
    for sym in ("_render_page_pil", "_draw_annotations", "render_annotated_pdf",
                "_LINE_W_PER_DPI", "_FONT_PX_PER_DPI"):
        assert sym not in src, f"burn-in symbol still present: {sym}"


def test_cli_annotate_rejects_dpi(capsys):
    """`annotate --dpi` must be an explicit argparse error (exit code 2)."""
    from scripts.cli import main as cli_main

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["annotate", "--case", "x", "--dpi", "200"])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err and "--dpi" in err


def test_skillmd_no_stale_wording():
    skill = Path(A.__file__).parents[2] / "cert-review-annotate" / "SKILL.md"
    text = skill.read_text(encoding="utf-8").lower()
    assert "burn-in" not in text
    assert "burn in" not in text
    assert "--dpi" not in text
