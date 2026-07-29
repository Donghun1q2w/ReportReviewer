"""upright_pdf regression tests (U1-U15).

The upright preprocessing is the load-bearing claim of the annotate change: the
page is turned *losslessly* (one rotation matrix transferred into the content
stream) so that annotations attach at ``/Rotate=0``. These tests therefore pin
three separate kinds of evidence:

  * **byte** evidence — an embedded image XObject's encoded stream and every
    untouched page's ``/Contents`` must come out byte-identical (nothing is
    re-rasterised, U2/U3/U9/U15);
  * **pixel** evidence — pdfium must render the normalized page exactly as it
    renders the original once the original's own turn is applied (U4b/U5/U6/U7);
  * **cache/contract** evidence — the sidecar gate, the double-normalization
    marker, the encrypted/45-degree guards and the import discipline
    (U1/U8/U9/U10/U11/U12/U14).

The pixel tests need ``pypdfium2`` (already a test-time dependency of
``test_annotate_pdf``); U13 additionally needs a Hangul TTF because it chains a
real ``write_annotated_pdf`` call, and is skipped when the font is absent.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pypdf
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from scripts import annotate_pdf as A
from scripts import upright_pdf as U
from scripts.annotate_pdf import write_annotated_pdf
from scripts.upright_pdf import (
    ensure_upright_pdf,
    page_upright_turns,
    upright_paths,
    write_upright_pdf,
)

_FONT = A.DEFAULT_FONT
requires_font = pytest.mark.skipif(
    not Path(_FONT).exists(), reason=f"Hangul font not present ({_FONT}); set CERT_REVIEW_FONT"
)

_FAIL_RGB = (255, 199, 206)

IMG_W, IMG_H = 60, 30  # deliberately asymmetric: a w/h mix-up cannot hide


# --------------------------------------------------------------------------- #
# Fixtures (6.1) — a real PDF carrying a real, flate-encoded image XObject
# --------------------------------------------------------------------------- #
def _asym_rgb_bytes(w: int = IMG_W, h: int = IMG_H) -> bytes:
    """Raw /DeviceRGB samples with no symmetry in x, y or channel."""
    out = bytearray()
    for y in range(h):
        for x in range(w):
            out += bytes(((x * 4) % 256, (y * 8) % 256, (x * 3 + y * 7) % 256))
    return bytes(out)


def _make_pdf_with_image(
    path: Path,
    rotate: int = 0,
    cropbox: tuple[float, float, float, float] | None = None,
    pages: int = 2,
    size: tuple[float, float] = (400, 300),
    rotates: list[int] | None = None,
) -> None:
    """Page 1 = image XObject + stroked box; page 2+ = distinct, image-free content.

    Mirrors ``annotate_pdf._image_xobject``'s construction on purpose (a *test*
    copy — the production module must never grow an image writer). ``rotates``
    overrides ``rotate`` per page so a mixed-/Rotate document can be built.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for i in range(pages):
        pg = writer.add_blank_page(width=size[0], height=size[1])
        if i == 0:
            st = StreamObject()
            st[NameObject("/Type")] = NameObject("/XObject")
            st[NameObject("/Subtype")] = NameObject("/Image")
            st[NameObject("/Width")] = NumberObject(IMG_W)
            st[NameObject("/Height")] = NumberObject(IMG_H)
            st[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
            st[NameObject("/BitsPerComponent")] = NumberObject(8)
            st.set_data(_asym_rgb_bytes())
            xobj = DictionaryObject()
            xobj[NameObject("/Im0")] = writer._add_object(st.flate_encode())
            pg[NameObject("/Resources")].get_object()[NameObject("/XObject")] = xobj
            data = (
                f"q {IMG_W} 0 0 {IMG_H} 30 40 cm /Im0 Do Q "
                f"q 0 0 1 RG 20 20 200 100 re S Q"
            ).encode("latin-1")
        else:
            data = f"q 1 0 0 RG {30 + i * 10} 30 150 80 re S Q".encode("latin-1")
        cs = DecodedStreamObject()
        cs.set_data(data)
        pg[NameObject("/Contents")] = writer._add_object(cs)
        deg = rotates[i] if rotates is not None else rotate
        if deg:
            pg[NameObject("/Rotate")] = NumberObject(deg)
        if cropbox is not None:
            pg[NameObject("/CropBox")] = ArrayObject([FloatObject(v) for v in cropbox])
    with open(path, "wb") as fh:
        writer.write(fh)


def _make_encrypted_pdf(path: Path, pages: int = 1) -> None:
    """A genuinely encrypted PDF (no mocking) — pypdf raises FileNotDecryptedError."""
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for i in range(pages):
        pg = writer.add_blank_page(width=400, height=300)
        st = DecodedStreamObject()
        st.set_data(f"q 0 0 1 RG {20 + i} 20 200 100 re S Q".encode("latin-1"))
        pg[NameObject("/Contents")] = writer._add_object(st)
    writer.encrypt("pw")
    with open(path, "wb") as fh:
        writer.write(fh)


def _make_corrupt_pdf(path: Path) -> None:
    """A truncated PDF — pypdf raises a PdfStreamError-family error on open."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<")


def _image_raw(page) -> tuple[bytes, str, int, int]:
    """(encoded stream bytes, /Filter, /Width, /Height) of the page's /Im0."""
    xo = page["/Resources"].get_object()["/XObject"].get_object()["/Im0"].get_object()
    return (xo._data, str(xo.get("/Filter")), int(xo["/Width"]), int(xo["/Height"]))


def _content_bytes(page) -> bytes:
    c = page.get_contents()
    return c.get_data() if c is not None else b""


def _box_wh(box) -> tuple[float, float]:
    return (float(box.width), float(box.height))


# --------------------------------------------------------------------------- #
# Render helpers (pixel evidence)
# --------------------------------------------------------------------------- #
def _render(pdf_path: Path, index: int = 0, scale: float = 1.0):
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return doc[index].render(scale=scale).to_pil().convert("RGB")
    finally:
        doc.close()


# Clockwise degrees -> PIL transpose op, the same convention as
# align_inputs._CW_TO_TRANSPOSE (PIL's ROTATE_* is counter-clockwise).
_CW_TO_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def _rotate_cw(img, deg: int):
    return img if deg % 360 == 0 else img.transpose(_CW_TO_TRANSPOSE[deg % 360])


def _mismatch_ratio(a, b, step: int = 2, thresh: int = 30) -> float:
    """Fraction of sampled pixels whose channel sums differ by more than ``thresh``."""
    assert a.size == b.size, f"render size differs: {a.size} vs {b.size}"
    pa, pb = a.load(), b.load()
    w, h = a.size
    total = bad = 0
    for y in range(0, h, step):
        for x in range(0, w, step):
            total += 1
            if abs(sum(pa[x, y][:3]) - sum(pb[x, y][:3])) > thresh:
                bad += 1
    return bad / max(total, 1)


def _color_bbox(img, target=_FAIL_RGB, tol: int = 25):
    """Bounding box of pixels within ``tol`` of ``target`` (None when absent)."""
    px = img.load()
    w, h = img.size
    xs: list[int] = []
    ys: list[int] = []
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y][:3]
            if abs(r - target[0]) <= tol and abs(g - target[1]) <= tol and abs(b - target[2]) <= tol:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def _imported_top_level(src: str) -> set[str]:
    """Top-level module names imported by ``src`` (import + from-import)."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


# --------------------------------------------------------------------------- #
# U1 — turn selection (page /Rotate + applied rotation, with the 45-deg clamp)
# --------------------------------------------------------------------------- #
def test_page_upright_turns_selection(tmp_path: Path):
    """r is clamped to 0 *before* combining with a — r=45 & a=90 must give 90."""
    src = tmp_path / "mixed.pdf"
    _make_pdf_with_image(src, pages=5, rotates=[0, 90, 0, 45, 45])
    reader = PdfReader(str(src))
    turns = page_upright_turns(reader, {3: 270, 4: 0, 5: 90})
    assert turns == {2: 90, 3: 270, 5: 90}

    # t == 0 with r != 0 is still a turn (the /Rotate key must be stripped).
    src2 = tmp_path / "r90.pdf"
    _make_pdf_with_image(src2, rotate=90, pages=1)
    assert page_upright_turns(PdfReader(str(src2)), {1: 270}) == {1: 0}

    # a fully upright document yields nothing at all
    src3 = tmp_path / "flat.pdf"
    _make_pdf_with_image(src3, pages=2)
    assert page_upright_turns(PdfReader(str(src3)), None) == {}


# --------------------------------------------------------------------------- #
# U2/U3 — losslessness: metadata rotation baked, content/image bytes intact
# --------------------------------------------------------------------------- #
def test_write_upright_metadata_rotation_lossless(tmp_path: Path):
    src = tmp_path / "img90.pdf"
    _make_pdf_with_image(src, rotate=90, pages=2)
    before = PdfReader(str(src))
    img_before = _image_raw(before.pages[0])
    p2_before = _content_bytes(before.pages[1])
    assert img_before[1] == "/FlateDecode" and img_before[2:] == (IMG_W, IMG_H)

    dst = tmp_path / "up" / "img90_upright.pdf"
    summary = write_upright_pdf(src, dst, {1: 90})
    assert summary == {"n_pages": 2, "baked": 1, "stripped": 0}

    after = PdfReader(str(dst))
    assert after.pages[0].get("/Rotate") in (None, 0)
    assert _box_wh(after.pages[0].mediabox) == pytest.approx((300.0, 400.0), abs=0.01)
    # the encoded image stream must be byte-identical — nothing was re-rasterised
    assert _image_raw(after.pages[0]) == img_before
    # the untouched page is verbatim
    assert _content_bytes(after.pages[1]) == p2_before


def test_write_upright_t0_strips_rotate_only(tmp_path: Path):
    """r=90 & a=270 -> t=0: strip /Rotate, never touch the content or the boxes."""
    src = tmp_path / "r90.pdf"
    _make_pdf_with_image(src, rotate=90, pages=2)
    before = PdfReader(str(src))
    p1_before = _content_bytes(before.pages[0])
    img_before = _image_raw(before.pages[0])

    dst = tmp_path / "up" / "r90_upright.pdf"
    summary = write_upright_pdf(src, dst, {1: 0})
    assert summary == {"n_pages": 2, "baked": 0, "stripped": 1}

    after = PdfReader(str(dst))
    assert after.pages[0].get("/Rotate") in (None, 0)
    assert _content_bytes(after.pages[0]) == p1_before
    assert _image_raw(after.pages[0]) == img_before
    assert _box_wh(after.pages[0].mediabox) == pytest.approx((400.0, 300.0), abs=0.01)


# --------------------------------------------------------------------------- #
# U4 — CropBox != MediaBox (literal dimensions + pixel-level legacy equivalence)
# --------------------------------------------------------------------------- #
@requires_font
def test_write_upright_cropbox_offset(tmp_path: Path):
    # (a) case-46-shaped CropBox: every box must swap consistently on t=90.
    crop = (3.96001, 2.88, 599.76001, 845.28)
    src = tmp_path / "crop46.pdf"
    _make_pdf_with_image(src, rotate=90, cropbox=crop, pages=1, size=(603.72, 848.16))
    dst = tmp_path / "up" / "crop46_upright.pdf"
    write_upright_pdf(src, dst, {1: 90})
    page = PdfReader(str(dst)).pages[0]
    assert page.get("/Rotate") in (None, 0)
    assert _box_wh(page.cropbox) == pytest.approx((842.4, 595.8), abs=0.01)
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 크롭박스")
    write_annotated_pdf(dst, {1: [ann]}, tmp_path / "crop46_out.pdf", rotations={}, font_path=_FONT)

    # (b) asymmetric CropBox: the *rendered* marker must not move vs the legacy
    #     path. This pins pypdf's box-transform arithmetic against a future
    #     regression without this plan hand-deriving the origin-offset formula.
    crop2 = (30, 5, 390, 250)
    src2 = tmp_path / "crop_asym.pdf"
    _make_pdf_with_image(src2, rotate=90, cropbox=crop2, pages=1)
    legacy = tmp_path / "crop_asym_legacy.pdf"
    write_annotated_pdf(src2, {1: [ann]}, legacy, rotations={1: 0}, font_path=_FONT)
    norm = tmp_path / "up" / "crop_asym_upright.pdf"
    write_upright_pdf(src2, norm, {1: 90})
    new = tmp_path / "crop_asym_new.pdf"
    write_annotated_pdf(norm, {1: [ann]}, new, rotations={}, font_path=_FONT)

    lb, nb = _color_bbox(_render(legacy)), _color_bbox(_render(new))
    assert lb is not None and nb is not None
    assert all(abs(x - y) <= 2 for x, y in zip(lb, nb)), f"legacy {lb} vs new {nb}"


# --------------------------------------------------------------------------- #
# U5/U6/U7 — pdfium render equivalence (the "lossless" claim, in pixels)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("r", [90, 180, 270])
def test_render_equivalence_metadata_rotation(tmp_path: Path, r):
    """A /Rotate-ed page and its baked equivalent must render identically."""
    src = tmp_path / f"meta{r}.pdf"
    _make_pdf_with_image(src, rotate=r, pages=1)
    dst = tmp_path / "up" / f"meta{r}_upright.pdf"
    write_upright_pdf(src, dst, {1: r})
    assert _mismatch_ratio(_render(dst), _render(src)) < 0.005


@pytest.mark.parametrize("a", [90, 180, 270])
def test_render_equivalence_content_rotation(tmp_path: Path, a):
    """a-only (page already /Rotate=0, content lying sideways): bake must equal a cw turn."""
    src = tmp_path / f"cont{a}.pdf"
    _make_pdf_with_image(src, rotate=0, pages=1)
    dst = tmp_path / "up" / f"cont{a}_upright.pdf"
    write_upright_pdf(src, dst, {1: a})
    assert _mismatch_ratio(_render(dst), _rotate_cw(_render(src), a)) < 0.005


def test_render_equivalence_combined(tmp_path: Path):
    """r=90 AND a=90 -> t=180: the bug-reproducing combination."""
    src = tmp_path / "comb.pdf"
    _make_pdf_with_image(src, rotate=90, pages=1)
    dst = tmp_path / "up" / "comb_upright.pdf"
    write_upright_pdf(src, dst, {1: 180})
    assert _mismatch_ratio(_render(dst), _rotate_cw(_render(src), 90)) < 0.005


# --------------------------------------------------------------------------- #
# U8/U9/U10/U11 — cache gate, stale-cache hygiene, marker guard, atomicity
# --------------------------------------------------------------------------- #
def test_ensure_upright_cache_hit_and_invalidation(tmp_path: Path):
    src = tmp_path / "src.pdf"
    _make_pdf_with_image(src, rotate=90, pages=2)
    cache = tmp_path / "case"
    up_pdf, up_scar = upright_paths(cache, "src")

    path1, used1, notes1 = ensure_upright_pdf(src, cache, {1: 90})
    assert (path1, used1) == (up_pdf, True)
    assert any("upright normalized" in n for n in notes1)
    assert up_pdf.exists() and up_scar.exists()

    sidecar = json.loads(up_scar.read_text(encoding="utf-8"))
    assert sidecar["schema_version"] == U.UPRIGHT_SCHEMA_VERSION
    assert sidecar["pypdf_version"] == pypdf.__version__
    assert sidecar["rotations"] == {"1": 90}
    # p1: r=90 + a=90 -> 180; p2 also carries /Rotate=90 with no applied turn -> 90
    assert sidecar["turns"] == {"1": 180, "2": 90}
    assert sidecar["n_pages"] == 2
    assert len(sidecar["source_sha256"]) == 64

    # 2nd call: cache hit -> no rewrite at all (bytes AND mtime unchanged)
    before_bytes, before_mtime = up_pdf.read_bytes(), up_pdf.stat().st_mtime_ns
    path2, used2, notes2 = ensure_upright_pdf(src, cache, {1: 90})
    assert (path2, used2) == (up_pdf, True)
    assert any("cache hit" in n for n in notes2)
    assert up_pdf.read_bytes() == before_bytes
    assert up_pdf.stat().st_mtime_ns == before_mtime

    def _regenerates(rotations) -> bool:
        _, _, notes = ensure_upright_pdf(src, cache, rotations)
        return any("upright normalized" in n for n in notes)

    # rotations map changed
    assert _regenerates({1: 180})
    assert json.loads(up_scar.read_text(encoding="utf-8"))["rotations"] == {"1": 180}

    # sidecar pypdf_version / schema_version tampered -> regenerate (contrarian#2)
    for key, bogus in (("pypdf_version", "0.0.0"), ("schema_version", "0.9")):
        data = json.loads(up_scar.read_text(encoding="utf-8"))
        data[key] = bogus
        up_scar.write_text(json.dumps(data), encoding="utf-8")
        assert _regenerates({1: 180}), f"stale {key} must invalidate the cache"
        assert json.loads(up_scar.read_text(encoding="utf-8"))[key] != bogus

    # source bytes changed -> regenerate
    old_sha = json.loads(up_scar.read_text(encoding="utf-8"))["source_sha256"]
    with open(src, "ab") as fh:
        fh.write(b"\n")
    assert _regenerates({1: 180})
    assert json.loads(up_scar.read_text(encoding="utf-8"))["source_sha256"] != old_sha


def test_ensure_upright_noop_when_already_upright(tmp_path: Path):
    # (a) nothing to do -> original path, no artefacts at all
    src = tmp_path / "flat.pdf"
    _make_pdf_with_image(src, rotate=0, pages=2)
    cache = tmp_path / "case"
    assert ensure_upright_pdf(src, cache, {}) == (src, False, [])
    assert not (cache / U.UPRIGHT_DIRNAME).exists()

    # (b) a stem that no longer needs normalization must not leave a stale cache
    up_pdf, up_scar = upright_paths(cache, "flat")
    up_pdf.parent.mkdir(parents=True, exist_ok=True)
    up_pdf.write_bytes(b"stale-pdf")
    up_scar.write_text(json.dumps({"schema_version": "1.0"}), encoding="utf-8")
    path, used, notes = ensure_upright_pdf(src, cache, None)
    assert (path, used) == (src, False)
    assert any("stale upright cache removed" in n for n in notes)
    assert not up_pdf.exists() and not up_scar.exists()


def test_double_normalization_guard(tmp_path: Path):
    """A normalized output fed back in must never be turned a second time."""
    src = tmp_path / "src.pdf"
    _make_pdf_with_image(src, rotate=90, pages=2)
    cache1 = tmp_path / "c1"
    out1, used1, _ = ensure_upright_pdf(src, cache1, None)
    assert used1 is True

    cache2 = tmp_path / "c2"
    path, used, notes = ensure_upright_pdf(out1, cache2, {1: 90})
    assert (path, used) == (out1, False)
    assert any("upright marker" in n for n in notes)
    assert not (cache2 / U.UPRIGHT_DIRNAME).exists()


def test_upright_write_atomic_no_tmp_residue(tmp_path: Path):
    src = tmp_path / "src.pdf"
    _make_pdf_with_image(src, rotate=90, pages=2)
    cache = tmp_path / "case"
    up_pdf, up_scar = upright_paths(cache, "src")
    ensure_upright_pdf(src, cache, None)
    assert list(up_pdf.parent.glob("*.tmp")) == []

    up_scar.unlink()                       # sidecar is the commit marker
    _, used, notes = ensure_upright_pdf(src, cache, None)
    assert used is True and any("upright normalized" in n for n in notes)
    assert up_scar.exists()
    assert list(up_pdf.parent.glob("*.tmp")) == []


# --------------------------------------------------------------------------- #
# U12 — encrypted sources (the real FileNotDecryptedError escape hatch)
# --------------------------------------------------------------------------- #
def test_encrypted_source_raises(tmp_path: Path):
    src = tmp_path / "enc.pdf"
    _make_encrypted_pdf(src)
    with pytest.raises(ValueError, match="encrypted"):
        write_upright_pdf(src, tmp_path / "up" / "enc_upright.pdf", {1: 90})
    # the path annotate_case actually takes: the guard must fire BEFORE
    # reader.metadata, which would raise FileNotDecryptedError (not a ValueError).
    with pytest.raises(ValueError, match="encrypted"):
        ensure_upright_pdf(src, tmp_path / "case", {1: 90})


# --------------------------------------------------------------------------- #
# U13 — the normalized PDF chains into the untouched writer
# --------------------------------------------------------------------------- #
@requires_font
def test_upright_chains_into_write_annotated_pdf(tmp_path: Path):
    """t collapses to 0, so the Square mapping is a pure scale of the swapped page."""
    src = tmp_path / "src.pdf"
    _make_pdf_with_image(src, rotate=90, pages=1)
    norm = tmp_path / "up" / "src_upright.pdf"
    write_upright_pdf(src, norm, {1: 90})

    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 정규화")
    out = tmp_path / "out.pdf"
    write_annotated_pdf(norm, {1: [ann]}, out, rotations={}, font_path=_FONT)

    page = PdfReader(str(out)).pages[0]
    assert page.get("/Rotate") in (None, 0)
    annots = [a.get_object() for a in page["/Annots"]]
    sq = [a for a in annots if str(a.get("/Subtype")) == "/Square"][0]
    assert [float(v) for v in sq["/Rect"]] == pytest.approx([75, 200, 150, 300], abs=0.01)

    ft = [a for a in annots if str(a.get("/Subtype")) == "/FreeText"][0]
    assert int(ft["/F"]) == 20                      # 4 Print | 16 NoRotate
    assert "/Matrix" not in ft["/AP"]["/N"].get_object()
    rc = [float(v) for v in ft["/Rect"]]
    bx = [float(v) for v in ft["/AP"]["/N"].get_object()["/BBox"]]
    assert rc[2] - rc[0] == pytest.approx(bx[2] - bx[0], abs=1e-6)
    assert rc[3] - rc[1] == pytest.approx(bx[3] - bx[1], abs=1e-6)


# --------------------------------------------------------------------------- #
# U14 — import discipline (direct imports only; transitive PIL is documented)
# --------------------------------------------------------------------------- #
def test_upright_module_import_discipline():
    """No *direct* rasterisation dependency, and the transitive one is documented.

    ``scripts.align_inputs`` pulls PIL in transitively, so the invariant is not
    "PIL is never loaded" but "this module never rasterises": no direct import,
    no rasterisation vocabulary anywhere in the code. The module docstring is
    excluded from the string scan precisely because it is where the transitive
    load and the not-a-raster-burn-in distinction are written down.
    """
    src = Path(U.__file__).read_text(encoding="utf-8")
    assert _imported_top_level(src) <= {"pypdf", "pathlib", "os", "scripts", "__future__"}

    doc = U.__doc__ or ""
    assert "PIL" in doc and "align_inputs" in doc, "transitive PIL load must be documented"
    assert "never rasterises" in doc

    code = src.replace(doc, "", 1)
    assert doc not in code, "module docstring must appear exactly once"
    for token in ("PIL", "pypdfium2", "render_", "burn"):
        assert token not in code, f"rasterisation vocabulary leaked into code: {token}"


# --------------------------------------------------------------------------- #
# U15 — the defensive out-of-range guard, demonstrated rather than assumed
# --------------------------------------------------------------------------- #
def test_write_upright_out_of_range_turns_guard(tmp_path: Path):
    src = tmp_path / "src.pdf"
    _make_pdf_with_image(src, rotate=0, pages=2)
    before = [_content_bytes(p) for p in PdfReader(str(src)).pages]

    dst = tmp_path / "up" / "src_upright.pdf"
    assert write_upright_pdf(src, dst, {99: 90}) == {"n_pages": 2, "baked": 0, "stripped": 0}

    after = PdfReader(str(dst))
    assert len(after.pages) == 2
    assert [_content_bytes(p) for p in after.pages] == before
