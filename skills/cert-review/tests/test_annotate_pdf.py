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
from pypdf.errors import PdfStreamError
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    FloatObject,
    NameObject,
    NumberObject,
)

from scripts import annotate_pdf as A
from scripts import upright_pdf as UP
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
from tests.test_upright_pdf import (  # shared synthetic-PDF fixtures (6.1)
    _color_bbox,
    _make_corrupt_pdf,
    _make_encrypted_pdf,
    _render,
    _rotate_cw,
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


# raw fractional -> display fractional; the exact inverse of
# A._aligned_to_user_frac (pinned by test_aligned_to_user_frac_all_rotations).
_FWD_FRAC = {
    0: lambda a, b: (a, b),
    90: lambda a, b: (1 - b, a),
    180: lambda a, b: (1 - a, 1 - b),
    270: lambda a, b: (b, 1 - a),
}


def _chip_geometry(ft) -> tuple[list[float], float, float]:
    """FreeText annot -> (/Rect as floats, chip width, chip height from /AP /BBox)."""
    rc = [float(v) for v in ft["/Rect"]]
    bx = [float(v) for v in ft["/AP"]["/N"].get_object()["/BBox"]]
    return rc, bx[2] - bx[0], bx[3] - bx[1]


def _assert_rect_matches_bbox(ft) -> tuple[list[float], float, float]:
    """_chip_geometry(ft), plus the /Rect-size == /AP /BBox-size invariant every
    NoRotate label must hold (a diverging pair means a viewer would scale the
    glyphs to fit /Rect, distorting them)."""
    rc, chip_w, chip_h = _chip_geometry(ft)
    assert rc[2] - rc[0] == pytest.approx(chip_w, abs=1e-6)
    assert rc[3] - rc[1] == pytest.approx(chip_h, abs=1e-6)
    return rc, chip_w, chip_h


def _display_chip(ft, rotate: int, wp: float = 400.0, hp: float = 300.0):
    """FreeText -> (chip box as the reader sees it, display page w, display page h).

    Forward-maps the NoRotate anchor (llx, ury) out of user space with _FWD_FRAC
    and unfolds the /AP /BBox size down-and-right from it — i.e. exactly what a
    NoRotate-implementing viewer does, so every assertion built on it is about
    what is actually seen rather than about raw coordinates.
    """
    rc, chip_w, chip_h = _chip_geometry(ft)
    ws, hs = A._aligned_page_size_pt(wp, hp, rotate)
    u, v = _FWD_FRAC[rotate](rc[0] / wp, (hp - rc[3]) / hp)
    return (u * ws, v * hs, u * ws + chip_w, v * hs + chip_h), ws, hs


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
    for t, f in _FWD_FRAC.items():
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


def test_label_rect_for_norotate_literals():
    """The NoRotate anchor: one corner transformed, natural size unfolded from it."""
    chip, size = (0.25, 0.25), (60.0, 14.0)
    f = A.label_rect_for_norotate
    assert list(f(chip, size, 0, 0, 400, 300, 0)) == pytest.approx([100, 211, 160, 225], abs=0.01)
    assert list(f(chip, size, 0, 0, 400, 300, 90)) == pytest.approx([100, 61, 160, 75], abs=0.01)
    assert list(f(chip, size, 0, 0, 400, 300, 180)) == pytest.approx([300, 61, 360, 75], abs=0.01)
    assert list(f(chip, size, 0, 0, 400, 300, 270)) == pytest.approx([300, 211, 360, 225], abs=0.01)
    # case 46 p1 CropBox offset (F13), r=0
    got = f(chip, size, 3.96001, 2.88, 599.76 - 3.96001, 845.28 - 2.88, 0)
    assert list(got) == pytest.approx([152.91, 620.68, 212.91, 634.68], abs=0.01)
    # the /Rect is always a valid, natural-shaped rectangle on every rotation
    for r in (0, 90, 180, 270):
        x0, y0, x1, y1 = f(chip, size, 0, 0, 400, 300, r)
        assert x1 - x0 == pytest.approx(60.0) and y1 - y0 == pytest.approx(14.0)
    with pytest.raises(ValueError):        # reuses _aligned_to_user_frac's guard
        f(chip, size, 0, 0, 400, 300, 45)


def test_aligned_bbox_to_display_box_undoes_applied_rotation():
    """All four applied rotations, including the 180 that misplaces a chip by 300px."""
    bbox = (0.25, 0.25, 0.5, 0.5)
    g = A._aligned_bbox_to_display_box
    assert list(g(bbox, 400, 300, 0)) == pytest.approx([100, 75, 200, 150], abs=0.01)
    assert list(g(bbox, 400, 300, 90)) == pytest.approx([100, 150, 200, 225], abs=0.01)
    assert list(g(bbox, 400, 300, 180)) == pytest.approx([200, 150, 300, 225], abs=0.01)
    assert list(g(bbox, 300, 400, 270)) == pytest.approx([150, 100, 225, 200], abs=0.01)


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
        assert int(ft["/F"]) == 4 | 16   # Print + NoRotate (label stays viewer-horizontal)
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
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_label_ap_never_carries_matrix_and_sets_norotate(tmp_path: Path, rotate):
    """The /AP /Matrix trick is gone; NoRotate + a naturally shaped /Rect replace it.

    Acrobat throws a FreeText's /AP away on a mere resize, so the label must not
    depend on one: /F bit 5 (NoRotate) keeps it viewer-horizontal and /Rect keeps
    the chip's unrotated width x height on every page rotation.
    """
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 회전")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate)
    annots = _annots(PdfReader(str(out)).pages[0])
    ft = _freetext(annots)

    assert "/Matrix" not in ft["/AP"]["/N"].get_object()
    assert int(ft["/F"]) == 20                       # 4 Print | 16 NoRotate
    assert int(_square(annots)["/F"]) == 4           # Square untouched
    assert "/F" not in _by_subtype(annots, "/Popup")[0]   # pypdf's Popup carries no flags

    rc, _, _ = _assert_rect_matches_bbox(ft)
    assert rc[2] > rc[0] and rc[3] > rc[1]           # RectangleObject does not normalise


@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(0, None, id="R0-A0-T0"),
        pytest.param(90, None, id="R90-A0-T90"),
        pytest.param(180, None, id="R180-A0-T180"),
        pytest.param(270, None, id="R270-A0-T270"),
        pytest.param(0, {1: 90}, id="R0-A90-T90-PU2601233"),
        pytest.param(90, {1: 270}, id="R90-A270-T0-PU2601565"),
        pytest.param(0, {1: 180}, id="R0-A180-T180"),   # worst measured drift: 300px
    ],
)
def test_label_anchor_lands_beside_the_square_in_display_space(tmp_path, rotate, rotations):
    """The label must sit next to its box *as the viewer sees it*, for every (R, A).

    Anchoring with T instead of the page's own /Rotate silently misplaces the chip
    by up to a third of the page whenever the applied rotation is non-zero; the
    (0, 180) case is the measured worst one and must never leave this list.
    """
    bbox = (0.25, 0.25, 0.5, 0.5)
    ann = A.Annotation("c", 1, bbox, "FAIL", "FAIL: 배치")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate, rotations=rotations)
    ft = _freetext(_annots(PdfReader(str(out)).pages[0]))
    chip, ws, hs = _display_chip(ft, rotate)
    # (chip is always wider than tall by construction of _display_chip/_chip_geometry
    # — that isn't rotation evidence; test_label_renders_horizontal_on_every_page_rotation
    # is what actually observes the rendered pixels. This test's job is position.)
    box = A._aligned_bbox_to_display_box(bbox, ws, hs, (rotations or {}).get(1, 0))
    assert not A._rects_overlap(chip, box), f"label overlaps its box: {chip} vs {box}"
    gap_x = max(box[0] - chip[2], chip[0] - box[2], 0.0)
    gap_y = max(box[1] - chip[3], chip[1] - box[3], 0.0)
    assert max(gap_x, gap_y) <= A.LABEL_GAP_PT + 2 * A.LABEL_BOX_PAD + 0.01


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
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_zero_chip_padding_keeps_rect_and_bbox_in_sync(tmp_path: Path, monkeypatch, rotate):
    """Boundary: no chip padding at all — /Rect must still equal the /AP /BBox.

    Parametrised over every rotation so DoD D6's "all rotations x both paddings"
    claim is literally what runs, not an extrapolation from a single rotate=90.
    """
    monkeypatch.setattr(A, "LABEL_BOX_PAD", 0.0)
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 패딩0")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate)
    ft = _freetext(_annots(PdfReader(str(out)).pages[0]))
    _assert_rect_matches_bbox(ft)
    assert int(ft["/F"]) == 20


