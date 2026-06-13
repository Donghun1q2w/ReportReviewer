"""tile_inputs.py — split rendered cert page PNGs into overlapping tiles.

When the model `Read`s a PNG, the image is downsampled to a fixed long-edge
(~1568 px) before the model sees it. A full MTC page (~3500 px wide) loses so
much detail that small chemistry/identification digits become illegible, which
is what drives the slow per-cell high-DPI cropping in Phase 2. Splitting each
page into a 2x2 grid of overlapping tiles roughly halves each tile's long edge,
so a tile survives downsampling with ~1.8x more detail — legible enough that the
OCR agent transcribes directly without crop-hunting.

A/B (case 4, p5-8, opus, single): full-page = ~24 min / 101 tool-uses / ~100
crops; 2x2 tiles = ~9 min / 23 tool-uses / 0 crops, identical identification
accuracy.

Constraint C1: image cropping only (Pillow), no OCR. Pillow handles Unicode
(Korean) paths natively, unlike cv2.imread. Tiles feed Claude Vision, which
still does all text recognition.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

_DEFAULT_ROWS = 2
_DEFAULT_COLS = 2
_DEFAULT_OVERLAP = 0.06  # fractional overlap so boundary cells appear in 2 tiles


def tile_bounds(
    rows: int, cols: int, overlap: float
) -> list[tuple[int, int, float, float, float, float]]:
    """Return fractional (r, c, x0, y0, x1, y1) boxes for an overlapping grid."""
    boxes: list[tuple[int, int, float, float, float, float]] = []
    for r in range(rows):
        for c in range(cols):
            x0 = max(0.0, c / cols - overlap)
            y0 = max(0.0, r / rows - overlap)
            x1 = min(1.0, (c + 1) / cols + overlap)
            y1 = min(1.0, (r + 1) / rows + overlap)
            boxes.append((r, c, x0, y0, x1, y1))
    return boxes


def tile_image(
    image: Image.Image,
    rows: int = _DEFAULT_ROWS,
    cols: int = _DEFAULT_COLS,
    overlap: float = _DEFAULT_OVERLAP,
) -> list[tuple[int, int, Image.Image]]:
    """Split a PIL image into rows*cols overlapping tiles.

    Returns a list of (row, col, tile_image). Pixel boxes are clamped and kept
    at least 1px so every tile is non-empty.
    """
    w, h = image.size
    tiles: list[tuple[int, int, Image.Image]] = []
    for r, c, x0, y0, x1, y1 in tile_bounds(rows, cols, overlap):
        left = max(0, min(int(round(x0 * w)), w - 1))
        top = max(0, min(int(round(y0 * h)), h - 1))
        right = max(left + 1, min(int(round(x1 * w)), w))
        bottom = max(top + 1, min(int(round(y1 * h)), h))
        tiles.append((r, c, image.crop((left, top, right, bottom))))
    return tiles


def _stems_in_png_dir(png_dir: Path) -> dict[str, list[Path]]:
    """Group rendered page PNGs by cert stem (strips trailing _pNN)."""
    stems: dict[str, list[Path]] = {}
    for png in sorted(png_dir.glob("*_p[0-9][0-9].png")):
        stem = png.stem.rsplit("_p", 1)[0]
        stems.setdefault(stem, []).append(png)
    return stems


def tile_case(
    case_id: str,
    cache_root: Path,
    rows: int = _DEFAULT_ROWS,
    cols: int = _DEFAULT_COLS,
    overlap: float = _DEFAULT_OVERLAP,
) -> dict:
    """Tile every rendered cert page of a case into ``.cache/<case>/tiles/``.

    Reads ``.cache/<case>/png/<stem>_pNN.png`` and writes
    ``.cache/<case>/tiles/<stem>_pNN_rRcC.png``. Returns a summary dict. Raises
    FileNotFoundError if the case has no rendered PNGs (run prep-inputs first).
    """
    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "png"
    if not png_dir.is_dir():
        raise FileNotFoundError(f"no rendered PNGs for case {case_id}: {png_dir}")

    stems = _stems_in_png_dir(png_dir)
    if not stems:
        raise FileNotFoundError(f"no <stem>_pNN.png under {png_dir}")

    tiles_dir = case_cache / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    certs_out: list[dict] = []
    for stem, pngs in stems.items():
        tile_count = 0
        for png in pngs:
            page_no = int(png.stem.rsplit("_p", 1)[1])
            with Image.open(png) as im:
                im = im.convert("RGB")
                for r, c, tile in tile_image(im, rows, cols, overlap):
                    out = tiles_dir / f"{stem}_p{page_no:02d}_r{r}c{c}.png"
                    tile.save(out)
                    tile_count += 1
        certs_out.append(
            {"stem": stem, "page_count": len(pngs), "tile_count": tile_count}
        )

    return {
        "case_id": str(case_id),
        "grid": f"{rows}x{cols}",
        "overlap": overlap,
        "tiles_dir": str(tiles_dir.resolve()),
        "certs": certs_out,
    }


__all__ = ["tile_bounds", "tile_image", "tile_case"]
