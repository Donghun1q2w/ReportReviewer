"""Tests for scripts.attachments — 기준 20 deterministic attachment index.

Self-contained: every fixture (extracted JSON + doctype sidecar) is synthesised
under tmp_path, so these tests carry no dataset coupling (do NOT add this file to
conftest._DATASET_COUPLED).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cli
from scripts.attachments import (
    build_attachments_pack,
    collect_finished_heats,
    _norm_heat,
)


# --- fixture builders -------------------------------------------------------

def _write_extracted(case_cache: Path, stem: str, pages: list[dict]) -> None:
    """pages: list of {"page": int, "heat_no": str|None}."""
    case_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "stem": stem,
        "page_extraction": [
            {"page": p["page"], "header": {"heat_no": p.get("heat_no")}}
            for p in pages
        ],
    }
    (case_cache / f"{stem}_extracted.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _write_png(case_cache: Path, stem: str, page_numbers: list[int]) -> None:
    """Create empty placeholder renders so ``_all_stems_covered`` sees this stem
    as rendered (same ``<stem>_pNN.png`` naming ``_stems_in_png_dir`` expects)."""
    png_dir = case_cache / "png"
    png_dir.mkdir(parents=True, exist_ok=True)
    for n in page_numbers:
        (png_dir / f"{stem}_p{n}.png").write_bytes(b"")


def _write_doctype(case_cache: Path, stem: str, pages: dict[int, str],
                   documents: list[dict] | None = None) -> None:
    case_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.1" if documents is not None else "1.0",
        "stem": stem,
        "pages": {str(p): t for p, t in pages.items()},
        "uncertain_pages": [],
    }
    if documents is not None:
        payload["documents"] = documents
    (case_cache / f"{stem}_doctype.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


# --- _norm_heat -------------------------------------------------------------

def test_norm_heat_strips_ws_and_uppercases():
    assert _norm_heat(" 14328912 ") == "14328912"
    assert _norm_heat("wf24 088280z") == "WF24088280Z"
    assert _norm_heat(None) == ""
    assert _norm_heat("") == ""


def test_norm_heat_no_fuzzy_substitution():
    # 0/O and 1/I are NOT folded — exact-only matching (기준 20 forbids fuzzy).
    assert _norm_heat("0O1I") == "0O1I"


# --- collect_finished_heats -------------------------------------------------

def test_collect_finished_heats_skips_excluded_pages(tmp_path):
    case = tmp_path / "C"
    _write_extracted(case, "certA", [
        {"page": 1, "heat_no": "H100"},           # included
        {"page": 2, "heat_no": "H200"},           # excluded (raw material)
        {"page": 3, "heat_no": "H300"},           # included
    ])
    _write_doctype(case, "certA", {
        1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL", 3: "MTC_FINISHED",
    })
    assert collect_finished_heats(case) == ["H100", "H300"]


def test_collect_finished_heats_verbatim_dedup_and_empty_drop(tmp_path):
    case = tmp_path / "C"
    _write_extracted(case, "certA", [
        {"page": 1, "heat_no": "H100"},
        {"page": 2, "heat_no": "H100"},           # duplicate → dropped
        {"page": 3, "heat_no": None},             # empty → dropped
        {"page": 4, "heat_no": "H400"},
    ])
    # no sidecar → nothing excluded
    assert collect_finished_heats(case) == ["H100", "H400"]


# --- build_attachments_pack -------------------------------------------------

def test_pack_coverage_exact_match_only(tmp_path):
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1, "heat_no": "14328912"},
    ])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 22: "NDE_REPORT"},
        documents=[{"doc_type": "NDE_REPORT", "pages": [22],
                    "related_heat_nos": ["14328912", "OTHER999"],
                    "related_po_items": [], "related_confidence": "high"}])
    _write_png(case_cache, "certA", [1, 22])
    pack = build_attachments_pack("C", tmp_path)
    att = pack["attachments"][0]
    assert att["matched_heat_nos"] == ["14328912"]
    assert att["unmatched_heat_nos"] == ["OTHER999"]
    assert pack["heat_coverage"] == {"NDE_REPORT": {"14328912": ["p.22"]}}
    assert pack["sidecar_present"] is True
    assert pack["finished_heats"] == ["14328912"]


def test_pack_unmatched_never_in_coverage(tmp_path):
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 5: "NDE_REPORT"},
        documents=[{"doc_type": "NDE_REPORT", "pages": [5],
                    "related_heat_nos": ["RAWMATERIALHEAT"],  # not in inventory (E5)
                    "related_po_items": [], "related_confidence": "high"}])
    pack = build_attachments_pack("C", tmp_path)
    att = pack["attachments"][0]
    assert att["matched_heat_nos"] == []
    assert att["unmatched_heat_nos"] == ["RAWMATERIALHEAT"]
    assert pack["heat_coverage"] == {}   # unmatched → no coverage, no auto-fail


def test_pack_multi_run_union_coverage(tmp_path):
    """E4: two same-type enclosed runs → coverage is the union of page ranges."""
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1, "heat_no": "H1"}, {"page": 2, "heat_no": "H2"},
    ])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 2: "MTC_FINISHED", 10: "NDE_REPORT", 20: "NDE_REPORT"},
        documents=[
            {"doc_type": "NDE_REPORT", "pages": [10],
             "related_heat_nos": ["H1"], "related_po_items": [],
             "related_confidence": "high"},
            {"doc_type": "NDE_REPORT", "pages": [20],
             "related_heat_nos": ["H1", "H2"], "related_po_items": [],
             "related_confidence": "high"},
        ])
    pack = build_attachments_pack("C", tmp_path)
    cov = pack["heat_coverage"]["NDE_REPORT"]
    assert sorted(cov["H1"]) == ["p.10", "p.20"]
    assert cov["H2"] == ["p.20"]


def test_pack_low_confidence_excluded_from_coverage(tmp_path):
    """결정 5-3: related_confidence 'low' → matched shown but NOT in coverage."""
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 9: "NDE_REPORT"},
        documents=[{"doc_type": "NDE_REPORT", "pages": [9],
                    "related_heat_nos": ["H1"], "related_po_items": [],
                    "related_confidence": "low"}])
    pack = build_attachments_pack("C", tmp_path)
    att = pack["attachments"][0]
    assert att["matched_heat_nos"] == ["H1"]      # informational
    assert pack["heat_coverage"] == {}            # low conf → state D, not coverage


def test_pack_po_only_report_heat_coverage_empty(tmp_path):
    """E3: enclosed report with only PO items (no heat column) → no coverage,
    related_po_items relayed for reviewer body cross-check."""
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 23: "PMI_REPORT"},
        documents=[{"doc_type": "PMI_REPORT", "pages": [23],
                    "related_heat_nos": [],
                    "related_po_items": ["PU2601565-039"],
                    "related_confidence": "high"}])
    pack = build_attachments_pack("C", tmp_path)
    att = pack["attachments"][0]
    assert att["related_po_items"] == ["PU2601565-039"]
    assert att["matched_heat_nos"] == []
    assert pack["heat_coverage"] == {}


def test_pack_sidecar_absent_is_not_error(tmp_path):
    """No doctype sidecar → sidecar_present false, empty attachments (legacy)."""
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    pack = build_attachments_pack("C", tmp_path)
    assert pack["sidecar_present"] is False
    assert pack["attachments"] == []
    assert pack["heat_coverage"] == {}
    assert pack["finished_heats"] == ["H1"]


def test_pack_sidecar_present_false_on_partial_stem_coverage(tmp_path):
    """Two rendered stems, only one classified -> sidecar_present is False.

    Guards against a partially-classified case reporting sidecar_present:true
    from stem A's sidecar while stem B (also rendered, no sidecar) has enclosed
    reports invisible to attachments[] — a caller trusting sidecar_present would
    otherwise treat stem B's silence as a confirmed zero-attachment state
    (기준 20 state B 미첨부 risk). Stem A's own attachment is still surfaced;
    only the case-level flag is downgraded.
    """
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    _write_extracted(case_cache, "certB", [{"page": 1, "heat_no": "H2"}])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 2: "NDE_REPORT"},
        documents=[{"doc_type": "NDE_REPORT", "pages": [2],
                    "related_heat_nos": ["H1"], "related_po_items": [],
                    "related_confidence": "high"}])
    # certB has no _doctype.json sidecar at all.
    _write_png(case_cache, "certA", [1, 2])
    _write_png(case_cache, "certB", [1])
    pack = build_attachments_pack("C", tmp_path)
    assert pack["sidecar_present"] is False
    assert [a["stem"] for a in pack["attachments"]] == ["certA"]
    assert pack["heat_coverage"] == {"NDE_REPORT": {"H1": ["p.2"]}}


def test_pack_norm_matches_whitespace_variant(tmp_path):
    """E9: header heat_no with trailing space still matches the related heat."""
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "14328912 "}])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 22: "NDE_REPORT"},
        documents=[{"doc_type": "NDE_REPORT", "pages": [22],
                    "related_heat_nos": ["14328912"], "related_po_items": [],
                    "related_confidence": "high"}])
    pack = build_attachments_pack("C", tmp_path)
    # matched recorded in inventory verbatim (with trailing space).
    assert pack["attachments"][0]["matched_heat_nos"] == ["14328912 "]
    assert pack["heat_coverage"]["NDE_REPORT"]["14328912 "] == ["p.22"]


def test_pack_written_to_disk_schema(tmp_path):
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    pack = build_attachments_pack("C", tmp_path)
    out = case_cache / "C_attachments.json"
    assert out.is_file()
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["schema_version"] == "1.0"
    assert on_disk["case_id"] == "C"


def test_pack_extracted_absent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_attachments_pack("C", tmp_path)   # no extracted json


# --- T-5: CLI exit-code matrix ----------------------------------------------

def _run_cli(monkeypatch, cache_root: Path, case_id: str) -> int:
    monkeypatch.setattr(cli, "CACHE_DIR", cache_root)
    return cli.main(["attachments", "--case", case_id])


def test_cli_attachments_ok_exit0(tmp_path, monkeypatch, capsys):
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    _write_doctype(case_cache, "certA",
        {1: "MTC_FINISHED", 22: "NDE_REPORT"},
        documents=[{"doc_type": "NDE_REPORT", "pages": [22],
                    "related_heat_nos": ["H1"], "related_po_items": [],
                    "related_confidence": "high"}])
    _write_png(case_cache, "certA", [1, 22])
    rc = _run_cli(monkeypatch, tmp_path, "C")
    out = capsys.readouterr().out
    assert rc == 0
    assert "sidecar_present=true" in out
    assert "coverage: NDE_REPORT 1 heat" in out


def test_cli_attachments_sidecar_absent_exit0(tmp_path, monkeypatch, capsys):
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [{"page": 1, "heat_no": "H1"}])
    rc = _run_cli(monkeypatch, tmp_path, "C")
    out = capsys.readouterr().out
    assert rc == 0
    assert "sidecar_present=false" in out
    assert "0 enclosed run(s)" in out


def test_cli_attachments_extracted_absent_exit1(tmp_path, monkeypatch, capsys):
    (tmp_path / "C").mkdir()
    rc = _run_cli(monkeypatch, tmp_path, "C")
    err = capsys.readouterr().err
    assert rc == 1
    assert "attachments" in err
