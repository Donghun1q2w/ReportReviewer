"""Provenance validator regression tests (C2/C8)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from scripts.source_validator import (
    MissingProvenanceError,
    REQUIRED_FIELDS,
    KNOWN_PROVENANCE_GAPS,
    validate_csv_row,
    validate_finding,
    filter_valid_findings,
    compute_sha256,
)


def _make_source(tmp_path: Path, content: str, name: str = "ref.md") -> tuple[Path, str]:
    """Write bytes (not text) so Windows newline translation doesn't break sha."""
    p = tmp_path / name
    data = content.encode("utf-8")
    p.write_bytes(data)
    sha = hashlib.sha256(data).hexdigest()
    return p, sha


def test_missing_field_rejected(tmp_path: Path):
    _make_source(tmp_path, "Mn 0.30 ~ 0.60")
    for missing in REQUIRED_FIELDS:
        row = {
            "source_file": "ref.md",
            "anchor": "p.1",
            "snippet": "Mn 0.30 ~ 0.60",
        }
        row[missing] = ""
        res = validate_csv_row(row, tmp_path, row_id=f"missing-{missing}")
        assert not res.ok, f"missing {missing} should fail"
        assert "missing" in res.reason


def test_missing_source_file_rejected(tmp_path: Path):
    row = {
        "source_file": "nonexistent.md",
        "anchor": "p.1",
        "snippet": "anything",
    }
    res = validate_csv_row(row, tmp_path, "missing-file")
    assert not res.ok
    assert "not found on disk" in res.reason


def test_snippet_not_in_source_rejected(tmp_path: Path):
    src, _ = _make_source(tmp_path, "Carbon 0.05 ~ 0.15")
    row = {
        "source_file": src.name,
        "anchor": "p.1",
        "snippet": "Sulfur 0.005 max",  # not in source
    }
    res = validate_csv_row(row, tmp_path, "snippet-test")
    assert not res.ok
    assert "snippet not found" in res.reason


def test_valid_row_accepted(tmp_path: Path):
    content = "## Table 1\nC 0.08–0.12\nMn 0.30–0.60\nP 0.020 max\n"
    src, _ = _make_source(tmp_path, content)
    row = {
        "source_file": src.name,
        "anchor": "Table1#Mn",
        "snippet": "Mn 0.30–0.60",
    }
    res = validate_csv_row(row, tmp_path, "ok-test")
    assert res.ok, res.reason


def test_whitespace_normalized_for_snippet(tmp_path: Path):
    src, _ = _make_source(tmp_path, "C\t 0.08    – 0.12")
    row = {
        "source_file": src.name,
        "anchor": "Table1#C",
        "snippet": "C 0.08 – 0.12",
    }
    res = validate_csv_row(row, tmp_path, "ws-test")
    assert res.ok


# --- KNOWN_PROVENANCE_GAPS waiver (SA-105 chemistry_limits.csv provisional
# exception — see source_validator.py module docstring) ------------------

def test_gap_listed_row_waived_when_snippet_missing(tmp_path: Path):
    src, _ = _make_source(tmp_path, "unrelated garbled OCR text", "SA-105_SA-105M.md")
    row = {
        "grade": "SA-105", "element": "C", "analysis": "Heat",
        "source_file": src.name, "anchor": "Table1#C", "snippet": "0.35 max.",
    }
    res = validate_csv_row(row, tmp_path, "gap-test", csv_name="chemistry_limits.csv")
    assert res.ok, res.reason
    assert res.waived
    assert res.waiver_reason


def test_gap_lookup_requires_exact_csv_element_match(tmp_path: Path):
    src, _ = _make_source(tmp_path, "unrelated garbled OCR text", "SA-105_SA-105M.md")
    # Same grade, but an element not in the 7-element gap set (only
    # C/Mn/Si/P/S/Cr/Mo are listed — Ni is not) must still fail normally.
    row = {
        "grade": "SA-105", "element": "Ni", "analysis": "Heat",
        "source_file": src.name, "anchor": "Table1#Ni", "snippet": "0.40 max.",
    }
    res = validate_csv_row(row, tmp_path, "gap-miss-element", csv_name="chemistry_limits.csv")
    assert not res.ok
    assert not res.waived


def test_gap_lookup_scoped_to_csv_name(tmp_path: Path):
    src, _ = _make_source(tmp_path, "unrelated garbled OCR text", "SA-105_SA-105M.md")
    row = {
        "grade": "SA-105", "element": "C", "analysis": "Heat",
        "source_file": src.name, "anchor": "Table1#C", "snippet": "0.35 max.",
    }
    # A gap-listed (grade, element, analysis) under a DIFFERENT csv filename
    # (or no csv_name at all) must not be waived — the allowlist key includes
    # the csv filename precisely to avoid a content-only coincidental match.
    res_wrong_csv = validate_csv_row(row, tmp_path, "gap-wrong-csv", csv_name="mechanical_limits.csv")
    assert not res_wrong_csv.ok
    res_no_csv_name = validate_csv_row(row, tmp_path, "gap-no-csv-name")
    assert not res_no_csv_name.ok


def test_known_provenance_gaps_covers_exactly_the_reported_sa105_elements():
    keys = {k for k in KNOWN_PROVENANCE_GAPS if k[0] == "chemistry_limits.csv" and k[1] == "SA-105"}
    assert {k[2] for k in keys} == {"C", "Mn", "Si", "P", "S", "Cr", "Mo"}
    assert all(k[3] == "Heat" for k in keys)
    assert all(reason for reason in KNOWN_PROVENANCE_GAPS.values())


def test_finding_without_evidence_rejected(tmp_path: Path):
    finding = {
        "finding_id": "F1-1",
        "category": "Chemistry",
        "severity": "Reject",
        "issue_summary": "Pb over limit",
        "evidence": [],
    }
    res = validate_finding(finding, tmp_path)
    assert not res.ok
    assert "no evidence" in res.reason


def test_filter_valid_findings_splits_dropped(tmp_path: Path):
    src, _ = _make_source(tmp_path, "Pb 0.004", "cert.md")
    good = {
        "finding_id": "F-good",
        "category": "Chemistry",
        "severity": "Reject",
        "issue_summary": "Pb over",
        "evidence": [{
            "channel": "body",
            "source_file": src.name,
            "anchor": "p.1",
            "snippet": "Pb 0.004",
        }],
    }
    bad = {
        "finding_id": "F-bad",
        "category": "Other",
        "severity": "Minor",
        "issue_summary": "no evidence",
        "evidence": [],
    }
    valid, dropped = filter_valid_findings([good, bad], tmp_path)
    assert [v["finding_id"] for v in valid] == ["F-good"]
    assert [d["finding_id"] for d in dropped] == ["F-bad"]
    assert dropped[0]["_drop_reason"]


def test_compute_sha256_matches_hashlib(tmp_path: Path):
    src, sha = _make_source(tmp_path, "abc")
    assert compute_sha256(src) == sha
