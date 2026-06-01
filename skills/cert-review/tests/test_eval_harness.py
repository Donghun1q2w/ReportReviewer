"""GT evaluation harness tests (Phase 7).

Run from the plugin dir:
    PYTHONIOENCODING=utf-8 python -m pytest tests/test_eval_harness.py -v

These tests exercise scripts.eval_harness:
    parse_gt, load_cert_findings, match_case, evaluate

C4 note: the package __init__.py installs a sys.audit hook that aborts open()
of the GT data directory from any module whose __name__ does not contain
"eval_harness". parse_gt reads the GT file from *inside* eval_harness, so its
frame is on the stack and the hook allows the read. The hermetic evaluate test
writes its own tiny GT markdown to tmp_path (a path that does NOT contain the
guarded literal), so it is not affected by the audit hook either.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.eval_harness import (
    parse_gt,
    load_cert_findings,
    match_case,
    evaluate,
)

# The single real GT file. Only eval_harness reads it (the read happens inside
# parse_gt), so passing the path through here does not violate C4.
REAL_GT_PATH = Path(
    r"D:\001_Work\2026\033_성적서 검토\Certification_Examine"
    r"\testbed\1. Standard Inspection\standard inspection GT data\GT_Answer.md"
)


# --------------------------------------------------------------------------- #
# 1. parse_gt on the real GT file
# --------------------------------------------------------------------------- #


def test_parse_gt_counts():
    """parse_gt returns ~46 cases / ~104 findings and the F4-5 Pb Reject finding."""
    if not REAL_GT_PATH.exists():
        pytest.skip(f"real GT file not present: {REAL_GT_PATH}")

    gt = parse_gt(REAL_GT_PATH)

    n_cases = len(gt)
    n_findings = sum(len(v) for v in gt.values())
    print(f"[parse_gt] cases={n_cases} findings={n_findings}")

    assert n_cases >= 44, f"expected >=44 cases, got {n_cases}"
    assert n_findings >= 100, f"expected >=100 findings, got {n_findings}"

    # Case '4' must exist and carry the P92 Pb Reject finding (F4-5).
    assert "4" in gt, f"case '4' missing; case ids = {sorted(gt.keys())}"
    case4 = gt["4"]

    pb = [
        f
        for f in case4
        if f.get("category") == "Chemistry"
        and f.get("severity") == "Reject"
        and "P92" in (f.get("material_grade") or "")
    ]
    print(f"[parse_gt] case4 findings={len(case4)} P92-Chem-Reject={len(pb)}")
    assert pb, (
        "case '4' should have a Chemistry/Reject/P92 finding (F4-5); "
        f"case4 = {[(f.get('finding_id'), f.get('category'), f.get('severity'), f.get('material_grade')) for f in case4]}"
    )
    # Sanity: it really is F4-5.
    assert any(f.get("finding_id") == "F4-5" for f in pb), (
        f"expected F4-5 among Pb findings, got {[f.get('finding_id') for f in pb]}"
    )


# --------------------------------------------------------------------------- #
# 2/3. match_case primitives
# --------------------------------------------------------------------------- #


def _finding(fid, category, severity, grade, page, summary, heat=None):
    return {
        "finding_id": fid,
        "category": category,
        "severity": severity,
        "material_grade": grade,
        "heat_no": heat,
        "page_ref": page,
        "issue_summary": summary,
    }


def test_match_case_perfect():
    """Identical gt/cert findings -> hits == gt_total and all rubric ratios 1.0."""
    gt = [
        _finding("F1-1", "Chemistry", "Reject", "P92",
                 "p.5-6", "P92 Pb over MPS max 0.001 percent"),
        _finding("F1-2", "Microstructure", "ActionRequired", "P91",
                 "p.3-4", "P91 delta ferrite content not reported in MTR"),
    ]
    # Cert findings carry the same comparable fields.
    cert = [
        _finding("C1", "Chemistry", "Reject", "P92",
                 "p.5-6", "P92 Pb over MPS max 0.001 percent"),
        _finding("C2", "Microstructure", "ActionRequired", "P91",
                 "p.3-4", "P91 delta ferrite content not reported in MTR"),
    ]

    res = match_case(gt, cert)
    print(f"[match perfect] hits={res['hits']} gt_total={res['gt_total']} rubric={res['rubric']}")

    assert res["gt_total"] == 2
    assert res["hits"] == res["gt_total"] == 2
    assert sorted(res["unmatched_gt_ids"]) == []
    assert res["extra_cert_ids"] == []

    for dim, ratio in res["rubric"].items():
        assert ratio == 1.0, f"rubric[{dim}] expected 1.0, got {ratio}"


def test_match_case_miss():
    """A cert finding that disagrees on a GATING dimension must NOT hit.

    Under the Issue-match predicate the gates are content + grade + page +
    severity-tier (category is diagnostic only). Here the cert finding is about
    a different grade AND an unrelated issue, so it must not hit.
    """
    gt = [
        _finding("F1-1", "Chemistry", "Reject", "P92",
                 "p.5-6", "P92 Pb over MPS max 0.001 percent"),
    ]
    cert = [
        _finding("C1", "Mechanical", "Reject", "A106-B",
                 "p.1", "A106-B tensile strength below minimum 415 MPa"),
    ]

    res = match_case(gt, cert)
    print(f"[match miss] hits={res['hits']} unmatched={res['unmatched_gt_ids']}")

    assert res["hits"] == 0
    assert res["unmatched_gt_ids"] == ["F1-1"]


def test_category_not_gated():
    """Issue-match: same issue with a DIFFERENT category still HITS.

    GT labels the same issue with different categories across cases, so category
    is diagnostic only — the issue (content+grade+page+severity-tier) governs.
    """
    gt = [
        _finding("F1-1", "DocumentError", "ActionRequired", "P92",
                 "p.5-6", "P92 Pb over MPS max 0.001 percent"),
    ]
    # Different category (Chemistry) + severity within the same tier
    # (Reject vs ActionRequired are both 'major'); same grade/page/content.
    cert = [
        _finding("C1", "Chemistry", "Reject", "P92",
                 "p.5-6", "P92 Pb over MPS max 0.001 percent"),
    ]

    res = match_case(gt, cert)
    print(f"[category not gated] hits={res['hits']} rubric={res['rubric']}")

    assert res["hits"] == 1
    # category disagreed -> diagnostic rubric records 0, but it did not block.
    assert res["rubric"]["category"] == 0.0


def test_semantic_match_cross_phrasing():
    """A cross-phrased cert finding (different wording, mixed EN/KO) HITS its GT.

    The cert finding and GT finding share:
      - category Chemistry (exact), severity Reject (exact)
      - grade token 'P92' ('SA-335-P92' vs 'P92')
      - page overlap (p.5 in 'p.5' and 'p.5-6')
      - KEY token 0.004 (decimal number) even though the summaries are phrased
        very differently (English vs Korean), so token-Jaccard alone is low.
    """
    gt = [
        _finding(
            "F-CP",
            "Chemistry",
            "Reject",
            "P92",
            "p.5-6",
            "P92 Pb(Lead) MPS 요구값 초과 — Actual 0.004% vs MPS max 0.001%",
        ),
    ]
    cert = [
        _finding(
            "C-CP",
            "Chemistry",
            "Reject",
            "SA-335-P92",
            "p.5",
            "Pb=0.004% violates MPS limit (<= 0.001%)",
        ),
    ]

    res = match_case(gt, cert)
    print(
        f"[semantic cross-phrasing] hits={res['hits']} matched_gt={res['matched_gt_ids']} "
        f"matched_cert={res['matched_cert_ids']} rubric={res['rubric']}"
    )

    assert res["gt_total"] == 1
    assert res["hits"] == 1
    assert res["matched_gt_ids"] == ["F-CP"]
    assert res["unmatched_gt_ids"] == []
    assert res["matched_cert_ids"] == ["C-CP"]
    assert res["extra_cert_ids"] == []


# --------------------------------------------------------------------------- #
# 4. evaluate — hermetic PASS / FAIL
# --------------------------------------------------------------------------- #

_TINY_GT = """# Tiny GT

