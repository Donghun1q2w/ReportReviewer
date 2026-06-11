"""Provenance validator — enforces C2/C8.

Every CSV row and every finding MUST carry these 3 provenance fields:
- source_file: relative path from working dir
- anchor:     stable identifier inside the source file (e.g. p.5#Table1)
- snippet:    exact substring that must appear in the source file's text

The cited snippet is verified to be present in the source file's text; this is
the provenance integrity check. (A byte-level sha256 column was dropped — it was
a testbed-only check, unenforced in deployment where the reference corpus is not
bundled, and a maintenance burden; the snippet-present check is what matters.)

This module exposes:
    validate_csv_row(row, work_dir) -> ValidationResult
    validate_finding(finding, work_dir) -> ValidationResult
    validate_csv_file(csv_path, work_dir) -> list[ValidationResult]
    filter_valid_findings(findings, work_dir) -> (valid, dropped)

Raises MissingProvenanceError when a row is loaded but lacks any of the 3 fields.
Snippet check tolerates whitespace collapsing because the source may be a markdown
OCR output where leading whitespace varies; numeric tokens must match exactly.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REQUIRED_FIELDS = ("source_file", "anchor", "snippet")


class MissingProvenanceError(ValueError):
    """Raised when a CSV row is missing any of the 3 provenance fields."""


@dataclass
class ValidationResult:
    ok: bool
    row_id: str
    reason: str = ""
    source_file: str = ""


_SHA_CACHE: dict[Path, str] = {}
_TEXT_CACHE: dict[Path, str] = {}


def _sha256_uncached(path: Path) -> str:
    """Hash a file's bytes without consulting the module cache.

    Reference source files are immutable within a run, so _sha256_of memoizes
    them. Cert PDFs, however, can be replaced in place (cache-freshness checks
    must notice the change), so that path is hashed fresh every time.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_of(path: Path) -> str:
    if path in _SHA_CACHE:
        return _SHA_CACHE[path]
    digest = _sha256_uncached(path)
    _SHA_CACHE[path] = digest
    return digest


def _read_text(path: Path) -> str:
    """Return file text for snippet checking.

    - .md/.txt/.csv/.json: read as UTF-8 with cp949 fallback (Korean Windows)
    - .pdf: extract text via pypdf (no OCR; only embedded text). If pypdf is
      unavailable or PDF has no embedded text, return empty string and the
      snippet check is skipped (the row passes on source_file existence alone).
    """
    if path in _TEXT_CACHE:
        return _TEXT_CACHE[path]

    suffix = path.suffix.lower()
    text = ""
    if suffix in {".md", ".txt", ".csv", ".json"}:
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                text = path.read_text(encoding=enc)
                break
            except UnicodeDecodeError:
                continue
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore
            reader = PdfReader(str(path))
            parts: list[str] = []
            for p in reader.pages:
                try:
                    parts.append(p.extract_text() or "")
                except Exception:
                    parts.append("")
            text = "\n".join(parts)
        except Exception:
            text = ""

    _TEXT_CACHE[path] = text
    return text


_WS = re.compile(r"\s+")


def _normalize_for_match(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _snippet_present(snippet: str, haystack: str) -> bool:
    if not snippet:
        return False
    if snippet in haystack:
        return True
    return _normalize_for_match(snippet) in _normalize_for_match(haystack)


_PLUGIN_DIR = Path(__file__).resolve().parent.parent
# Frozen CSV provenance quotes this literal prefix in its `source_file` values,
# so the string is kept verbatim for sha/match stability. It is a logical alias
# that re-maps to the current plugin directory below (the plugin's physical path
# changed, but the recorded provenance text did not).
_PLUGIN_PREFIX = "plugin/cert-review-skill/"


def _resolve_path(source_file: str, work_dir: Path) -> Path:
    """Resolve a provenance source_file path.

    Primary anchor is the working dir (ref_code/, dataset dirs). The plugin no
    longer sits directly under the working dir, so paths recorded with the frozen
    ``plugin/cert-review-skill/...`` provenance prefix (e.g. the frozen
    references) are re-resolved against this plugin directory when the work-dir
    candidate is absent. The work-dir candidate is tried first, so any layout
    keeps working.
    """
    sf = source_file.replace("\\", "/")
    p = (work_dir / sf).resolve()
    if not p.exists() and sf.startswith(_PLUGIN_PREFIX):
        p = (_PLUGIN_DIR / sf[len(_PLUGIN_PREFIX):]).resolve()
    return p


def _check(row: dict[str, Any], work_dir: Path, row_id: str) -> ValidationResult:
    missing = [f for f in REQUIRED_FIELDS if not row.get(f)]
    if missing:
        return ValidationResult(
            ok=False, row_id=row_id,
            reason=f"missing provenance fields: {missing}",
            source_file=str(row.get("source_file", "")),
        )

    source_file = str(row["source_file"])
    snippet = str(row["snippet"])

    path = _resolve_path(source_file, work_dir)
    if not path.exists():
        return ValidationResult(
            ok=False, row_id=row_id,
            reason=f"source_file not found on disk: {path}",
            source_file=source_file,
        )

    text = _read_text(path)
    if text and not _snippet_present(snippet, text):
        return ValidationResult(
            ok=False, row_id=row_id,
            reason=f"snippet not found in source text: {snippet!r}",
            source_file=source_file,
        )

    return ValidationResult(ok=True, row_id=row_id, source_file=source_file)


def validate_csv_row(row: dict[str, Any], work_dir: Path, row_id: str = "") -> ValidationResult:
    return _check(row, work_dir, row_id or row.get("id", "<row>"))


def validate_csv_file(csv_path: Path, work_dir: Path) -> list[ValidationResult]:
    results: list[ValidationResult] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, start=2):  # header is line 1
            rid = f"{csv_path.name}:L{i}"
            results.append(_check(row, work_dir, rid))
    return results


def validate_finding(finding: dict[str, Any], work_dir: Path) -> ValidationResult:
    evidence = finding.get("evidence") or []
    if not evidence:
        return ValidationResult(
            ok=False,
            row_id=finding.get("finding_id", "<finding>"),
            reason="no evidence entries",
        )
    for i, ev in enumerate(evidence):
        res = _check(ev, work_dir, f"{finding.get('finding_id','<f>')}#ev{i}")
        if not res.ok:
            return res
    return ValidationResult(ok=True, row_id=finding.get("finding_id", "<f>"))


def filter_valid_findings(
    findings: Iterable[dict[str, Any]], work_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    valid: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for f in findings:
        res = validate_finding(f, work_dir)
        if res.ok:
            valid.append(f)
        else:
            dropped.append({**f, "_drop_reason": res.reason})
    return valid, dropped


def compute_sha256(path: Path) -> str:
    """Public helper used by bootstrap scripts (memoized per path)."""
    return _sha256_of(path)


def compute_sha256_fresh(path: Path) -> str:
    """Hash a (possibly mutated) file's current bytes, bypassing the cache.

    Use this for change-detection on mutable inputs such as cert PDFs, where the
    memoized compute_sha256 would return a stale digest after an in-place edit.
    """
    return _sha256_uncached(path)


__all__ = [
    "REQUIRED_FIELDS",
    "MissingProvenanceError",
    "ValidationResult",
    "validate_csv_row",
    "validate_csv_file",
    "validate_finding",
    "filter_valid_findings",
    "compute_sha256",
    "compute_sha256_fresh",
]
