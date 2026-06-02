"""PowerShell-friendly CLI entry point for cert-review-skill.

Usage (Windows PowerShell):
    python -m scripts.cli build-manifest
    python -m scripts.cli prep-inputs --case 4
    python -m scripts.cli validate-refs
    python -m scripts.cli compare --case 4
    python -m scripts.cli build-report --case 4
    python -m scripts.cli evaluate --case 4
    python -m scripts.cli evaluate --all

Run from `plugin/cert-review-skill/` with PYTHONIOENCODING=utf-8.

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


def _resolve_work_dir() -> Path:
    """Locate the working directory that holds the input dataset.

    Priority (so the deployed skill runs from an arbitrary user folder while the
    in-repo testbed regression keeps working):
      1. env `CERT_REVIEW_WORKDIR` — explicit override.
      2. testbed/dev layout — PLUGIN_DIR.parent.parent if it contains the
         dataset dirs (keeps `plugin/cert-review-skill/` working in the testbed).
      3. current working directory (deployment default).
    """
    env = os.environ.get("CERT_REVIEW_WORKDIR")
    if env:
        return Path(env).resolve()
    candidate = PLUGIN_DIR.parent.parent
    if (candidate / "ref_code").exists() or (
        candidate / "standard inspection Cert cleanup data"
    ).exists():
        return candidate
    return Path.cwd()


WORK_DIR = _resolve_work_dir()
# Input dir names default to the standard-inspection dataset layout but are
# overridable via env so a deployed user can point at their own folder names.
CERT_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_CERT_DIR", "standard inspection Cert cleanup data")
MPS_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_MPS_DIR", "standard inspection MPS cleanup data")
RAWDATA_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_RAWDATA_DIR", "rawdata")
REF_CODE_DIR = WORK_DIR / os.environ.get("CERT_REVIEW_REF_CODE_DIR", "ref_code")
CACHE_DIR = PLUGIN_DIR / ".cache"
OUTPUT_DIR = WORK_DIR / "output"
MANIFEST_PATH = PLUGIN_DIR / "manifest.json"


def _ensure_utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def cmd_build_manifest(args: argparse.Namespace) -> int:
    """Scan working dir and emit manifest.json indexing all 46 cases.

    Pulls from three primary sources:
    - standard inspection Cert cleanup data/<case>/*.pdf
    - standard inspection MPS cleanup data/<case>/*.pdf
    - rawdata/<case>/{*.pdf, *.zip}

    The ground-truth directory is intentionally never scanned here; the
    evaluation harness is the only module permitted to read it.
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
        raw_case = RAWDATA_DIR / case_id

        certs = sorted(p.name for p in cert_case.glob("*.pdf") if p.is_file())
        mps_files = (
            sorted(p.name for p in mps_case.glob("*.pdf") if p.is_file())
            if mps_case.exists() else []
        )
        raw_pdfs = (
            sorted(p.name for p in raw_case.glob("*.pdf") if p.is_file())
            if raw_case.exists() else []
        )
        raw_zips = (
            sorted(p.name for p in raw_case.glob("*.zip") if p.is_file())
            if raw_case.exists() else []
        )

        cases.append({
            "case_id": case_id,
            "cert_dir": str(cert_case.relative_to(WORK_DIR)).replace("\\", "/"),
            "mps_dir": (
                str(mps_case.relative_to(WORK_DIR)).replace("\\", "/")
                if mps_case.exists() else None
            ),
            "rawdata_dir": (
                str(raw_case.relative_to(WORK_DIR)).replace("\\", "/")
                if raw_case.exists() else None
            ),
            "cert_pdfs": certs,
            "mps_pdfs": mps_files,
            "rawdata": {
                "pdfs": raw_pdfs,
                "zips": raw_zips,
            },
            "has_cert_pdf": bool(certs),
            "has_mps": bool(mps_files),
            "is_zip_only": (not certs) and bool(raw_zips),
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
    print(f"     zip_only   = {sum(1 for c in cases if c['is_zip_only'])}")
    return 0


def cmd_prep_inputs(args: argparse.Namespace) -> int:
    """Phase 1: prepare 3-channel inputs (PNG body / annotations / zip).

    Renders cert PDFs to per-page PNGs, extracts live reviewer annotations from
    the rawdata originals, unpacks zips (zip-only cases), and
    writes a skeleton extracted.json per cert for Phase-2 Vision to fill.
    """
    from scripts.prep_inputs import prep_case  # noqa: PLC0415

    summary = prep_case(
        case_id=args.case,
        work_dir=WORK_DIR,
        cache_root=CACHE_DIR,
        dpi=200,
    )

    total_pngs = sum(c["png_count"] for c in summary["certs"])
    print(
        f"[OK] prep-inputs --case {args.case}: "
        f"{len(summary['certs'])} cert(s), {total_pngs} PNG(s), "
        f"zip_only={summary['zip_only']}"
    )
    for c in summary["certs"]:
        print(
            f"     {c['cert_pdf']} -> "
            f"{c['png_count']} png, {c['annotations_count']} annot"
        )
        print(f"        skeleton: {c['skeleton_path']}")
    for note in summary["notes"]:
        print(f"     note: {note}")
    return 0


def cmd_validate_refs(args: argparse.Namespace) -> int:
    """Phase 3: validate all CSV rows carry 4 provenance fields."""
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


def cmd_compare(args: argparse.Namespace) -> int:
    """Phase 4: deterministic comparison."""
    from scripts.compare_engine import compare_case  # noqa: PLC0415

    data_dir = PLUGIN_DIR / "data"
    result = compare_case(
        case_id=args.case,
        work_dir=WORK_DIR,
        cache_root=CACHE_DIR,
        data_dir=data_dir,
    )
    stats = result["stats"]
    print(f"[OK] compare --case {args.case}:")
    print(f"     total findings   = {stats['total']}")
    print(f"     dropped (no prov) = {stats['dropped']}")
    print(f"     by category      = {stats['by_category']}")
    print(f"     by severity      = {stats['by_severity']}")
    out_path = CACHE_DIR / args.case / f"{args.case}_findings.json"
    print(f"     written: {out_path}")
    if stats["dropped"]:
        drop_path = CACHE_DIR / args.case / f"{args.case}_dropped.json"
        drop_path.write_text(
            json.dumps(result["dropped_findings"], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"     dropped log: {drop_path}")
    return 0


def cmd_build_report(args: argparse.Namespace) -> int:
    """Phase 6: build 6-sheet Korean Excel report."""
    print(f"[TODO] build-report --case {args.case}: implementation pending Step 4")
    return 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Phase 7: strict GT match + rubric diagnostic.

    eval_harness is the ONLY module permitted to read the GT directory; the CLI
    merely passes the GT path through to it.
    """
    from scripts.eval_harness import evaluate, gt_path_for, parse_gt  # noqa: PLC0415

    gt_path = gt_path_for(WORK_DIR)
    if not gt_path.exists():
        print(f"[ERROR] GT file not found: {gt_path}", file=sys.stderr)
        return 1

    if args.all:
        case_ids = list(parse_gt(gt_path).keys())
    else:
        case_ids = [args.case]

    # The CLI layer may stamp with wall-clock time; eval_harness internals must not.
    stamp = _stamp_now()

    agg = evaluate(
        case_ids=case_ids,
        work_dir=WORK_DIR,
        cache_root=CACHE_DIR,
        gt_path=gt_path,
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
        f"= {agg['precision'] * 100:.1f}%  (target >= 90%)"
    )
    print(f"     dropped   = {agg['dropped_total']}  (target 0)")
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

    p = sub.add_parser("prep-inputs", help="Prepare 4-channel inputs for a case")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_prep_inputs)

    sub.add_parser("validate-refs", help="Validate provenance of all reference CSVs").set_defaults(func=cmd_validate_refs)

    p = sub.add_parser("compare", help="Run deterministic comparison for a case")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_compare)

    p = sub.add_parser("build-report", help="Build 6-sheet xlsx report")
    p.add_argument("--case", required=True)
    p.set_defaults(func=cmd_build_report)

    p = sub.add_parser("evaluate", help="Evaluate against GT (strict + rubric)")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--case")
    group.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_evaluate)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
