"""Tests for scripts.mill_cert — 기준 21/22 deterministic cross-comparison pack.

Self-contained: every fixture (extracted JSON + doctype sidecar) is synthesised
under tmp_path, so these tests carry no dataset coupling (do NOT add this file
to conftest._DATASET_COUPLED). Adversarial scenarios T1-T18/T24-T31 from the
mill-cert-review-domain plan; T19-T22 live in test_merge_reviews.py /
test_compliance_report_mill_cert.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import cli
from scripts.mill_cert import (
    MILL_CERT_SUFFIX,
    _grade_family,
    _grade_probe,
    build_mill_cert_pack,
    compare_chemistry,
    compare_tensile,
    is_forging,
    scale_suspect,
    values_equal,
)


# --- fixture builders -------------------------------------------------------

def _write_extracted(case_cache: Path, stem: str, entries: list[dict]) -> None:
    """entries: page_extraction 엔트리 리스트를 그대로 기록.

    엔트리 형식(필요 필드만):
      {"page": 3,
       "header": {"heat_no": "B14339", "grade": "A182-F22 CL.3",
                  "spec": "ASTM A182-F22 CL.3-2022a", "cert_no": "DL-26-074-38",
                  "size_od_wt": "DN15 SW", "quantity": 33,
                  "mill_cert_no": "201404-004866", "mill_maker": "SeAH Besteel",
                  "starting_material": "ROUND BAR(OD40)"},
       "doc_type": "MTC_FINISHED",
       "chemistry": {"analysis_type": "Heat",
                     "elements": {"C": {"value": 0.15, "unit": "%"}}},
       "mechanical": {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94,
                      "RA_pct": 75.64,
                      "hardness": {"value": 185, "unit": "HBW"}},
       "heat_treatment": [{"stage": "Normalizing", "temp_C": 900,
                           "hold_min": 99, "cooling": "Air"}],
       "remarks": ["MILL CERT NO.: 201404-004866"]}
    최소 엔트리(legacy)는 {"page": N, "header": {}, "doc_type": "...", "remarks": [...]}.
    """
    case_cache.mkdir(parents=True, exist_ok=True)
    (case_cache / f"{stem}_extracted.json").write_text(
        json.dumps({"stem": stem, "page_extraction": entries}, ensure_ascii=False),
        encoding="utf-8")


def _write_doctype(case_cache: Path, stem: str, pages: dict[int, str]) -> None:
    case_cache.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "stem": stem,
        "pages": {str(p): t for p, t in pages.items()},
        "uncertain_pages": [],
    }
    (case_cache / f"{stem}_doctype.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _elems(**kv) -> dict:
    """{"C": 0.15} -> {"C": {"value": 0.15, "unit": "%"}}."""
    return {k: {"value": v, "unit": "%"} for k, v in kv.items()}


_ROUTING = [{"cert_grade_pattern": r"SA-?182\s*F22", "asme_spec": "SA-182"}]


def _pu_case(case_cache: Path, *, mill_mech: dict | None = None,
             mill_heat: str = "B14339", mill_cert_no: str = "201404-004866",
             finished_mill_cert_no: str | None = "201404-004866",
             finished_remarks: list[str] | None = None) -> None:
    """합성 PU2601564형 케이스: p3 완제품(단조 A182-F22) + p4 mill cert."""
    if mill_mech is None:
        mill_mech = {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94,
                     "RA_pct": 75.64, "hardness": {"value": 185, "unit": "HB"}}
    _write_extracted(case_cache, "certA", [
        {"page": 3,
         "header": {"heat_no": "B14339", "grade": "A182-F22 CL.3",
                    "spec": "ASTM A182-F22 CL.3-2022a", "cert_no": "DL-26-074-38",
                    "size_od_wt": "DN15 SW", "quantity": 33,
                    "mill_cert_no": finished_mill_cert_no,
                    "mill_maker": "SeAH Besteel",
                    "starting_material": "ROUND BAR(OD40)"},
         "doc_type": "MTC_FINISHED",
         "chemistry": {"analysis_type": "Heat",
                       "elements": _elems(C=0.15, Si=0.18, Mn=0.45, P=0.012,
                                          S=0.008, Cr=2.25, Mo=0.95)},
         "mechanical": {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94,
                        "RA_pct": 75.64,
                        "hardness": {"value": 185, "unit": "HBW"}},
         "heat_treatment": [
             {"stage": "Normalizing", "temp_C": 900, "hold_min": 99, "cooling": "Air"},
             {"stage": "Tempering", "temp_C": 730, "hold_min": 150, "cooling": "Air"}],
         "remarks": finished_remarks or []},
        {"page": 4,
         "header": {"heat_no": mill_heat, "cert_no": mill_cert_no,
                    "grade": "A182 F22 CL3", "vendor": "SeAH Besteel"},
         "doc_type": "MTC_RAW_MATERIAL",
         "chemistry": {"analysis_type": "Ladle",
                       "elements": _elems(C=0.15, Si=0.18, Mn=0.45, P=0.012,
                                          S=0.008, Cr=2.25, Mo=0.95)},
         "mechanical": mill_mech,
         "heat_treatment": [
             {"stage": "N", "temp_C": 900, "hold_min": 99, "cooling": "AC"},
             {"stage": "T", "temp_C": 730, "hold_min": 150, "cooling": "AC"}],
         "remarks": ["EN10204:2004 Type 3.1", "R/BAR HOT FORGING"]},
    ])
    _write_doctype(case_cache, "certA", {3: "MTC_FINISHED", 4: "MTC_RAW_MATERIAL"})


def _single_doc(pack: dict) -> dict:
    assert len(pack["mill_cert_runs"]) == 1
    docs = pack["mill_cert_runs"][0]["mill_docs"]
    assert len(docs) == 1
    return docs[0]


# --- T1: values_equal / trailing zero ---------------------------------------

def test_values_equal_trailing_zero_and_scale():
    assert values_equal("582.70", 582.7) is True          # AC-2 / T1
    assert values_equal(15, 0.15) is False                # AC-2
    assert values_equal(447.77, 447.77) is True
    assert values_equal(None, 1) is False
    assert values_equal("", "") is False
    assert values_equal("abc", 1) is False


# --- T2/T3: 배율 함정 가드 ---------------------------------------------------

def test_scale_suspect_x100_and_x1000():
    assert scale_suspect(0.15, 15) == 100                 # T2 (양방향)
    assert scale_suspect(15, 0.15) == 100
    assert scale_suspect(0.015, 15) == 1000               # T3
    assert scale_suspect(0.15, 0.15) is None              # 동일값
    assert scale_suspect(0, 0) is None                    # 0 값 제외
    assert scale_suspect(None, 15) is None
    assert scale_suspect(0.15, 0.16) is None


def test_compare_chemistry_scale_suspect_recorded():
    result = compare_chemistry(_elems(C=0.15), _elems(C=15))
    (rec,) = result["per_element"]
    assert rec["equal"] is False
    assert rec["scale_suspect"] == 100                    # T2


# --- T4/T5/T6/T7: 인장 상태기계 ----------------------------------------------

def test_tensile_partial_identical_two_of_four():        # T4 / AC-4
    mtc = {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94, "RA_pct": 75.64}
    mill = {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 28.0, "RA_pct": 70.0}
    result = compare_tensile(mtc, mill)
    assert result["n_reported"] == 4
    assert result["n_equal"] == 2
    assert result["state"] == "partial_identical"


def test_tensile_all_identical():                        # T5 (단위 수준)
    mech = {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94, "RA_pct": 75.64}
    result = compare_tensile(mech, dict(mech))
    assert result["state"] == "all_identical"
    assert result["n_reported"] == 4
    assert result["n_equal"] == 4


def test_tensile_single_coincidence_is_partial():        # T6 (n=1 보수 규칙)
    result = compare_tensile({"YS_MPa": 447.77}, {"YS_MPa": 447.77})
    assert result["n_reported"] == 1
    assert result["state"] == "partial_identical"


def test_tensile_insufficient_when_mill_absent():        # T7
    mtc = {"TS_MPa": 582.71, "YS_MPa": 447.77}
    assert compare_tensile(mtc, None)["state"] == "insufficient"
    assert compare_tensile(mtc, {})["state"] == "insufficient"


def test_tensile_distinct():
    mtc = {"TS_MPa": 582.71, "YS_MPa": 447.77}
    mill = {"TS_MPa": 590.0, "YS_MPa": 450.0}
    assert compare_tensile(mtc, mill)["state"] == "distinct"


# --- T8/T28/T29: 화학 공통 원소·동의어·CE류 ----------------------------------

def test_chemistry_one_sided_elements_not_compared():    # T8
    mtc = _elems(C=0.15, Si=0.18, Mn=0.45)
    mill = _elems(C=0.15, Si=0.18, Mn=0.45, Cu=0.02, Ni=0.05,
                  As=0.003, Sn=0.002, Sb=0.001)
    result = compare_chemistry(mtc, mill)
    assert {r["element"] for r in result["per_element"]} == {"C", "SI", "MN"}
    assert result["n_common"] == 3
    assert result["one_sided_elements"]["mill_only"] == ["AS", "CU", "NI", "SB", "SN"]
    assert result["one_sided_elements"]["mtc_only"] == []


def test_chemistry_element_alias_alt_to_al():            # T28 (G-M1)
    result = compare_chemistry(_elems(Al=0.025), _elems(Alt=0.025))
    (rec,) = result["per_element"]
    assert rec["element"] == "AL"
    assert rec["equal"] is True


def test_chemistry_ce_family_excluded():                 # T29 (G-M1)
    result = compare_chemistry(_elems(C=0.15, CEV=0.42, CEF=0.40),
                               _elems(C=0.15, CEV=0.42, CEF=0.40))
    assert {r["element"] for r in result["per_element"]} == {"C"}
    assert result["excluded_keys"] == ["CEF", "CEV"]


# --- T12/T13/T14: 단조품 술어 ------------------------------------------------

def test_is_forging_spec_regex_paths():
    assert is_forging("A182-F22 CL.3", "ASTM A182-F22 CL.3-2022a", [], None)["forging"] is True
    assert is_forging(None, "SA-105", [], None)["forging"] is True
    r = is_forging("Gr.B", "SA-106 Gr.B seamless pipe", [], None)   # T12
    assert r["forging"] is False
    assert r["basis"] == "단조 계열 근거 없음"


def test_is_forging_keyword_path():                      # T13
    r = is_forging(None, None, ["R/BAR HOT FORGING QUALITY"], None)
    assert r["forging"] is True
    assert r["basis"] == "remark keyword"


def test_is_forging_routing_path():                      # T14
    assert is_forging("SA-182 F22", None, [], _ROUTING)["forging"] is True   # csv도 regex도 가능
    assert is_forging("SA-182 F22", None, [], None)["forging"] is True       # regex 단독
    # 라우팅 경로 단독 검증: regex/keyword 불발 grade가 CSV로만 SA-182 라우팅.
    routing = [{"cert_grade_pattern": r"CUSTOMALLOY\s*X1", "asme_spec": "SA-182"}]
    r = is_forging("CUSTOMALLOY X1", None, [], routing)
    assert r["forging"] is True
    assert r["basis"] == "grade_routing: SA-182"


# --- T31: grade 라우팅 정규화 프로브 (C-H1) ----------------------------------

def test_grade_probe_normalisation():
    assert "SA-182 F22" in _grade_probe("ASTM A182-F22 CL.3-2022a")
    assert "SA-182 F22" in _grade_probe("A182 F22 CL3")
    assert _grade_probe(None) == ""


def test_grade_family_probe_and_one_sided_none():        # T31
    fam_mtc = _grade_family("A182-F22 CL.3", "ASTM A182-F22 CL.3-2022a", _ROUTING)
    fam_mill = _grade_family("A182 F22 CL3", None, _ROUTING)
    assert fam_mtc == "SA-182-F22"
    assert fam_mill == "SA-182-F22"
    assert _grade_family("UNROUTABLE-GRADE-999", None, _ROUTING) is None
    assert _grade_family("A182 F22", None, None) is None  # routing 부재 -> None


# --- T5/AC-3: 합성 PU2601564형 팩 통합 ---------------------------------------

def test_pack_pu2601564_form_all_identical(tmp_path):    # T5 / AC-3 / a5
    case_cache = tmp_path / "PU"
    _pu_case(case_cache)
    pack = build_mill_cert_pack("PU", tmp_path, routing=_ROUTING)
    assert pack["applicable"] is True
    doc = _single_doc(pack)
    assert doc["transcription_missing"] is False
    assert doc["en10204"] == {"found": True, "type": "3.1",
                              "verbatim": "EN10204:2004 Type 3.1"}   # T30
    (match,) = doc["matches"]
    assert match["tensile"]["state"] == "all_identical"
    assert match["tensile"]["n_reported"] == 4
    assert match["is_forging"]["forging"] is True
    assert match["linkage"]["heat_match"] is True
    assert match["linkage"]["grade_family_match"] is True            # T31
    assert match["linkage"]["mill_cert_no_match"] is True
    assert match["chemistry"]["n_diff"] == 0
    assert match["chemistry"]["n_common"] == 7
    # 보조근거: 경도·열처리 동일 (Info 전용 — FAIL 트리거 아님).
    assert match["aux"]["hardness"]["equal"] is True
    assert match["aux"]["heat_treatment"]["equal"] is True
    # 완제품 헤더 verbatim 동반 (G-H2).
    assert match["header"]["size_od_wt"] == "DN15 SW"
    assert match["header"]["quantity"] == 33
    assert match["header"]["mill_maker"] == "SeAH Besteel"
    # 팩 파일 기록 확인.
    out = case_cache / f"PU{MILL_CERT_SUFFIX}"
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8"))["applicable"] is True


# --- T9: MILL CERT 부재 ------------------------------------------------------

def test_pack_not_applicable_without_raw_material_run(tmp_path):   # T9
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1, "header": {"heat_no": "H100"}, "doc_type": "MTC_FINISHED"},
    ])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED"})
    pack = build_mill_cert_pack("C", tmp_path)
    assert pack["applicable"] is False
    assert pack["mill_cert_runs"] == []
    assert (case_cache / f"C{MILL_CERT_SUFFIX}").is_file()


def test_pack_extracted_absent_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        build_mill_cert_pack("C", tmp_path)


# --- T10/T11: heat 매칭 ------------------------------------------------------

def test_pack_heat_mismatch_unmatched(tmp_path):         # T10
    case_cache = tmp_path / "C"
    _pu_case(case_cache, mill_heat="B99999")
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    doc = _single_doc(pack)
    assert doc["matches"] == []
    assert doc["unmatched"] is True
    assert doc["same_stem_finished"] == [
        {"heat_no": "B14339", "grade": "A182-F22 CL.3"}]


def test_pack_heat_notation_variants_match(tmp_path):    # T11
    case_cache = tmp_path / "C"
    _pu_case(case_cache, mill_heat=" b14339 ")
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    doc = _single_doc(pack)
    assert len(doc["matches"]) == 1
    assert doc["matches"][0]["linkage"]["heat_match"] is True


# --- T15: legacy 최소 엔트리 -------------------------------------------------

def test_pack_legacy_minimal_entries_transcription_missing(tmp_path):   # T15
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1, "header": {"heat_no": "H100"}, "doc_type": "MTC_FINISHED"},
        {"page": 2, "header": {}, "doc_type": "MTC_RAW_MATERIAL",
         "remarks": ["문서 유형: 원자재 성적서(동봉 Mill Cert)"]},
    ])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL"})
    pack = build_mill_cert_pack("C", tmp_path)
    doc = _single_doc(pack)
    assert doc["transcription_missing"] is True
    assert doc["matches"] == []          # 비교 생략 (heat 미상)


# --- T16: 파손 JSON ----------------------------------------------------------

def test_pack_broken_json_skipped_with_issue(tmp_path):  # T16
    case_cache = tmp_path / "C"
    _pu_case(case_cache)
    (case_cache / "certB_extracted.json").write_text(
        '{"stem": "certB", "page_extraction": [', encoding="utf-8")
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    assert any("certB" in i for i in pack["issues"])
    assert len(_single_doc(pack)["matches"]) == 1        # 정상 stem은 계속 처리


# --- T17/T18: MILL CERT NO. 참조 ---------------------------------------------

def test_mill_cert_no_remark_fallback(tmp_path):         # T17
    case_cache = tmp_path / "C"
    _pu_case(case_cache, finished_mill_cert_no=None,
             finished_remarks=["MILL CERT NO.: 201404-004866"])
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    (match,) = _single_doc(pack)["matches"]
    assert match["linkage"]["mill_cert_no_ref"] == "201404-004866"
    assert match["linkage"]["mill_cert_no_match"] is True


def test_mill_cert_no_mismatch(tmp_path):                # T18
    case_cache = tmp_path / "C"
    _pu_case(case_cache, finished_mill_cert_no="999999-000001")
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    (match,) = _single_doc(pack)["matches"]
    assert match["linkage"]["mill_cert_no_match"] is False


def test_mill_cert_no_absent_is_null(tmp_path):          # 1-g N/A 행 근거
    case_cache = tmp_path / "C"
    _pu_case(case_cache, finished_mill_cert_no=None)
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    (match,) = _single_doc(pack)["matches"]
    assert match["linkage"]["mill_cert_no_ref"] is None
    assert match["linkage"]["mill_cert_no_match"] is None


# --- T24: H/P 채널 -----------------------------------------------------------

def test_chemistry_product_only_channel_excluded(tmp_path):   # T24
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1,
         "header": {"heat_no": "H1", "grade": "A182 F22"},
         "doc_type": "MTC_FINISHED",
         "chemistry": {"analysis_type": "Product",
                       "elements": _elems(C=0.14)}},
        {"page": 2,
         "header": {"heat_no": "H1", "cert_no": "M1"},
         "doc_type": "MTC_RAW_MATERIAL",
         "chemistry": {"analysis_type": "Ladle",
                       "elements": _elems(C=0.15)}},
    ])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL"})
    pack = build_mill_cert_pack("C", tmp_path)
    (match,) = _single_doc(pack)["matches"]
    assert match["chemistry"]["n_common"] == 0           # Product 단독 배제


def test_chemistry_product_falls_back_to_heat_page(tmp_path):
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1,
         "header": {"heat_no": "H1", "grade": "A182 F22"},
         "doc_type": "MTC_FINISHED",
         "chemistry": {"analysis_type": "Product", "elements": _elems(C=0.14)}},
        {"page": 2,
         "header": {"heat_no": "H1", "grade": "A182 F22"},
         "doc_type": "MTC_FINISHED",
         "chemistry": {"analysis_type": "Heat", "elements": _elems(C=0.15)}},
        {"page": 3,
         "header": {"heat_no": "H1", "cert_no": "M1"},
         "doc_type": "MTC_RAW_MATERIAL",
         "chemistry": {"analysis_type": "Ladle", "elements": _elems(C=0.15)}},
    ])
    _write_doctype(case_cache, "certA",
                   {1: "MTC_FINISHED", 2: "MTC_FINISHED", 3: "MTC_RAW_MATERIAL"})
    pack = build_mill_cert_pack("C", tmp_path)
    doc = _single_doc(pack)
    p1_match = next(m for m in doc["matches"] if m["page"] == 1)
    assert p1_match["chemistry"]["n_common"] == 1        # 같은 heat의 Heat 채널 폴백
    assert p1_match["chemistry"]["per_element"][0]["equal"] is True


# --- T25: 열처리·경도 보조 근거 ----------------------------------------------

def test_aux_heat_treatment_and_hardness(tmp_path):      # T25 / C-M3
    case_cache = tmp_path / "C"
    _pu_case(case_cache)
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    (match,) = _single_doc(pack)["matches"]
    ht = match["aux"]["heat_treatment"]
    assert ht["equal"] is True                           # (N 900/99)+(T 730/150), cooling 제외
    assert match["aux"]["hardness"]["equal"] is True     # 185 == 185 (스칼라)
    assert match["aux"]["hardness"]["mtc_unit"] == "HBW"
    assert match["aux"]["hardness"]["mill_unit"] == "HB"


def test_aux_heat_treatment_differs(tmp_path):           # T25 상이 케이스
    case_cache = tmp_path / "C"
    mill_mech = {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94,
                 "RA_pct": 75.64, "hardness": {"value": 190, "unit": "HB"}}
    _pu_case(case_cache, mill_mech=mill_mech)
    # mill 열처리 온도를 변조.
    jp = case_cache / "certA_extracted.json"
    data = json.loads(jp.read_text(encoding="utf-8"))
    data["page_extraction"][1]["heat_treatment"][0]["temp_C"] = 910
    jp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    pack = build_mill_cert_pack("C", tmp_path, routing=_ROUTING)
    (match,) = _single_doc(pack)["matches"]
    assert match["aux"]["heat_treatment"]["equal"] is False
    assert match["aux"]["hardness"]["equal"] is False    # 185 != 190


# --- T26: 다중 heat 단일 런 (G-H1) -------------------------------------------

def test_multi_heat_single_run_split(tmp_path):          # T26 / AC-14
    case_cache = tmp_path / "C"
    mech = {"TS_MPa": 500.0, "YS_MPa": 400.0}
    _write_extracted(case_cache, "certA", [
        # mill cert 런 p1-6: p1-2 heat A(+무헤더 p3), p4-6 heat B.
        {"page": 1, "header": {"heat_no": "HA", "cert_no": "MA"},
         "doc_type": "MTC_RAW_MATERIAL", "mechanical": mech},
        {"page": 2, "header": {"heat_no": "HA"}, "doc_type": "MTC_RAW_MATERIAL"},
        {"page": 3, "header": {}, "doc_type": "MTC_RAW_MATERIAL"},
        {"page": 4, "header": {"heat_no": "HB", "cert_no": "MB"},
         "doc_type": "MTC_RAW_MATERIAL", "mechanical": mech},
        {"page": 5, "header": {"heat_no": "HB"}, "doc_type": "MTC_RAW_MATERIAL"},
        {"page": 6, "header": {}, "doc_type": "MTC_RAW_MATERIAL"},
        # 완제품.
        {"page": 7, "header": {"heat_no": "HA", "grade": "G1"},
         "doc_type": "MTC_FINISHED", "mechanical": mech},
        {"page": 8, "header": {"heat_no": "HB", "grade": "G2"},
         "doc_type": "MTC_FINISHED", "mechanical": mech},
    ])
    _write_doctype(case_cache, "certA", {
        1: "MTC_RAW_MATERIAL", 2: "MTC_RAW_MATERIAL", 3: "MTC_RAW_MATERIAL",
        4: "MTC_RAW_MATERIAL", 5: "MTC_RAW_MATERIAL", 6: "MTC_RAW_MATERIAL",
        7: "MTC_FINISHED", 8: "MTC_FINISHED",
    })
    pack = build_mill_cert_pack("C", tmp_path)
    (run,) = pack["mill_cert_runs"]
    assert len(run["mill_docs"]) == 2
    doc_a, doc_b = run["mill_docs"]
    assert doc_a["pages"] == [1, 2, 3]                   # 무헤더 p3는 선행 doc 부속
    assert doc_b["pages"] == [4, 5, 6]
    assert [m["page"] for m in doc_a["matches"]] == [7]  # 각자 자기 heat만
    assert [m["page"] for m in doc_b["matches"]] == [8]


# --- T27: 동일 heat 다품목 (G-H2) --------------------------------------------

def test_same_heat_multi_item_page_matches(tmp_path):    # T27 / AC-15
    case_cache = tmp_path / "C"
    mech = {"TS_MPa": 500.0, "YS_MPa": 400.0}
    _write_extracted(case_cache, "certA", [
        {"page": 1, "header": {"heat_no": "HA", "grade": "G1",
                               "size_od_wt": "660*35.1mm", "quantity": 2},
         "doc_type": "MTC_FINISHED", "mechanical": mech},
        {"page": 2, "header": {"heat_no": "HA", "grade": "G1",
                               "size_od_wt": "660*40mm", "quantity": 3},
         "doc_type": "MTC_FINISHED", "mechanical": mech},
        {"page": 3, "header": {"heat_no": "HA", "cert_no": "MA"},
         "doc_type": "MTC_RAW_MATERIAL", "mechanical": mech},
    ])
    _write_doctype(case_cache, "certA",
                   {1: "MTC_FINISHED", 2: "MTC_FINISHED", 3: "MTC_RAW_MATERIAL"})
    pack = build_mill_cert_pack("C", tmp_path)
    doc = _single_doc(pack)
    assert [m["page"] for m in doc["matches"]] == [1, 2]  # 페이지별 레코드
    assert doc["matches"][0]["header"]["size_od_wt"] == "660*35.1mm"
    assert doc["matches"][1]["header"]["size_od_wt"] == "660*40mm"
    assert doc["matches"][0]["header"]["quantity"] == 2
    assert doc["matches"][1]["header"]["quantity"] == 3


# --- T30: EN10204 (C-H2) -----------------------------------------------------

def test_en10204_found_and_absent(tmp_path):             # T30
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1, "header": {"heat_no": "H1"}, "doc_type": "MTC_FINISHED"},
        {"page": 2, "header": {"heat_no": "H1", "cert_no": "M1"},
         "doc_type": "MTC_RAW_MATERIAL",
         "remarks": ["Inspection certificate EN10204:2004 Type 3.1"]},
    ])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL"})
    pack = build_mill_cert_pack("C", tmp_path)
    doc = _single_doc(pack)
    assert doc["en10204"]["found"] is True
    assert doc["en10204"]["type"] == "3.1"

    case_cache2 = tmp_path / "D"
    _write_extracted(case_cache2, "certA", [
        {"page": 1, "header": {"heat_no": "H1"}, "doc_type": "MTC_FINISHED"},
        {"page": 2, "header": {"heat_no": "H1", "cert_no": "M1"},
         "doc_type": "MTC_RAW_MATERIAL", "remarks": ["no type marking here"]},
    ])
    _write_doctype(case_cache2, "certA", {1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL"})
    pack2 = build_mill_cert_pack("D", tmp_path)
    assert _single_doc(pack2)["en10204"] == {
        "found": False, "type": None, "verbatim": None}


# --- T9 CLI: mill-cert 서브커맨드 --------------------------------------------

def _run_cli(monkeypatch, cache_root: Path, case_id: str) -> int:
    monkeypatch.setattr(cli, "CACHE_DIR", cache_root)
    return cli.main(["mill-cert", "--case", case_id])


def test_cli_mill_cert_no_run_exit0(tmp_path, monkeypatch, capsys):   # T9 / AC-8 / a4
    case_cache = tmp_path / "C"
    _write_extracted(case_cache, "certA", [
        {"page": 1, "header": {"heat_no": "H100"}, "doc_type": "MTC_FINISHED"},
    ])
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED"})
    assert _run_cli(monkeypatch, tmp_path, "C") == 0
    out = capsys.readouterr().out
    assert "applicable=false" in out
    pack = json.loads((case_cache / f"C{MILL_CERT_SUFFIX}").read_text(encoding="utf-8"))
    assert pack["applicable"] is False


def test_cli_mill_cert_applicable_exit0(tmp_path, monkeypatch, capsys):
    case_cache = tmp_path / "PU"
    _pu_case(case_cache)
    assert _run_cli(monkeypatch, tmp_path, "PU") == 0
    out = capsys.readouterr().out
    assert "applicable=true" in out


def test_cli_mill_cert_missing_extracted_exit1(tmp_path, monkeypatch, capsys):
    assert _run_cli(monkeypatch, tmp_path, "NOPE") == 1
    assert "[ERROR] mill-cert" in capsys.readouterr().err
