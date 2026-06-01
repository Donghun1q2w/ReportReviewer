"""PDF annotation extractor — reads /Annots dictionaries embedded in PDF.

This is NOT OCR. No text extraction from page content streams.
Only reads annotation metadata using pypdf.

Constraint C1: only pypdf allowed — no pdfplumber/pymupdf/fitz/tesseract.
Constraint C7: pathlib throughout, UTF-8 encoding.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ANNOTATION_SUBTYPES = {
    "FreeText", "Text", "Square", "Circle", "Polygon", "PolyLine",
    "Highlight", "Underline", "Squiggly", "StrikeOut", "Caret",
    "Stamp", "Ink", "Note",
}


def _decode_pdf_string(val: Any) -> str:
    """Safely decode a pypdf string object to Python str."""
    if val is None:
        return ""
    # pypdf may return PdfString, TextStringObject, ByteStringObject, or plain str
    if isinstance(val, bytes):
        for enc in ("utf-16-be", "utf-8", "cp949", "latin-1"):
            try:
                s = val.decode(enc)
                # strip BOM if present
                return s.lstrip("﻿")
            except (UnicodeDecodeError, ValueError):
                continue
        return val.hex()
    # pypdf string objects support str() conversion
    try:
        s = str(val)
        return s.lstrip("﻿")
    except Exception:
        return ""


def _resolve_annot(raw: Any) -> dict[str, Any] | None:
    """Resolve an IndirectObject or dict-like annotation to a plain dict."""
    try:
        obj = raw.get_object() if hasattr(raw, "get_object") else raw
        if not hasattr(obj, "get"):
            return None
        return obj  # type: ignore[return-value]
    except Exception:
        return None


def _parse_rect(rect_val: Any) -> list[float] | None:
    """Parse /Rect into [x1, y1, x2, y2] floats."""
    if rect_val is None:
        return None
    try:
        items = list(rect_val)
        return [float(v) for v in items[:4]]
    except Exception:
        return None


def extract_annotations(pdf_path: Path) -> list[dict]:
    """Return annotations sorted by (page, y, x).

    Each item:
        {
            "page":     int (1-indexed),
            "author":   str | None,
            "subtype":  str,
            "text":     str,
            "rect":     [x1, y1, x2, y2] | None,
            "modified": str | None,
        }

    Subtypes captured: FreeText, Text, Square, Circle, Polygon, PolyLine,
    Highlight, Underline, Squiggly, StrikeOut, Caret, Stamp, Ink, Note.
    Marking-only annotations (no text) are included with text="".
    """
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    results: list[dict] = []

    for page_idx, page in enumerate(reader.pages, start=1):
        try:
            annots = page.annotations  # list[IndirectObject] or None
        except Exception:
            annots = None
        if not annots:
            continue

        for raw in annots:
            try:
                obj = _resolve_annot(raw)
                if obj is None:
                    continue

                subtype_raw = obj.get("/Subtype")
                subtype = _decode_pdf_string(subtype_raw).lstrip("/")
                if not subtype:
                    # Try name object directly
                    try:
                        subtype = str(subtype_raw).lstrip("/")
                    except Exception:
                        subtype = ""

                if subtype not in ANNOTATION_SUBTYPES:
                    continue

                text = _decode_pdf_string(obj.get("/Contents"))
                author_raw = obj.get("/T")
                author: str | None = _decode_pdf_string(author_raw) if author_raw is not None else None
                if author == "":
                    author = None

                modified_raw = obj.get("/M")
                modified: str | None = _decode_pdf_string(modified_raw) if modified_raw is not None else None
                if modified == "":
                    modified = None

                rect = _parse_rect(obj.get("/Rect"))

                results.append({
                    "page": page_idx,
                    "author": author,
                    "subtype": subtype,
                    "text": text,
                    "rect": rect,
                    "modified": modified,
                })
            except Exception:
                continue  # tolerate malformed annotations

    # Sort by (page, y descending from top = y2 desc, x1)
    # PDF coords: y increases upward, so higher y2 = closer to top of page
    def _sort_key(a: dict) -> tuple:
        r = a["rect"] or [0.0, 0.0, 0.0, 0.0]
        return (a["page"], -r[3], r[0])

    results.sort(key=_sort_key)
    return results


def extract_case_annotations(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
) -> dict[str, list[dict]]:
    """For each cert PDF in 'standard inspection Cert cleanup data/<case_id>/',
    extract annotations and write to cache_root/<case_id>/<cert_stem>_annotations.json.

    Returns mapping {cert_stem: annotations}.
    """
    cert_dir = work_dir / "standard inspection Cert cleanup data" / case_id
    if not cert_dir.exists():
        raise FileNotFoundError(f"Cert directory not found: {cert_dir}")

    out_dir = cache_root / case_id
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, list[dict]] = {}

    for pdf_path in sorted(cert_dir.glob("*.pdf")):
        stem = pdf_path.stem
        annotations = extract_annotations(pdf_path)

        cache_file = out_dir / f"{stem}_annotations.json"
        cache_file.write_text(
            json.dumps(annotations, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        mapping[stem] = annotations

    return mapping


__all__ = ["extract_annotations", "extract_case_annotations"]