@requires_font
def test_applied_rotation_normalised_modulo_360(tmp_path: Path):
    """450 deg must behave exactly like 90 deg (it did before NoRotate too)."""
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "F")
    _, o1 = _attach(tmp_path, {1: [ann]}, rotate=0, rotations={1: 90})
    d2 = tmp_path / "d2"
    d2.mkdir()
    _, o2 = _attach(d2, {1: [ann]}, rotate=0, rotations={1: 450})
    r1, _, _ = _chip_geometry(_freetext(_annots(PdfReader(str(o1)).pages[0])))
    r2, _, _ = _chip_geometry(_freetext(_annots(PdfReader(str(o2)).pages[0])))
    assert r1 == pytest.approx(r2, abs=0.01)


@requires_font
def test_invalid_applied_rotation_still_raises(tmp_path: Path):
    """Bad input keeps the pre-existing failure mode — no new defensive code."""
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "F")
    with pytest.raises(ValueError):
        _attach(tmp_path, {1: [ann]}, rotate=0, rotations={1: 45})


@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(90, None, id="R90-A0"),
        pytest.param(0, {1: 90}, id="R0-A90-display-space"),
    ],
)
def test_max_length_label_on_rotated_page_stays_clamped(tmp_path: Path, rotate, rotations):
    """A 50-char label is wider than the display page: _place_label's clamp must
    still bite in display space, and /Rect must stay in sync with the /AP /BBox.

    Parametrised with a=90 (not just r=90) so this actually exercises the
    display-space clamp path, not just the case where display == aligned space.
    """
    ann = A.Annotation("c", 1, (0.85, 0.85, 0.98, 0.95), "FAIL", "가" * 49 + "…")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate, rotations=rotations)
    ft = _freetext(_annots(PdfReader(str(out)).pages[0]))
    _assert_rect_matches_bbox(ft)
    chip, ws, hs = _display_chip(ft, rotate)
    assert chip[0] >= -A.LABEL_BOX_PAD - 0.01                     # clamped to the left edge
    assert -A.LABEL_BOX_PAD - 0.01 <= chip[1] <= hs + A.LABEL_BOX_PAD + 0.01
    # No right/bottom bound: the clamp is left/top-only (max(0, min(cx, page_w-tw)))
    # and this label's chip (497.5pt) is deliberately wider than the display page
    # (ws=300 or 400), so the chip legitimately overflows past the right edge —
    # that overflow is the pre-existing, unchanged behavior this test documents.


