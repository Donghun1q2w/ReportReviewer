"""PowerShell-friendly CLI entry point for cert-review-skill.

Usage (Windows PowerShell):
    python -m scripts.cli build-manifest
    python -m scripts.cli prep-inputs --case 4
    python -m scripts.cli validate-refs
    python -m scripts.cli evaluate --case 4
    python -m scripts.cli evaluate --all

Run from the plugin/skill directory (this file's parent) with
PYTHONIOENCODING=utf-8.

Exit codes:
    0 = success / PASS
    1 = failure / FAIL
    2 = usage error
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent


_DATASET_MARKER = "standard inspection Cert cleanup data"


def _resolve_work_dir() -> Path:
    """Locate the working directory that holds the input dataset.

    Priority (so the deployed skill runs from an arbitrary user folder while the
    in-repo regression keeps working) — no hard-coded testbed path:
      1. env `CERT_REVIEW_WORKDIR` — explicit override.
      2. walk upward from CWD (and from the plugin dir) looking for a directory
         that contains the cert-cleanup dataset folder. This makes the skill
         self-contained regardless of how deeply the plugin is nested.
      3. current working directory (deployment default).
    """
    env = os.environ.get("CERT_REVIEW_WORKDIR")
    if env:
        return Path(env).resolve()

    for start in (Path.cwd(), PLUGIN_DIR):
        for cand in (start, *start.parents):
            if (cand / _DATASET_MARKER).is_dir():
                return cand
    return Path.cwd()


WORK_DIR = _resolve_work_dir()
# Input dir names default to the standard-inspection dataset layout but are
# overridable via env so a deployed user can point at their own folder names.
CERT_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_CERT_DIR", "standard inspection Cert cleanup data")
MPS_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_MPS_DIR", "standard inspection MPS cleanup data")
REF_CODE_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_REF_CODE_DIR", "ref_code")
CACHE_DIR = PLUGIN_DIR / ".cache"
MANIFEST_PATH = PLUGIN_DIR / "manifest.json"


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def _manifest_case_ids() -> list[str]:
    """Case ids that have cert PDFs, read from manifest.json (for --all handlers).

    Raises FileNotFoundError if the manifest is absent so callers can report it.
    """
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError("manifest.json not found; run build-manifest first")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    return [c["case_id"] for c in manifest.get("cases", []) if c.get("has_cert_pdf")]


def cmd_build_manifest(args: argparse.Namespace) -> int:
    """Scan working dir and emit manifest.json indexing all cases.

    Pulls from two primary sources:
    - standard inspection Cert cleanup data/<case>/*.pdf
    - standard inspection MPS cleanup data/<case>/*.pdf

    Neither the ground-truth directory nor rawdata is scanned here; the
    evaluation harness is the only module permitted to read GT, and rawdata is
    forbidden during operation.
    """
    if not CERT_DIR.exists():
        print(f"[ERROR] Cert dir not found: {CERT_DIR}", file=sys.stderr)
        return 1

    cases: list[dict] = []
    case_ids = sorted(
        [p.name for p in CERT_DIR.iterdir() if p.is_dir()],
        key=_case_sort_key,
    )

    for case_id in case_ids:
        cert_case = CERT_DIR / case_id
        mps_case = MPS_DIR / case_id

        certs = sorted(p.name for p in cert_case.glob("*.pdf") if p.is_file())
        mps_files = (
            sorted(p.name for p in mps_case.glob("*.pdf") if p.is_file())
            if mps_case.exists() else []
        )

        cases.append({
            "case_id": case_id,
            "cert_dir": str(cert_case.relative_to(WORK_DIR)).replace("\\", "/"),
            "mps_dir": (
                str(mps_case.relative_to(WORK_DIR)).replace("\\", "/")
                if mps_case.exists() else None
            ),
            "cert_pdfs": certs,
            "mps_pdfs": mps_files,
            "has_cert_pdf": bool(certs),
            "has_mps": bool(mps_files),
        })

    manifest = {
        "schema_version": "2.0",
        "generated_at": _iso_now(),
        "work_dir": str(WORK_DIR).replace("\\", "/"),
        "case_count": len(cases),
        "cases": cases,
    }

    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] manifest written: {MANIFEST_PATH}")
    print(f"     case_count = {len(cases)}")
    print(f"     with_cert  = {sum(1 for c in cases if c['has_cert_pdf'])}")
    print(f"     with_mps   = {sum(1 for c in cases if c['has_mps'])}")
    return 0


def cmd_prep_inputs(args: argparse.Namespace) -> int:
    """Phase 1: prepare the body input channel (per-page PNGs).

    Renders the cert-cleanup PDFs to per-page PNGs and writes a skeleton
    extracted.json per cert for Phase-2 Vision to fill. Operation reads ONLY the
    cert-cleanup folder; rawdata originals are never touched.
    """
    from scripts.prep_inputs import prep_case  # noqa: PLC0415

    summary = prep_case(
        case_id=args.case,
        work_dir=WORK_DIR,
        cache_root=CACHE_DIR,
        dpi=args.dpi,
        force=args.force,
    )

    total_pngs = sum(c["png_count"] for c in summary["certs"])
    n_rendered = sum(1 for c in summary["certs"] if c.get("rendered"))
    n_skipped = len(summary["certs"]) - n_rendered
    print(
        f"[OK] prep-inputs --case {args.case}: "
        f"{len(summary['certs'])} cert(s), {total_pngs} PNG(s) "
        f"({n_rendered} rendered, {n_skipped} cached)"
    )
    for c in summary["certs"]:
        tag = "render" if c.get("rendered") else "cached"
        print(f"     [{tag}] {c['cert_pdf']} -> {c['png_count']} png")
        print(f"        skeleton: {c['skeleton_path']}")
    for note in summary["notes"]:
        print(f"     note: {note}")
    return 0


def cmd_validate_refs(args: argparse.Namespace) -> int:
    """Phase 3: validate all CSV rows carry 3 provenance fields."""
    import csv as _csv
    from scripts.source_validator import validate_csv_row  # noqa: PLC0415

    data_dir = PLUGIN_DIR / "data"
    if not data_dir.exists():
        print("[INFO] no CSV files in data/, nothing to validate")
        return 0

    csv_files = [
        p for p in data_dir.iterdir()
        if p.is_file() and p.suffix.lower() == ".csv"
    ]
    if not csv_files:
        print("[INFO] no CSV files in data/, nothing to validate")
        return 0

    csv_files = sorted(csv_files)
    total_rows = 0
    total_failures = 0

    for csv_path in csv_files:
        file_rows = 0
        file_valid = 0
        file_failures: list[str] = []

        with open(csv_path, "r", encoding="utf-8", newline="") as fh:
            reader = _csv.DictReader(fh)
            for i, row in enumerate(reader, start=2):
                row_id = f"{csv_path.name}:L{i}"
                result = validate_csv_row(row, WORK_DIR, row_id)
                file_rows += 1
                if result.ok:
                    file_valid += 1
                else:
                    if len(file_failures) < 3:
                        file_failures.append(f"  L{i}: {result.reason}")

        file_failed = file_rows - file_valid
        status = "OK" if file_failed == 0 else "FAIL"
        print(
            f"[{status}] {csv_path.name}: "
            f"{file_rows} rows, {file_valid} valid, {file_failed} failed"
        )
        for reason in file_failures:
            print(reason)

        total_rows += file_rows
        total_failures += file_failed

    n = len(csv_files)
    if total_failures == 0:
        print(f"[OK] {n} CSVs validated, {total_rows} total rows, {total_failures} failures")
        return 0
    else:
        print(f"[FAIL] {n} CSVs validated, {total_rows} total rows, {total_failures} failures")
        return 1


def cmd_check_extraction(args: argparse.Namespace) -> int:
    """Phase 2.5: extraction completeness gate.

    Verifies every rendered cert page has a page_extraction entry before the
    compliance review (Phase 4) runs. Exit 0 only when ALL checked certs are
    fully covered — the review must not proceed on a partial extraction.
    """
    from scripts.extraction_check import check_cases  # noqa: PLC0415

    if args.all:
        if not CERT_DIR.exists():
            print(f"[ERROR] Cert dir not found: {CERT_DIR}", file=sys.stderr)
            return 1
        case_ids = sorted(
            [p.name for p in CERT_DIR.iterdir() if p.is_dir()],
            key=_case_sort_key,
        )
    else:
        case_ids = [args.case]

    agg = check_cases(case_ids, CACHE_DIR)
    for case in agg["cases"]:
        status = "OK" if case["ok"] else "FAIL"
        line = f"[{status}] case {case['case_id']}:"
        details = []
        for c in case["certs"]:
            details.append(
                f"{c['stem'][:40]}… {c['extracted_pages']}/{c['png_pages']}p"
                if len(c["stem"]) > 40 else
                f"{c['stem']} {c['extracted_pages']}/{c['png_pages']}p"
            )
        print(line, "; ".join(details) if details else "(no certs)")
        for issue in case["issues"]:
            print(f"     issue: {issue}")
        for c in case["certs"]:
            for issue in c["issues"]:
                print(f"     {c['stem']}: {issue}")

    verdict = "OK" if agg["ok"] else "FAIL"
    print(f"[{verdict}] check-extraction: {agg['n_cases'] - agg['n_failed']}/{agg['n_cases']} case(s) complete")
    return 0 if agg["ok"] else 1


def cmd_cache_status(args: argparse.Namespace) -> int:
    """Report per-cert cache freshness (missing/stale/legacy/fresh).

    Reuses extraction_check's coverage logic and adds the sidecar/sha256/PNG
    checks. A complete extraction without a sidecar is backfilled (legacy). The
    machine-readable verdict is written to .cache/cache_status.json. Exit 0
    unless an I/O error prevents reporting.
    """
    from scripts.extraction_check import cache_status_cases  # noqa: PLC0415

    if args.all:
        if not CERT_DIR.exists():
            print(f"[ERROR] Cert dir not found: {CERT_DIR}", file=sys.stderr)
            return 1
        case_ids = sorted(
            [p.name for p in CERT_DIR.iterdir() if p.is_dir()],
            key=_case_sort_key,
        )
    else:
        case_ids = [args.case]

    try:
        agg = cache_status_cases(case_ids, CACHE_DIR, WORK_DIR)
    except OSError as e:
        print(f"[ERROR] cache-status I/O failure: {e}", file=sys.stderr)
        return 1

    for case in agg["cases"]:
        for c in case["certs"]:
            stem = c["stem"]
            label = f"{stem[:46]}…" if len(stem) > 46 else stem
            print(
                f"[{c['status']:7}] case {case['case_id']:>7}  "
                f"{c['extracted_pages']}/{c['png_pages']}p  {label}"
            )
        for issue in case["issues"]:
            print(f"     case {case['case_id']} issue: {issue}")

    t = agg["totals"]
    print(
        f"[OK] cache-status: {agg['n_cases']} case(s) — "
        f"fresh={t['fresh']} legacy={t['legacy']} stale={t['stale']} missing={t['missing']}"
    )

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        status_path = CACHE_DIR / "cache_status.json"
        status_path.write_text(
            json.dumps(agg, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"     report: {status_path}")
    except OSError as e:
        print(f"[ERROR] could not write cache_status.json: {e}", file=sys.stderr)
        return 1

    return 0


def cmd_crop(args: argparse.Namespace) -> int:
    """High-DPI crop of a fractional bbox region of one cert page."""
    from scripts.crop import crop_region  # noqa: PLC0415

    try:
        out_path = crop_region(
            case_id=args.case,
            stem=args.stem,
            page=args.page,
            bbox=args.bbox,
            work_dir=WORK_DIR,
            cache_root=CACHE_DIR,
            dpi=args.dpi,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] crop: {e}", file=sys.stderr)
        return 1

    print(f"[OK] crop --case {args.case} --stem {args.stem} --page {args.page}")
    print(str(out_path))
    return 0


def cmd_annotate(args: argparse.Namespace) -> int:
    """Burn 주의/N/A/FAIL review verdicts onto cert PDFs (PASS excluded).

    Consumes ``.cache/<case>/<case>_annotations.json`` (produced by the
    annotation-locator agent) and writes ``<stem>_annotated.pdf`` under
    ``output/reports/<case>/``. Backward-compatible: a missing annotations file
    is a per-case SKIP under --all, an error for a single --case.
    """
    from scripts.annotate_pdf import annotate_case  # noqa: PLC0415

    if args.all and args.out:
        print("[ERROR] --out is only valid with a single --case", file=sys.stderr)
        return 2

    if args.all:
        try:
            case_ids = _manifest_case_ids()
        except FileNotFoundError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 1
    else:
        case_ids = [args.case]

    any_done = False
    for cid in case_ids:
        try:
            summary = annotate_case(
                case_id=cid,
                work_dir=WORK_DIR,
                cache_root=CACHE_DIR,
                cert_dir=CERT_DIR,
                out_dir=Path(args.out) if args.out else None,
                dpi=args.dpi,
            )
        except FileNotFoundError as e:
            if args.all:
                print(f"[SKIP] annotate --case {cid}: {e}", file=sys.stderr)
                continue
            print(f"[ERROR] annotate --case {cid}: {e}", file=sys.stderr)
            return 1
        except (ValueError, OSError) as e:
            print(f"[ERROR] annotate --case {cid}: {e}", file=sys.stderr)
            if not args.all:
                return 1
            continue
        any_done = True
        print(
            f"[OK] annotate --case {cid}: {summary['n_pdfs']} cert PDF(s), "
            f"{summary['boxes_drawn']} annotation(s), {summary['rows_skipped']} skipped"
        )
        for d in summary["outputs"]:
            print(f"     {d['stem']}: {d['boxes']} box(es)/{d['pages']}p -> {d['out_path']}")
        if summary["skip_counts"]:
            print(f"     skip reasons: {summary['skip_counts']}")
        for note in summary["notes"]:
            print(f"     note: {note}")
    if not any_done:
        print("[INFO] annotate: no case had a <case>_annotations.json", file=sys.stderr)
        return 0 if args.all else 1
    return 0


def cmd_tile_inputs(args: argparse.Namespace) -> int:
    """Split rendered page PNGs into overlapping tiles for legible Vision reads."""
    from scripts.tile_inputs import tile_case  # noqa: PLC0415

    if args.all:
        try:
            case_ids = _manifest_case_ids()
        except FileNotFoundError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            return 1
    else:
        case_ids = [args.case]

    any_done = False
    for cid in case_ids:
        try:
            summary = tile_case(case_id=cid, cache_root=CACHE_DIR)
        except (FileNotFoundError, ValueError) as e:
            if args.all:
                continue
            print(f"[ERROR] tile-inputs: {e}", file=sys.stderr)
            return 1
        any_done = True
        total = sum(c["tile_count"] for c in summary["certs"])
        print(f"[OK] tile-inputs --case {cid}: grid {summary['grid']}, {total} tile(s)")
        for c in summary["certs"]:
            print(f"     {c['stem']}: {c['page_count']}p -> {c['tile_count']} tiles")
    if not any_done:
        print("[INFO] tile-inputs: no rendered PNGs found (run prep-inputs first)")
        return 0 if args.all else 1
    return 0


def cmd_orient_sheets(args: argparse.Namespace) -> int:
    """Phase 1.5: compose labelled contact sheets for orientation detection."""
    from scripts.orient_sheets import build_orient_sheets  # noqa: PLC0415

    try:
        summary = build_orient_sheets(case_id=args.case, cache_root=CACHE_DIR)
    except FileNotFoundError as e:
        print(f"[ERROR] orient-sheets: {e}", file=sys.stderr)
        return 1

    print(f"[OK] orient-sheets --case {args.case}: {summary['n_sheets']} sheet(s)")
    for stem, n in summary["stems"].items():
        print(f"     {stem}: {n} page(s)")
    print(f"     index: {summary['index_path']}")
    return 0


def cmd_align_inputs(args: argparse.Namespace) -> int:
    """Phase 1.5: apply detected page rotations to rendered cert PNGs.

    Gate contract: exit 0 only when every rendered stem has an orientation
    record AND every flagged page was rotated — the orchestrator must not
    proceed to tile-inputs/OCR otherwise.
    """
    from scripts.align_inputs import align_case  # noqa: PLC0415

    try:
        summary = align_case(case_id=args.case, cache_root=CACHE_DIR)
    except FileNotFoundError as e:
        print(f"[ERROR] align-inputs: {e}", file=sys.stderr)
        return 1

    verdict = "OK" if summary["ok"] else "FAIL"
    total_rotated = sum(s["rotated"] for s in summary["stems"])
    print(f"[{verdict}] align-inputs --case {args.case}: {total_rotated} page(s) rotated")
    for s in summary["stems"]:
        print(
            f"     {s['stem']}: detected {s['pages_detected']}p, "
            f"rotated {s['rotated']}, already-applied {s['skipped_already_applied']}"
        )
        if s["failed_pages"]:
            print(f"        FAILED pages: {s['failed_pages']}")
        for issue in s["issues"]:
            print(f"        issue: {issue}")
    if summary["uncovered_stems"]:
        print(
            f"     uncovered stems (no orientation record — re-delegate page-aligner): "
            f"{summary['uncovered_stems']}"
        )
    return 0 if summary["ok"] else 1


def cmd_classify_sheets(args: argparse.Namespace) -> int:
    """Phase 1.6: compose UPRIGHT contact sheets for document-type classification.

    Must run AFTER align-inputs — the orient/ sheets are pre-alignment pixels and
    cannot be reused (letterhead/title strings are unreadable when rotated). This
    re-composes from the now-upright png/ into a separate classify/ directory.
    """
    from scripts.orient_sheets import build_orient_sheets  # noqa: PLC0415
    from scripts.doctype import CLASSIFY_SHEETS_DIRNAME  # noqa: PLC0415

    try:
        summary = build_orient_sheets(
            case_id=args.case,
            cache_root=CACHE_DIR,
            sheets_dirname=CLASSIFY_SHEETS_DIRNAME,
        )
    except FileNotFoundError as e:
        print(f"[ERROR] classify-sheets: {e}", file=sys.stderr)
        return 1

    print(f"[OK] classify-sheets --case {args.case}: {summary['n_sheets']} sheet(s)")
    for stem, n in summary["stems"].items():
        print(f"     {stem}: {n} page(s)")
    print(f"     index: {summary['index_path']}")
    print("     -> delegate doc-classifier, then run check-doctype")
    return 0


def cmd_check_doctype(args: argparse.Namespace) -> int:
    """Phase 1.6 gate: every rendered stem must have a valid doctype sidecar.

    Gate contract (mirrors align-inputs): exit 0 only when every rendered stem
    has a <stem>_doctype.json that fully and validly labels its pages and keeps
    at least one page in the review — the orchestrator must not delegate the OCR
    extractor otherwise. A high exclusion ratio is a WARNING (exit 0), not a
    failure.
    """
    from scripts.doctype import check_doctype_case  # noqa: PLC0415

    try:
        summary = check_doctype_case(case_id=args.case, cache_root=CACHE_DIR)
    except FileNotFoundError as e:
        print(f"[ERROR] check-doctype: {e}", file=sys.stderr)
        return 1

    verdict = "OK" if summary["ok"] else "FAIL"
    print(f"[{verdict}] check-doctype --case {args.case}:")
    for s in summary["stems"]:
        dist = ", ".join(f"{k}:{v}" for k, v in sorted(s["by_type"].items())) or "—"
        print(
            f"     {s['stem']}: {s['pages_total']}p "
            f"(included {s['included']}, excluded {s['excluded']}) "
            f"[{dist}]"
        )
        if s["uncertain_pages"]:
            print(f"        uncertain pages: {s['uncertain_pages']}")
        for w in s["warnings"]:
            print(f"        [WARN] {w}")
        for issue in s["issues"]:
            print(f"        issue: {issue}")
    if summary["uncovered_stems"]:
        print(
            f"     uncovered stems (no doctype record — re-delegate doc-classifier): "
            f"{summary['uncovered_stems']}"
        )
    return 0 if summary["ok"] else 1


def cmd_prep_mps(args: argparse.Namespace) -> int:
    """Render + tile the case's MPS PDFs for the shared mps-extractor digest."""
    from scripts.prep_mps import prep_mps_case  # noqa: PLC0415

    try:
        summary = prep_mps_case(
            case_id=args.case, work_dir=WORK_DIR, cache_root=CACHE_DIR, dpi=args.dpi
        )
    except FileNotFoundError as e:
        print(f"[ERROR] prep-mps: {e}", file=sys.stderr)
        return 1

    total_pages = sum(d["page_count"] for d in summary["docs"])
    total_tiles = sum(d["tile_count"] for d in summary["docs"])
    print(
        f"[OK] prep-mps --case {args.case}: {len(summary['docs'])} MPS doc(s), "
        f"{total_pages}p -> {total_tiles} tiles (grid {summary['grid']})"
    )
    for d in summary["docs"]:
        print(f"     {d['file']}: {d['page_count']}p -> {d['tile_count']} tiles")
    print(f"     tiles: {summary['mps_tiles_dir']}")
    return 0


def cmd_limits(args: argparse.Namespace) -> int:
    """Emit the per-case reference-limit pack (relevant CSV rows only)."""
    from scripts.refpack import build_limits_pack  # noqa: PLC0415

    try:
        pack = build_limits_pack(
            case_id=args.case,
            work_dir=WORK_DIR,
            cache_root=CACHE_DIR,
            data_dir=PLUGIN_DIR / "data",
        )
    except FileNotFoundError as e:
        print(f"[ERROR] limits: {e}", file=sys.stderr)
        return 1

    print(f"[OK] limits --case {args.case}:")
    for name in sorted(pack["limits"]):
        print(f"     {name}: {len(pack['limits'][name])} row(s)")
    if pack["unrouted"]:
        print(f"     unrouted grades: {pack['unrouted']}")
    print(f"     report: {pack['output_path']}")
    return 0


def cmd_attachments(args: argparse.Namespace) -> int:
    """Emit the per-case 기준 20 attachment index (enclosed-document presence)."""
    from scripts.attachments import build_attachments_pack  # noqa: PLC0415

    try:
        pack = build_attachments_pack(case_id=args.case, cache_root=CACHE_DIR)
    except FileNotFoundError as e:
        print(f"[ERROR] attachments: {e}", file=sys.stderr)
        return 1

    atts = pack["attachments"]
    print(
        f"[OK] attachments --case {args.case}: {len(atts)} enclosed run(s), "
        f"sidecar_present={str(pack['sidecar_present']).lower()}"
    )
    cov = pack["heat_coverage"]
    if cov:
        parts = [f"{dt} {len(heats)} heat" for dt, heats in sorted(cov.items())]
        print(f"     coverage: {', '.join(parts)}")
    unmatched_total = sum(len(a.get("unmatched_heat_nos") or []) for a in atts)
    if unmatched_total:
        print(f"     unmatched related heats: {unmatched_total}")
    print(f"     report: {pack['output_path']}")
    return 0


def cmd_merge_parts(args: argparse.Namespace) -> int:
    """Merge chunked Vision OCR fragments into <stem>_extracted.json."""
    from scripts.merge_parts import merge_case  # noqa: PLC0415

    try:
        summary = merge_case(
            case_id=args.case,
            cache_root=CACHE_DIR,
            stem=args.stem,
            extracted_at=_iso_now(),
        )
    except (FileNotFoundError, OSError) as e:
        print(f"[ERROR] merge-parts: {e}", file=sys.stderr)
        return 1

    print(f"[OK] merge-parts --case {args.case}: {len(summary['stems'])} stem(s)")
    for r in summary["stems"]:
        pages = r["pages"]
        span = f"{pages[0]}-{pages[-1]}" if pages else "(none)"
        print(f"     {r['stem']}: {r['fragments']} fragment(s) -> {len(pages)} page(s) [{span}]")
        print(f"        written: {r['written']}")
    for issue in summary["issues"]:
        print(f"     issue: {issue}")
    return 0


def cmd_merge_reviews(args: argparse.Namespace) -> int:
    """Merge per-domain partial reviews into <case>_review.json."""
    from scripts.merge_reviews import merge_all, merge_case  # noqa: PLC0415

    def _print_case(r: dict) -> None:
        print(
            f"[OK] merge-reviews --case {r['case_id']}: "
            f"{len(r['sources'])} partial(s) -> "
            f"{r['n_materials']} material(s), {r['n_findings']} finding(s)"
        )
        print(f"     sources: {', '.join(r['sources'])}")
        if r["missing_domains"]:
            print(f"     missing domains: {', '.join(r['missing_domains'])}")
        if r.get("n_excluded_docs"):
            print(f"     excluded docs: {r['n_excluded_docs']}")
        print(f"     written: {r['written']}")
        if r["backup"]:
            print(f"     backup:  {r['backup']}")
        for issue in r["issues"]:
            print(f"     issue: {issue}")

    if args.all:
        try:
            summary = merge_all(CACHE_DIR, MANIFEST_PATH)
        except (FileNotFoundError, OSError, ValueError) as e:
            print(f"[FAIL] merge-reviews: {e}", file=sys.stderr)
            return 1
        for r in summary["cases"]:
            _print_case(r)
        n = len(summary["cases"])
        if n == 0:
            print("[FAIL] merge-reviews --all: no case had partial reviews", file=sys.stderr)
            return 1
        print(
            f"[OK] merge-reviews --all: {n} case(s) merged, "
            f"{len(summary['skipped'])} skipped (no partials)"
        )
        return 0

    try:
        r = merge_case(args.case, CACHE_DIR)
    except (FileNotFoundError, OSError, ValueError) as e:
        print(f"[FAIL] merge-reviews --case {args.case}: {e}", file=sys.stderr)
        return 1
    _print_case(r)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Phase 7: GT match (per-case comments.md) + rubric diagnostic.

    eval_harness is the ONLY module permitted to read the GT directory; the CLI
    asks it for the case list (folder scan) and lets it read each case's
    comments.md internally so the input guard is satisfied.
    """
    from scripts.eval_harness import evaluate, list_cases  # noqa: PLC0415

    if args.all:
        case_ids = list_cases(WORK_DIR)
        if not case_ids:
            print(
                f"[ERROR] no GT cases found under: {WORK_DIR}", file=sys.stderr
            )
            return 1
    else:
        case_ids = [args.case]

    # The CLI layer may stamp with wall-clock time; eval_harness internals must not.
    stamp = _stamp_now()

    agg = evaluate(
        case_ids=case_ids,
        work_dir=WORK_DIR,
        cache_root=CACHE_DIR,
        stamp=stamp,
    )

    print(f"[{agg['verdict']}] evaluate ({agg['n_cases']} case(s)):")
    print(
        f"     recall    = {agg['total_hits']}/{agg['total_gt']} "
        f"= {agg['recall'] * 100:.1f}%  (target 100%)"
    )
    print(
        f"     case_pass = {agg['case_pass_count']}/{agg['n_cases']} "
        f"(target {agg['n_cases']}/{agg['n_cases']})"
    )
    print(
        f"     precision = {agg['total_matched_cert']}/{agg['total_cert']} "
        f"= {agg['precision'] * 100:.1f}%  (참고)"
    )
    print(f"     verdict   = {agg['verdict']}")
    print(f"     report    : {agg['report_md']}")
    return 0 if agg["pass"] else 1


def _case_sort_key(name: str):
    """Sort '4', '7', '10', ..., '30 & 31', '47 & 48' deterministically."""
    head = name.split("&")[0].strip()
    try:
        return (int(head), name)
    except ValueError:
        return (10**9, name)


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _stamp_now() -> str:
    """Filename-safe timestamp stamp (CLI layer is allowed to read wall-clock)."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdout()
    parser = argparse.ArgumentParser(prog="cert-review", description="MTC review pipeline CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("build-manifest", help="Scan working dir and emit manifest.json").set_defaults(func=cmd_build_manifest)

    p = sub.add_parser("prep-inputs", help="Prepare body (PNG) inputs for a case")
    p.add_argument("--case", required=True)
    p.add_argument("--dpi", type=int, default=300, help="Render DPI (default 300)")
    p.add_argument("--force", action="store_true", help="Re-render even if cached")
    p.set_defaults(func=cmd_prep_inputs)

    sub.add_parser("validate-refs", help="Validate provenance of all reference CSVs").set_defaults(func=cmd_validate_refs)

    p = sub.add_parser("check-extraction", help="Gate: every rendered page must be extracted")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_check_extraction)

    p = sub.add_parser("cache-status", help="Per-cert cache freshness (missing/stale/legacy/fresh)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_cache_status)

    p = sub.add_parser("crop", help="High-DPI crop of a fractional bbox region of a cert page")
    p.add_argument("--case", required=True)
    p.add_argument("--stem", required=True)
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--bbox", required=True, help="x0,y0,x1,y1 as 0.0-1.0 fractions")
    p.add_argument("--dpi", type=int, default=300, help="Render DPI (default 300)")
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("tile-inputs", help="Split rendered PNGs into 2x2 overlapping tiles (legible Vision reads)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true", help="Every manifest case with rendered PNGs")
    p.set_defaults(func=cmd_tile_inputs)

    p = sub.add_parser("orient-sheets", help="Compose labelled contact sheets for page-orientation detection (page-aligner input)")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_orient_sheets)

    p = sub.add_parser("align-inputs", help="Apply detected page rotations to rendered cert PNGs (idempotent)")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_align_inputs)

    p = sub.add_parser("classify-sheets", help="Phase 1.6: compose upright contact sheets for document-type classification (doc-classifier input)")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_classify_sheets)

    p = sub.add_parser("check-doctype", help="Phase 1.6 gate: every rendered stem must have a valid <stem>_doctype.json")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_check_doctype)

    p = sub.add_parser("prep-mps", help="Render + tile MPS PDFs for the shared mps-extractor digest")
    p.add_argument("--case", required=True)
    p.add_argument("--dpi", type=int, default=300, help="Render DPI (default 300)")
    p.set_defaults(func=cmd_prep_mps)

    p = sub.add_parser("limits", help="Per-case reference-limit pack (relevant CSV rows)")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_limits)

    p = sub.add_parser("attachments", help="기준 20: enclosed-document attachment index (requirement-vs-attachment input)")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_attachments)

    p = sub.add_parser("merge-parts", help="Merge chunked Vision fragments into <stem>_extracted.json")
    p.add_argument("--case", required=True)
    p.add_argument("--stem", help="Merge only this cert stem (default: all stems with fragments)")
    p.set_defaults(func=cmd_merge_parts)

    p = sub.add_parser("merge-reviews", help="Merge per-domain partial reviews into <case>_review.json")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true", help="Merge every manifest case that has partials")
    p.set_defaults(func=cmd_merge_reviews)

    p = sub.add_parser(
        "annotate",
        help="Burn 주의/N/A/FAIL verdicts onto cert PDFs as boxed image annotations (PASS excluded)",
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true", help="Every manifest case with a <case>_annotations.json")
    p.add_argument("--dpi", type=int, default=200, help="Render DPI for burn-in (default 200; bbox is fractional so DPI affects only sharpness/size)")
    p.add_argument("--out", help="Output directory (single --case only; default <WORK>/output/reports/<case>)")
    p.set_defaults(func=cmd_annotate)

    p = sub.add_parser("evaluate", help="Evaluate against GT (strict + rubric)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
