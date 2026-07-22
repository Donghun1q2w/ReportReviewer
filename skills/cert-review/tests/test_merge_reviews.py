"""Tests for scripts.merge_reviews — domain partial review merge.

Self-contained: every fixture is built under tmp_path, so these tests carry no
dataset coupling (do NOT add this file to conftest._DATASET_COUPLED).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.merge_reviews import (
    _item_token,
    _material_key,
    discover_partials,
    merge_all,
    merge_case,
    partial_path,
)

# Top-level keys the merged review.json must carry — identical to the real
# .cache/<case>/<case>_review.json schema (no merge metadata leaks in).
_TOPLEVEL_KEYS = {
    "case_id",
    "po_number",
    "mps_files",
    "code_edition_note",
    "materials",
    "findings",
    "excluded_documents",
}
# Every merged material must carry all five domain section arrays.
_MATERIAL_KEYS = {
    "item_name",
    "heat_no",
    "grade_cert",
    "grade_spec",
    "size",
    "qty",
    "verdict",
    "chemistry",
    "mechanical",
    "heat_treatment",
    "nde",
    "doc_checks",
}

_DOMAIN_SECTION = {
    "chemistry": "chemistry",
    "mechanical": "mechanical",
    "heat_treatment": "heat_treatment",
    "nde": "nde",
    "format": "doc_checks",
}


def _write_partial(
    case_cache: Path,
    domain: str,
    *,
    case_id: str = "99",
    materials: list[dict] | None = None,
    findings: list[dict] | None = None,
    po_number: str | None = "PU-1",
    mps_files: list[str] | None = None,
    code_edition_note: str | None = None,
) -> Path:
    """Write a synthetic per-domain partial review file."""
    partial: dict = {"case_id": case_id}
    if po_number is not None:
        partial["po_number"] = po_number
    if mps_files is not None:
        partial["mps_files"] = mps_files
    if code_edition_note is not None:
        partial["code_edition_note"] = code_edition_note
    partial["materials"] = materials if materials is not None else []
    partial["findings"] = findings if findings is not None else []

    case_cache.mkdir(parents=True, exist_ok=True)
    path = case_cache / f"{case_cache.name}_review_{domain}.json"
    path.write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
    return path


def _material(
    domain: str,
    *,
    heat_no: str = "N100",
    grade_cert: str = "A106 Gr.B",
    verdict: str = "PASS",
    rows: list[dict] | None = None,
    item_name: str = "Seamless Pipe",
    grade_spec: str = "SA-106-B",
    size: str = "48.3 x 7.14",
    qty: str = "10",
) -> dict:
    """Build a partial material carrying exactly its domain section array."""
    section = _DOMAIN_SECTION[domain]
    return {
        "item_name": item_name,
        "heat_no": heat_no,
        "grade_cert": grade_cert,
        "grade_spec": grade_spec,
        "size": size,
        "qty": qty,
        "verdict": verdict,
        section: rows if rows is not None else [{"_d": domain}],
    }


def _finding(no: int, category: str, content: str) -> dict:
    return {
        "no": no,
        "severity": "Minor",
        "category": category,
        "location": "p.1",
        "content": content,
        "action": "fix it",
    }


def test_five_partials_merge_sections_verdict_and_findings(tmp_path):
    case = tmp_path / "99"
    # Same material (heat/grade) judged by all 5 domains; worst verdict = FAIL.
    verdicts = {
        "chemistry": "PASS",
        "mechanical": "주의",
        "heat_treatment": "PASS",
        "nde": "FAIL",
        "format": "PASS",
    }
    for i, domain in enumerate(
        ["chemistry", "mechanical", "heat_treatment", "nde", "format"]
    ):
        _write_partial(
            case,
            domain,
            materials=[_material(domain, verdict=verdicts[domain])],
            findings=[_finding(1, domain, f"issue from {domain}")],
        )

    result = merge_case("99", tmp_path)

    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))
    # Exact top-level key set (no merge metadata leaked).
    assert set(out.keys()) == _TOPLEVEL_KEYS
    assert len(out["materials"]) == 1
    mat = out["materials"][0]
    assert set(mat.keys()) == _MATERIAL_KEYS
    # Each domain section landed in the right array.
    for domain, section in _DOMAIN_SECTION.items():
        assert mat[section] == [{"_d": domain}], (domain, mat[section])
    # Worst-verdict aggregation.
    assert mat["verdict"] == "FAIL"
    # Findings concatenated in domain order, re-numbered 1..5.
    assert [f["no"] for f in out["findings"]] == [1, 2, 3, 4, 5]
    assert [f["category"] for f in out["findings"]] == [
        "chemistry",
        "mechanical",
        "heat_treatment",
        "nde",
        "format",
    ]
    assert result["missing_domains"] == []
    assert len(result["sources"]) == 5


def test_worst_verdict_warn_when_no_fail(tmp_path):
    case = tmp_path / "99"
    _write_partial(case, "chemistry", materials=[_material("chemistry", verdict="PASS")])
    _write_partial(case, "mechanical", materials=[_material("mechanical", verdict="주의")])
    # N/A and blank verdicts are ignored.
    _write_partial(case, "nde", materials=[_material("nde", verdict="N/A")])

    merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))
    assert out["materials"][0]["verdict"] == "주의"


def test_no_recognised_verdict_yields_mipanjeong(tmp_path):
    # Every domain says N/A or blank: must surface 미판정 + issue, not PASS.
    case = tmp_path / "99"
    _write_partial(case, "chemistry", materials=[_material("chemistry", verdict="N/A")])
    _write_partial(case, "nde", materials=[_material("nde", verdict="")])

    result = merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))
    assert out["materials"][0]["verdict"] == "미판정"
    assert any("미판정" in issue for issue in result["issues"])


def test_partial_domain_missing_warns_and_proceeds(tmp_path, capsys):
    case = tmp_path / "99"
    _write_partial(case, "chemistry", materials=[_material("chemistry")])
    _write_partial(case, "mechanical", materials=[_material("mechanical")])

    result = merge_case("99", tmp_path)

    assert set(result["missing_domains"]) == {"heat_treatment", "nde", "format"}
    # Missing domains are reported as issues and warned on stderr.
    assert any("heat_treatment" in i for i in result["issues"])
    err = capsys.readouterr().err
    assert "missing partial" in err
    # The merge still produced a usable output.
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))
    assert out["materials"][0]["chemistry"] == [{"_d": "chemistry"}]
    assert out["materials"][0]["nde"] == []


def test_no_partials_raises(tmp_path):
    (tmp_path / "99").mkdir()
    with pytest.raises(FileNotFoundError, match="no partial"):
        merge_case("99", tmp_path)


def test_case_id_mismatch_raises(tmp_path):
    case = tmp_path / "99"
    _write_partial(case, "chemistry", case_id="99", materials=[_material("chemistry")])
    _write_partial(case, "mechanical", case_id="88", materials=[_material("mechanical")])

    with pytest.raises(ValueError, match="case_id mismatch"):
        merge_case("99", tmp_path)


def test_material_key_normalized_and_one_sided_preserved(tmp_path):
    case = tmp_path / "99"
    # Same heat/grade but with whitespace differences (leading/trailing space and
    # a double space inside grade_cert) -> normalisation (strip + collapse runs)
    # must fold them into ONE material.
    _write_partial(
        case,
        "chemistry",
        materials=[_material("chemistry", heat_no=" N100 ", grade_cert="A106  Gr.B")],
    )
    _write_partial(
        case,
        "mechanical",
        materials=[_material("mechanical", heat_no="N100", grade_cert="A106 Gr.B")],
    )
    # A material that only NDE saw -> preserved with empty sections elsewhere.
    _write_partial(
        case,
        "nde",
        materials=[_material("nde", heat_no="N200", grade_cert="A106 Gr.B")],
    )

    merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))

    assert len(out["materials"]) == 2
    by_heat = {m["heat_no"]: m for m in out["materials"]}
    # Normalised match: chemistry (first-seen, raw " N100 ") + mechanical folded
    # into the same material; the first-seen identity value is kept verbatim.
    merged = by_heat[" N100 "]
    assert merged["chemistry"] == [{"_d": "chemistry"}]
    assert merged["mechanical"] == [{"_d": "mechanical"}]
    assert merged["nde"] == []
    # NDE-only material preserved with empty non-NDE sections.
    nde_only = by_heat["N200"]
    assert nde_only["nde"] == [{"_d": "nde"}]
    assert nde_only["chemistry"] == []
    assert nde_only["mechanical"] == []


def test_exact_duplicate_finding_removed(tmp_path):
    case = tmp_path / "99"
    _write_partial(
        case,
        "chemistry",
        materials=[_material("chemistry")],
        findings=[_finding(1, "Chem", "Cr out of range")],
    )
    # Same (category, content) appears again in another domain -> dropped.
    _write_partial(
        case,
        "mechanical",
        materials=[_material("mechanical")],
        findings=[
            _finding(1, "Chem", "Cr out of range"),
            _finding(2, "Mech", "TS below min"),
        ],
    )

    result = merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))

    contents = [(f["category"], f["content"]) for f in out["findings"]]
    assert contents == [("Chem", "Cr out of range"), ("Mech", "TS below min")]
    assert [f["no"] for f in out["findings"]] == [1, 2]
    assert any("duplicate finding" in i for i in result["issues"])


def test_existing_review_backed_up(tmp_path):
    case = tmp_path / "99"
    case.mkdir()
    existing = case / "99_review.json"
    existing.write_text(
        json.dumps({"case_id": "99", "old": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_partial(case, "chemistry", materials=[_material("chemistry")])

    result = merge_case("99", tmp_path)

    backup = case / "99_review.json.bak"
    assert backup.exists()
    assert json.loads(backup.read_text(encoding="utf-8")) == {"case_id": "99", "old": True}
    assert result["backup"] is not None
    # The new file overwrote the old content.
    out = json.loads(existing.read_text(encoding="utf-8"))
    assert "old" not in out
    assert set(out.keys()) == _TOPLEVEL_KEYS


def test_toplevel_first_wins_and_note_join(tmp_path):
    case = tmp_path / "99"
    _write_partial(
        case,
        "chemistry",
        po_number="PU-1",
        mps_files=["mps_a.pdf"],
        code_edition_note="chem note",
        materials=[_material("chemistry")],
    )
    _write_partial(
        case,
        "mechanical",
        po_number="PU-2",  # divergence -> issue, first kept
        mps_files=["mps_a.pdf"],
        code_edition_note="chem note",  # duplicate string -> deduped
        materials=[_material("mechanical")],
    )
    _write_partial(
        case,
        "nde",
        po_number="PU-1",
        code_edition_note="nde note",
        materials=[_material("nde")],
    )

    result = merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))

    assert out["po_number"] == "PU-1"
    assert out["mps_files"] == ["mps_a.pdf"]
    # Notes joined in domain order with dedup.
    assert out["code_edition_note"] == "chem note\nnde note"
    assert any("po_number" in i for i in result["issues"])


def test_discover_and_partial_path_helpers(tmp_path):
    case = tmp_path / "99"
    _write_partial(case, "nde", materials=[_material("nde")])
    _write_partial(case, "chemistry", materials=[_material("chemistry")])

    # discover returns domains in the fixed merge order, not write order.
    assert discover_partials(case) == ["chemistry", "nde"]
    assert partial_path(case, "nde").name == "99_review_nde.json"


# --- multi-item same-heat/grade regression (real case P2600721-01) ---------
#
# One MTC covered two PO items from the SAME heat (S12601002QX) and grade
# (P91 Type1): ITEM 011 (660*35.1mm, qty 2) and ITEM 013 (660*40mm, qty 4).
# Keying materials on (heat_no, grade_cert) alone collapsed them into one
# merged material — header from the first item, every domain section
# overwritten by the last — i.e. ITEM 011's row silently carried ITEM 013's
# measured values. _item_token discriminates by parsed item number (naming
# format varies per domain), falling back to the normalised size prefix.


@pytest.mark.parametrize(
    "item_name",
    [
        "ITEM 011",
        "Seamless Alloy Steel Pipe (PO Item No. 011)",
        "Seamless Alloy Steel Pipe (PO Item 011)",
        "Seamless Alloy Steel Pipe (ITEM 011)",
        "item no: 11",
    ],
)
def test_item_token_folds_naming_variants(item_name):
    assert _item_token({"item_name": item_name}) == "item:11"


def test_item_token_size_fallback_strips_length_suffix():
    base = _item_token({"item_name": "Pipe", "size": '660*35.1mm (26"*AWT35.1)'})
    with_len = _item_token(
        {"item_name": "Pipe", "size": '660*35.1mm (26"*AWT35.1), Length 6000mm'}
    )
    assert base == with_len
    assert base.startswith("size:")


def test_material_key_degrades_to_legacy_when_no_item_no_size():
    m = {"item_name": "Pipe", "heat_no": "N100", "grade_cert": "A106 Gr.B"}
    assert _material_key(m) == ("N100", "A106 Gr.B", "")


def test_multi_item_same_heat_grade_stay_separate(tmp_path):
    case = tmp_path / "99"
    heat, grade = "S12601002QX", "P91 Type1 UT"
    # Domain-specific naming variants observed in the real case.
    _write_partial(case, "chemistry", materials=[
        _material("chemistry", heat_no=heat, grade_cert=grade,
                  item_name="Seamless Alloy Steel Pipe (PO Item No. 011)",
                  size='660*35.1mm (26"*AWT35.1)', qty="2 (Pieces)",
                  rows=[{"element": "C", "value": "0.10"}]),
        _material("chemistry", heat_no=heat, grade_cert=grade,
                  item_name="Seamless Alloy Steel Pipe (PO Item No. 013)",
                  size='660*40mm (26"*AWT40)', qty="4 (Pieces)",
                  rows=[{"element": "C", "value": "0.09"}]),
    ])
    _write_partial(case, "mechanical", materials=[
        _material("mechanical", heat_no=heat, grade_cert=grade,
                  item_name="ITEM 011", size='660*35.1mm (26"*AWT35.1)',
                  qty="2", rows=[{"specimen": "016", "ts": 680}]),
        _material("mechanical", heat_no=heat, grade_cert=grade, verdict="주의",
                  item_name="ITEM 013", size='660*40mm (26"*AWT40)',
                  qty="4", rows=[{"specimen": "989", "ts": 670}]),
    ])
    _write_partial(case, "format", materials=[
        _material("format", heat_no=heat, grade_cert=grade,
                  item_name="Seamless Alloy Steel Pipe (PO Item No. 011)",
                  size='660*35.1mm (26"*AWT35.1), Length 6000mm',
                  qty="Pieces 2 / Weight(MT) 6.397", rows=[{"check": "p.1"}]),
        _material("format", heat_no=heat, grade_cert=grade,
                  item_name="Seamless Alloy Steel Pipe (PO Item No. 013)",
                  size='660*40mm (26"*AWT40), Length 6000mm',
                  qty="Pieces 4 / Weight(MT) 14.675", rows=[{"check": "p.2"}]),
    ])

    result = merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))

    assert result["n_materials"] == 2
    by_item = {_item_token(m): m for m in out["materials"]}
    assert set(by_item) == {"item:11", "item:13"}
    # Each item keeps its OWN domain rows — no cross-item mixing.
    assert by_item["item:11"]["mechanical"] == [{"specimen": "016", "ts": 680}]
    assert by_item["item:13"]["mechanical"] == [{"specimen": "989", "ts": 670}]
    assert by_item["item:11"]["chemistry"] == [{"element": "C", "value": "0.10"}]
    assert by_item["item:13"]["chemistry"] == [{"element": "C", "value": "0.09"}]
    assert by_item["item:11"]["doc_checks"] == [{"check": "p.1"}]
    assert by_item["item:13"]["doc_checks"] == [{"check": "p.2"}]
    # Identity fields stay per-item; verdict aggregates per-item (worst).
    assert by_item["item:11"]["qty"] == "2 (Pieces)"
    assert by_item["item:13"]["qty"] == "4 (Pieces)"
    assert by_item["item:11"]["verdict"] == "PASS"
    assert by_item["item:13"]["verdict"] == "주의"
    # No cross-item identity divergence issues (size/qty of 013 vs 011).
    assert not any("'660*40mm" in i and "'660*35.1mm" in i for i in result["issues"])


def _write_doctype(case_cache: Path, stem: str, pages: dict[int, str],
                   uncertain: list[int] | None = None) -> None:
    case_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "stem": stem,
        "pages": {str(p): t for p, t in pages.items()},
        "uncertain_pages": uncertain or [],
    }
    (case_cache / f"{stem}_doctype.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_excluded_documents_empty_without_sidecar(tmp_path):
    """T-5: no doctype sidecar -> excluded_documents == [] (backward compat)."""
    case = tmp_path / "99"
    _write_partial(case, "chemistry", materials=[_material("chemistry")],
                   findings=[_finding(1, "Chem", "Cr out of range")])

    result = merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))
    assert out["excluded_documents"] == []
    assert result["n_excluded_docs"] == 0
    # findings untouched
    assert [f["content"] for f in out["findings"]] == ["Cr out of range"]


def test_excluded_documents_injected_from_sidecar(tmp_path):
    """T-5: doctype sidecar -> excluded_documents runs injected; findings unchanged."""
    case = tmp_path / "99"
    _write_partial(case, "chemistry", materials=[_material("chemistry")],
                   findings=[_finding(1, "Chem", "Cr out of range")])
    # Two enclosed non-MTC runs on one stem: raw-material p30-31, NDE p55.
    _write_doctype(case, "certA", {
        1: "MTC_FINISHED", 30: "MTC_RAW_MATERIAL", 31: "MTC_RAW_MATERIAL",
        55: "NDE_REPORT",
    })

    result = merge_case("99", tmp_path)
    out = json.loads((case / "99_review.json").read_text(encoding="utf-8"))

    ex = out["excluded_documents"]
    assert result["n_excluded_docs"] == 2
    assert [d["doc_type"] for d in ex] == ["MTC_RAW_MATERIAL", "NDE_REPORT"]
    assert ex[0]["pages"] == [30, 31]
    assert ex[0]["page_range"] == "p.30-31"
    assert ex[1]["pages"] == [55]
    assert ex[0]["doc_type_ko"] == "원자재 성적서(동봉 Mill Cert)"
    assert all("제외됨" in d["note"] for d in ex)
    # findings[] must NOT be polluted by exclusion memos (기준 17.7).
    assert [f["content"] for f in out["findings"]] == ["Cr out of range"]


def test_merge_all_only_cases_with_partials(tmp_path):
    cache_root = tmp_path / "cache"
    # Case 99 has partials; case 88 has none.
    _write_partial(cache_root / "99", "chemistry", case_id="99", materials=[_material("chemistry")])
    (cache_root / "88").mkdir(parents=True)

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"cases": [{"case_id": "99"}, {"case_id": "88"}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    summary = merge_all(cache_root, manifest)

    assert [c["case_id"] for c in summary["cases"]] == ["99"]
    assert summary["skipped"] == ["88"]
    assert (cache_root / "99" / "99_review.json").exists()
    assert not (cache_root / "88" / "88_review.json").exists()