@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(90, None, id="R90-A0-three-labels"),
        pytest.param(0, {1: 90}, id="R0-A90-three-labels"),
    ],
)
def test_multiple_labels_on_rotated_page_do_not_overlap(tmp_path: Path, rotate, rotations):
    """Three labels on one *rotated* page: the shared display space must hold.

    write_annotated_pdf computes ws/hs/a once per page and every label on that page
    reuses them through the same `placed` list. The pre-NoRotate multi-annotation
    test runs at rotate=0, where display space == aligned space, so it never
    exercises this. The boxes are deliberately close enough that the first chip's
    preferred slot is taken, forcing _place_label's above -> below -> right fallback.

    Only each chip's own Square is asserted clear: _place_label avoids other
    *labels* and the page edge, never other annotations' boxes — a pre-existing
    property of the untouched function, not something this change may claim.
    """
    anns = [
        A.Annotation("c", 1, (0.10, 0.50, 0.30, 0.65), "FAIL", "FAIL: 가"),
        A.Annotation("c", 1, (0.14, 0.50, 0.34, 0.65), "주의", "주의: 나"),
        A.Annotation("c", 1, (0.18, 0.50, 0.38, 0.65), "N/A", "N/A: 다"),
    ]
    (_, drawn, _, _), out = _attach(tmp_path, {1: anns}, rotate=rotate, rotations=rotations)
    assert drawn == 3
    annots = _annots(PdfReader(str(out)).pages[0])
    squares = _by_subtype(annots, "/Square")
    freetexts = _by_subtype(annots, "/FreeText")
    assert len(squares) == 3 and len(freetexts) == 3

    a = (rotations or {}).get(1, 0)
    chips = []
    for ann, sq, ft in zip(anns, squares, freetexts):
        assert str(ft["/NM"]) == f"{sq['/NM']}-label"   # pairing is explicit, not positional
        chip, ws, hs = _display_chip(ft, rotate)
        own_box = A._aligned_bbox_to_display_box(ann.bbox, ws, hs, a)
        assert not A._rects_overlap(chip, own_box), f"label sits on its own box: {chip}"
        chips.append(chip)

    for i in range(len(chips)):
        for j in range(i + 1, len(chips)):
            assert not A._rects_overlap(chips[i], chips[j]), (
                f"labels {i} and {j} overlap in display space: {chips[i]} vs {chips[j]}"
            )


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
def test_annotate_case_normalizes_alignment_rotation(tmp_path: Path):
    """The a != 0 path now goes through the upright preprocessing (deliberate change).

    Replaces ``test_annotate_case_consumes_alignment_record``. The old expectations
    (Square /Rect (100, 75, 200, 150) on a 400x300 MediaBox, T=90) belong to the
    *fallback* path from here on; the direct ``write_annotated_pdf`` tests
    (``test_rect_matches_metadata_rotation``, ``test_label_anchor_lands_beside_the_``
    ``square_in_display_space``, A5, A8) keep pinning them, so no coverage is lost.
    """
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
    assert summary["outputs"][0]["upright"] is True
    assert summary["outputs"][0]["skipped"] is False
    assert (case_cache / "upright" / "certA_upright.pdf").exists()
    reader = PdfReader(str(tmp_path / "out" / "certA_annotated.pdf"))
    page = reader.pages[0]
    # upright 정규화로 90도 bake — w/h 스왑, 래스터 아님
    assert [float(v) for v in page.mediabox] == [0, 0, 300, 400]
    assert all(p.get("/Rotate") in (None, 0) for p in reader.pages)
    sq = _square(_annots(page))
    assert [float(v) for v in sq["/Rect"]] == pytest.approx([75, 200, 150, 300], abs=0.01)  # t=0
    # The real entry point must produce NoRotate labels too.
    ft = _freetext(_annots(page))
    assert int(ft["/F"]) == 20                      # 4 Print | 16 NoRotate
    assert "/Matrix" not in ft["/AP"]["/N"].get_object()
    _assert_rect_matches_bbox(ft)


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


