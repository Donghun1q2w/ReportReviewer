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


# ---------------------------------------------------------------------------
# Cache freshness status (speed-optimization gate)
# ---------------------------------------------------------------------------
#
# Per cert PDF, decide whether Phase-1/Phase-2 may be skipped on a re-run:
#   missing : no _extracted.json, or page_extraction is empty.
#   stale   : sidecar sha256 != current PDF sha256, OR the PNG set is incomplete.
#   legacy  : extraction is complete (coverage OK) but there is no sidecar — the
#             sidecar is backfilled from the current PDF sha256 and reported.
#   fresh   : extraction complete + sidecar present + sidecar sha256 matches.
#
# Resolving the current PDF sha256 needs the cert PDF, whose work-dir-relative
# path is recorded in the extracted JSON's ``cert_file``. Reading the cert PDF is
# inside the input whitelist (cert cleanup + .cache only).

def _resolve_cert_pdf(data: dict, work_dir: Path | None) -> Path | None:
    """Resolve the cert PDF path from an extracted JSON's ``cert_file`` field."""
    if work_dir is None:
        return None
    cert_file = data.get("cert_file")
    if not isinstance(cert_file, str) or not cert_file:
        return None
    return (Path(work_dir) / cert_file.replace("\\", "/")).resolve()


def cache_status_case(
    case_id: str,
    cache_root: Path,
    work_dir: Path | None = None,
    *,
    backfill: bool = True,
) -> dict:
    """Classify each cert PDF in a case as missing/stale/legacy/fresh.

    Reuses ``check_case`` for the page-coverage verdict (no duplicate logic) and
    adds the sidecar/sha256/PNG-set checks. When ``backfill`` is True a complete
    extraction that lacks a sidecar gets one written (``backfilled: true``,
    ``dpi: null``) and is reported as ``legacy``.
    """
    from scripts.prep_inputs import (  # noqa: PLC0415
        expected_pngs,
        load_sidecar,
        sidecar_path,
    )
    from scripts.source_validator import compute_sha256_fresh  # noqa: PLC0415

    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "png"

    coverage = check_case(case_id, cache_root)
    cov_by_stem = {c["stem"]: c for c in coverage["certs"]}

    certs: list[dict] = []
    for stem, cov in sorted(cov_by_stem.items()):
        extracted_path = case_cache / f"{stem}_extracted.json"
        data: dict = {}
        if extracted_path.exists():
            try:
                data = json.loads(extracted_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}

        extraction_complete = bool(cov["ok"])
        has_extracted = extracted_path.exists() and bool(data.get("page_extraction"))

        scar_path = sidecar_path(case_cache, stem)
        sidecar = load_sidecar(scar_path)

        cur_sha = ""
        cert_pdf = _resolve_cert_pdf(data, work_dir)
        if cert_pdf is not None and cert_pdf.exists():
            cur_sha = compute_sha256_fresh(cert_pdf)

        # PNG completeness vs the sidecar's recorded rendered_pages.
        png_set_ok = True
        if sidecar and isinstance(sidecar.get("rendered_pages"), int):
            png_set_ok = all(
                p.exists()
                for p in expected_pngs(png_dir, stem, sidecar["rendered_pages"])
            )

        sha_matches = bool(sidecar) and bool(cur_sha) and sidecar.get("pdf_sha256") == cur_sha
        backfilled = False

        if not has_extracted:
            status = "missing"
        elif sidecar is None:
            if extraction_complete:
                status = "legacy"
                if backfill:
                    scar_path.write_text(
                        json.dumps(
                            {
                                "pdf_sha256": cur_sha,
                                "dpi": None,
                                "rendered_pages": cov["png_pages"],
                                "backfilled": True,
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                    backfilled = True
            else:
                status = "stale"
        elif (cur_sha and not sha_matches) or not png_set_ok:
            status = "stale"
        elif extraction_complete:
            status = "fresh"
        else:
            status = "stale"

        certs.append({
            "stem": stem,
            "status": status,
            "png_pages": cov["png_pages"],
            "extracted_pages": cov["extracted_pages"],
            "coverage_ok": extraction_complete,
            "sidecar": bool(sidecar) or backfilled,
            "backfilled": backfilled,
            "sha_matches": sha_matches,
        })

    case_issues = list(coverage["issues"])
    return {
        "case_id": str(case_id),
        "certs": certs,
        "issues": case_issues,
        "counts": _status_counts(certs),
    }


def _status_counts(certs: list[dict]) -> dict[str, int]:
    counts = {"fresh": 0, "stale": 0, "legacy": 0, "missing": 0}
    for c in certs:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    return counts


def cache_status_cases(
    case_ids: list[str],
    cache_root: Path,
    work_dir: Path | None = None,
    *,
    backfill: bool = True,
) -> dict:
    """Aggregate cache-status across cases."""
    results = [
        cache_status_case(c, cache_root, work_dir, backfill=backfill)
        for c in case_ids
    ]
    totals = {"fresh": 0, "stale": 0, "legacy": 0, "missing": 0}
    for r in results:
        for k, v in r["counts"].items():
            totals[k] = totals.get(k, 0) + v
    return {
        "n_cases": len(results),
        "totals": totals,
        "cases": results,
    }


__all__ = [
    "check_case",
    "check_cases",
    "cache_status_case",
    "cache_status_cases",
]
