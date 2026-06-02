"""Compare-engine regression tests (Phase 4).

These tests exercise scripts.compare_engine against the real reference CSVs in
data/ and synthetic extracted.json fixtures placed in a pytest tmp cache dir.

Provenance (C2/C8) is honored end to end: every finding that survives into
result['findings'] has been re-validated by source_validator.filter_valid_findings,
so the body + MPS evidence entries must point at real files with matching sha256.

Design note (why the synthetic cert_file is a PDF, not the CSV the prompt
suggested): source_validator._read_text DOES extract text from .csv/.md/.json
sources and then enforces that the evidence snippet is present in that text.
The body-channel evidence snippet emitted by compare_engine is "Pb=0.004%",
which does not appear in grade_routing.csv -> the body evidence would be
rejected and the Pb finding would be silently dropped. So the cert_file is
instead the real P92 MPS PDF, which is an image-only scan with no real
embedded text and whose path/sha are reachable from work_dir.

KNOWN PRODUCT BUGS these tests surface (assertions intentionally NOT weakened):

  BUG A (source_validator._read_text / _check): a multi-page image-only PDF
  has no embedded text, yet pypdf returns "" per page and _read_text joins
  them with "\n", producing a *whitespace-only but truthy* string (e.g.
  "\n\n" for 3 pages). _check then does `if text and not _snippet_present(...)`
  -> the snippet check runs against effectively-empty text and rejects any
  real-content evidence snippet. The docstring of _read_text promises "return
  empty string and the snippet check is skipped" for no-text PDFs, but the
  skip never fires. Fix: return "" when the joined text is whitespace-only
  (or guard with `if text.strip()` in _check). This causes the P92 Pb finding
  (body + mps evidence both anchored on the image PDF) to be dropped, so
  test_pb_reject_finding and test_findings_have_required_schema_fields fail.

  BUG B (compare_engine._check_annotations): line ~658 unconditionally calls
  `extracted_path.relative_to(work_dir)`, so compare_case raises ValueError
  whenever the cache dir is not a subpath of work_dir (e.g. pytest tmp_path on
  a different drive). Worked around here via the cache_root fixture, which
  anchors the cache under work_dir.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from scripts.compare_engine import (
    compare_case,
    _grade_route,
    _a106_adjusted_mn_max,
    _resolve_grade_keys,
)
from scripts.refdata_loader import load_csv
from scripts.source_validator import compute_sha256


def test_a106_cmn_footnote():
    """A106/SA-106 Table 1 C/Mn footnote raises the Mn ceiling when C is low.

    case 24 (Gr.B, C=0.17, base Mn max 1.06): adjusted = 1.06 + 13*0.06 = 1.84
    -> capped at 1.65, so Mn=1.21% PASSES (not a violation).
    """
    # Low carbon -> ceiling rises to the 1.65 cap (Gr.B/C).
    adj = _a106_adjusted_mn_max(0.17, "SA-106-B", 1.06)
    assert abs(adj - 1.65) < 1e-9, adj
    assert 1.21 <= adj          # Mn=1.21 is within the adjusted ceiling -> PASS
    assert 1.70 > adj           # Mn=1.70 would still FAIL

    # Carbon near the spec max -> only a small bump (no false PASS for high Mn).
    adj2 = _a106_adjusted_mn_max(0.29, "SA-106-B", 1.06)
    assert abs(adj2 - 1.12) < 1e-9, adj2   # 1.06 + 1*0.06
    assert 1.21 > adj2          # Mn=1.21 still FAILS at C=0.29

    # Carbon at/above spec max -> no allowance (returns base).
    assert _a106_adjusted_mn_max(0.30, "SA-106-B", 1.06) == 1.06
    # Grade A cap is 1.35.
    assert _a106_adjusted_mn_max(0.05, "SA-106-A", 0.93) == 1.35
    # Non-A106 grade -> footnote does not apply.
    assert _a106_adjusted_mn_max(0.05, "SA-335-P91", 0.60) is None


# Exact snippet that lives verbatim in BOTH the extracted.json annotation item
# AND the llm_findings evidence — provenance must validate against extracted.json.
_DELTA_FERRITE_SNIPPET = (
    "The MTR shall clearly state that the delta ferrite content does not exceed 5%"
)


# --- Fixed locations (per task spec) -----------------------------------------

WORK = Path(
    r"D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection"
)
PLUGIN = WORK / "plugin" / "cert-review-skill"
DATA_DIR = PLUGIN / "data"

# A real file that exists, is reachable relative to WORK, and (being an
# image-only scanned PDF) yields no embedded pypdf text -> snippet check is
# skipped so body evidence validates on sha + path. This is the same PDF that
# backs the P92 Pb MPS override row in mps_overrides.csv.
CERT_PDF_ABS = WORK / "standard inspection MPS cleanup data" / "4" / "17. MPS-ANDRES-335P92.pdf"
CERT_REL = "standard inspection MPS cleanup data/4/17. MPS-ANDRES-335P92.pdf"

CANONICAL_FINDING_KEYS = {
    "finding_id",
    "category",
    "severity",
    "material_grade",
    "heat_no",
    "cert_pdf",
    "page_ref",
    "issue_summary",
    "details",
    "structured",
    "required_action",
    "evidence",
}


# --- Fixtures ----------------------------------------------------------------

@pytest.fixture
def cache_root(tmp_path: Path):
    """A unique cache dir that lives UNDER work_dir.

    compare_engine._check_annotations calls
    ``extracted_path.relative_to(work_dir)`` unconditionally, so compare_case
    crashes with ValueError whenever the cache dir is not a subpath of
    work_dir. pytest's tmp_path is on a different drive (C:) than work_dir
    (D:), which is cross-drive and can never be relative. To keep per-test
    isolation (we still derive uniqueness from tmp_path.name) while satisfying
    the engine's hard requirement, we anchor the cache under
    work_dir/.pytest_cache_runs/<unique> and clean it up afterward.

    NOTE: this is a workaround for a real robustness limitation in
    compare_engine (see _check_annotations line ~658) — see the failure report.
    """
    root = WORK / ".pytest_cache_runs" / tmp_path.name
    root.mkdir(parents=True, exist_ok=True)
    try:
        yield root
    finally:
        shutil.rmtree(WORK / ".pytest_cache_runs", ignore_errors=True)


# --- Helpers -----------------------------------------------------------------

def _write_extracted(cache_root: Path, case_id: str, payload: dict) -> Path:
    """Write <cache_root>/<case_id>/<case_id>_extracted.json (UTF-8)."""
    case_dir = cache_root / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    out = case_dir / f"{case_id}_extracted.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _cert_sha() -> str:
    assert CERT_PDF_ABS.exists(), f"fixture cert PDF missing: {CERT_PDF_ABS}"
    return compute_sha256(CERT_PDF_ABS)


# --- 1. Grade routing --------------------------------------------------------

def test_grade_route_matches_p91():
    routing = load_csv(DATA_DIR / "grade_routing.csv", WORK)
    row = _grade_route("SA-335 P91", routing)
    assert row is not None, "SA-335 P91 should route"
    assert row["asme_spec"] == "SA-335"


def test_grade_route_and_keys_wpb():
    """WPB/WPC carbon-steel fittings must route and resolve to SA-234-WPB/WPC
    chemistry keys. Regression: chem key was garbled ('WPB^(D'), routing had no
    WPB/WPC row, and _resolve_grade_keys only captured 'WP'+digit grades."""
    routing = load_csv(DATA_DIR / "grade_routing.csv", WORK)
    for cert_grade, key in [
        ("SA-234 WPB", "SA-234-WPB"),
        ("A234 WPC", "SA-234-WPC"),
        ("WPB", "SA-234-WPB"),
    ]:
        row = _grade_route(cert_grade, routing)
        assert row is not None, f"{cert_grade} should route"
        assert row["asme_spec"] == "SA-234"
        keys = _resolve_grade_keys(row, cert_grade)
        assert key in keys, f"{cert_grade} -> {keys} missing {key}"


# --- 2. THE KEY REGRESSION: GT Case 4 F4-5 (P92 Pb trace element) ------------

def test_pb_reject_finding(cache_root: Path):
    """A P92 Heat analysis reporting Pb=0.004% violates the MPS override
    Pb_max<=0.001 and MUST surface as a Chemistry/Reject finding that survives
    provenance filtering (i.e. lands in result['findings'], not dropped)."""
    case_id = "case_pb_regression"
    payload = {
        "cert_file": CERT_REL,
        "cert_sha256": _cert_sha(),
        "page_extraction": [
            {
                "page": 1,
                "header": {"grade": "SA-335 P92"},
                "chemistry": {
                    "analysis_type": "Heat",
                    "elements": {
                        "Pb": {"value": 0.004, "unit": "%"},
                    },
                },
            }
        ],
        "channels": {},
    }
    _write_extracted(cache_root, case_id, payload)

    result = compare_case(case_id, WORK, cache_root, DATA_DIR)

    pb_findings = [
        f
        for f in result["findings"]
        if f["category"] == "Chemistry"
        and f["severity"] == "Reject"
        and "Pb" in f["issue_summary"]
    ]
    assert pb_findings, (
        "Expected a Chemistry/Reject Pb finding in result['findings']; "
        f"got findings={[ (f['category'], f['severity'], f['issue_summary']) for f in result['findings'] ]} "
        f"dropped={[ (d['finding_id'], d.get('_drop_reason')) for d in result['dropped_findings'] ]}"
    )

    # It must have survived provenance filtering (already true since it is in
    # result['findings']) AND must NOT appear in dropped_findings.
    dropped_ids = {d["finding_id"] for d in result["dropped_findings"]}
    assert all(f["finding_id"] not in dropped_ids for f in pb_findings)


# --- 3. Clean cert => no chemistry/mechanical findings -----------------------

def test_clean_cert_no_findings(cache_root: Path):
    """All-in-range P92 chemistry (and no mechanical/HT/NDE/annotation data)
    yields zero chemistry or mechanical findings.

    Elements chosen are all within the SA-335-P92 code range and none of them
    carry a P92 MPS trace-element override (Pb/Sn/As/Sb/Bi are deliberately
    excluded)."""
    case_id = "case_clean"
    payload = {
        "cert_file": CERT_REL,
        "cert_sha256": _cert_sha(),
        "page_extraction": [
            {
                "page": 1,
                "header": {"grade": "SA-335 P92"},
                "chemistry": {
                    "analysis_type": "Heat",
                    "elements": {
                        "C": {"value": 0.10, "unit": "%"},   # [0.07, 0.13]
                        "Mn": {"value": 0.45, "unit": "%"},  # [0.30, 0.60]
                        "Cr": {"value": 9.00, "unit": "%"},  # [8.50, 9.50]
                        "Mo": {"value": 0.45, "unit": "%"},  # [0.30, 0.60]
                    },
                },
            }
        ],
        "channels": {},
    }
    _write_extracted(cache_root, case_id, payload)

    result = compare_case(case_id, WORK, cache_root, DATA_DIR)

    chem_mech = [
        f for f in result["findings"] if f["category"] in ("Chemistry", "Mechanical")
    ]
    assert chem_mech == [], (
        "Clean in-range cert should produce no chemistry/mechanical findings; "
        f"got {[ (f['finding_id'], f['issue_summary']) for f in chem_mech ]}"
    )


# --- 4. Schema conformance of every surviving finding ------------------------

def test_findings_have_required_schema_fields(cache_root: Path):
    """Every finding in result['findings'] carries the full canonical schema,
    including a non-empty evidence list and a populated structured dict."""
    case_id = "case_schema"
    payload = {
        "cert_file": CERT_REL,
        "cert_sha256": _cert_sha(),
        "page_extraction": [
            {
                "page": 1,
                "header": {"grade": "SA-335 P92"},
                "chemistry": {
                    "analysis_type": "Heat",
                    "elements": {
                        "Pb": {"value": 0.004, "unit": "%"},  # MPS Reject
                        "C": {"value": 0.20, "unit": "%"},    # code Reject (max 0.13)
                    },
                },
            }
        ],
        "channels": {},
    }
    _write_extracted(cache_root, case_id, payload)

    result = compare_case(case_id, WORK, cache_root, DATA_DIR)

    assert result["findings"], "expected at least one finding for schema check"
    for f in result["findings"]:
        missing = CANONICAL_FINDING_KEYS - set(f.keys())
        assert not missing, f"{f.get('finding_id')} missing keys: {missing}"
        assert f["cert_pdf"] == CERT_REL
        assert isinstance(f["structured"], dict) and f["structured"], (
            f"{f['finding_id']} structured must be a populated dict"
        )
        assert isinstance(f["evidence"], list) and f["evidence"], (
            f"{f['finding_id']} evidence must be a non-empty list"
        )
        for ev in f["evidence"]:
            for prov in ("channel", "source_file", "anchor", "snippet", "sha256"):
                assert prov in ev, f"{f['finding_id']} evidence missing {prov}"


# --- 5. LLM-authored findings merge + provenance resolution ------------------

def test_llm_findings_merge(cache_root: Path):
    """compare_case ingests an optional <case>_llm_findings.json, RESOLVES full
    provenance for each evidence entry against the case's extracted.json, and
    runs the same source_validator gate.

    Assertions:
      - An LLM finding whose evidence snippet IS literally present in
        extracted.json (channel=annotations) survives into result['findings']
        with full 4-field evidence (source_file/anchor/snippet/sha256), where
        source_file points at the extracted.json and anchor == 'channels.annotations'.
      - An LLM finding whose evidence snippet is NOT present is DROPPED
        (recorded in dropped_findings, absent from findings) — Claude cannot
        invent a citation.
    """
    case_id = "case_llm_merge"
    extracted_payload = {
        "cert_file": CERT_REL,
        "cert_sha256": _cert_sha(),
        # No deterministic-trigger data: keep page_extraction empty so the only
        # findings come from the LLM file. This isolates the merge behavior.
        "page_extraction": [],
        "channels": {
            "annotations": {
                "items": [
                    {
                        "page": 3,
                        "subtype": "Highlight",
                        "text": _DELTA_FERRITE_SNIPPET,
                    }
                ]
            },
            "emails": {"items": []},
        },
    }
    ext_path = _write_extracted(cache_root, case_id, extracted_payload)

    llm_doc = {
        "case_id": case_id,
        "findings": [
            {
                "finding_id": "L4-1",
                "category": "Microstructure",
                "severity": "ActionRequired",
                "material_grade": "P91",
                "heat_no": None,
                "cert_pdf": CERT_REL,
                "page_ref": "p.3-4",
                "issue_summary": "delta ferrite 함량 명시 요구 (MTR 보완 필요)",
                "details": "MTR must state delta ferrite content <= 5%.",
                "required_action": "Request revised MTR stating delta ferrite content.",
                "evidence": [
                    {
                        "channel": "annotations",
                        "snippet": _DELTA_FERRITE_SNIPPET,
                    }
                ],
            },
            {
                # This snippet does NOT appear anywhere in extracted.json ->
                # must be DROPPED by the provenance gate.
                "finding_id": "L4-2",
                "category": "DocumentError",
                "severity": "ActionRequired",
                "material_grade": "P91",
                "heat_no": None,
                "cert_pdf": CERT_REL,
                "page_ref": "p.5",
                "issue_summary": "fabricated citation",
                "details": "This evidence snippet was never in the source.",
                "required_action": "n/a",
                "evidence": [
                    {
                        "channel": "annotations",
                        "snippet": "THIS TEXT IS NOT IN THE EXTRACTED JSON AT ALL 9z9z",
                    }
                ],
            },
        ],
    }
    (cache_root / case_id / f"{case_id}_llm_findings.json").write_text(
        json.dumps(llm_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    result = compare_case(case_id, WORK, cache_root, DATA_DIR)

    # --- The honest (resolvable) LLM finding survived with full provenance. ---
    kept = [f for f in result["findings"] if f["finding_id"] == "L4-1"]
    assert kept, (
        "Expected LLM finding L4-1 to survive provenance filtering; "
        f"findings={[f['finding_id'] for f in result['findings']]} "
        f"dropped={[(d['finding_id'], d.get('_drop_reason')) for d in result['dropped_findings']]}"
    )
    f = kept[0]
    # Canonical schema present.
    missing = CANONICAL_FINDING_KEYS - set(f.keys())
    assert not missing, f"L4-1 missing canonical keys: {missing}"
    assert f["category"] == "Microstructure"
    assert f["severity"] == "ActionRequired"
    assert isinstance(f["evidence"], list) and f["evidence"], "L4-1 must carry evidence"
    ev = f["evidence"][0]
    # Full 4-field provenance resolved deterministically by the engine.
    for prov in ("channel", "source_file", "anchor", "snippet", "sha256"):
        assert ev.get(prov), f"L4-1 evidence missing/empty {prov}: {ev}"
    assert ev["anchor"] == "channels.annotations", ev["anchor"]
    assert ev["snippet"] == _DELTA_FERRITE_SNIPPET
    # source_file resolves to the case's extracted.json and sha matches.
    assert ext_path.name in ev["source_file"], ev["source_file"]
    assert ev["sha256"] == compute_sha256(ext_path)

    # --- The fabricated-citation LLM finding was DROPPED. ---
    assert all(f["finding_id"] != "L4-2" for f in result["findings"]), (
        "L4-2 cites a snippet absent from extracted.json and must NOT survive"
    )
    dropped_ids = {d["finding_id"] for d in result["dropped_findings"]}
    assert "L4-2" in dropped_ids, (
        "L4-2 must be recorded in dropped_findings (provenance honesty); "
        f"dropped={dropped_ids}"
    )
