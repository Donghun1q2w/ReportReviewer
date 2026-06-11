"""prep_inputs.py — Phase-1 deterministic (non-Vision) input preparation.

Produces the BODY input channel for a case WITHOUT any OCR:
  body — per-page PNGs rendered from each cert PDF (pdf_split, pdfium raster)

For each cert PDF a SKELETON <cert_stem>_extracted.json is written, conforming to
references/extraction-schema.json v2.0. Phase-2 Claude Vision later fills
channels.body.pages and page_extraction. Re-running prep is idempotent: a skeleton
that already carries non-empty page_extraction is preserved.

A render-cache SIDECAR <cert_stem>_prep.json is written next to the skeleton,
recording the source PDF sha256, the render dpi and the rendered page count. On a
re-run, when the sidecar matches (same sha256 + dpi) AND every rendered PNG is
present, the PDF is NOT re-rendered. ``--force`` overrides the gate. The sidecar
is deliberately a separate file (not stored inside _extracted.json) because
Phase-2 Claude Vision rewrites the whole _extracted.json, which would otherwise
drop the render metadata.

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
from scripts.source_validator import compute_sha256_fresh

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"

_PREP_SIDECAR_SUFFIX = "_prep.json"


def _load_existing_skeleton(path: Path) -> dict | None:
    """Return the parsed skeleton if it exists and is valid JSON, else None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def sidecar_path(case_cache: Path, cert_stem: str) -> Path:
    """Return the render-cache sidecar path for a cert stem."""
    return Path(case_cache) / f"{cert_stem}{_PREP_SIDECAR_SUFFIX}"


def load_sidecar(path: Path) -> dict | None:
    """Return the parsed render-cache sidecar if present and valid, else None."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def expected_pngs(png_dir: Path, cert_stem: str, rendered_pages: int) -> list[Path]:
    """Return the per-page PNG paths a render of ``rendered_pages`` should yield."""
    return [
        Path(png_dir) / f"{cert_stem}_p{n:02d}.png"
        for n in range(1, int(rendered_pages) + 1)
    ]


def render_is_cached(
    sidecar: dict | None,
    pdf_sha256: str,
    dpi: int,
    png_dir: Path,
    cert_stem: str,
) -> bool:
    """True when a prior render can be reused (skip re-rendering this PDF).

    Requires the sidecar to exist with a matching pdf_sha256 + dpi AND every
    ``<stem>_pNN.png`` for ``rendered_pages`` to be present on disk. Any mismatch
    or missing PNG forces a re-render.
    """
    if not sidecar:
        return False
    if sidecar.get("pdf_sha256") != pdf_sha256:
        return False
    if sidecar.get("dpi") != dpi:
        return False
    rendered_pages = sidecar.get("rendered_pages")
    if not isinstance(rendered_pages, int) or rendered_pages <= 0:
        return False
    return all(p.exists() for p in expected_pngs(png_dir, cert_stem, rendered_pages))


def prep_case(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
    dpi: int = 200,
    force: bool = False,
) -> dict:
    """Produce the deterministic (non-Vision) body inputs for a case and write a
    skeleton extracted.json per cert that Phase-2 Claude Vision will fill.

    The render cache gate skips re-rendering a PDF whose sidecar
    (<stem>_prep.json) matches the current sha256 + dpi and whose PNGs are all
    present; ``force=True`` re-renders unconditionally.

    Returns a summary dict:
        {
          "case_id": str,
          "certs": [
            {"cert_pdf": str, "png_count": int, "skeleton_path": str,
             "rendered": bool, "sidecar_path": str}
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

        pdf_sha256 = compute_sha256_fresh(cert_pdf)
        scar_path = sidecar_path(case_cache, cert_stem)
        sidecar = load_sidecar(scar_path)

        # Render cache gate: reuse a prior render when the sidecar matches and
        # every page PNG is present (unless --force).
        if not force and render_is_cached(sidecar, pdf_sha256, dpi, png_dir, cert_stem):
            rendered = False
            rendered_pages = int(sidecar["rendered_pages"])
            pngs = expected_pngs(png_dir, cert_stem, rendered_pages)
            notes.append(f"[skip] {cert_stem} unchanged")
        else:
            rendered = True
            pngs = split_pdf(cert_pdf, png_dir, dpi=dpi)
            rendered_pages = len(pngs)
            scar_path.write_text(
                json.dumps(
                    {
                        "pdf_sha256": pdf_sha256,
                        "dpi": dpi,
                        "rendered_pages": rendered_pages,
                        "backfilled": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

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
                "cert_sha256": pdf_sha256,
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
            "rendered": rendered,
            "sidecar_path": str(scar_path).replace("\\", "/"),
        })

    return {
        "case_id": case_id,
        "certs": certs_summary,
        "notes": notes,
    }


__all__ = [
    "prep_case",
    "sidecar_path",
    "load_sidecar",
    "expected_pngs",
    "render_is_cached",
]