## Case 99

- **case_id**: 99
- **project**: Hermetic
- **summary**: hermetic one-case fixture

### Certificate: `HERM-001.pdf`

- **materials**: P92

#### F99-1 — [Reject] [Chemistry] P92 Pb over MPS max 0.001 percent

- **category**: Chemistry
- **severity**: Reject
- **material_grade**: P92
- **heat_no**: _N/A_
- **page_ref**: p.5-6
- **issue_summary**: P92 Pb over MPS max 0.001 percent
- **details**: Actual 0.004 vs max 0.001
- **required_action**: NCR
- **sources**: PDF annotation p.5

#### F99-2 — [ActionRequired] [Microstructure] P91 delta ferrite content not reported in MTR

- **category**: Microstructure
- **severity**: ActionRequired
- **material_grade**: P91
- **heat_no**: _N/A_
- **page_ref**: p.3-4
- **issue_summary**: P91 delta ferrite content not reported in MTR
- **details**: missing
- **required_action**: re-issue
- **sources**: PDF annotation p.3

---
"""


def _write_tiny_gt(tmp_path: Path) -> Path:
    # A plain tmp_path file — NOT under the guarded 'standard inspection GT data'
    # literal, so the audit hook does not block this read.
    gt_path = tmp_path / "tiny_gt.md"
    gt_path.write_text(_TINY_GT, encoding="utf-8")
    return gt_path


def _write_cache(tmp_path: Path, case_id: str, findings: list[dict]) -> Path:
    cache_root = tmp_path / "cache"
    case_dir = cache_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    payload = {"findings": findings, "dropped_findings": [], "stats": {"dropped": 0}}
    (case_dir / f"{case_id}_findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cache_root


def _matching_cert_findings() -> list[dict]:
    return [
        _finding("C99-1", "Chemistry", "Reject", "SA335 P92",
                 "p.5-6", "P92 Pb over MPS max 0.001 percent"),
        _finding("C99-2", "Microstructure", "ActionRequired", "P91",
                 "p.3-4", "P91 delta ferrite content not reported in MTR"),
    ]


def test_load_cert_findings_roundtrip(tmp_path: Path):
    """Sanity: load_cert_findings reads the cache JSON written by the helper."""
    cache_root = _write_cache(tmp_path, "99", _matching_cert_findings())
    loaded = load_cert_findings("99", cache_root)
    assert [f["finding_id"] for f in loaded] == ["C99-1", "C99-2"]
    assert load_cert_findings("does-not-exist", cache_root) == []


def test_evaluate_pass_conditions(tmp_path: Path):
    """Full coverage -> PASS; a missing GT finding -> FAIL."""
    gt_path = _write_tiny_gt(tmp_path)

    # --- PASS scenario: cert covers both GT findings, no extras, no drops. ---
    work_dir = tmp_path / "work_pass"
    work_dir.mkdir()
    cache_root = _write_cache(tmp_path, "99", _matching_cert_findings())

    agg_pass = evaluate(
        case_ids=["99"],
        work_dir=work_dir,
        cache_root=cache_root,
        gt_path=gt_path,
        stamp="pass",
    )
    print(
        f"[evaluate PASS] verdict={agg_pass['verdict']} recall={agg_pass['recall']} "
        f"precision={agg_pass['precision']} case_pass={agg_pass['case_pass_count']}/{agg_pass['n_cases']} "
        f"dropped={agg_pass['dropped_total']}"
    )
    assert agg_pass["pass"] is True
    assert agg_pass["verdict"] == "PASS"
    assert agg_pass["recall"] == 1.0
    assert agg_pass["precision"] >= 0.9
    assert agg_pass["case_pass_count"] == agg_pass["n_cases"] == 1
    assert agg_pass["dropped_total"] == 0
    # report artifacts written under work_dir/output/eval
    assert Path(agg_pass["report_json"]).exists()
    assert Path(agg_pass["report_md"]).exists()

    # --- FAIL scenario: cert is missing F99-2 -> recall < 1.0 -> FAIL. ---
    work_dir_fail = tmp_path / "work_fail"
    work_dir_fail.mkdir()
    only_one = [_matching_cert_findings()[0]]  # drop the Microstructure finding
    cache_root_fail = _write_cache(tmp_path / "fail", "99", only_one)

    agg_fail = evaluate(
        case_ids=["99"],
        work_dir=work_dir_fail,
        cache_root=cache_root_fail,
        gt_path=gt_path,
        stamp="fail",
    )
    print(
        f"[evaluate FAIL] verdict={agg_fail['verdict']} recall={agg_fail['recall']} "
        f"unmatched={[pc['unmatched_gt_ids'] for pc in agg_fail['per_case']]}"
    )
    assert agg_fail["pass"] is False
    assert agg_fail["verdict"] == "FAIL"
    assert agg_fail["recall"] < 1.0
    assert agg_fail["case_pass_count"] != agg_fail["n_cases"]
    assert "F99-2" in agg_fail["per_case"][0]["unmatched_gt_ids"]
