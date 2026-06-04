"""Pure domain-helper regression tests (grade routing + reference normalization).

The deterministic finding orchestration (compare_case + the _check_* rule
families) has been removed in favor of the LLM compliance path. What remains
under test here are the side-effect-free domain helpers in
scripts.compare_engine that encode ASME/ASTM rules:

  - _a106_adjusted_mn_max : A106/SA-106 Table 1 C/Mn footnote (Mn ceiling).
  - _grade_route          : match a cert grade against grade_routing.csv.
  - _resolve_grade_keys   : derive the chemistry/mech/HT CSV lookup keys.

The two grade-routing tests read the real grade_routing.csv under data/ and so
are dataset-coupled (load_csv resolves provenance against the working dir);
conftest skips them when CERT_REVIEW_WORKDIR / the dataset is absent.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.compare_engine import (
    _grade_route,
    _a106_adjusted_mn_max,
    _resolve_grade_keys,
)
from scripts.refdata_loader import load_csv


# --- Locations -----------------------------------------------------------
# WORK is the dataset working dir (ref_code / cert dirs), overridable via env.
# PLUGIN is THIS plugin's own dir, resolved from the test file location so the
# suite is self-contained regardless of where the plugin is checked out.

WORK = Path(
    os.environ.get(
        "CERT_REVIEW_WORKDIR",
        r"D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection",
    )
)
PLUGIN = Path(__file__).resolve().parents[1]
DATA_DIR = PLUGIN / "data"


# --- 1. A106/SA-106 C/Mn footnote -------------------------------------------

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


# --- 2. Grade routing --------------------------------------------------------

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