def _dark_pixel_bbox(img, step=2):
    """Bounding box of the label chip: its grey border (80,80,80) and black glyphs
    are the only sub-250 sum pixels — the verdict fills (sum >= 646) and the test
    page's pure-blue stroke (sum 255) never qualify."""
    px = img.load()
    w, h = img.size
    xs, ys = [], []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if sum(px[x, y][:3]) < 250:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


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
    # rotated page: NoRotate + the natural /Rect still render glyphs (Popup is invisible)
    rot_dir = tmp_path / "rot"
    rot_dir.mkdir()
    _, out2 = _attach(rot_dir, {1: [ann]}, rotate=90)
    assert _dark_pixel_count(_render_first_page(out2)) > 50, "rotated label not rendered"


@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(0, None, id="R0-A0"),
        pytest.param(90, None, id="R90-A0"),
        pytest.param(180, None, id="R180-A0"),
        pytest.param(270, None, id="R270-A0"),
        pytest.param(0, {1: 90}, id="R0-A90-T90-PU2601233"),
        pytest.param(90, {1: 270}, id="R90-A270-T0-PU2601565"),
    ],
)
def test_label_renders_horizontal_on_every_page_rotation(tmp_path: Path, rotate, rotations):
    """pdfium (which implements NoRotate) must draw the chip wider than tall.

    This is the only *pixel* evidence in the suite, so the two real applied-rotation
    cases belong here too — reading /AP /BBox instead would prove nothing about how
    the annotation is actually composited onto a rotated page.
    """
    ann = A.Annotation("c", 1, (0.2, 0.2, 0.8, 0.5), "주의", "주의: 한글 라벨 렌더 확인")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate, rotations=rotations)
    img = _render_first_page(out)
    assert _has_color(img, _WARN_RGB), "label chip background not rendered"
    bb = _dark_pixel_bbox(img)
    assert bb is not None, "no dark chip/glyph pixels — Korean label not rendered"
    assert (bb[2] - bb[0]) > (bb[3] - bb[1]), (
        f"chip is taller than wide at /Rotate={rotate}, applied={rotations}"
        " — it rotated with the page"
    )


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


