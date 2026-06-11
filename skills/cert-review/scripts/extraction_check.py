"""extraction_check.py — Phase-2 completeness gate (deterministic, no OCR).

Verifies that Claude Vision extraction (Phase 2) actually covered EVERY rendered
cert page before the compliance review (Phase 4) is allowed to run. The defect
this guards against: a review generated from an ad-hoc subset of pages silently
misses findings that live on later pages (dimension tables, remarks, NDE
attachments). The gate is purely structural — it never judges content.

Per cert PDF (one ``<stem>_extracted.json`` per ``<stem>_pNN.png`` family):
  - the extracted JSON must exist and parse;
  - ``page_extraction`` must contain an entry for every rendered page number;
  - ``channels.body.pages`` must list the same covered pages.

Pages with no reviewable content (photo attachments, blank scans) still need an
entry — use ``header: {}`` plus a remark explaining why the page carries no
fields. Coverage means "the model looked at the page and recorded the result",
not "every page has tabular data".

Constraint C1: no OCR libraries here — this module only counts files and reads
JSON. It reads ONLY the plugin .cache directory.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PAGE_PNG_RE = re.compile(r"^(?P<stem>.+)_p(?P<page>\d+)\.png$")


def _page_pngs_by_stem(png_dir: Path) -> dict[str, set[int]]:
    """Group rendered page PNGs by cert stem -> set of page numbers.

    Auxiliary images (zoom crops etc.) that do not match ``<stem>_pNN.png``
    are ignored; only prep-inputs page renders count toward coverage.
    """
    out: dict[str, set[int]] = {}
    if not png_dir.is_dir():
        return out
    for png in png_dir.glob("*.png"):
        m = _PAGE_PNG_RE.match(png.name)
        if not m:
            continue
        out.setdefault(m.group("stem"), set()).add(int(m.group("page")))
    return out


def check_case(case_id: str, cache_root: Path) -> dict:
    """Check extraction completeness for one case.

    Returns:
        {
          "case_id": str,
          "ok": bool,
          "certs": [
            {"stem": str, "png_pages": int, "extracted_pages": int,
             "missing_pages": [int, ...], "issues": [str, ...], "ok": bool}
          ],
          "issues": [str, ...],   # case-level issues (no PNGs / no JSONs)
        }
    """
    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "png"

    case_issues: list[str] = []
    certs: list[dict] = []

    by_stem = _page_pngs_by_stem(png_dir)
    if not by_stem:
        case_issues.append("no rendered page PNGs (run prep-inputs first)")

    for stem, pages in sorted(by_stem.items()):
        issues: list[str] = []
        extracted_path = case_cache / f"{stem}_extracted.json"

        covered: set[int] = set()
        body_pages: set[int] = set()
        if not extracted_path.exists():
            issues.append(f"extracted.json missing: {extracted_path.name}")
        else:
            try:
                data = json.loads(extracted_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                issues.append(f"extracted.json unreadable: {e}")
                data = {}
            pe = data.get("page_extraction") or []
            for entry in pe:
                if not isinstance(entry, dict):
                    continue
                p = entry.get("page")
                if isinstance(p, int):
                    covered.add(p)
                elif isinstance(p, str) and p.isdigit():
                    covered.add(int(p))
            body = ((data.get("channels") or {}).get("body") or {})
            for p in body.get("pages") or []:
                if isinstance(p, int):
                    body_pages.add(p)
                elif isinstance(p, str) and str(p).isdigit():
                    body_pages.add(int(p))

            if not pe:
                issues.append("page_extraction is EMPTY (Phase-2 Vision OCR not done)")

        missing = sorted(pages - covered)
        if missing and "page_extraction is EMPTY (Phase-2 Vision OCR not done)" not in issues \
                and not any(i.startswith("extracted.json") for i in issues):
            issues.append(f"pages without extraction entry: {missing}")
        if covered and body_pages != covered:
            issues.append(
                f"channels.body.pages ({sorted(body_pages)}) != covered pages ({sorted(covered)})"
            )

        certs.append({
            "stem": stem,
            "png_pages": len(pages),
            "extracted_pages": len(covered),
            "missing_pages": missing,
            "issues": issues,
            "ok": not issues,
        })

    return {
        "case_id": str(case_id),
        "ok": (not case_issues) and bool(certs) and all(c["ok"] for c in certs),
        "certs": certs,
        "issues": case_issues,
    }


def check_cases(case_ids: list[str], cache_root: Path) -> dict:
    """Aggregate completeness check across cases."""
    results = [check_case(c, cache_root) for c in case_ids]
    return {
        "ok": all(r["ok"] for r in results),
        "n_cases": len(results),
        "n_failed": sum(1 for r in results if not r["ok"]),
        "cases": results,
    }


__all__ = ["check_case", "check_cases"]
