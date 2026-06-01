"""zip_unpacker.py — extract rawdata/*.zip for cases lacking a primary cert PDF.

Hard constraints (C1): stdlib only, NO OCR libraries.
Encoding (C7): Korean filenames inside zip may use cp437 (default) or cp949.
               Flag bit 0x800 means UTF-8; otherwise re-encode as cp437 → decode as cp949.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_CERT_KEYWORDS = ("MTC", "Cert", "cert", "mtc", "성적서")

# Additional folder-level keywords that indicate a cert scan directory.
# Used when PDFs inside a zip carry only timestamp names (e.g. 20260127101901.pdf)
# but their parent folder describes the cert issue category.
_CERT_DIR_KEYWORDS = (
    "불일치",   # mismatch
    "누락",     # missing
    "확인",     # confirmation / review
    "성적서",
    "MTC",
    "Cert",
    "cert",
    "mtc",
)


def _fix_filename(info: zipfile.ZipInfo) -> str:
    """Return a correctly decoded filename for a ZipInfo entry.

    If the UTF-8 flag (bit 11) is set the name is already unicode.
    Otherwise zipfile decoded the raw bytes as cp437 — re-encode to cp437
    bytes then decode as cp949 (Korean).  Fall back to the original if that
    fails (e.g. ASCII-only names).
    """
    if info.flag_bits & 0x800:
        # Already UTF-8; trust zipfile's decoding.
        return info.filename

    # zipfile decoded using cp437 by default.
    raw = info.filename.encode("cp437", errors="surrogateescape")
    try:
        return raw.decode("cp949")
    except (UnicodeDecodeError, LookupError):
        return info.filename


def _is_hidden(name: str) -> bool:
    """Return True for __MACOSX/* entries and hidden ._* files."""
    parts = name.replace("\\", "/").split("/")
    return parts[0] == "__MACOSX" or any(p.startswith("._") for p in parts if p)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def unpack_zip(zip_path: Path, out_dir: Path) -> list[Path]:
    """Extract *zip_path* contents into *out_dir*.

    Handles CP437-encoded filenames and re-decodes as CP949 when needed.
    Skips __MACOSX/* and hidden ._* entries.

    Returns a list of absolute paths of extracted files.
    """
    zip_path = Path(zip_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            corrected_name = _fix_filename(info)

            if _is_hidden(corrected_name):
                continue

            # Determine target path using the corrected name.
            target = out_dir / corrected_name

            if corrected_name.endswith("/"):
                # Directory entry — just create it.
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)

            # Extract raw bytes from zip and write to target.
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())

            extracted.append(target)

    return extracted


def unpack_case_zips(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
) -> dict[str, list[str]]:
    """Scan ``rawdata/<case_id>/*.zip`` and extract each archive.

    Each zip is extracted into ``cache_root/<case_id>/zip/<zip_stem>/``.

    Returns ``{zip_filename: [extracted paths relative to work_dir]}``.
    """
    work_dir = Path(work_dir)
    cache_root = Path(cache_root)

    rawdata_dir = work_dir / "rawdata" / case_id
    if not rawdata_dir.is_dir():
        return {}

    result: dict[str, list[str]] = {}

    for zip_file in sorted(rawdata_dir.glob("*.zip")):
        out_dir = cache_root / case_id / "zip" / zip_file.stem
        extracted = unpack_zip(zip_file, out_dir)
        rel_paths = []
        for p in extracted:
            try:
                rel_paths.append(str(p.relative_to(work_dir)))
            except ValueError:
                rel_paths.append(str(p))
        result[zip_file.name] = rel_paths

    return result


def find_extracted_certs(case_id: str, cache_root: Path) -> list[Path]:
    """Find cert PDFs extracted for *case_id*.

    Searches ``cache_root/<case_id>/zip/`` recursively for ``.pdf`` files
    whose name contains any of: MTC, Cert, cert, mtc, 성적서.

    Returns absolute paths.
    """
    cache_root = Path(cache_root)
    zip_root = cache_root / case_id / "zip"

    if not zip_root.is_dir():
        return []

    found: list[Path] = []
    for pdf in zip_root.rglob("*.pdf"):
        # Match on filename first (e.g. "MTC_xxx.pdf", "성적서.pdf").
        name_match = any(kw in pdf.name for kw in _CERT_KEYWORDS)
        # Also accept PDFs whose immediate parent directory name signals a cert
        # category — common when zips contain timestamp-named scan files grouped
        # into labelled folders (e.g. "1. Heat No. 불일치/20260127101901.pdf").
        dir_match = any(kw in pdf.parent.name for kw in _CERT_DIR_KEYWORDS)
        if name_match or dir_match:
            found.append(pdf.resolve())

    return found