def test_no_ap_matrix_symbol():
    """The /AP rotation-matrix trick must be gone (Acrobat drops it on resize)."""
    src = Path(A.__file__).read_text(encoding="utf-8")
    assert "_AP_MATRIX" not in src


def test_cli_annotate_rejects_dpi(capsys):
    """`annotate --dpi` must be an explicit argparse error (exit code 2)."""
    from scripts.cli import main as cli_main

    with pytest.raises(SystemExit) as exc_info:
        cli_main(["annotate", "--case", "x", "--dpi", "200"])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err and "--dpi" in err


# --------------------------------------------------------------------------- #
# T8. Upright preprocessing integration (A2-A9)
# --------------------------------------------------------------------------- #
_BBOX = [0.25, 0.25, 0.5, 0.5]
_LEGACY_RECT = [100, 75, 200, 150]     # T=90 on the un-normalized 400x300 page
_UPRIGHT_RECT = [75, 200, 150, 300]    # t=0 on the normalized 300x400 page


def _case_layout(tmp_path: Path, case_id: str = "9"):
    """(work, cert_root, cache_root, case_cache, out_dir) for an annotate_case run."""
    work = tmp_path / "work"
    cert_root = work / CERT_CLEANUP_DIRNAME
    cache_root = tmp_path / "cache"
    case_cache = cache_root / case_id
    case_cache.mkdir(parents=True, exist_ok=True)
    return work, cert_root, cache_root, case_cache, tmp_path / "out"


def _run_case(work, cert_root, cache_root, out_dir, ann_path, case_id="9"):
    return annotate_case(
        case_id=case_id, work_dir=work, cache_root=cache_root, cert_dir=cert_root,
        out_dir=out_dir, annotations_path=ann_path, font_path=_FONT,
    )


def _by_stem(summary: dict, stem: str) -> dict:
    return next(o for o in summary["outputs"] if o["stem"] == stem)


def _without_freetext(src: Path, dst: Path) -> Path:
    """Copy a PDF with every /FreeText annotation dropped (Square + Popup kept)."""
    w = PdfWriter(clone_from=str(src))
    for pg in w.pages:
        arr = pg.get("/Annots")
        if arr is None:
            continue
        pg[NameObject("/Annots")] = ArrayObject(
            [a for a in arr if a.get_object().get("/Subtype") != "/FreeText"]
        )
    with open(dst, "wb") as fh:
        w.write(fh)
    return dst


def _assert_label_beside_box(ft, *, rotate: int, wp: float, hp: float, a: int = 0):
    """The chip must sit clear of, and adjacent to, its box in display space."""
    chip, ws, hs = _display_chip(ft, rotate, wp=wp, hp=hp)
    box = A._aligned_bbox_to_display_box(tuple(_BBOX), ws, hs, a)
    assert not A._rects_overlap(chip, box), f"label overlaps its box: {chip} vs {box}"
    gap_x = max(box[0] - chip[2], chip[0] - box[2], 0.0)
    gap_y = max(box[1] - chip[3], chip[1] - box[3], 0.0)
    assert max(gap_x, gap_y) <= A.LABEL_GAP_PT + 2 * A.LABEL_BOX_PAD + 0.01


