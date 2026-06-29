"""annotate_pdf.py — burn review verdicts onto cert PDFs as boxed annotations.

Consumes a standalone ``<case>_annotations.json`` (produced by the
``annotation-locator`` agent) plus the original cert PDF(s), and writes
``<stem>_annotated.pdf`` with a border-only rectangle + <=50 char Korean label
around each 주의 / N/A / FAIL region. **PASS is never annotated.**

This is a deterministic *renderer* — it does not locate cells; it draws the
coordinates handed to it. Locating (page + fractional bbox) is the
``annotation-locator`` agent's job, so the cert-review review logic (the 5
reviewers, review-criteria, review.json schema) is untouched.

Constraint C1: no OCR libraries. Only ``pypdfium2`` (rasterise), ``Pillow``
(draw) and ``pypdf`` (page splice) are used — none perform OCR. Verdict
canonicalisation and the four verdict colours are reused from
``compliance_report`` so the burn-in matches the 6-sheet Excel report exactly.

Coordinate convention: fractional bbox ``[x0, y0, x1, y1]`` in ``[0, 1]`` with a
top-left origin — identical to ``crop.py`` — applied to the *same*
``pypdfium2`` ``page.render(scale=dpi/72)`` raster. Because pdfium applies the
page ``/Rotate`` when rendering, no rotation maths are needed here.

Reassembly is *copy-through*: only pages that carry annotations are rasterised
and re-embedded; every other page is preserved verbatim from the original PDF
(pypdf splice). This keeps file size and peak memory ~1 page and preserves the
original page objects.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter

from scripts.compliance_report import (
    _FAIL_FILL,
    _NA_FILL,
    _WARN_FILL,
    _canon_verdict,
)
from scripts.crop import bbox_to_pixels, parse_bbox, resolve_stem

# Hangul-capable label font; override via CERT_REVIEW_FONT for non-Windows hosts.
DEFAULT_FONT = os.environ.get("CERT_REVIEW_FONT", r"C:\Windows\Fonts\malgun.ttf")
LABEL_MAX = 50
LABEL_BOX_PAD = 2        # px padding of the label text chip around the glyphs
_LINE_W_PER_DPI = 75     # box outline width = max(3, round(dpi / this))
_FONT_PX_PER_DPI = 0.16  # label font px = clamp(round(dpi * this), 20, 64)

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
    box_px: tuple[int, int, int, int],
    tw: int,
    th: int,
    page_w: int,
    page_h: int,
    placed: list[tuple[int, int, int, int]],
    pad: int = 6,
) -> tuple[int, int]:
    """Pick a label top-left that avoids already-placed labels and the page edge.

    Tries above / below / right of the box, then stacks downward; always clamps
    inside the page. The box itself is never moved (only the label).
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
# Rendering (impure)
# --------------------------------------------------------------------------- #
def _render_page_pil(pdf_page, dpi: int) -> Image.Image:
    bitmap = pdf_page.render(scale=dpi / 72.0)
    return bitmap.to_pil().convert("RGB")


def _draw_annotations(
    img: Image.Image, anns: list[Annotation], font: ImageFont.FreeTypeFont, dpi: int
) -> int:
    """Draw border-only boxes + labels onto ``img``; return the count drawn."""
    draw = ImageDraw.Draw(img)
    page_w, page_h = img.size
    line_w = max(3, round(dpi / _LINE_W_PER_DPI))
    placed: list[tuple[int, int, int, int]] = []
    seen_boxes: set[tuple[int, int, int, int]] = set()
    drawn = 0

    for ann in anns:
        rgb = _verdict_rgb(ann.verdict)
        if rgb is None:  # PASS/other slipped through — never annotate
            continue
        box = bbox_to_pixels(ann.bbox, page_w, page_h)
        if box in seen_boxes:  # identical box already drawn -> dedupe
            continue
        seen_boxes.add(box)

        # border-only rectangle (no fill)
        draw.rectangle(box, outline=rgb, fill=None, width=line_w)

        # label: verdict-coloured chip + black text, placed clear of the box
        l, t, r, b = draw.textbbox((0, 0), ann.label, font=font)
        tw, th = r - l, b - t
        x, y = _place_label(box, tw, th, page_w, page_h, placed)
        chip = (x - LABEL_BOX_PAD, y - LABEL_BOX_PAD, x + tw + LABEL_BOX_PAD, y + th + LABEL_BOX_PAD)
        draw.rectangle(chip, fill=rgb, outline=(80, 80, 80), width=1)
        draw.text((x - l, y - t), ann.label, font=font, fill=(0, 0, 0))
        placed.append(chip)
        drawn += 1

    return drawn


def _load_font(font_path: str, dpi: int) -> ImageFont.FreeTypeFont:
    font_px = max(20, min(64, round(dpi * _FONT_PX_PER_DPI)))
    try:
        return ImageFont.truetype(font_path, font_px)
    except OSError as e:  # missing font -> hard failure (Korean integrity rule)
        raise OSError(
            f"Korean label font not loadable: {font_path!r} ({e}). "
            f"Set CERT_REVIEW_FONT or install a Hangul-capable TTF."
        ) from e


def render_annotated_pdf(
    pdf_path: Path | str,
    anns_by_page: dict[int, list[Annotation]],
    out_pdf: Path | str,
    dpi: int = 200,
    font_path: str = DEFAULT_FONT,
) -> tuple[Path, int, int, int]:
    """Copy-through burn-in: rasterise only annotated pages, keep the rest.

    Owns the page-range guard: annotations whose page is outside ``1..n_pages``
    are counted into the returned ``oob_count`` and not drawn. Returns
    ``(out_path, boxes_drawn, page_count, oob_count)``. Opens the source PDF once.
    """
    pdf_path, out_pdf = Path(pdf_path), Path(out_pdf)
    reader = PdfReader(str(pdf_path))
    n_pages = len(reader.pages)
    oob_count = sum(len(a) for p, a in anns_by_page.items() if not 1 <= p <= n_pages)
    font = _load_font(font_path, dpi) if any(1 <= p <= n_pages for p in anns_by_page) else None

    doc = pdfium.PdfDocument(str(pdf_path))
    writer = PdfWriter()
    drawn_total = 0
    try:
        for i in range(n_pages):
            anns = anns_by_page.get(i + 1)
            if not anns:
                writer.add_page(reader.pages[i])  # copy-through (verbatim)
                continue
            img = _render_page_pil(doc[i], dpi)
            drawn_total += _draw_annotations(img, anns, font, dpi)
            buf = io.BytesIO()
            # quality high to keep burned Korean labels crisp (legibility QA'd)
            img.save(buf, format="PDF", resolution=float(dpi), quality=95)
            buf.seek(0)
            writer.add_page(PdfReader(buf).pages[0])
    finally:
        doc.close()

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
    dpi: int = 200,
    annotations_path: Path | str | None = None,
    font_path: str = DEFAULT_FONT,
) -> dict:
    """Render every cert PDF of a case from its ``<case>_annotations.json``.

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
        # render_annotated_pdf owns the page-range guard and opens the PDF once.
        _, drawn, pages, oob = render_annotated_pdf(pdf_path, by_page, out_pdf, dpi, font_path)
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
    "render_annotated_pdf",
    "load_annotations",
]
