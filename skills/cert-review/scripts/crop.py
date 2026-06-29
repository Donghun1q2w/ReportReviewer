"""crop.py — high-DPI crop of a fractional bbox region of one cert page.

Replaces the ad-hoc per-case zoom scripts: the model can re-read an ambiguous
cell deterministically by cropping a sub-region of a single page at a higher DPI
than the full-page render. The bbox is given as 0.0–1.0 FRACTIONS (top-left
origin) so it is resolution-independent; this module converts the fractions to
pixels against the rendered page size and saves the crop.

Constraint C1: no OCR libraries — pypdfium2 is a rasteriser only.
Constraint C7: pathlib throughout, encoding handled by PIL/pdfium.
Reads ONLY the cert-cleanup PDFs and writes under the plugin .cache directory.
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"


def parse_bbox(bbox: str | tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Parse and validate a fractional bbox 'x0,y0,x1,y1' (each in [0.0, 1.0]).

    Returns the 4-tuple of floats. Raises ValueError on malformed input, out of
    range values, or a non-positive width/height.
    """
    if isinstance(bbox, str):
        parts = [p.strip() for p in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError(f"bbox must have 4 comma-separated values, got: {bbox!r}")
        try:
            x0, y0, x1, y1 = (float(p) for p in parts)
        except ValueError as e:
            raise ValueError(f"bbox values must be numeric: {bbox!r}") from e
    else:
        x0, y0, x1, y1 = (float(v) for v in bbox)

    for name, v in (("x0", x0), ("y0", y0), ("x1", x1), ("y1", y1)):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"bbox {name}={v} out of range [0.0, 1.0]")
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"bbox must have x1>x0 and y1>y0, got: {(x0, y0, x1, y1)}")
    return (x0, y0, x1, y1)


def bbox_to_pixels(
    bbox: tuple[float, float, float, float],
    width_px: int,
    height_px: int,
) -> tuple[int, int, int, int]:
    """Convert a fractional bbox to integer pixel box (left, top, right, bottom).

    Pixels are clamped to the image extent and the box is guaranteed at least
    1px wide/high so PIL.crop yields a non-empty image.
    """
    x0, y0, x1, y1 = bbox
    left = int(round(x0 * width_px))
    top = int(round(y0 * height_px))
    right = int(round(x1 * width_px))
    bottom = int(round(y1 * height_px))
    left = max(0, min(left, width_px - 1))
    top = max(0, min(top, height_px - 1))
    right = max(left + 1, min(right, width_px))
    bottom = max(top + 1, min(bottom, height_px))
    return (left, top, right, bottom)


def _bbox_slug(bbox: tuple[float, float, float, float]) -> str:
    """Render a bbox as a filename slug: x0xy0-x1xy1 with 2-decimal coords."""
    x0, y0, x1, y1 = bbox
    return f"{x0:.2f}x{y0:.2f}-{x1:.2f}x{y1:.2f}"


def resolve_stem(
    case_id: str, stem: str, work_dir: Path, cert_root: Path | None = None
) -> Path:
    """Resolve a cert PDF by stem within a case, allowing a unique prefix match.

    Exact stem match wins. Otherwise a unique prefix match is accepted; an
    ambiguous prefix raises ValueError listing the candidates.

    ``cert_root`` overrides the cert-cleanup root directory (so an env-aware
    ``CERT_DIR`` can be passed in instead of the hard-coded default); when
    omitted the default ``work_dir/<CERT_CLEANUP_DIRNAME>`` is used so existing
    callers are unaffected.
    """
    root = Path(cert_root) if cert_root is not None else Path(work_dir) / CERT_CLEANUP_DIRNAME
    cert_dir = root / str(case_id)
    if not cert_dir.is_dir():
        raise FileNotFoundError(f"cert dir not found: {cert_dir}")

    pdfs = sorted(cert_dir.glob("*.pdf"))
    by_stem = {p.stem: p for p in pdfs}

    if stem in by_stem:
        return by_stem[stem]

    prefix_hits = [p for p in pdfs if p.stem.startswith(stem)]
    if len(prefix_hits) == 1:
        return prefix_hits[0]
    if len(prefix_hits) > 1:
        cands = ", ".join(p.stem for p in prefix_hits)
        raise ValueError(f"ambiguous stem {stem!r}; candidates: {cands}")
    raise FileNotFoundError(
        f"no cert PDF matching stem {stem!r} in case {case_id}; "
        f"available: {', '.join(by_stem) or '(none)'}"
    )


def crop_region(
    case_id: str,
    stem: str,
    page: int,
    bbox: str | tuple[float, float, float, float],
    work_dir: Path,
    cache_root: Path,
    dpi: int = 300,
) -> Path:
    """Render one cert page at ``dpi`` and save the fractional ``bbox`` crop.

    Returns the absolute path to the saved PNG under
    ``.cache/<case>/crops/<stem>_p<NN>_<slug>.png``.
    """
    if page < 1:
        raise ValueError(f"page must be >= 1, got {page}")

    parsed = parse_bbox(bbox)
    pdf_path = resolve_stem(case_id, stem, work_dir)
    cert_stem = pdf_path.stem

    crops_dir = Path(cache_root) / str(case_id) / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        n_pages = len(doc)
        if page > n_pages:
            raise ValueError(f"page {page} out of range (1..{n_pages}) for {cert_stem}")
        pdf_page = doc[page - 1]
        scale = dpi / 72.0
        bitmap = pdf_page.render(scale=scale)
        pil_image = bitmap.to_pil()
    finally:
        doc.close()

    width_px, height_px = pil_image.size
    box = bbox_to_pixels(parsed, width_px, height_px)
    crop = pil_image.crop(box)

    out_path = crops_dir / f"{cert_stem}_p{page:02d}_{_bbox_slug(parsed)}.png"
    crop.save(str(out_path))
    return out_path.resolve()


__all__ = [
    "parse_bbox",
    "bbox_to_pixels",
    "resolve_stem",
    "crop_region",
]
