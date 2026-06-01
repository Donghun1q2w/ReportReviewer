"""Render cert PDFs to per-page PNGs using pypdfium2 (rasterisation only, no OCR).

Constraint C1: no OCR libraries. pypdfium2 is a CPU/GPU rasteriser.
Constraint C7: pathlib throughout, encoding='utf-8' on all file I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium


def split_pdf(pdf_path: Path, out_dir: Path, dpi: int = 200) -> list[Path]:
    """Render each page of pdf_path to a PNG inside out_dir.

    Returns the list of PNG paths in page order (1-indexed in filename:
    _p01.png, _p02.png, ...).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem
    results: list[Path] = []

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        n_pages = len(doc)
        for i in range(n_pages):
            page = doc[i]
            # scale factor: pdfium default is 72 dpi, so scale = dpi/72
            scale = dpi / 72.0
            bitmap = page.render(scale=scale)
            pil_image = bitmap.to_pil()
            page_num = i + 1
            png_path = out_dir / f"{stem}_p{page_num:02d}.png"
            pil_image.save(str(png_path))
            results.append(png_path)
    finally:
        doc.close()

    return results


def split_case(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
    dpi: int = 200,
) -> dict[str, list[str]]:
    """For each cert PDF in 'standard inspection Cert cleanup data/<case_id>/',
    split into PNGs under cache_root/<case_id>/png/.

    Returns mapping {cert_stem: [png_relative_paths]}.
    """
    cert_dir = work_dir / "standard inspection Cert cleanup data" / case_id
    png_dir = cache_root / case_id / "png"
    png_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, list[str]] = {}

    pdf_files = sorted(cert_dir.glob("*.pdf"))
    for pdf_path in pdf_files:
        pngs = split_pdf(pdf_path, png_dir, dpi=dpi)
        rel_paths = [str(p.relative_to(cache_root)).replace("\\", "/") for p in pngs]
        result[pdf_path.stem] = rel_paths

    return result


def _cli_main(argv: list[str] | None = None) -> int:
    """Minimal standalone CLI: pdf_split <pdf_path> <out_dir> [dpi]."""
    import argparse

    parser = argparse.ArgumentParser(prog="pdf_split", description="Render PDF pages to PNG")
    parser.add_argument("pdf_path", type=Path, help="Path to the cert PDF")
    parser.add_argument("out_dir", type=Path, help="Output directory for PNGs")
    parser.add_argument("--dpi", type=int, default=200, help="Render DPI (default 200)")
    args = parser.parse_args(argv)

    pngs = split_pdf(args.pdf_path, args.out_dir, dpi=args.dpi)
    for p in pngs:
        print(str(p))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
