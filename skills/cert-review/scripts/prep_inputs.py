"""prep_inputs.py — Phase-1 deterministic (non-Vision) input preparation.

Produces all four input channels for a case WITHOUT any OCR:
  1. body   — per-page PNGs rendered from each cert PDF (pdf_split, pdfium raster)
  2. annotations — live reviewer /Annots read from the rawdata ORIGINAL PDF
                   (the cert-cleanup '_cert.pdf' files have FLATTENED annotations,
                    so we MUST target rawdata originals matched by stem).
                   Additionally, reviewer memos living on the case's OTHER
                   rawdata PDFs (MPS files etc., not matched to any cert) are
                   pooled case-wide and ADDED to every cert's annotation channel,
                   each tagged with a "source_pdf" field.
  3. emails — parsed .msg files (msg_loader), shared across the case's certs
  4. zip_attachments — for zip-only cases, the unpacked archive manifest

For each cert PDF a SKELETON <cert_stem>_extracted.json is written, conforming to
references/extraction-schema.json v2.0. Phase-2 Claude Vision later fills
channels.body.pages and page_extraction. Re-running prep is idempotent: a skeleton
that already carries non-empty page_extraction is preserved (only annotations/emails
channels are refreshed).

Constraint C1: NO Python OCR libs — only existing modules + stdlib + pypdf/pypdfium2.
Constraint C7: pathlib throughout, encoding='utf-8' on all file I/O.
Never reference the literal ground-truth directory string.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.msg_loader import load_case_emails
from scripts.pdf_annotations import extract_annotations
from scripts.pdf_split import split_pdf
from scripts.source_validator import compute_sha256
from scripts.zip_unpacker import find_extracted_certs, unpack_case_zips

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"
RAWDATA_DIRNAME = "rawdata"


def _normalize_stem(stem: str) -> str:
    """Normalise a PDF stem for matching: strip trailing '_cert'/'_comment'
    suffixes, lowercase, and remove spaces."""
    s = stem
    for suffix in ("_cert", "_comment"):
        if s.lower().endswith(suffix):
            s = s[: -len(suffix)]
    return s.lower().replace(" ", "")


def _longest_common_prefix_len(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


def _match_rawdata_original(
    cert_pdf: Path, rawdata_pdfs: list[Path]
) -> Path | None:
    """Match a cert PDF to its rawdata original by normalised stem.

    Strategy: exact normalised-stem match; else the rawdata pdf with the longest
    common normalised-stem prefix; else (if exactly one rawdata pdf) that one;
    else None.
    """
    if not rawdata_pdfs:
        return None

    cert_norm = _normalize_stem(cert_pdf.stem)

    # 1) exact normalised-stem match
    for raw in rawdata_pdfs:
        if _normalize_stem(raw.stem) == cert_norm:
            return raw

    # 2) longest common normalised-stem prefix (require a non-trivial overlap)
    best: Path | None = None
    best_len = 0
    for raw in rawdata_pdfs:
        plen = _longest_common_prefix_len(cert_norm, _normalize_stem(raw.stem))
        if plen > best_len:
            best_len = plen
            best = raw
    if best is not None and best_len > 0:
        return best

    # 3) sole rawdata pdf fallback
    if len(rawdata_pdfs) == 1:
        return rawdata_pdfs[0]

    return None


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
    """Produce all deterministic (non-Vision) inputs for a case and write a
    skeleton extracted.json per cert that Phase-2 Claude Vision will fill.

    Returns a summary dict:
        {
          "case_id": str,
          "certs": [
            {"cert_pdf": str, "png_count": int,
             "annotations_count": int, "skeleton_path": str}
          ],
          "emails_count": int,
          "zip_only": bool,
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
    rawdata_dir = work_dir / RAWDATA_DIRNAME / case_id

    # ── 1. Determine cert PDFs to OCR ────────────────────────────────────────
    cleanup_pdfs = (
        sorted(cert_cleanup_dir.glob("*.pdf")) if cert_cleanup_dir.is_dir() else []
    )

    zip_only = False
    zip_manifest: dict[str, list[str]] = {}

    if cleanup_pdfs:
        cert_pdfs = cleanup_pdfs
    else:
        # Zip-only path: unpack rawdata zips then locate cert PDFs inside.
        raw_zips = (
            sorted(rawdata_dir.glob("*.zip")) if rawdata_dir.is_dir() else []
        )
        if raw_zips:
            zip_only = True
            zip_manifest = unpack_case_zips(case_id, work_dir, cache_root)
            cert_pdfs = sorted(find_extracted_certs(case_id, cache_root))
            if not cert_pdfs:
                notes.append("zip_only: no cert PDFs found after unpacking zips")
        else:
            cert_pdfs = []
            notes.append("no cert PDFs in cleanup dir and no rawdata zips")

    # zip_attachments channel content (shared across certs in this case)
    zip_attachments = [
        {"zip_file": zip_name, "extracted_files": files}
        for zip_name, files in zip_manifest.items()
    ]

    # ── 2./3. Build rawdata-original candidate set for annotation matching ────
    rawdata_pdfs = (
        sorted(rawdata_dir.glob("*.pdf")) if rawdata_dir.is_dir() else []
    )

    # ── 4. Emails (shared across the case's certs) ───────────────────────────
    emails = load_case_emails(case_id, work_dir, cache_root)

    # ── Pre-compute the set of rawdata originals matched to a cert ────────────
    # Auxiliary annotations are pooled from EVERY rawdata pdf that is NOT one of
    # these matched originals (i.e. MPS files and any other rawdata PDFs), so
    # reviewer memos living on MPS PDFs become visible downstream.
    matched_originals: set[Path] = set()
    if not zip_only:
        for cert_pdf in cert_pdfs:
            m = _match_rawdata_original(cert_pdf, rawdata_pdfs)
            if m is not None:
                matched_originals.add(m)

    aux_annotations: list[dict] = []
    if not zip_only:
        seen: set[tuple[str, str]] = set()
        for raw in rawdata_pdfs:
            if raw in matched_originals:
                continue
            for item in extract_annotations(raw):
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                dedup_key = (item["text"], raw.name)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                aux_annotations.append({
                    "page": item.get("page"),
                    "author": item.get("author"),
                    "subtype": item.get("subtype"),
                    "text": item.get("text"),
                    "source_pdf": raw.name,
                })
        if aux_annotations:
            notes.append(
                f"aux_annotations: pooled {len(aux_annotations)} memo(s) "
                f"from non-cert rawdata PDFs"
            )

    # ── Per-cert processing ──────────────────────────────────────────────────
    certs_summary: list[dict] = []

    for cert_pdf in cert_pdfs:
        cert_stem = cert_pdf.stem

        # 2. Render per-page PNGs.
        pngs = split_pdf(cert_pdf, png_dir, dpi=dpi)

        # 3. Annotations.
        if zip_only:
            # Live annotations live in the extracted cert PDF itself.
            annotations = extract_annotations(cert_pdf)
        else:
            matched = _match_rawdata_original(cert_pdf, rawdata_pdfs)
            if matched is None:
                annotations = []
                notes.append(
                    f"{cert_pdf.name}: no rawdata original matched — "
                    f"annotations empty"
                )
            else:
                annotations = extract_annotations(matched)
                if not annotations:
                    notes.append(
                        f"{cert_pdf.name}: matched {matched.name} "
                        f"but it has 0 annotations"
                    )

        # Add the case-level auxiliary (MPS / other rawdata) memos alongside the
        # cert's OWN matched annotations — never replacing them.
        annotations = annotations + aux_annotations

        ann_path = case_cache / f"{cert_stem}_annotations.json"
        ann_path.write_text(
            json.dumps(annotations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 5. Skeleton extracted.json (idempotent: preserve OCR'd content).
        skeleton_path = case_cache / f"{cert_stem}_extracted.json"

        try:
            cert_rel = str(cert_pdf.relative_to(work_dir)).replace("\\", "/")
        except ValueError:
            # zip-extracted certs live under cache_root, not work_dir.
            cert_rel = str(cert_pdf).replace("\\", "/")

        existing = _load_existing_skeleton(skeleton_path)
        existing_pages = (
            existing.get("page_extraction") if isinstance(existing, dict) else None
        )

        if existing and existing_pages:
            # Already OCR'd — preserve page_extraction + channels.body, only
            # refresh the deterministic channels.
            existing.setdefault("channels", {})
            existing["channels"]["annotations"] = {
                "engine": "pypdf",
                "items": annotations,
            }
            existing["channels"]["emails"] = {
                "engine": "extract-msg",
                "items": emails,
            }
            existing["channels"]["zip_attachments"] = zip_attachments
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
                    "annotations": {"engine": "pypdf", "items": annotations},
                    "emails": {"engine": "extract-msg", "items": emails},
                    "zip_attachments": zip_attachments,
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
            "annotations_count": len(annotations),
            "skeleton_path": str(skeleton_path).replace("\\", "/"),
        })

    return {
        "case_id": case_id,
        "certs": certs_summary,
        "emails_count": len(emails),
        "zip_only": zip_only,
        "notes": notes,
    }


__all__ = ["prep_case"]
