"""prep_inputs.py — Phase-1 deterministic (non-Vision) input preparation.

Produces the BODY input channel for a case WITHOUT any OCR:
  body — per-page PNGs rendered from each cert PDF (pdf_split, pdfium raster)

For each cert PDF a SKELETON <cert_stem>_extracted.json is written, conforming to
references/extraction-schema.json v2.0. Phase-2 Claude Vision later fills
channels.body.pages and page_extraction. Re-running prep is idempotent: a skeleton
that already carries non-empty page_extraction is preserved.

Operation reads ONLY the cert-cleanup PDFs. The rawdata originals (which carry
live reviewer annotations / ground truth) are NEVER touched — there is no
annotation channel and no zip-unpack fallback.

Constraint C1: NO Python OCR libs — only existing modules + stdlib + pypdf/pypdfium2.
Constraint C7: pathlib throughout, encoding='utf-8' on all file I/O.
Never reference the literal ground-truth or rawdata directories.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.pdf_split import split_pdf
from scripts.source_validator import compute_sha256

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"


def _load_existing_skeleton(path: Path) -> dict | None:
    """Return the parsed skeleton if it exists and is valid JSON, else None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def prep_case(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
    dpi: int = 200,
) -> dict:
    """Produce the deterministic (non-Vision) body inputs for a case and write a
    skeleton extracted.json per cert that Phase-2 Claude Vision will fill.

    Returns a summary dict:
        {
          "case_id": str,
          "certs": [
            {"cert_pdf": str, "png_count": int, "skeleton_path": str}
          ],
          "notes": [str, ...],
        }
    """
    work_dir = Path(work_dir)
    cache_root = Path(cache_root)

    case_cache = cache_root / case_id
    png_dir = case_cache / "png"
    case_cache.mkdir(parents=True, exist_ok=True)

    notes: list[str] = []

    cert_cleanup_dir = work_dir / CERT_CLEANUP_DIRNAME / case_id

    # ── 1. Determine cert PDFs to OCR (cert-cleanup folder only) ──────────────
    cert_pdfs = (
        sorted(cert_cleanup_dir.glob("*.pdf")) if cert_cleanup_dir.is_dir() else []
    )
    if not cert_pdfs:
        notes.append("no cert PDFs in cleanup dir")

    # ── 2. Per-cert processing ────────────────────────────────────────────────
    certs_summary: list[dict] = []

    for cert_pdf in cert_pdfs:
        cert_stem = cert_pdf.stem

        # Render per-page PNGs.
        pngs = split_pdf(cert_pdf, png_dir, dpi=dpi)

        # Skeleton extracted.json (idempotent: preserve OCR'd content).
        skeleton_path = case_cache / f"{cert_stem}_extracted.json"

        try:
            cert_rel = str(cert_pdf.relative_to(work_dir)).replace("\\", "/")
        except ValueError:
            cert_rel = str(cert_pdf).replace("\\", "/")

        existing = _load_existing_skeleton(skeleton_path)
        existing_pages = (
            existing.get("page_extraction") if isinstance(existing, dict) else None
        )

        if existing and existing_pages:
            # Already OCR'd — preserve page_extraction + channels.body untouched.
            skeleton = existing
            notes.append(f"{cert_pdf.name}: skipped_existing_ocr")
        else:
            skeleton = {
                "schema_version": "2.0",
                "case_id": case_id,
                "cert_file": cert_rel,
                "cert_sha256": compute_sha256(cert_pdf),
                "extracted_at": None,
                "channels": {
                    "body": {"engine": "claude-vision", "pages": []},
                },
                "page_extraction": [],
            }

        skeleton_path.write_text(
            json.dumps(skeleton, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        certs_summary.append({
            "cert_pdf": cert_rel,
            "png_count": len(pngs),
            "skeleton_path": str(skeleton_path).replace("\\", "/"),
        })

    return {
        "case_id": case_id,
        "certs": certs_summary,
        "notes": notes,
    }


__all__ = ["prep_case"]
