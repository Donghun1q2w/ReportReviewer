"""annotate_pdf.py — attach review verdicts to cert PDFs as native PDF annotations.

Consumes a standalone ``<case>_annotations.json`` (produced by the
``annotation-locator`` agent) plus the original cert PDF(s), and writes
``<stem>_annotated.pdf`` in which every 주의 / N/A / FAIL region carries native,
individually editable PDF annotation objects:

  * a border-only ``/Square`` (no fill, verdict-coloured border) — the *main*
    annotation. It carries the Korean label as its ``/Contents`` comment thread
    plus an Acrobat-native empty ``/Popup`` companion (bidirectional
    ``/Popup``–``/Parent`` link), so a viewer can open a comment thread on the
    box exactly the way the in-house reviewer's Adobe Acrobat "사각형" tool does
    (ref: the real in-house sample ``docs/PU2601564.pdf``).
  * a ``/FreeText`` label with a self-generated appearance stream (a vector chip
    + a 4x-oversampled Hangul-glyph image XObject) so the ≤50-char Korean label
    is *always visible* in every major viewer — including pdfium-family viewers
    that never synthesise a FreeText appearance. The FreeText is an always-shown
    label overlay, not a comment carrier, so — matching the reference pattern of
    one main annotation per popup — it has **no** ``/Popup``.

**PASS is never annotated.**

This is a deterministic *renderer* — it does not locate cells; it attaches the
coordinates handed to it. Locating (page + fractional bbox) is the
``annotation-locator`` agent's job, so the cert-review review logic (the 5
reviewers, review-criteria, review.json schema) is untouched.

Constraint C1: no OCR libraries. Only ``pypdf`` (native annotation objects +
copy-through re-assembly) and ``Pillow`` (label appearance-stream glyph raster
only — the page itself is never rasterised) are used; neither performs OCR.
Verdict canonicalisation and the four verdict colours are reused from
``compliance_report`` so the annotations match the 6-sheet Excel report exactly.

Reassembly is *copy-through*: ``PdfWriter(clone_from=...)`` preserves every page
object verbatim (``/Contents`` bytes, MediaBox/CropBox/Rotate unchanged); the new
annotations are only appended to each page's ``/Annots``, so every annotation can
be individually deleted / moved / edited in a viewer and no page content is
altered. Since a ``/Popup`` draws nothing (empty, no ``/Contents`` — the same
state as the reference document), it too leaves page content byte-identical.

Coordinate convention: the annotation-locator's fractional bbox ``[x0, y0, x1,
y1]`` in ``[0, 1]`` is in the *aligned* image space (the upright pixels the
reviewers saw). It is mapped back to the original user space ``/Rect`` (points,
bottom-left origin) using ``T = (R + A) % 360`` — where ``R`` is the page
``/Rotate`` (inherited page attributes are already flattened onto the leaf by
``PdfReader``) and ``A`` is the align-inputs applied clockwise rotation — plus
the page ``/CropBox`` origin offset. The FreeText label is the one exception: it
is *anchored*, not mapped. It carries the NoRotate flag (``/F`` bit 5), which pins
the UPPER-LEFT corner of its ``/Rect`` to a fixed page location and then draws the
chip unrotated from there, so the label is placed by transforming that single
corner out of the *display* space (the page turned by its own ``/Rotate``) — the
space the reader actually sees. Its ``/Rect`` is therefore always the chip's
natural, never-swapped width x height.

Annotation metadata: ``/T = "cert-review"`` (the tool name — the author column in
Acrobat's comment panel; identical on both the Square and the FreeText so both
read as one tool's output), ``/Subj = verdict``, a deterministic in-document
``/NM``, and ``/M`` + ``/CreationDate`` stamped with the run's wall-clock time
(``D:YYYYMMDDHHMMSS``). Reading wall-clock time in ``_pdf_now`` is this module's
only such call, mirroring the cli.py timestamp convention.

Note: Adobe Acrobat throws a ``/FreeText``'s supplied ``/AP`` away and re-lays the
label out with its own fonts not only when the text is *edited* but also when the
annotation is merely **resized** (measured on a real ``/Rotate=90`` cert). The
label therefore never relies on an ``/AP`` ``/Matrix``: whatever a viewer
regenerates is laid out inside a naturally wide ``/Rect`` (one line, no vertical
stacking) and NoRotate keeps it viewer-horizontal. Moving/deleting is unaffected.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import FreeText, Popup, Rectangle
from pypdf.constants import AnnotationFlag
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    FloatObject,
    NameObject,
    NumberObject,
    StreamObject,
    TextStringObject,
)

from scripts.align_inputs import VALID_ROTATIONS, applied_rotations
from scripts.compliance_report import (
    _FAIL_FILL,
    _NA_FILL,
    _WARN_FILL,
    _canon_verdict,
)
from scripts.crop import parse_bbox, resolve_stem

# Hangul-capable label font; override via CERT_REVIEW_FONT for non-Windows hosts.
DEFAULT_FONT = os.environ.get("CERT_REVIEW_FONT", r"C:\Windows\Fonts\malgun.ttf")
LABEL_MAX = 50

# Point-space calibration (was px @200dpi in the burn-in era; equivalents noted).
BORDER_W_PT = 2           # /Square border width (pt); old 3px@200dpi ≈ 1.08pt
LABEL_FONT_PT = 10.0      # label font (pt); old 32px@200dpi ≈ 11.5pt
LABEL_GAP_PT = 4.0        # box↔label gap (pt); old pad 6px@200dpi ≈ 2.16pt
LABEL_BOX_PAD = 2.0       # chip inner padding (pt); old 2px ≈ 0.72pt
AP_OVERSAMPLE = 4.0       # glyph raster scale (10pt*4=40px ≈ 300dpi)
_CHIP_BORDER_W = 0.75     # chip border width (pt), grey
_LABEL_GRAY = 0.313725    # chip border grey level (old (80, 80, 80))
ANNOT_AUTHOR = "cert-review"          # /T — tool constant (not a person's name)
POPUP_W_PT, POPUP_H_PT = 180.0, 120.0  # Acrobat-conventional UI-hint size
# FreeText /F flags: Print + NoRotate. NoRotate pins the label's upper-left
# /Rect corner to the page but leaves its appearance unrotated, so the chip
# stays viewer-horizontal on a /Rotate-ed page even after Acrobat discards our
# /AP and regenerates its own. Square/Popup keep plain Print (they have no
# directional content, so page rotation is exactly what they want).
FREETEXT_FLAGS = AnnotationFlag.PRINT | AnnotationFlag.NO_ROTATE

# verdict -> openpyxl PatternFill (single source = compliance_report).
# PASS is intentionally absent: it is never annotated.
_VERDICT_FILL = {"주의": _WARN_FILL, "N/A": _NA_FILL, "FAIL": _FAIL_FILL}
_ANNOTATABLE = frozenset(_VERDICT_FILL)  # {"주의", "N/A", "FAIL"}


# --------------------------------------------------------------------------- #
# Pure helpers (font/render-independent — deterministically unit-testable)
# --------------------------------------------------------------------------- #
def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    """``'FFFFC7CE'`` (ARGB) / ``'FFC7CE'`` (RGB) / ``'#FFC7CE'`` -> ``(r, g, b)``.

    An 8-digit value carries a leading alpha byte; it is stripped **by position**
    (``s[2:]``), never by character class — ``lstrip('F')`` would corrupt
    ``'FFFFC7CE'`` to ``'C7CE'``.
    """
    s = str(h).lstrip("#")
    if len(s) == 8:  # ARGB -> drop the alpha byte (first two hex digits)
        s = s[2:]
    if len(s) != 6:
        raise ValueError(f"bad hex colour: {h!r}")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _verdict_rgb(verdict: Any) -> tuple[int, int, int] | None:
    """Canonical verdict -> outline RGB (report colours). PASS/other -> ``None``."""
    fill = _VERDICT_FILL.get(_canon_verdict(verdict))
    if fill is None:
        return None
    return _hex_to_rgb(fill.fgColor.rgb)


def _truncate(text: Any, limit: int = LABEL_MAX) -> str:
    """Collapse whitespace and cap at ``limit`` code points (… as the last char).

    ``len`` counts Unicode code points, so a Hangul syllable is one unit.
    """
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1] + "…"


def _label_for(rec: dict) -> str:
    """On-box label: explicit ``label`` if present, else ``'<verdict>: <ref>'``."""
    explicit = rec.get("label")
    if explicit:
        return _truncate(explicit)
    verdict = _canon_verdict(rec.get("verdict"))
    ref = rec.get("source_ref") or ""
    return _truncate(f"{verdict}: {ref}".strip().rstrip(":").strip())


def _rects_overlap(a: tuple, b: tuple) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _place_label(
    box_px: tuple[float, float, float, float],
    tw: float,
    th: float,
    page_w: float,
    page_h: float,
    placed: list[tuple[float, float, float, float]],
    pad: float = LABEL_GAP_PT,
) -> tuple[float, float]:
    """Pick a label top-left that avoids already-placed labels and the page edge.

    Tries above / below / right of the box, then stacks downward; always clamps
    inside the page. The box itself is never moved (only the label). Pure geometry
    in whatever single space the caller passes (display space for the NoRotate
    label; points now, pixels in the burn-in era) — box, chip and page extent must
    simply all be in that same space.
    """
    left, top, right, bottom = box_px
    candidates = [
        (left, top - th - pad),    # above
        (left, bottom + pad),      # below
        (right + pad, top),        # right
    ]
    for cx, cy in candidates:
        x = max(0, min(cx, page_w - tw))
        y = max(0, min(cy, page_h - th))
        rect = (x - LABEL_BOX_PAD, y - LABEL_BOX_PAD, x + tw + LABEL_BOX_PAD, y + th + LABEL_BOX_PAD)
        if not any(_rects_overlap(rect, p) for p in placed):
            return x, y
    # fallback: stack downward from just below the box
    x = max(0, min(left, page_w - tw))
    y = max(0, min(bottom + pad, page_h - th))
    for _ in range(40):
        rect = (x - LABEL_BOX_PAD, y - LABEL_BOX_PAD, x + tw + LABEL_BOX_PAD, y + th + LABEL_BOX_PAD)
        if not any(_rects_overlap(rect, p) for p in placed):
            break
        y = min(y + th + pad, page_h - th)
    return x, y


# --------------------------------------------------------------------------- #
# Annotation record + parsing (dual gate, never raises on bad rows)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Annotation:
    stem: str | None
    page: int
    bbox: tuple[float, float, float, float]
    verdict: str
    label: str


def load_annotations(path: Path | str) -> tuple[list[Annotation], dict[str, int]]:
    """Parse ``<case>_annotations.json`` -> ``(annotations, skip_counts)``.

    Dual gate per record: canonical verdict ∈ {주의, N/A, FAIL} (PASS excluded)
    AND a parseable fractional bbox AND an integer ``page >= 1``. Rejected
    records are tallied by reason and never raise.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out: list[Annotation] = []
    skips: dict[str, int] = {}

    def bump(reason: str) -> None:
        skips[reason] = skips.get(reason, 0) + 1

    for rec in data.get("annotations") or []:
        verdict = _canon_verdict(rec.get("verdict"))
        if verdict not in _ANNOTATABLE:
            bump("pass_or_other_excluded")
            continue
        page = rec.get("page")
        # bool is an int subclass — reject it explicitly
        if not (isinstance(page, int) and not isinstance(page, bool) and page >= 1):
            bump("bad_page")
            continue
        try:
            bbox = parse_bbox(rec.get("bbox"))
        except (ValueError, TypeError):
            bump("bad_bbox")
            continue
        out.append(Annotation(rec.get("stem"), page, bbox, verdict, _label_for(rec)))

    return out, skips