@requires_font
def test_annotate_case_normalizes_metadata_rotation(tmp_path: Path):
    """r != 0 with no alignment record: the output must be fully upright (/Rotate=0).

    That every output page reports /Rotate == 0 is the premise of the whole
    change — it is what makes a viewer's rotation-following edit chrome and the
    NoRotate anchor mathematically the same transform.
    """
    work, cert_root, cache_root, _, out_dir = _case_layout(tmp_path)
    _make_pdf(cert_root / "9" / "certA.pdf", 2, rotate=90)
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 회전"}],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)

    assert summary["boxes_drawn"] == 1
    assert _by_stem(summary, "certA")["upright"] is True
    reader = PdfReader(str(out_dir / "certA_annotated.pdf"))
    assert all(p.get("/Rotate") in (None, 0) for p in reader.pages)
    page = reader.pages[0]
    assert [float(v) for v in page.mediabox] == pytest.approx([0, 0, 300, 400], abs=0.01)
    assert [float(v) for v in _square(_annots(page))["/Rect"]] == pytest.approx(
        _UPRIGHT_RECT, abs=0.01
    )
    _assert_label_beside_box(_freetext(_annots(page)), rotate=0, wp=300, hp=400)


@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(90, None, id="R90-A0"),
        pytest.param(0, {1: 90}, id="R0-A90"),
    ],
)
def test_annotate_case_visual_equivalence_with_legacy_path(tmp_path: Path, rotate, rotations):
    """The verdict box must land on exactly the same pixels as before the change.

    Scope note (measured, not assumed): the *Square* is pixel-identical on both
    parameters, but the whole-annotation colour bbox is not, and must not be, on
    the a != 0 parameter. The legacy output keeps the page sideways and therefore
    anchors the NoRotate chip beside the box *as the reader of that sideways page*
    sees it; the new output is upright, so the chip is anchored beside the box as
    the reader of the upright page sees it. Both are correct for their own file
    and they are ~15px apart once the legacy render is turned upright, so the
    comparison is made with the label stripped from both sides and each output's
    label is then checked against its own box (which is the property that has to
    hold). Deviation from the plan's A3 wording, recorded deliberately.
    """
    work, cert_root, cache_root, case_cache, out_dir = _case_layout(tmp_path)
    src = cert_root / "9" / "certA.pdf"
    _make_pdf(src, 1, rotate=rotate)
    a = (rotations or {}).get(1, 0)
    if rotations:
        (case_cache / "certA_alignment.json").write_text(
            json.dumps({"applied": {str(k): v for k, v in rotations.items()}}), encoding="utf-8"
        )
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 동등성"}],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)
    assert _by_stem(summary, "certA")["upright"] is True
    new_out = out_dir / "certA_annotated.pdf"

    # legacy = the untouched writer called directly on the original PDF
    ann = A.Annotation("certA", 1, tuple(_BBOX), "FAIL", "FAIL: 동등성")
    legacy_out = tmp_path / "legacy.pdf"
    write_annotated_pdf(src, {1: [ann]}, legacy_out, rotations=rotations, font_path=_FONT)

    new_img = _render(_without_freetext(new_out, tmp_path / "new_sq.pdf"))
    legacy_img = _rotate_cw(_render(_without_freetext(legacy_out, tmp_path / "leg_sq.pdf")), a)
    nb, lb = _color_bbox(new_img), _color_bbox(legacy_img)
    assert nb is not None and lb is not None
    assert all(abs(x - y) <= 2 for x, y in zip(nb, lb)), f"legacy {lb} vs new {nb}"

    # each output's label sits beside its box in that output's own display space
    _assert_label_beside_box(
        _freetext(_annots(PdfReader(str(new_out)).pages[0])), rotate=0, wp=300, hp=400
    )
    _assert_label_beside_box(
        _freetext(_annots(PdfReader(str(legacy_out)).pages[0])),
        rotate=rotate, wp=400, hp=300, a=a,
    )


