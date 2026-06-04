"""GT evaluation harness tests — comments.md based (Phase 7, req 3).

Run from the plugin dir with the dataset mounted:
    CERT_REVIEW_WORKDIR=<WORK> PYTHONIOENCODING=utf-8 python -m pytest tests/test_eval_harness.py -v

These tests exercise scripts.eval_harness:
    parse_comments, load_predictions, match_case, evaluate

C4 note: the package __init__.py installs a sys.audit hook that aborts open()
of the GT data directory from any module whose __name__ does not contain
"eval_harness". parse_comments reads each case's comments.md from *inside*
eval_harness, so its frame is on the stack and the hook allows the read. The
synthetic match/recall tests build issues + predictions in memory and never
touch the GT directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts.eval_harness import (
    parse_comments,
    load_predictions,
    match_case,
    evaluate,
    list_cases,
)

# Dataset root (WORK). Overridable via env so the suite runs anywhere the
# dataset is mounted; conftest skips this module when the dataset is absent.
WORK = Path(
    os.environ.get(
        "CERT_REVIEW_WORKDIR",
        r"D:\001_Work\2026\033_성적서 검토\Certification_Examine"
        r"\testbed\1. Standard Inspection",
    )
)


def _issue(issue_id, pages, text):
    return {
        "issue_id": issue_id,
        "pages": set(pages),
        "topic_tokens": set(),
        "text": text,
    }


def _pred(fid, page, summary, grade=None):
    return {
        "finding_id": fid,
        "issue_summary": summary,
        "page_ref": page,
        "material_grade": grade,
    }


# --------------------------------------------------------------------------- #
# 1. parse_comments on the real per-case comments.md (case 4)
# --------------------------------------------------------------------------- #


def test_list_cases_discovers_case4():
    cases = list_cases(WORK)
    assert "4" in cases, f"case '4' missing; got {cases[:10]} ..."
    # compound folder names are returned verbatim
    assert "30 & 31" in cases


def test_parse_comments_case4_known_issues():
    """Case 4 comments.md yields the known reviewer issues, with multi-page
    repetition of one topic collapsed into a single clustered issue."""
    issues = parse_comments("4", WORK)
    assert issues, "expected non-empty issues for case 4"

    def find(token_substr):
        hits = [i for i in issues if token_substr.lower() in i["text"].lower()]
        return hits

    # delta ferrite requirement (≤5% / ≤2.5%) — repeated on p.3,4,5,6 ->
    # ONE clustered issue spanning all those pages.
    df = find("delta ferrite")
    assert df, "delta ferrite issue not extracted"
    df_pages = set().union(*(i["pages"] for i in df))
    assert {3, 4, 5, 6} <= df_pages, (
        f"delta ferrite issue should span p.3-6 (cluster merge); got {sorted(df_pages)}"
    )
    # the cluster should be a SINGLE issue (multi-page repetition merged)
    assert len(df) == 1, f"delta ferrite should be one merged cluster, got {len(df)}"

    # Pb non-conformity (MPS 0.001 max / actual 0.004)
    pb = [i for i in issues if "pb" in i["text"].lower() and "0.004" in i["text"]]
    assert pb, "Pb non-conformity issue not extracted"
    pb_pages = set().union(*(i["pages"] for i in pb))
    assert {5, 6} <= pb_pages, f"Pb issue should span p.5-6; got {sorted(pb_pages)}"

    # SA106C Mn 1.65% (cert-1 p.7,8 + cert-2 p.1 all merge on topic)
    sa106 = [i for i in issues if "1.65" in i["text"]]
    assert sa106, "SA106C Mn 1.65% issue not extracted"

    # Noise must NOT appear as issues: '삭제 요청' / bare label lines.
    for i in issues:
        assert i["text"].strip() not in {"삭제 요청", "텍스트 상자", "설명선"}

    # text-less markings section must be ignored (no 'Circle'/'Square' residue)
    for i in issues:
        low = i["text"].lower()
        assert "circle×" not in low and "square×" not in low


# --------------------------------------------------------------------------- #
# 2. match_case — recall / precision on synthetic predictions
# --------------------------------------------------------------------------- #


def test_match_full_recall():
    """Every GT issue covered by a prediction -> recall 1.0, no extras."""
    gt = [
        _issue("G-1", [3, 4, 5, 6],
               "delta ferrite content does not exceed 5% per AMS 2315 ASTM E562"),
        _issue("G-2", [5, 6],
               "MPS requirement Pb(Lead) 0.001 max actual 0.004 non-conformity"),
    ]
    pred = [
        _pred("P1", "성적서 p.3-6 미세조직",
              "delta ferrite 미표기 — AMS 2315 / ASTM E562 기준 5% 이하 명시 요청"),
        _pred("P2", "성적서 p.5 화학성분 Pb",
              "Pb 0.004로 MPS 한계 0.001 초과 non-conformity"),
    ]

    res = match_case(gt, pred)
    assert res["gt_total"] == 2
    assert res["hits"] == 2
    assert res["unmatched_gt_ids"] == []
    assert res["extra_cert_ids"] == []


def test_match_partial_recall():
    """One of two GT issues matched -> recall 0.5; the missed one is reported."""
    gt = [
        _issue("G-1", [5, 6],
               "Pb(Lead) 0.001 max actual 0.004 non-conformity"),
        _issue("G-2", [7, 8], "SA106C는 Mn Max 1.65%"),
    ]
    pred = [
        _pred("P1", "p.5", "Pb 0.004 violates MPS limit 0.001"),
    ]

    res = match_case(gt, pred)
    assert res["hits"] == 1
    assert res["gt_total"] == 2
    assert res["unmatched_gt_ids"] == ["G-2"]
    # precision side: the single prediction matched.
    assert res["matched_cert_ids"] == ["P1"]
    assert res["extra_cert_ids"] == []


def test_match_empty_predictions():
    """No predictions -> zero hits, all GT issues unmatched."""
    gt = [_issue("G-1", [1], "SA106C는 Mn Max 1.65%")]
    res = match_case(gt, [])
    assert res["hits"] == 0
    assert res["gt_total"] == 1
    assert res["unmatched_gt_ids"] == ["G-1"]
    assert res["extra_cert_ids"] == []
    assert res["cert_total"] == 0


def test_match_page_gate_blocks_wrong_page():
    """Same content but a disjoint page -> no hit (page gate)."""
    gt = [_issue("G-1", [5], "Pb 0.004 over MPS 0.001 non-conformity")]
    pred = [_pred("P1", "p.99", "Pb 0.004 over MPS limit 0.001")]
    res = match_case(gt, pred)
    assert res["hits"] == 0
    assert res["unmatched_gt_ids"] == ["G-1"]


# --------------------------------------------------------------------------- #
# 3. load_predictions — review.json mapping + back-compat
# --------------------------------------------------------------------------- #


def _write_review(tmp_path: Path, case_id: str, findings, materials=None) -> Path:
    cache_root = tmp_path / "cache"
    case_dir = cache_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case_id,
        "materials": materials or [{"grade_spec": "SA-335-P92"}],
        "findings": findings,
    }
    (case_dir / f"{case_id}_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cache_root


def test_load_predictions_from_review(tmp_path: Path):
    cache_root = _write_review(
        tmp_path, "99",
        findings=[
            {"no": 1, "severity": "Reject", "category": "Chemistry",
             "location": "성적서 p.5 화학성분 Pb",
             "content": "Pb 0.004 over MPS 0.001", "action": "NCR"},
        ],
    )
    preds = load_predictions("99", cache_root)
    assert len(preds) == 1
    p = preds[0]
    assert p["issue_summary"] == "Pb 0.004 over MPS 0.001"
    assert "p.5" in p["page_ref"]
    # material_grade falls back to the case material grade
    assert p["material_grade"] == "SA-335-P92"


def test_load_predictions_review_takes_priority(tmp_path: Path):
    """review.json wins over a stale findings.json when both exist."""
    cache_root = _write_review(
        tmp_path, "99",
        findings=[{"no": 1, "content": "from review", "location": "p.1"}],
    )
    # also drop a back-compat findings.json
    (cache_root / "99" / "99_findings.json").write_text(
        json.dumps({"findings": [{"issue_summary": "from findings",
                                  "page_ref": "p.2"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    preds = load_predictions("99", cache_root)
    assert len(preds) == 1
    assert preds[0]["issue_summary"] == "from review"


def test_load_predictions_findings_backcompat(tmp_path: Path):
    cache_root = tmp_path / "cache"
    (cache_root / "99").mkdir(parents=True)
    (cache_root / "99" / "99_findings.json").write_text(
        json.dumps({"findings": [
            {"issue_summary": "delta ferrite missing", "page_ref": "p.3",
             "material_grade": "P91"},
        ]}, ensure_ascii=False),
        encoding="utf-8",
    )
    preds = load_predictions("99", cache_root)
    assert len(preds) == 1
    assert preds[0]["issue_summary"] == "delta ferrite missing"


def test_load_predictions_missing_returns_empty(tmp_path: Path):
    assert load_predictions("does-not-exist", tmp_path) == []


# --------------------------------------------------------------------------- #
# 4. evaluate — PASS / FAIL end-to-end against real comments.md
# --------------------------------------------------------------------------- #


def test_evaluate_case4_fail_when_no_predictions(tmp_path: Path):
    """With an empty cache (no review.json), case 4 has unmatched GT -> FAIL."""
    work_out = tmp_path / "work"
    work_out.mkdir()
    empty_cache = tmp_path / "cache"
    empty_cache.mkdir()

    # parse_comments must read the real GT from WORK; the report writes to work_out.
    # Provide both: GT lookup uses WORK, output uses work_out — but evaluate uses
    # one work_dir for both. Mirror the GT dir into work_out via a symlink-free
    # copy is overkill; instead evaluate against WORK and write under WORK/output.
    agg = evaluate(
        case_ids=["4"],
        work_dir=WORK,
        cache_root=empty_cache,
        stamp="test_fail",
    )
    assert agg["verdict"] == "FAIL"
    assert agg["recall"] < 1.0
    assert agg["total_gt"] >= 1
    assert Path(agg["report_md"]).exists()
    assert Path(agg["report_json"]).exists()
    # clean up the report artifacts we wrote into the dataset's output dir
    for k in ("report_md", "report_json"):
        try:
            Path(agg[k]).unlink()
        except OSError:
            pass


def test_evaluate_case4_pass_with_covering_predictions(tmp_path: Path):
    """Synthetic predictions that cover every case-4 GT issue -> PASS."""
    issues = parse_comments("4", WORK)
    # Build one prediction per GT issue: reuse the GT text + pages so each is a
    # guaranteed content+page hit. (This validates the evaluate plumbing, not
    # the production predictor.)
    cache_root = tmp_path / "cache"
    case_dir = cache_root / "4"
    case_dir.mkdir(parents=True)
    findings = [
        {"no": k, "content": gi["text"],
         "location": " ".join(f"p.{p}" for p in sorted(gi["pages"]))}
        for k, gi in enumerate(issues, start=1)
    ]
    (case_dir / "4_review.json").write_text(
        json.dumps({"case_id": "4", "materials": [], "findings": findings},
                   ensure_ascii=False),
        encoding="utf-8",
    )

    agg = evaluate(
        case_ids=["4"],
        work_dir=WORK,
        cache_root=cache_root,
        stamp="test_pass",
    )
    assert agg["recall"] == 1.0, f"expected full recall; per_case={agg['per_case']}"
    assert agg["case_pass_count"] == agg["n_cases"] == 1
    assert agg["verdict"] == "PASS"
    for k in ("report_md", "report_json"):
        try:
            Path(agg[k]).unlink()
        except OSError:
            pass