# --------------------------------------------------------------------------- #
# Coordinate transform (aligned fractional bbox -> original user-space /Rect)
# --------------------------------------------------------------------------- #
def _aligned_to_user_frac(u: float, v: float, t: int) -> tuple[float, float]:
    """Aligned fractional ``(u, v)`` (top-left) -> user fractional ``(a, b)``.

    Inverts the align-inputs upright rotation ``T = (R + A) % 360`` so a point in
    the pixels the reviewers saw maps back to the original page's fractional
    position. Raises on any T ∉ {0, 90, 180, 270}.
    """
    if t == 0:
        return (u, v)
    if t == 90:
        return (v, 1.0 - u)
    if t == 180:
        return (1.0 - u, 1.0 - v)
    if t == 270:
        return (1.0 - v, u)
    raise ValueError(f"rotation must be one of 0/90/180/270, got {t!r}")


def aligned_bbox_to_user_rect(
    bbox: tuple[float, float, float, float],
    mx0: float,
    my0: float,
    wp: float,
    hp: float,
    t: int,
) -> tuple[float, float, float, float]:
    """Aligned fractional bbox -> user-space /Rect (pt, bottom-left origin).

    Both corners are transformed and then min/max-normalised, because a 90/270
    rotation swaps which corner is the geometric minimum.
    """
    x0, y0, x1, y1 = bbox
    my1 = my0 + hp
    pts = []
    for u, v in ((x0, y0), (x1, y1)):
        a, b = _aligned_to_user_frac(u, v, t)
        pts.append((mx0 + a * wp, my1 - b * hp))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _aligned_page_size_pt(wp: float, hp: float, t: int) -> tuple[float, float]:
    """Page size in pt after a ``t``-degree turn — width/height swap on 90/270.

    The one caller passes the page's own ``/Rotate`` (display space), but the
    turn is generic: any of the module's rotation angles works here.
    """
    if t in (90, 270):
        return (hp, wp)
    return (wp, hp)


