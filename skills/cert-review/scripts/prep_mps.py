"""prep_mps.py — render + tile the MPS (구매시방서) PDFs for one case.

The MPS PDFs are scanned (no text layer), so each review agent that needs an
MPS special-requirement would otherwise Vision-OCR the same scanned pages
independently — redundant across the 5 reviewers and slow (downsampled scans
need crops). This step renders the case's MPS PDFs to PNGs and 2x2 tiles once,
so a single `mps-extractor` agent can transcribe them into a shared digest the
reviewers consume instead of re-reading the raw MPS.

A/B (case 4): reviewers reading a shared MPS digest instead of raw MPS dropped
the review wall from ~95 min to ~32 min (tool-uses per heavy reviewer ~48 ->
~18) with recall 3/4 -> 4/4.

Constraint C1: render (pypdfium2) + crop (Pillow) only, no OCR — Claude Vision
still reads the tiles. Constraint C7: pathlib + utf-8 throughout.
"""

from __future__ import annotations

from pathlib import Path

from scripts.pdf_split import split_pdf
from scripts.tile_inputs import _DEFAULT_COLS, _DEFAULT_OVERLAP, _DEFAULT_ROWS, tile_image

from PIL import Image

MPS_CLEANUP_DIRNAME = "standard inspection MPS cleanup data"


def prep_mps_case(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
    dpi: int = 300,
    rows: int = _DEFAULT_ROWS,
    cols: int = _DEFAULT_COLS,
    overlap: float = _DEFAULT_OVERLAP,
) -> dict:
    """Render + tile every MPS PDF of a case.

    Reads ``<work_dir>/standard inspection MPS cleanup data/<case>/*.pdf`` and
    writes page PNGs to ``.cache/<case>/mps_png/`` and 2x2 tiles to
    ``.cache/<case>/mps_tiles/<stem>_pNN_rRcC.png``. Returns a summary dict.
    Raises FileNotFoundError if the case has no MPS folder.
    """
    mps_dir = Path(work_dir) / MPS_CLEANUP_DIRNAME / str(case_id)
    if not mps_dir.is_dir():
        raise FileNotFoundError(f"no MPS folder for case {case_id}: {mps_dir}")

    pdfs = sorted(mps_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"no MPS PDFs under {mps_dir}")

    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "mps_png"
    tiles_dir = case_cache / "mps_tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    docs_out: list[dict] = []
    for pdf in pdfs:
        pages = split_pdf(pdf, png_dir, dpi=dpi)
        tile_count = 0
        for png in pages:
            page_no = int(png.stem.rsplit("_p", 1)[1])
            with Image.open(png) as im:
                im = im.convert("RGB")
                for r, c, tile in tile_image(im, rows, cols, overlap):
                    out = tiles_dir / f"{pdf.stem}_p{page_no:02d}_r{r}c{c}.png"
                    tile.save(out)
                    tile_count += 1
        docs_out.append(
            {"file": pdf.name, "stem": pdf.stem, "page_count": len(pages), "tile_count": tile_count}
        )

    return {
        "case_id": str(case_id),
        "grid": f"{rows}x{cols}",
        "mps_png_dir": str(png_dir.resolve()),
        "mps_tiles_dir": str(tiles_dir.resolve()),
        "docs": docs_out,
    }


__all__ = ["prep_mps_case"]