@requires_font
def test_annotate_case_skips_upright_when_flat(tmp_path: Path):
    """r=0 and no applied rotation: no derivative, no cache, bytes verbatim."""
    work, cert_root, cache_root, case_cache, out_dir = _case_layout(tmp_path)
    src = cert_root / "9" / "certA.pdf"
    _make_pdf(src, 2)
    orig = [_content_bytes(p) for p in PdfReader(str(src)).pages]
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 평면"}],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)

    out = _by_stem(summary, "certA")
    assert out["upright"] is False and out["skipped"] is False
    assert not (case_cache / UP.UPRIGHT_DIRNAME).exists()
    assert [_content_bytes(p) for p in PdfReader(str(out_dir / "certA_annotated.pdf")).pages] == orig


@requires_font
@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(OSError("cache dir unwritable"), id="OSError"),
        pytest.param(PdfStreamError("truncated"), id="PyPdfError"),
    ],
)
def test_annotate_case_falls_back_when_normalization_fails(tmp_path: Path, monkeypatch, exc):
    """Tier 1: preprocessing may fail; the legacy NoRotate path still delivers.

    Parametrised over both halves of the catch tuple — pypdf's PyPdfError family
    is neither an OSError nor a ValueError, so dropping it would turn a cache
    hiccup into a whole-case crash.
    """
    work, cert_root, cache_root, case_cache, out_dir = _case_layout(tmp_path)
    _make_pdf(cert_root / "9" / "certA.pdf", 1, rotate=90)

    def _boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr("scripts.annotate_pdf.ensure_upright_pdf", _boom)
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 폴백"}],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)

    assert summary["boxes_drawn"] == 1
    out = _by_stem(summary, "certA")
    assert out["upright"] is False and out["skipped"] is False
    assert any("falling back" in n for n in summary["notes"])
    assert not (case_cache / UP.UPRIGHT_DIRNAME).exists()
    page = PdfReader(str(out_dir / "certA_annotated.pdf")).pages[0]
    assert page.get("/Rotate") == 90                       # legacy: page left as-is
    assert [float(v) for v in _square(_annots(page))["/Rect"]] == pytest.approx(
        _LEGACY_RECT, abs=0.01
    )


@requires_font
def test_summary_upright_field_backward_shape(tmp_path: Path):
    """outputs[*] gains keys, never loses or renames them (additive only)."""
    work, cert_root, cache_root, _, out_dir = _case_layout(tmp_path)
    _make_pdf(cert_root / "9" / "certA.pdf", 1)
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [{"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 형태"}],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)
    assert summary["outputs"]
    for out in summary["outputs"]:
        assert set(out) == {"stem", "pages", "boxes", "out_path", "upright", "skipped"}


@requires_font
@pytest.mark.parametrize(
    ("kind", "maker", "note_fragment"),
    [
        pytest.param("encrypted", _make_encrypted_pdf, "encrypted", id="encrypted"),
        pytest.param("corrupt", _make_corrupt_pdf, "annotation failed", id="corrupt"),
    ],
)
def test_annotate_case_survives_unreadable_pdf_real(tmp_path: Path, kind, maker, note_fragment):
    """Tier 2: a genuinely unreadable PDF (no mocking) may not kill the case.

    pypdf raises FileNotDecryptedError / PdfStreamError here — neither an OSError
    nor a ValueError — so before the catch tuple was widened this took the whole
    case down. Only the offending stem is skipped now.
    """
    work, cert_root, cache_root, case_cache, out_dir = _case_layout(tmp_path)
    _make_pdf(cert_root / "9" / "certA.pdf", 1, rotate=90)
    maker(cert_root / "9" / "certB.pdf")
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [
            {"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 정상"},
            {"stem": "certB", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 불능"},
        ],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)   # must not raise

    bad = _by_stem(summary, "certB")
    assert bad["skipped"] is True and bad["boxes"] == 0
    assert not (out_dir / "certB_annotated.pdf").exists()
    assert any(note_fragment in n for n in summary["notes"]), summary["notes"]

    good = _by_stem(summary, "certA")
    assert good["upright"] is True and good["skipped"] is False
    reader = PdfReader(str(out_dir / "certA_annotated.pdf"))
    assert all(p.get("/Rotate") in (None, 0) for p in reader.pages)
    assert [float(v) for v in _square(_annots(reader.pages[0]))["/Rect"]] == pytest.approx(
        _UPRIGHT_RECT, abs=0.01
    )
    assert not (case_cache / UP.UPRIGHT_DIRNAME / "certB_upright.pdf").exists()