def _aligned_bbox_to_display_box(
    bbox: tuple[float, float, float, float], ws: float, hs: float, a: int
) -> tuple[float, float, float, float]:
    """Aligned fractional bbox -> display-space box in pt (top-left origin, y-down).

    ``a`` is the align-inputs applied rotation, i.e. the turn that takes the
    *display* (what a viewer actually shows) to the *aligned* space the reviewers
    annotated in; undoing it puts the cell back where the reader sees it. The
    label is placed here, not in aligned space, because a NoRotate annotation is
    always drawn display-horizontal — "above / below / right of the box" has to
    mean what the reader sees. When ``a == 0`` the two spaces coincide and this is
    a plain scale, so the unrotated and page-rotation-only cases are unchanged.

    Both corners are transformed and min/max-normalised — legitimate for a *box*,
    unlike the NoRotate anchor below, which must keep one specific corner.
    """
    pts = [
        _aligned_to_user_frac(bbox[0], bbox[1], a),
        _aligned_to_user_frac(bbox[2], bbox[3], a),
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs) * ws, min(ys) * hs, max(xs) * ws, max(ys) * hs)


def label_rect_for_norotate(
    chip_topleft_frac: tuple[float, float],
    chip_size_pt: tuple[float, float],
    mx0: float,
    my0: float,
    wp: float,
    hp: float,
    r: int,
) -> tuple[float, float, float, float]:
    """Display-space chip top-left -> user-space /Rect for a NoRotate label.

    A NoRotate annotation keeps the UPPER-LEFT corner of its /Rect glued to a
    fixed page location and then draws its never-rotated width x height down and
    to the right of it, so exactly one corner is transformed and the /Rect keeps
    the chip's natural shape (which is also what makes an Acrobat-regenerated
    appearance lay the label out on one line).

    Deliberately NOT ``aligned_bbox_to_user_rect``: normalising two corners with
    min/max picks a *different* corner as the geometric minimum on 90/270, so the
    label would unfold from the wrong end of the box.

    ``r`` is the page's own ``/Rotate`` — the turn the viewer applies — not the
    review-space ``T``; NoRotate resists page rotation, nothing else. Raises via
    ``_aligned_to_user_frac`` on any r outside {0, 90, 180, 270}.
    """
    ax, ay = _aligned_to_user_frac(chip_topleft_frac[0], chip_topleft_frac[1], r)
    chip_w, chip_h = chip_size_pt
    llx = mx0 + ax * wp
    ury = my0 + hp - ay * hp          # PDF is y-up; ay is a top-down fraction
    return (llx, ury - chip_h, llx + chip_w, ury)


