"""merge_reviews.py — merge per-domain partial reviews into <case>_review.json.

The compliance review (SKILL.md Phase 4) is split across five domain subagents
that each write a partial review under .cache/<case>/:

    <case>_review_<domain>.json   domain ∈ {chemistry, mechanical,
                                            heat_treatment, nde, format}

Each partial carries the SAME top-level skeleton (case_id, po_number?,
mps_files?, code_edition_note?) plus the materials[] it could judge from its own
domain and the findings[] it raised. A partial material fills exactly ONE domain
section array (chemistry → chemistry, mechanical → mechanical, heat_treatment →
heat_treatment, nde → nde, format → doc_checks) and carries a domain-scoped
verdict.

This module deterministically merges those partials into the single
<case>_review.json consumed downstream (compliance_report.py's 6-sheet Excel and
eval_harness.load_predictions). The merged JSON's schema is INVARIANT — top-level
{case_id, po_number, mps_files, code_edition_note, materials[], findings[],
excluded_documents[]} with materials[] = {item_name, heat_no, grade_cert,
grade_spec, size, qty, verdict, chemistry[], mechanical[], heat_treatment[],
nde[], doc_checks[]} and findings[] = {no, severity, category, location, content,
action}. ``excluded_documents[]`` is a deterministic Phase 1.6 injection (from the
<stem>_doctype.json sidecars — see scripts.doctype) listing enclosed non-MTC
document runs excluded from comparison; each record carries {stem, doc_type,
doc_type_ko, pages, page_range, note, related_heat_nos, related_po_items,
related_confidence} — the last three are the 기준 20 related identifiers joined
from the sidecar's advisory documents[] (verbatim from the enclosed document's
own table; []/[]/"low" on a 1.0 sidecar). It never touches findings[] (기준 17.7
informational separation, keeps eval precision unaffected) and is [] when no
doctype sidecar exists. Merge metadata (source files, issues) is reported on
stdout only — never written into the output JSON.

Constraint: pure JSON reshaping. No domain re-judgement happens here; the merge
only relays each partial's verdicts (aggregating a material's per-domain verdicts
to its worst) and re-numbers findings globally.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from scripts.doctype import excluded_documents_for_case

# Fixed domain merge order. Drives section placement, code_edition_note join
# order, and findings concatenation order.
_DOMAIN_ORDER = ["chemistry", "mechanical", "heat_treatment", "nde", "format"]

# domain -> the materials[] section key it populates.
_DOMAIN_SECTION = {
    "chemistry": "chemistry",
    "mechanical": "mechanical",
    "heat_treatment": "heat_treatment",
    "nde": "nde",
    "format": "doc_checks",
}

# All section keys a merged material must carry (downstream reads each one).
_SECTION_KEYS = ["chemistry", "mechanical", "heat_treatment", "nde", "doc_checks"]

# Identity fields carried verbatim from the first partial that names them.
_IDENT_FIELDS = ["item_name", "grade_spec", "size", "qty"]

# Worst-verdict aggregation rank: FAIL > 주의 > PASS; everything else ignored.
_VERDICT_RANK = {"PASS": 1, "주의": 2, "FAIL": 3}
_RANK_VERDICT = {1: "PASS", 2: "주의", 3: "FAIL"}

_WS_RE = re.compile(r"\s+")

# Item-number discriminator parsed from item_name. Domains name the same item
# differently — "ITEM 011", "Seamless Alloy Steel Pipe (PO Item No. 011)",
# "(PO Item 011)", "(ITEM 011)" — but all carry the item number, which
# int-normalisation makes zero-padding-insensitive.
_ITEM_NO_RE = re.compile(r"(?:PO\s*)?ITEM(?:\s*NO\.?)?\s*[#:]?\s*0*(\d+)", re.IGNORECASE)


def _norm_ws(value: str | None) -> str:
    """strip + collapse internal whitespace runs to a single space."""
    if not value:
        return ""
    return _WS_RE.sub(" ", str(value)).strip()


def _item_token(material: dict) -> str:
    """Per-item discriminator for multi-item certs sharing heat_no + grade.

    One MTC can cover several PO items from the SAME heat and grade that differ
    only in size/qty (e.g. ITEM 011 660*35.1mm vs ITEM 013 660*40mm). Keying on
    (heat_no, grade_cert) alone collapses those into one merged material whose
    header comes from the first item while each domain section is overwritten
    by the last — i.e. mislabelled data. Discriminate by:

    1. the item number parsed from item_name (format varies per domain, the
       number does not);
    2. else the normalised size up to the first comma (some domains append
       ", Length ..." after the base size);
    3. else "" — single-item behaviour, key degrades to (heat_no, grade_cert).

    Cross-domain naming inconsistency can at worst SPLIT a material into two
    visible rows (loud, reviewable) — never silently mislabel values.
    """
    m = _ITEM_NO_RE.search(_norm_ws(material.get("item_name")))
    if m:
        return f"item:{int(m.group(1))}"
    size = _norm_ws(material.get("size")).split(",")[0].strip()
    if size:
        return f"size:{size}"
    return ""


def _material_key(material: dict) -> tuple[str, str, str]:
    """Whitespace-normalised (heat_no, grade_cert, item_token) match key."""
    return (
        _norm_ws(material.get("heat_no")),
        _norm_ws(material.get("grade_cert")),
        _item_token(material),
    )


def partial_path(case_cache: Path, domain: str) -> Path:
    """Return the partial review path for one domain under a case cache dir."""
    return case_cache / f"{case_cache.name}_review_{domain}.json"


def discover_partials(case_cache: Path) -> list[str]:
    """Return the domains (in fixed order) that have a partial file present."""
    return [d for d in _DOMAIN_ORDER if partial_path(case_cache, d).is_file()]


def merge_case(case_id: str, cache_root: Path) -> dict:
    """Merge all present domain partials for one case into <case>_review.json.

    Returns {"case_id", "sources": [str, ...], "missing_domains": [str, ...],
    "n_materials", "n_findings", "written", "backup", "issues": [str, ...]}.

    Raises FileNotFoundError when no partial exists for the case.
    """
    case_cache = Path(cache_root) / str(case_id)

    present = discover_partials(case_cache)
    if not present:
        raise FileNotFoundError(
            f"no partial reviews (*_review_<domain>.json) under {case_cache}"
        )
    missing = [d for d in _DOMAIN_ORDER if d not in present]

    issues: list[str] = []
    for d in missing:
        msg = f"missing partial: {d}"
        issues.append(msg)
        print(f"[WARN] case {case_id}: {msg}", file=sys.stderr)

    sources: list[str] = []
    case_id_str = str(case_id)

    # Top-level accumulators.
    merged_case_id: str | None = None
    po_number = None
    mps_files = None
    notes: list[str] = []

    # materials: preserve first-seen order across domains.
    mat_order: list[tuple[str, str, str]] = []
    mat_by_key: dict[tuple[str, str, str], dict] = {}
    # per-material accumulated domain verdict rank (worst).
    mat_verdict_rank: dict[tuple[str, str, str], int] = {}

    # findings accumulated in domain order; re-numbered globally at the end.
    merged_findings: list[dict] = []
    seen_finding_keys: set[tuple[str, str]] = set()

    for domain in present:
        path = partial_path(case_cache, domain)
        sources.append(path.name)
        partial = json.loads(path.read_text(encoding="utf-8"))

        # --- top-level: case_id consistency (hard error) ----------------- #
        p_case = partial.get("case_id")
        if p_case is not None:
            if merged_case_id is None:
                merged_case_id = p_case
            elif p_case != merged_case_id:
                raise ValueError(
                    f"case_id mismatch in {path.name}: "
                    f"'{p_case}' != '{merged_case_id}'"
                )

        # po_number / mps_files: first non-empty wins; later divergence -> issue.
        p_po = partial.get("po_number")
        if p_po not in (None, ""):
            if po_number is None:
                po_number = p_po
            elif p_po != po_number:
                issues.append(
                    f"{domain}: po_number '{p_po}' != '{po_number}' (kept first)"
                )
        p_mps = partial.get("mps_files")
        if p_mps:
            if mps_files is None:
                mps_files = p_mps
            elif p_mps != mps_files:
                issues.append(
                    f"{domain}: mps_files {p_mps} != {mps_files} (kept first)"
                )

        # code_edition_note: collect non-empty, dedup, join in domain order.
        note = partial.get("code_edition_note")
        note = note.strip() if isinstance(note, str) else ""
        if note and note not in notes:
            notes.append(note)

        # --- materials: fill this domain's section into the keyed material - #
        section_key = _DOMAIN_SECTION[domain]
        for material in partial.get("materials") or []:
            key = _material_key(material)
            if key not in mat_by_key:
                merged = {
                    "item_name": material.get("item_name", ""),
                    "heat_no": material.get("heat_no", ""),
                    "grade_cert": material.get("grade_cert", ""),
                    "grade_spec": material.get("grade_spec", ""),
                    "size": material.get("size", ""),
                    "qty": material.get("qty", ""),
                    "verdict": "",
                }
                for sk in _SECTION_KEYS:
                    merged[sk] = []
                mat_by_key[key] = merged
                mat_order.append(key)
                mat_verdict_rank[key] = 0
            merged = mat_by_key[key]

            # Identity fields: first non-empty wins; later divergence -> issue.
            for field in _IDENT_FIELDS:
                val = material.get(field)
                if val in (None, ""):
                    continue
                cur = merged.get(field)
                if cur in (None, ""):
                    merged[field] = val
                elif val != cur:
                    issues.append(
                        f"{domain}: material ({key[0]}/{key[1]}) {field} "
                        f"'{val}' != '{cur}' (kept first)"
                    )

            # Domain section array.
            merged[section_key] = material.get(section_key) or []

            # Aggregate the domain verdict into the material's worst verdict.
            rank = _VERDICT_RANK.get(_norm_ws(material.get("verdict")))
            if rank and rank > mat_verdict_rank[key]:
                mat_verdict_rank[key] = rank

        # --- findings: append in domain order, dropping exact dup -------- #
        for finding in partial.get("findings") or []:
            dedup = (
                _norm_ws(finding.get("category")),
                _norm_ws(finding.get("content")),
            )
            if dedup != ("", "") and dedup in seen_finding_keys:
                issues.append(
                    f"{domain}: duplicate finding dropped "
                    f"(category='{finding.get('category')}')"
                )
                continue
            if dedup != ("", ""):
                seen_finding_keys.add(dedup)
            merged_findings.append(finding)

    # Finalise material verdicts (worst aggregate; no recognised verdict from
    # any domain must surface as 미판정, never silently pass).
    materials_out: list[dict] = []
    for key in mat_order:
        merged = mat_by_key[key]
        rank = mat_verdict_rank[key]
        if rank == 0:
            merged["verdict"] = "미판정"
            issues.append(
                f"material ({key[0]}/{key[1]}): no recognised domain verdict "
                "-> 미판정"
            )
        else:
            merged["verdict"] = _RANK_VERDICT[rank]
        materials_out.append(merged)

    # Re-number findings globally, 1-based, preserving order.
    findings_out: list[dict] = []
    for i, finding in enumerate(merged_findings, start=1):
        renum = dict(finding)
        renum["no"] = i
        findings_out.append(renum)

    # Phase 1.6 deterministic injection: enclosed non-MTC document runs excluded
    # from comparison (from the <stem>_doctype.json sidecars). Info-only; never
    # mixed into findings (기준 17.7). [] when the case has no doctype sidecar.
    excluded_docs = excluded_documents_for_case(case_cache)

    review = {
        "case_id": merged_case_id if merged_case_id is not None else case_id_str,
        "po_number": po_number if po_number is not None else "",
        "mps_files": mps_files if mps_files is not None else [],
        "code_edition_note": "\n".join(notes),
        "materials": materials_out,
        "findings": findings_out,
        "excluded_documents": excluded_docs,
    }

    # Write output, backing up any existing file first.
    out_path = case_cache / f"{case_id_str}_review.json"
    backup_path = None
    if out_path.exists():
        backup_path = out_path.with_suffix(".json.bak")
        backup_path.write_text(
            out_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    out_path.write_text(
        json.dumps(review, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "case_id": case_id_str,
        "sources": sources,
        "missing_domains": missing,
        "n_materials": len(materials_out),
        "n_findings": len(findings_out),
        "n_excluded_docs": len(excluded_docs),
        "written": str(out_path).replace("\\", "/"),
        "backup": str(backup_path).replace("\\", "/") if backup_path else None,
        "issues": issues,
    }


def merge_all(cache_root: Path, manifest_path: Path) -> dict:
    """Merge every manifest case that has at least one domain partial.

    Cases with no partial under .cache/<case>/ are silently skipped (they were
    not split into domain reviews). Returns {"cases": [merge_case result, ...],
    "skipped": [case_id, ...], "issues": [str, ...]}.
    """
    cache_root = Path(cache_root)
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))

    results: list[dict] = []
    skipped: list[str] = []
    for case in manifest.get("cases") or []:
        case_id = case.get("case_id")
        if case_id is None:
            continue
        case_cache = cache_root / str(case_id)
        if not discover_partials(case_cache):
            skipped.append(str(case_id))
            continue
        results.append(merge_case(case_id, cache_root))

    return {
        "cases": results,
        "skipped": skipped,
        "issues": [i for r in results for i in r["issues"]],
    }


__all__ = [
    "merge_case",
    "merge_all",
    "discover_partials",
    "partial_path",
]