@requires_font
def test_annotate_case_isolates_upright_failure_per_stem(tmp_path: Path, monkeypatch):
    """A selective preprocessing failure must not leak into a sibling stem."""
    work, cert_root, cache_root, case_cache, out_dir = _case_layout(tmp_path)
    _make_pdf(cert_root / "9" / "certA.pdf", 1, rotate=90)
    _make_pdf(cert_root / "9" / "certB.pdf", 1, rotate=90)

    def _selective(pdf_path, case_cache_dir, rotations):
        if Path(pdf_path).stem == "certA":
            raise OSError("boom")
        return UP.ensure_upright_pdf(pdf_path, case_cache_dir, rotations)

    monkeypatch.setattr("scripts.annotate_pdf.ensure_upright_pdf", _selective)
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [
            {"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 실패"},
            {"stem": "certB", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 성공"},
        ],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)

    assert len(summary["outputs"]) == 2 and summary["boxes_drawn"] == 2
    a_out, b_out = _by_stem(summary, "certA"), _by_stem(summary, "certB")
    assert (a_out["upright"], a_out["skipped"]) == (False, False)
    assert (b_out["upright"], b_out["skipped"]) == (True, False)
    assert any("certA: upright normalization failed" in n and "falling back" in n
               for n in summary["notes"])

    page_a = PdfReader(str(out_dir / "certA_annotated.pdf")).pages[0]
    assert page_a.get("/Rotate") == 90                      # legacy path, untouched
    assert [float(v) for v in _square(_annots(page_a))["/Rect"]] == pytest.approx(
        _LEGACY_RECT, abs=0.01
    )
    page_b = PdfReader(str(out_dir / "certB_annotated.pdf")).pages[0]
    assert page_b.get("/Rotate") in (None, 0)
    assert [float(v) for v in _square(_annots(page_b))["/Rect"]] == pytest.approx(
        _UPRIGHT_RECT, abs=0.01
    )

    up_dir = case_cache / UP.UPRIGHT_DIRNAME
    assert (up_dir / "certB_upright.pdf").exists()
    assert not (up_dir / "certA_upright.pdf").exists()


@requires_font
def test_unresolved_stem_produces_no_upright_artifact(tmp_path: Path):
    """An unresolved stem is dropped upstream, so it can never reach the cache."""
    work, cert_root, cache_root, case_cache, out_dir = _case_layout(tmp_path)
    _make_pdf(cert_root / "9" / "certA.pdf", 1)
    ann_path = tmp_path / "9_annotations.json"
    _write_annotations(
        ann_path,
        [
            {"stem": "certA", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 실존"},
            {"stem": "ghost", "page": 1, "bbox": _BBOX, "verdict": "FAIL", "label": "FAIL: 유령"},
        ],
    )
    summary = _run_case(work, cert_root, cache_root, out_dir, ann_path)

    assert summary["n_pdfs"] == 1 and summary["rows_skipped"] == 1
    assert any("unresolved stem 'ghost'" in n for n in summary["notes"])
    assert not (case_cache / UP.UPRIGHT_DIRNAME).exists()   # flat case -> no dir at all
    assert list(case_cache.rglob("*ghost*")) == []


def test_skillmd_no_stale_wording():
    skill = Path(A.__file__).parents[2] / "cert-review-annotate" / "SKILL.md"
    text = skill.read_text(encoding="utf-8").lower()
    assert "burn-in" not in text
    assert "burn in" not in text
    assert "--dpi" not in text
    assert "norotate" in text, "SKILL.md must document the NoRotate label flag"
    # the *reason* the caveat was rewritten: resizing (not just editing) triggers
    # Acrobat's AP regeneration. Pin the fact, not merely the flag name. SKILL.md's
    # stated language is English (module docstring), so "resize" is the required
    # term; a Korean gloss may or may not additionally be present.
    assert "resize" in text, (
        "SKILL.md must state that a mere resize also regenerates the appearance"
    )