# --------------------------------------------------------------------------- #
# Label appearance stream (Pillow glyph raster only — the page is never touched)
# --------------------------------------------------------------------------- #
def _rgb01(rgb255: tuple[int, int, int]) -> ArrayObject:
    """RGB 0..255 tuple -> PDF colour array of FloatObject in 0..1."""
    return ArrayObject([FloatObject(c / 255.0) for c in rgb255])


def _render_label_image(label: str, font: ImageFont.FreeTypeFont, bg_rgb255: tuple[int, int, int]) -> Image.Image:
    """Render the Korean label as black glyphs on the verdict-coloured chip.

    Rendered once per annotation; ``img.size`` is the single source of the chip
    geometry for BOTH the FreeText /Rect placement and the /AP /BBox, so the
    raster and its placement cannot diverge (real font metrics, WYSIWYG).
    """
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    l, t, r, b = draw.textbbox((0, 0), label, font=font)
    img = Image.new("RGB", (max(1, r - l), max(1, b - t)), tuple(bg_rgb255))
    ImageDraw.Draw(img).text((-l, -t), label, font=font, fill=(0, 0, 0))
    return img


def _chip_size_pt(img: Image.Image) -> tuple[float, float]:
    """Glyph image -> chip (text-extent) size in pt, undoing the oversampling."""
    return (img.size[0] / AP_OVERSAMPLE, img.size[1] / AP_OVERSAMPLE)


