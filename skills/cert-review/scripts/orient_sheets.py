"""orient_sheets.py — contact sheets for page-orientation detection (Phase 1.5).

Scanned certs arrive with per-page rotation mixed inside one PDF (metadata
/Rotate = 0, the scan CONTENT itself is sideways). Reading every full page to
judge orientation would cost one Vision Read per page; instead this module
composes the rendered cert pages into labelled contact sheets (3x4 thumbnails,
~12 pages per Read) that the `page-aligner` agent reads to emit a per-page
rotation map (`<stem>_orientation.json`). The deterministic rotation itself is
applied later by align_inputs.py — this module only prepares detection input.

Cert pages only (`.cache/<case>/png/`): the MPS channel is out of scope by
decision (see docs/plans/2026-07-09_085623_page-orientation-alignment.md).

Constraint C1: composition only (Pillow) — no OCR, no text extraction. The
page-number labels are drawn upright so the agent can reference pages even when
the page content itself is rotated.
Constraint C7: pathlib throughout, encoding='utf-8' on all file I/O.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from scripts.tile_inputs import _stems_in_png_dir

_DEFAULT_COLS = 3
_DEFAULT_ROWS = 4
_THUMB_LONG = 360   # thumbnail long edge (px)
_LABEL_H = 26       # per-cell label bar height (px)
_HEADER_H = 34      # per-sheet header height (px)
_PAD = 6            # cell padding (px)

# Label font: digits/ASCII only, so a missing TTF falls back to the PIL
# bitmap font instead of hard-failing (unlike annotate_pdf's Korean labels).
_LABEL_FONT = os.environ.get("CERT_REVIEW_FONT", r"C:\Windows\Fonts\malgun.ttf")

SHEETS_DIRNAME = "orient"
SHEETS_INDEX_NAME = "sheets_index.json"


def _load_label_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_LABEL_FONT, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _cell_size(thumb_long: int) -> tuple[int, int]:
    """Fixed cell box that fits a thumbnail of either orientation + label bar."""
    side = thumb_long + 2 * _PAD
    return side, side + _LABEL_H


def _thumbnail(png: Path, thumb_long: int) -> Image.Image:
    with Image.open(png) as im:
        im = im.convert("RGB")
        im.thumbnail((thumb_long, thumb_long), Image.LANCZOS)
        return im.copy()


def _compose_sheet(
    stem: str,
    sheet_no: int,
    pages: list[tuple[int, Path]],
    cols: int,
    rows: int,
    thumb_long: int,
) -> Image.Image:
    cell_w, cell_h = _cell_size(thumb_long)
    width = cols * cell_w
    height = _HEADER_H + rows * cell_h
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)

    header_font = _load_label_font(20)
    label_font = _load_label_font(18)

    draw.text(
        (_PAD, (_HEADER_H - 20) // 2),
        f"{stem} — sheet {sheet_no:02d} (labels are upright; judge each page's content)",
        font=header_font,
        fill=(0, 0, 0),
    )
    draw.line([(0, _HEADER_H - 1), (width, _HEADER_H - 1)], fill=(0, 0, 0))

    for i, (page_no, png) in enumerate(pages):
        r, c = divmod(i, cols)
        x0 = c * cell_w
        y0 = _HEADER_H + r * cell_h

        # Upright label bar above the thumbnail.
        draw.rectangle([x0, y0, x0 + cell_w - 1, y0 + _LABEL_H - 1], outline=(0, 0, 0))
        draw.text((x0 + _PAD, y0 + 4), f"p{page_no:02d}", font=label_font, fill=(0, 0, 0))

        thumb = _thumbnail(png, thumb_long)
        tx = x0 + (cell_w - thumb.size[0]) // 2
        ty = y0 + _LABEL_H + _PAD + (thumb_long - thumb.size[1]) // 2
        sheet.paste(thumb, (tx, ty))
        draw.rectangle(
            [tx - 1, ty - 1, tx + thumb.size[0], ty + thumb.size[1]],
            outline=(160, 160, 160),
        )
    return sheet


def build_orient_sheets(
    case_id: str,
    cache_root: Path,
    cols: int = _DEFAULT_COLS,
    rows: int = _DEFAULT_ROWS,
    thumb_long: int = _THUMB_LONG,
    sheets_dirname: str = SHEETS_DIRNAME,
) -> dict:
    """Compose labelled contact sheets from a case's rendered cert pages.

    Reads ``.cache/<case>/png/<stem>_pNN.png`` (cert channel only) and writes
    ``.cache/<case>/<sheets_dirname>/<stem>__sheetNN.png`` plus a
    machine-readable index ``<sheets_dirname>/sheets_index.json``. Returns a
    summary dict. Raises FileNotFoundError when the case has no rendered PNGs
    (run prep-inputs first).

    ``sheets_dirname`` defaults to ``orient`` (Phase 1.5). Phase 1.6 reuses this
    builder with ``classify`` to compose UPRIGHT sheets (post-alignment pixels)
    for document-type reading; the default-path behaviour is byte-identical.
    """
    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "png"
    if not png_dir.is_dir():
        raise FileNotFoundError(f"no rendered PNGs for case {case_id}: {png_dir}")

    stems = _stems_in_png_dir(png_dir)
    if not stems:
        raise FileNotFoundError(f"no <stem>_pNN.png under {png_dir}")

    sheets_dir = case_cache / sheets_dirname
    sheets_dir.mkdir(parents=True, exist_ok=True)

    per_sheet = cols * rows
    sheets_out: list[dict] = []
    stems_out: dict[str, int] = {}

    for stem, pngs in sorted(stems.items()):
        # Idempotent regeneration: drop this stem's previous sheets so a
        # page-count drop cannot leave a stale trailing sheet behind.
        stale_re = re.compile(re.escape(stem) + r"__sheet\d+\.png\Z")
        for old in sheets_dir.iterdir():
            if stale_re.fullmatch(old.name):
                old.unlink(missing_ok=True)

        numbered = sorted(
            (int(p.stem.rsplit("_p", 1)[1]), p) for p in pngs
        )
        stems_out[stem] = len(numbered)
        for si in range(0, len(numbered), per_sheet):
            chunk = numbered[si : si + per_sheet]
            sheet_no = si // per_sheet + 1
            sheet = _compose_sheet(stem, sheet_no, chunk, cols, rows, thumb_long)
            out = sheets_dir / f"{stem}__sheet{sheet_no:02d}.png"
            sheet.save(out)
            sheets_out.append({
                "file": out.name,
                "stem": stem,
                "sheet_no": sheet_no,
                "pages": [n for n, _ in chunk],
            })

    index = {
        "schema_version": "1.0",
        "case_id": str(case_id),
        "grid": f"{cols}x{rows}",
        "thumb_long": thumb_long,
        "stems": stems_out,
        "sheets": sheets_out,
    }
    index_path = sheets_dir / SHEETS_INDEX_NAME
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "case_id": str(case_id),
        "sheets_dir": str(sheets_dir.resolve()),
        "index_path": str(index_path.resolve()),
        "n_sheets": len(sheets_out),
        "stems": stems_out,
    }


__all__ = ["build_orient_sheets", "SHEETS_DIRNAME", "SHEETS_INDEX_NAME"]