def _image_xobject(writer: PdfWriter, img: Image.Image):
    """Register ``img`` as a flate-encoded /DeviceRGB image XObject; return its ref."""
    w, h = img.size
    st = StreamObject()
    st[NameObject("/Type")] = NameObject("/XObject")
    st[NameObject("/Subtype")] = NameObject("/Image")
    st[NameObject("/Width")] = NumberObject(w)
    st[NameObject("/Height")] = NumberObject(h)
    st[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
    st[NameObject("/BitsPerComponent")] = NumberObject(8)
    st.set_data(img.tobytes())
    return writer._add_object(st.flate_encode())  # flate_encode returns a new object


def _label_ap(
    writer: PdfWriter,
    img: Image.Image,
    verdict_rgb255: tuple[int, int, int],
):
    """Build the FreeText /AP /N Form XObject (vector chip + glyph image); return ref.

    ``img`` is the pre-rendered label raster from ``_render_label_image`` — the
    same object whose size drove the /Rect placement, so /BBox ≡ chip geometry.

    No ``/Matrix``, ever: the label's /Rect is already the chip's natural,
    unrotated shape and the annotation carries NoRotate, so the identity mapping
    of /BBox onto /Rect is exactly right on every page rotation. A rotation
    /Matrix here would also be silently dropped the moment Acrobat regenerates
    the appearance (see the module docstring).
    """
    im_ref = _image_xobject(writer, img)
    tw_pt, th_pt = _chip_size_pt(img)
    w = tw_pt + 2 * LABEL_BOX_PAD
    h = th_pt + 2 * LABEL_BOX_PAD
    r01, g01, b01 = (c / 255.0 for c in verdict_rgb255)
    gr = _LABEL_GRAY
    content = (
        f"q {r01:g} {g01:g} {b01:g} rg 0 0 {w:g} {h:g} re f "
        f"{gr:g} {gr:g} {gr:g} RG {_CHIP_BORDER_W:g} w "
        f"{LABEL_BOX_PAD:g} {LABEL_BOX_PAD:g} {tw_pt:g} {th_pt:g} re S Q "
        f"q {tw_pt:g} 0 0 {th_pt:g} {LABEL_BOX_PAD:g} {LABEL_BOX_PAD:g} cm /Im0 Do Q"
    ).encode("latin-1")

    form = StreamObject()
    form[NameObject("/Type")] = NameObject("/XObject")
    form[NameObject("/Subtype")] = NameObject("/Form")
    form[NameObject("/FormType")] = NumberObject(1)
    form[NameObject("/BBox")] = ArrayObject(
        [FloatObject(0), FloatObject(0), FloatObject(w), FloatObject(h)]
    )
    res = DictionaryObject()
    xobj = DictionaryObject()
    xobj[NameObject("/Im0")] = im_ref
    res[NameObject("/XObject")] = xobj
    form[NameObject("/Resources")] = res
    form.set_data(content)
    return writer._add_object(form)


# --------------------------------------------------------------------------- #
# Annotation builders (Square main + Popup companion + FreeText label overlay)
# --------------------------------------------------------------------------- #
def _pdf_now() -> str:
    """Run wall-clock time as a PDF date string (offset omitted — spec-allowed)."""
    return time.strftime("D:%Y%m%d%H%M%S")


def _build_square(
    rect_pt: tuple[float, float, float, float],
    verdict: str,
    label: str,
    nm: str,
    stamp: str,
) -> Rectangle:
    """Border-only /Square (no fill) — the main annotation carrying the comment."""
    sq = Rectangle(rect=rect_pt, interior_color=None)  # interior_color=None -> no /IC
    sq[NameObject("/C")] = _rgb01(_verdict_rgb(verdict))
    bs = DictionaryObject()
    bs[NameObject("/W")] = NumberObject(BORDER_W_PT)
    bs[NameObject("/S")] = NameObject("/S")
    sq[NameObject("/BS")] = bs
    sq[NameObject("/F")] = NumberObject(4)
    sq[NameObject("/Contents")] = TextStringObject(label)
    sq[NameObject("/T")] = TextStringObject(ANNOT_AUTHOR)
    sq[NameObject("/Subj")] = TextStringObject(str(verdict))
    sq[NameObject("/NM")] = TextStringObject(nm)
    sq[NameObject("/M")] = TextStringObject(stamp)
    sq[NameObject("/CreationDate")] = TextStringObject(stamp)
    return sq


def _popup_rect(
    sq_rect: tuple[float, float, float, float],
    mx0: float,
    my0: float,
    wp: float,
    hp: float,
) -> tuple[float, float, float, float]:
    """UI-hint popup rect right of the Square, clamped inside the CropBox.

    The coordinates are a viewer hint only (a collapsed popup shows nothing), so
    they are not literal-tested — only the CropBox clamp is guaranteed.
    """
    x0 = sq_rect[2] + LABEL_GAP_PT
    x0 = min(x0, mx0 + wp - POPUP_W_PT)
    x0 = max(x0, mx0)
    y1 = sq_rect[3]
    y1 = min(y1, my0 + hp)
    y1 = max(y1, my0 + POPUP_H_PT)
    return (x0, y1 - POPUP_H_PT, x0 + POPUP_W_PT, y1)


def _build_popup(
    square: Rectangle,
    rect_pt: tuple[float, float, float, float],
    nm: str,
    stamp: str,
) -> Popup:
    """Empty Acrobat-native /Popup companion (bidirectional link to its Square).

    No /Contents — the same collapsed, empty state as the reference document's
    Acrobat square annotation. /Open=False is set by the constructor.
    """
    pop = Popup(rect=rect_pt, parent=square, open=False)  # kwarg is 'parent' (F16)
    pop[NameObject("/NM")] = TextStringObject(f"{nm}-popup")
    pop[NameObject("/M")] = TextStringObject(stamp)
    return pop


def _build_label_annot(
    writer: PdfWriter,
    rect_pt: tuple[float, float, float, float],
    verdict: str,
    label: str,
    img: Image.Image,
    nm: str,
    stamp: str,
) -> FreeText:
    """Always-visible /FreeText label with a self-generated appearance stream.

    /DA is overwritten manually: the FreeText constructor's colour kwargs pollute
    /DA in pypdf 6.6.2 (F5). border_color is deliberately *omitted* (its truthy
    default only feeds the /DA we overwrite; passing None would add /BS W=0).
    No /Popup — this is a label overlay, not a comment carrier.

    /F carries NoRotate on top of Print (FREETEXT_FLAGS) so the chip stays
    viewer-horizontal on a rotated page; ``rect_pt`` is therefore the chip's
    natural width x height anchored at its upper-left corner, never a rotated box.
    """
    rgb = _verdict_rgb(verdict)  # non-None: write_annotated_pdf filters PASS first
    ft = FreeText(
        text=label,
        rect=rect_pt,
        font_size=f"{LABEL_FONT_PT:g}pt",
        background_color="{:02x}{:02x}{:02x}".format(*rgb),
    )
    ft[NameObject("/DA")] = TextStringObject(f"/Helv {LABEL_FONT_PT:g} Tf 0 g")
    ft[NameObject("/F")] = NumberObject(FREETEXT_FLAGS)
    ft[NameObject("/T")] = TextStringObject(ANNOT_AUTHOR)
    ft[NameObject("/Subj")] = TextStringObject(str(verdict))
    ft[NameObject("/NM")] = TextStringObject(f"{nm}-label")
    ft[NameObject("/M")] = TextStringObject(stamp)
    ap = DictionaryObject()
    ap[NameObject("/N")] = _label_ap(writer, img, rgb)
    ft[NameObject("/AP")] = ap
    return ft


def _load_font(font_path: str) -> ImageFont.FreeTypeFont:
    """Load the Hangul label font at the oversampled glyph size (hard-fail if absent)."""
    size = int(round(LABEL_FONT_PT * AP_OVERSAMPLE))
    try:
        return ImageFont.truetype(font_path, size)
    except OSError as e:  # missing font -> hard failure (Korean integrity rule)
        raise OSError(
            f"Korean label font not loadable: {font_path!r} ({e}). "
            f"Set CERT_REVIEW_FONT or install a Hangul-capable TTF."
        ) from e


# --------------------------------------------------------------------------- #
# Writer (copy-through: clone every page verbatim, append annotations only)
# --------------------------------------------------------------------------- #
def write_annotated_pdf(
    pdf_path: Path | str,
    anns_by_page: dict[int, list[Annotation]],
    out_pdf: Path | str,
    rotations: dict[int, int] | None = None,
    font_path: str = DEFAULT_FONT,
) -> tuple[Path, int, int, int]:
    """Attach native annotations to a PDF, preserving every page verbatim.

    ``PdfWriter(clone_from=...)`` copies all pages byte-for-byte; annotations are
    only appended to ``/Annots``. Owns the page-range guard: annotations whose
    page is outside ``1..n_pages`` are counted into the returned ``oob_count`` and
    not attached. ``rotations`` (``{page: deg_cw}``, the align-inputs applied map)
    plus each page's ``/Rotate`` and ``/CropBox`` map the aligned fractional bbox
    back to the original user-space ``/Rect``. Each item becomes a
    Square+Popup+FreeText bundle counted as one.

    The Square's /Rect is mapped from the aligned (review) space via ``T``; the
    FreeText label is instead anchored in the *display* space (the page turned by
    its own ``/Rotate``) because it carries NoRotate and is therefore always drawn
    viewer-horizontal. The two coincide whenever the applied rotation is 0.

    Returns ``(out_path, boxes_drawn, page_count, oob_count)``.
    """
    pdf_path, out_pdf = Path(pdf_path), Path(out_pdf)
    reader = PdfReader(str(pdf_path))
    n_pages = len(reader.pages)
    oob_count = sum(len(a) for p, a in anns_by_page.items() if not 1 <= p <= n_pages)
    has_valid = any(1 <= p <= n_pages for p in anns_by_page)
    font = _load_font(font_path) if has_valid else None

    writer = PdfWriter(clone_from=reader)  # clone the already-parsed reader (single parse)
    stamp = _pdf_now()  # one wall-clock read per call (deterministic across items)
    drawn_total = 0

    for p in sorted(anns_by_page):
        if not 1 <= p <= n_pages:
            continue  # out of range — already counted into oob_count
        anns = anns_by_page[p]
        page = reader.pages[p - 1]
        box = page.cropbox  # pypdf returns MediaBox when CropBox is absent
        mx0 = float(box.left)
        my0 = float(box.bottom)
        wp = float(box.width)
        hp = float(box.height)
        r = int(page.get("/Rotate") or 0) % 360
        if r not in VALID_ROTATIONS:
            r = 0
        a = (rotations.get(p, 0) if rotations else 0) % 360
        t = (r + a) % 360
        ws, hs = _aligned_page_size_pt(wp, hp, r)  # display space (what a viewer shows)

        placed: list[tuple[float, float, float, float]] = []
        seen: set = set()
        seq = 0
        for ann in anns:
            rgb = _verdict_rgb(ann.verdict)
            if rgb is None:  # PASS/other slipped through
                continue
            rect = aligned_bbox_to_user_rect(ann.bbox, mx0, my0, wp, hp, t)
            key = (tuple(round(v, 2) for v in rect), ann.verdict, ann.label)
            if key in seen:  # same rect + verdict + label already attached -> dedupe
                continue
            seen.add(key)
            seq += 1
            nm = f"cert-review-p{p:02d}-{seq:02d}"

            # Square (main) -> Popup (companion) -> FreeText (label overlay).
            sq = _build_square(rect, ann.verdict, ann.label, nm, stamp)
            writer.add_annotation(p - 1, sq)  # returns sq itself, sets .indirect_reference (F16)
            pop = _build_popup(sq, _popup_rect(rect, mx0, my0, wp, hp), nm, stamp)
            writer.add_annotation(p - 1, pop)  # pypdf auto-sets sq[/Popup] back-link (F17)
            sq[NameObject("/Popup")] = pop.indirect_reference  # defensive explicit (idempotent)

            # Label: render once; img.size drives placement AND the /AP /BBox.
            img = _render_label_image(ann.label, font, rgb)
            tw_pt, th_pt = _chip_size_pt(img)
            # Placed in DISPLAY space: a NoRotate label is drawn viewer-horizontal,
            # so above/below/right must mean what the reader sees. Identical to the
            # aligned space (and to the pre-NoRotate placement) whenever a == 0.
            box_disp = _aligned_bbox_to_display_box(ann.bbox, ws, hs, a)
            lx, ly = _place_label(box_disp, tw_pt, th_pt, ws, hs, placed, pad=LABEL_GAP_PT)
            chip = (
                lx - LABEL_BOX_PAD,
                ly - LABEL_BOX_PAD,
                lx + tw_pt + LABEL_BOX_PAD,
                ly + th_pt + LABEL_BOX_PAD,
            )
            placed.append(chip)
            # Only the chip's top-left is transformed (the NoRotate anchor); its
            # size is the /AP /BBox size, so /Rect and /BBox can never diverge.
            label_rect = label_rect_for_norotate(
                (chip[0] / ws, chip[1] / hs),
                (chip[2] - chip[0], chip[3] - chip[1]),
                mx0, my0, wp, hp, r,
            )
            ft = _build_label_annot(writer, label_rect, ann.verdict, ann.label, img, nm, stamp)
            writer.add_annotation(p - 1, ft)
            drawn_total += 1  # one Square+Popup+FreeText bundle = one count

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
    return out_pdf, drawn_total, n_pages, oob_count


# --------------------------------------------------------------------------- #
# Case driver
# --------------------------------------------------------------------------- #
def annotate_case(
    case_id: str,
    work_dir: Path | str,
    cache_root: Path | str,
    cert_dir: Path | str,
    out_dir: Path | str | None = None,
    annotations_path: Path | str | None = None,
    font_path: str = DEFAULT_FONT,
) -> dict:
    """Annotate every cert PDF of a case from its ``<case>_annotations.json``.

    ``cert_dir`` is the cert-cleanup *root* (env-aware ``CERT_DIR`` from the
    CLI); the case folder is ``cert_dir/<case_id>``. Output defaults to
    ``work_dir/output/reports/<case_id>/<stem>_annotated.pdf`` (co-located with
    the Excel report).
    """
    work_dir, cache_root, cert_dir = Path(work_dir), Path(cache_root), Path(cert_dir)
    ann_path = (
        Path(annotations_path)
        if annotations_path
        else cache_root / str(case_id) / f"{case_id}_annotations.json"
    )
    if not ann_path.exists():
        raise FileNotFoundError(f"annotations file not found: {ann_path}")

    anns, skips = load_annotations(ann_path)
    rows_skipped = sum(skips.values())

    case_cert_dir = cert_dir / str(case_id)
    pdfs = sorted(case_cert_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"no cert PDF found in {case_cert_dir}")

    resolved: dict[str | None, Path | None] = {}  # memoize: avoid re-globbing per annotation

    def resolve(stem: str | None) -> Path | None:
        if stem in resolved:
            return resolved[stem]
        if not stem:
            r = pdfs[0] if len(pdfs) == 1 else None
        else:
            try:  # single matching implementation = crop.resolve_stem
                r = resolve_stem(case_id, stem, work_dir, cert_root=cert_dir)
            except (FileNotFoundError, ValueError):
                r = None
        resolved[stem] = r
        return r

    out_dir = Path(out_dir) if out_dir else (work_dir / "output" / "reports" / str(case_id))
    notes: list[str] = []
    groups: dict[Path, dict[int, list[Annotation]]] = {}
    for ann in anns:
        pdf_path = resolve(ann.stem)
        if pdf_path is None:
            rows_skipped += 1
            notes.append(f"unresolved stem {ann.stem!r} (case has {len(pdfs)} PDF(s))")
            continue
        groups.setdefault(pdf_path, {}).setdefault(ann.page, []).append(ann)

    outputs: list[dict] = []
    boxes_drawn = 0
    for pdf_path, by_page in groups.items():
        out_pdf = out_dir / f"{pdf_path.stem}_annotated.pdf"
        rotations = applied_rotations(cache_root / str(case_id), pdf_path.stem)
        # write_annotated_pdf owns the page-range guard and opens the PDF once.
        _, drawn, pages, oob = write_annotated_pdf(
            pdf_path, by_page, out_pdf, rotations=rotations, font_path=font_path
        )
        boxes_drawn += drawn
        if oob:
            rows_skipped += oob
            notes.append(f"{pdf_path.stem}: {oob} annotation(s) out of page range 1..{pages}")
        outputs.append(
            {"stem": pdf_path.stem, "pages": pages, "boxes": drawn, "out_path": str(out_pdf)}
        )

    return {
        "case_id": str(case_id),
        "n_pdfs": len(outputs),
        "boxes_drawn": boxes_drawn,
        "rows_skipped": rows_skipped,
        "skip_counts": skips,
        "outputs": outputs,
        "notes": notes,
    }


__all__ = [
    "Annotation",
    "annotate_case",
    "write_annotated_pdf",
    "load_annotations",
]
