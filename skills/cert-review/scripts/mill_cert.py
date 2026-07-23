"""mill_cert.py — 기준 21/22 deterministic MILL CERT cross-comparison pack.

Builds ``<case>_mill_cert.json``, the single deterministic input for the
mill-cert-reviewer agent (기준 21 verification/linkage, 기준 22 cross-compare).
Joins the Phase 1.6 ``MTC_RAW_MATERIAL`` runs (doctype sidecars) against the
fully-transcribed mill-cert page entries in ``*_extracted.json`` and the
finished-product INCLUDED pages, then computes — deterministically, no
judgement — per-match linkage (heat / MILL CERT NO. reference / grade family),
the forging predicate, the tensile identity state machine (규칙 22.2) and the
common-element chemistry comparison (규칙 22.1). The agent narrates verdicts
and findings from this pack; the verdict mapping table lives in
``references/review-criteria.md`` 기준 21/22 and ``agents/mill-cert-reviewer.md``.

Matching is exact string equality after normalisation (whitespace stripped,
upper-cased) — no fuzzy matching (attachments idiom). Numeric identity is exact
Decimal equality after ``str()`` normalisation — no tolerance. The tensile state
machine is conservative: a single coincidental match (n=1, k=1) is
``partial_identical`` (주의), never ``all_identical`` (FAIL basis).

Constants below (``_FORGING_ASME_SPECS``, ``TENSILE_PROPS``,
``_ELEMENT_ALIASES``, ``_CE_FAMILY``) are classification/field-name constants,
NOT numeric limit values — C8 (no hard-coded limits) is not implicated.

Constraint C1: JSON reading only (no OCR). Constraint C7: pathlib + utf-8.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from scripts.attachments import _norm_heat
from scripts.compare_engine import _grade_route, _resolve_grade_keys
from scripts.doctype import (
    compress_pages,
    excluded_documents_for_case,
    excluded_pages_map,
)

MILL_CERT_SUFFIX = "_mill_cert.json"

# extraction-schema.json mechanical property keys — order mirrors the schema's
# narrative order; the set (not the order) drives the 규칙 22.2 state machine.
TENSILE_PROPS = ("TS_MPa", "YS_MPa", "EL_pct", "RA_pct")

# 단조 계열 술어 (분류 상수 — 수치 한계 아님, C8 비저촉. grade_routing.csv
# asme_spec 열과 동기: 단조 spec은 SA-105 / SA-182 뿐).
_FORGING_SPEC_RE = re.compile(r"\bS?A\s*-?\s*(?:105|182)\b", re.IGNORECASE)
_FORGING_ASME_SPECS = frozenset({"SA-105", "SA-182"})
_FORGING_KEYWORD_RE = re.compile(r"FORG(?:ING|ED)", re.IGNORECASE)
_MILL_CERT_NO_RE = re.compile(
    r"MILL\s*CERT(?:IFICATE)?\.?\s*NO\.?\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9\-/\.]*)",
    re.IGNORECASE)
_EN10204_RE = re.compile(
    r"EN\s*-?\s*10204(?:\s*[:：]\s*\d{4})?\s*(?:TYPE)?\s*(3\.1|3\.2|2\.1|2\.2)",
    re.IGNORECASE)
_SCALE_FACTORS = (100, 1000)
# 원소 키 동의어 정규화 (실측 근거: case 53 완제품 "Al" vs mill "Alt") —
# 확장 가능 최소 테이블.
_ELEMENT_ALIASES = {"ALT": "AL", "SOLAL": "AL", "SAL": "AL"}
# 탄소당량류는 측정 원소가 아닌 산출값 — per-element 비교에서 제외.
_CE_FAMILY = frozenset({"CE", "CEV", "CEQ", "CEF", "PCM", "CEIIW"})

_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")


# ---------------------------------------------------------------------------
# 수치 동일성 술어 (결정적 정의)
# ---------------------------------------------------------------------------

def _dec(v) -> Decimal | None:
    """number/str -> Decimal(str(v)); None/''/변환불가 -> None."""
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def values_equal(a, b) -> bool:
    """정규화 후 Decimal 정확 일치. 양쪽 non-None일 때만 True 가능.

    trailing zero: JSON number 582.70은 float 582.7로 파싱돼 자동 동치,
    문자열 '582.70' 입력도 Decimal('582.70') == Decimal('582.7') → True.
    허용오차 없음 — 정확 일치만 "동일".
    """
    da, db = _dec(a), _dec(b)
    return da is not None and db is not None and da == db


def scale_suspect(mtc_v, mill_v) -> int | None:
    """한쪽이 다른 쪽의 정확히 ×100/×1000 (양방향)이면 해당 배율 반환, 아니면 None.

    0 값 제외 (0×100 == 0은 배율 함정이 아니라 동일값).
    """
    da, db = _dec(mtc_v), _dec(mill_v)
    if da is None or db is None or da == 0 or db == 0:
        return None
    for factor in _SCALE_FACTORS:
        if da * factor == db or db * factor == da:
            return factor
    return None


# ---------------------------------------------------------------------------
# 단조품 술어 (결정적 정의)
# ---------------------------------------------------------------------------

def _joined_text(remarks) -> str:
    """remarks(list[str] | str | None) -> 결합 문자열."""
    if remarks is None:
        return ""
    if isinstance(remarks, str):
        return remarks
    return " ".join(str(r) for r in remarks)


def is_forging(grade, spec, remarks, routing=None) -> dict:
    """{"forging": bool, "basis": str}. 판정 순서(첫 매치 채택):

    1) (spec or '')+' '+(grade or '') 에 _FORGING_SPEC_RE 매치 -> basis "spec: <매치>"
    2) remarks 결합 문자열에 _FORGING_KEYWORD_RE -> basis "remark keyword"
    3) routing 제공 시 _grade_route를 정규화 프로브(_grade_probe)로 시도,
       asme_spec ∈ _FORGING_ASME_SPECS
    4) 불발 -> {"forging": False, "basis": "단조 계열 근거 없음"}
    """
    combined = f"{spec or ''} {grade or ''}"
    m = _FORGING_SPEC_RE.search(combined)
    if m:
        return {"forging": True, "basis": f"spec: {m.group(0)}"}
    if _FORGING_KEYWORD_RE.search(_joined_text(remarks)):
        return {"forging": True, "basis": "remark keyword"}
    if routing:
        for cand in (grade, spec, _grade_probe(grade), _grade_probe(spec)):
            if not cand:
                continue
            routed = _grade_route(cand, routing)
            if routed and (routed.get("asme_spec") or "").strip() in _FORGING_ASME_SPECS:
                return {
                    "forging": True,
                    "basis": f"grade_routing: {(routed.get('asme_spec') or '').strip()}",
                }
    return {"forging": False, "basis": "단조 계열 근거 없음"}


# ---------------------------------------------------------------------------
# 인장 교차비교 상태기계 (규칙 22.2)
# ---------------------------------------------------------------------------

def compare_tensile(mtc_mech, mill_mech) -> dict:
    """규칙 22.2 상태기계.

    경계 확정: n=1·k=1은 "전체 동일"이 아니라 partial_identical(주의) —
    단일 우연 일치 FAIL 방지 보수 규칙. 비단조품은 state 무관 FAIL/주의 금지
    (판정 매핑표 — review-criteria.md 기준 22.2).
    """
    per = []
    for p in TENSILE_PROPS:
        a = (mtc_mech or {}).get(p)
        b = (mill_mech or {}).get(p)
        both = a is not None and b is not None
        per.append({"property": p, "mtc": a, "mill": b, "both_reported": both,
                    "equal": values_equal(a, b) if both else None})
    n = sum(1 for r in per if r["both_reported"])
    k = sum(1 for r in per if r["equal"])
    if n == 0:
        state = "insufficient"       # -> 기준 22.2 N/A
    elif k == n and n >= 2:
        state = "all_identical"      # 단조품이면 FAIL 근거
    elif k >= 1:
        state = "partial_identical"  # 단조품이면 주의 (n==1&k==1 포함)
    else:
        state = "distinct"           # PASS
    return {"per_property": per, "n_reported": n, "n_equal": k, "state": state}


# ---------------------------------------------------------------------------
# 화학 교차비교 (규칙 22.1)
# ---------------------------------------------------------------------------

def _norm_element_key(key) -> str:
    """원소 키 정규화: upper + 비영숫자 제거 후 _ELEMENT_ALIASES 적용."""
    norm = _NON_ALNUM_RE.sub("", str(key).upper())
    return _ELEMENT_ALIASES.get(norm, norm)


def _reported_elements(elems) -> dict[str, object]:
    """elements dict -> {정규화 키: value} (value non-None만). CE류 제외 키는
    별도 수집을 위해 여기서는 걸러내지 않는다 — 호출부에서 분리."""
    out: dict[str, object] = {}
    for key, rec in (elems or {}).items():
        if not isinstance(rec, dict):
            continue
        value = rec.get("value")
        if value is None:
            continue
        out.setdefault(_norm_element_key(key), value)
    return out


def compare_chemistry(mtc_elems, mill_elems) -> dict:
    """elements dict(extraction-schema.json) 교차비교 (규칙 22.1).

    키 정규화: upper + 비영숫자 제거 후 _ELEMENT_ALIASES 적용. _CE_FAMILY 키는
    비교 제외 -> excluded_keys에 기록. 공통 원소(정규화 키 교집합, value 양쪽
    non-None)만 per_element에. 편측 원소는 비교하지 않되 one_sided_elements로
    노출(정보성 — 판정 비사용, 리뷰어 note 전용).
    """
    mtc = _reported_elements(mtc_elems)
    mill = _reported_elements(mill_elems)

    excluded_keys = sorted(k for k in (set(mtc) | set(mill)) if k in _CE_FAMILY)
    mtc = {k: v for k, v in mtc.items() if k not in _CE_FAMILY}
    mill = {k: v for k, v in mill.items() if k not in _CE_FAMILY}

    common = sorted(set(mtc) & set(mill))
    per_element = []
    n_equal = 0
    for element in common:
        a, b = mtc[element], mill[element]
        equal = values_equal(a, b)
        if equal:
            n_equal += 1
        per_element.append({
            "element": element,
            "mtc": a,
            "mill": b,
            "equal": equal,
            "scale_suspect": scale_suspect(a, b),
        })
    return {
        "per_element": per_element,
        "n_common": len(common),
        "n_equal": n_equal,
        "n_diff": len(common) - n_equal,
        "one_sided_elements": {
            "mtc_only": sorted(set(mtc) - set(mill)),
            "mill_only": sorted(set(mill) - set(mtc)),
        },
        "excluded_keys": excluded_keys,
    }


# ---------------------------------------------------------------------------
# grade 계열 비교 (라우팅 정규화 프로브)
# ---------------------------------------------------------------------------

def _grade_probe(s: str | None) -> str:
    """라우팅용 정규화 프로브: upper 후

    (1) S 미선행 'A<3자리>' -> 'SA-<3자리>'  (예: 'ASTM A182-F22' -> 'ASTM SA-182-F22')
    (2) 숫자-하이픈-영문 경계 -> 공백        ('SA-182-F22' -> 'SA-182 F22')
    -> grade_routing.csv 패턴('SA-?182\\s*F22')이 매치 가능해짐.
    """
    if not s:
        return ""
    out = str(s).upper()
    out = re.sub(r"\b(?<!S)A\s*-?\s*(\d{3})", r"SA-\1", out)
    out = re.sub(r"(\d)-([A-Z])", r"\1 \2", out)
    return out


def _grade_family(grade, spec, routing) -> str | None:
    """후보 [grade, spec, _grade_probe(grade), _grade_probe(spec)] 순으로
    _grade_route 시도. routed되면 keys = _resolve_grade_keys(routed, <해당 후보>)
    후 keys[0] 반환 (keys 비면 None — IndexError 가드). 전부 불발 -> None.
    """
    if not routing:
        return None
    for cand in (grade, spec, _grade_probe(grade), _grade_probe(spec)):
        if not cand:
            continue
        routed = _grade_route(cand, routing)
        if routed:
            keys = _resolve_grade_keys(routed, cand)
            return keys[0] if keys else None
    return None


# ---------------------------------------------------------------------------
# 팩 빌더 내부 도우미
# ---------------------------------------------------------------------------

def _norm_token(v) -> str | None:
    """cert_no류 토큰 정규화: 공백 제거 + 대문자. 빈 값 -> None."""
    norm = _norm_heat(v)
    return norm or None


def _first_non_null(values):
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def _entry_has_table_data(entry: dict) -> bool:
    """페이지 엔트리에 표 데이터(chemistry elements / mechanical / HT)가 있는가."""
    chem = entry.get("chemistry") or {}
    if isinstance(chem, dict) and (chem.get("elements") or {}):
        return True
    if entry.get("mechanical"):
        return True
    if entry.get("heat_treatment"):
        return True
    return False


def _ht_normalized(stages) -> list[dict]:
    """열처리 단계 정규화: stage_norm("NORM" 포함 또는 N 시작→"N", "TEMPER" 포함
    또는 T 시작→"T", 그 외 대문자 verbatim) + temp_C + hold_min. cooling은 비교
    제외·보존."""
    out: list[dict] = []
    for st in stages or []:
        if not isinstance(st, dict):
            continue
        stage = str(st.get("stage") or "").upper()
        if "NORM" in stage or stage.startswith("N"):
            stage_norm = "N"
        elif "TEMPER" in stage or stage.startswith("T"):
            stage_norm = "T"
        else:
            stage_norm = stage
        out.append({
            "stage_norm": stage_norm,
            "temp_C": st.get("temp_C"),
            "hold_min": st.get("hold_min"),
            "cooling": st.get("cooling"),
        })
    return out


def _ht_key_set(normalized: list[dict]) -> frozenset:
    """(stage_norm, temp_C, hold_min) 튜플 집합 — Decimal 정규화로 900/900.0 동치."""
    return frozenset(
        (st["stage_norm"], _dec(st["temp_C"]), _dec(st["hold_min"]))
        for st in normalized
    )


def _en10204_scan(text: str) -> dict:
    """결합 문자열에서 EN10204 타입 표기 추출 (정보성 — D10)."""
    m = _EN10204_RE.search(text)
    if m:
        return {"found": True, "type": m.group(1), "verbatim": m.group(0)}
    return {"found": False, "type": None, "verbatim": None}


class _MillDoc:
    """런 내부 서브그룹(단일 mill cert 문서) 누적기."""

    def __init__(self, page: int):
        self.pages: list[int] = [page]
        self.heat_key: str | None = None
        self.cert_key: str | None = None
        self.entries: list[dict] = []


def _split_run_into_docs(pages: list[int], stem_entries: dict[int, dict],
                         issues: list[str], stem: str) -> list[_MillDoc]:
    """[G-H1] 런 -> mill_docs 서브그룹 분할 (heat_no/cert_no 변화 기준).

    _group_runs는 연속 동일 라벨을 1런으로 묶으므로 혼합 제강사·복수 heat가
    단일 런이 될 수 있다(실측: PU2601233 p15-50 36p 단일런). 페이지 헤더의
    heat/cert 키 변화에서 새 doc을 시작하고, 무헤더 연속 페이지는 현재 doc에
    부속시킨다.
    """
    docs: list[_MillDoc] = []
    cur: _MillDoc | None = None
    for page in sorted(pages):
        entry = stem_entries.get(page)
        if entry is None:
            issues.append(f"{stem}: mill cert page {page} has no extracted entry (skipped)")
            continue
        header = entry.get("header") or {}
        heat_k = _norm_heat(header.get("heat_no")) if header.get("heat_no") else None
        cert_k = _norm_token(header.get("cert_no")) if header.get("cert_no") else None
        new = (cur is None) \
            or bool(heat_k and cur.heat_key and heat_k != cur.heat_key) \
            or bool(cert_k and cur.cert_key and cert_k != cur.cert_key)
        if new:
            cur = _MillDoc(page)
            docs.append(cur)
        else:
            cur.pages.append(page)
        cur.heat_key = cur.heat_key or heat_k
        cur.cert_key = cur.cert_key or cert_k
        cur.entries.append(entry)
    return docs


def _doc_record(doc: _MillDoc) -> dict:
    """mill_doc 레코드 산출 (첫 non-null header/표 필드 + 전 페이지 remarks 결합).

    한계: 1페이지에 복수 heat가 인쇄된 판재형 mill cert는 header 단일 필드
    특성상 대표 heat만 실린다 — 후속 과제 (revision 문서 기재).
    """
    headers = [e.get("header") or {} for e in doc.entries]
    remarks: list[str] = []
    for e in doc.entries:
        remarks.extend(str(r) for r in (e.get("remarks") or []))

    chemistry = _first_non_null(
        e.get("chemistry") for e in doc.entries
        if isinstance(e.get("chemistry"), dict) and (e.get("chemistry") or {}).get("elements")
    )
    mechanical = _first_non_null(e.get("mechanical") for e in doc.entries)
    heat_treatment = _first_non_null(e.get("heat_treatment") for e in doc.entries)
    hardness = _first_non_null(
        (e.get("mechanical") or {}).get("hardness") for e in doc.entries
    )

    header_text = " ".join(
        str(v) for h in headers for v in h.values() if isinstance(v, str)
    )
    en10204 = _en10204_scan(" ".join(remarks) + " " + header_text)

    transcription_missing = all(
        not (e.get("header") or {}) and not _entry_has_table_data(e)
        for e in doc.entries
    )

    return {
        "cert_no": _first_non_null(h.get("cert_no") for h in headers),
        "vendor": _first_non_null(h.get("vendor") for h in headers),
        "heat_no": _first_non_null(h.get("heat_no") for h in headers),
        "grade": _first_non_null(h.get("grade") for h in headers),
        "spec": _first_non_null(h.get("spec") for h in headers),
        "chemistry": chemistry,
        "mechanical": mechanical,
        "heat_treatment": heat_treatment,
        "hardness": hardness,
        "remarks": remarks,
        "pages": list(doc.pages),
        "page_range": compress_pages(doc.pages),
        "en10204": en10204,
        "transcription_missing": transcription_missing,
    }


def _mtc_heat_elements(entry: dict, heat_key: str | None,
                       finished_pages: list[tuple[str, int, dict]]) -> dict:
    """MTC 채널 규칙: analysis_type ∈ {"Heat","Heat+Product",None} 페이지의
    elements만. "Product" 단독이면 같은 heat의 다른 INCLUDED 페이지 중 Heat
    채널 페이지를 탐색, 없으면 {} (n_common=0)."""
    chem = entry.get("chemistry") or {}
    if not isinstance(chem, dict):
        return {}
    if chem.get("analysis_type") != "Product":
        return chem.get("elements") or {}
    for _stem, _page, other in finished_pages:
        if other is entry:
            continue
        header = other.get("header") or {}
        if _norm_heat(header.get("heat_no")) != (heat_key or ""):
            continue
        other_chem = other.get("chemistry") or {}
        if not isinstance(other_chem, dict):
            continue
        if other_chem.get("analysis_type") in ("Heat", "Heat+Product") \
                and (other_chem.get("elements") or {}):
            return other_chem["elements"]
    return {}


_MATCH_HEADER_FIELDS = (
    "grade", "spec", "heat_no", "size_od_wt", "quantity", "po_number",
    "cert_no", "mill_cert_no", "mill_maker", "starting_material",
)


def _build_match(stem: str, page: int, entry: dict, doc_rec: dict,
                 heat_key: str | None,
                 finished_pages: list[tuple[str, int, dict]],
                 routing) -> dict:
    """[G-H2] 매칭 완제품 페이지 1개당 1 match 레코드 (헤더 verbatim 동반)."""
    header = entry.get("header") or {}
    page_remarks = [str(r) for r in (entry.get("remarks") or [])]

    # linkage: heat(매칭 자체) + MILL CERT NO. 참조 + grade 계열.
    ref = header.get("mill_cert_no")
    if ref in (None, ""):
        ref = None
        for r in page_remarks:
            m = _MILL_CERT_NO_RE.search(r)
            if m:
                ref = m.group(1)
                break
    doc_cert_key = _norm_token(doc_rec.get("cert_no"))
    if ref is None:
        mill_cert_no_match = None
    elif doc_cert_key is None:
        mill_cert_no_match = None  # 편측 불발 — 판정 불가 (grade_family와 동일 패턴)
    else:
        mill_cert_no_match = _norm_token(ref) == doc_cert_key

    fam_mtc = _grade_family(header.get("grade"), header.get("spec"), routing)
    fam_mill = _grade_family(doc_rec.get("grade"), doc_rec.get("spec"), routing)
    grade_family_match = (fam_mtc == fam_mill) if (fam_mtc and fam_mill) else None

    linkage = {
        "heat_match": True,
        "mill_cert_no_ref": ref,
        "mill_cert_no_match": mill_cert_no_match,
        "grade_family_mtc": fam_mtc,
        "grade_family_mill": fam_mill,
        "grade_family_match": grade_family_match,
    }

    forging = is_forging(
        header.get("grade"), header.get("spec"),
        page_remarks + list(doc_rec.get("remarks") or []), routing,
    )

    mtc_elems = _mtc_heat_elements(entry, heat_key, finished_pages)
    mill_chem = doc_rec.get("chemistry") or {}
    mill_elems = mill_chem.get("elements") or {} if isinstance(mill_chem, dict) else {}
    chemistry = compare_chemistry(mtc_elems, mill_elems)

    tensile = compare_tensile(entry.get("mechanical"), doc_rec.get("mechanical"))

    # aux — 보조 근거 (FAIL 트리거 아님, Info/note 전용).
    mtc_hard = ((entry.get("mechanical") or {}).get("hardness") or {})
    mill_hard = ((doc_rec.get("mechanical") or {}).get("hardness") or {})
    mtc_h = mtc_hard.get("value")   # dict 직접 비교 금지 — 스칼라 추출 (C-M3)
    mill_h = mill_hard.get("value")
    hardness = {
        "mtc": mtc_h,
        "mill": mill_h,
        "mtc_unit": mtc_hard.get("unit"),
        "mill_unit": mill_hard.get("unit"),
        "equal": values_equal(mtc_h, mill_h)
        if (mtc_h is not None and mill_h is not None) else None,
    }

    ht_mtc = _ht_normalized(entry.get("heat_treatment"))
    ht_mill = _ht_normalized(doc_rec.get("heat_treatment"))
    ht_equal = (_ht_key_set(ht_mtc) == _ht_key_set(ht_mill)) \
        if (ht_mtc and ht_mill) else None
    aux = {
        "hardness": hardness,
        "heat_treatment": {"mtc": ht_mtc, "mill": ht_mill, "equal": ht_equal},
    }

    return {
        "stem": stem,
        "page": page,
        "header": {f: header.get(f) for f in _MATCH_HEADER_FIELDS},
        "linkage": linkage,
        "is_forging": forging,
        "chemistry": chemistry,
        "tensile": tensile,
        "aux": aux,
    }


# ---------------------------------------------------------------------------
# 팩 빌더
# ---------------------------------------------------------------------------

def build_mill_cert_pack(case_id: str, cache_root: Path,
                         routing: list[dict] | None = None) -> dict:
    """기준 21/22 교차비교 팩을 계산해 ``<case>_mill_cert.json``으로 기록.

    Returns a dict:
        {
          "schema_version": "1.0",
          "case_id": str,
          "applicable": bool,        # MTC_RAW_MATERIAL 런 존재 여부 (위임 조건)
          "mill_cert_runs": [
            {"stem", "pages", "page_range",
             "mill_docs": [
               {cert_no, vendor, heat_no, grade, spec, chemistry, mechanical,
                heat_treatment, hardness, remarks, pages, page_range, en10204,
                transcription_missing,
                matches: [{stem, page, header, linkage, is_forging,
                           chemistry, tensile, aux}, ...],
                unmatched?, same_stem_finished?},
               ...]},
            ...],
          "issues": [str, ...],
          "output_path": str,
        }

    Raises FileNotFoundError when the case has no ``*_extracted.json`` (run
    prep-inputs + Phase-2 first) — same idiom as attachments.build_attachments_pack.
    MTC_RAW_MATERIAL 런 0건은 오류가 아니다: ``applicable: false`` 팩을 기록하고
    정상 반환한다 (CLI exit 0).
    """
    cache_root = Path(cache_root)
    case_cache = cache_root / str(case_id)
    extracted_files = sorted(case_cache.glob("*_extracted.json"))
    if not extracted_files:
        raise FileNotFoundError(
            f"no *_extracted.json in {case_cache} (run prep-inputs + Phase-2 first)"
        )

    issues: list[str] = []

    # 전 stem의 page 엔트리 로딩 (파손 JSON은 관용적 skip + issues).
    entries_by_stem: dict[str, dict[int, dict]] = {}
    for jp in extracted_files:
        stem = jp.name[: -len("_extracted.json")]
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            issues.append(f"unreadable extracted JSON skipped: {jp.name}")
            continue
        if not isinstance(data, dict):
            issues.append(f"non-dict extracted JSON skipped: {jp.name}")
            continue
        pages: dict[int, dict] = {}
        for entry in data.get("page_extraction") or []:
            if not isinstance(entry, dict):
                continue
            try:
                page_no = int(entry.get("page"))
            except (TypeError, ValueError):
                continue
            pages[page_no] = entry
        entries_by_stem[stem] = pages

    raw_runs = [
        rec for rec in excluded_documents_for_case(case_cache)
        if rec.get("doc_type") == "MTC_RAW_MATERIAL"
    ]

    # 완제품 측: INCLUDED + heat_no 보유 페이지 인덱스 (attachments 관용구).
    finished_pages: list[tuple[str, int, dict]] = []
    for stem in sorted(entries_by_stem):
        excluded = excluded_pages_map(case_cache, stem)
        for page_no in sorted(entries_by_stem[stem]):
            if page_no in excluded:
                continue
            entry = entries_by_stem[stem][page_no]
            header = entry.get("header") or {}
            if header.get("heat_no") in (None, ""):
                continue
            finished_pages.append((stem, page_no, entry))

    mill_cert_runs: list[dict] = []
    for rec in raw_runs:
        stem = rec.get("stem", "")
        run_pages = [int(p) for p in (rec.get("pages") or [])]
        stem_entries = entries_by_stem.get(stem, {})
        docs = _split_run_into_docs(run_pages, stem_entries, issues, stem)

        mill_docs: list[dict] = []
        for doc in docs:
            doc_rec = _doc_record(doc)
            matches: list[dict] = []
            if doc.heat_key:
                for f_stem, f_page, f_entry in finished_pages:
                    f_header = f_entry.get("header") or {}
                    if _norm_heat(f_header.get("heat_no")) != doc.heat_key:
                        continue
                    matches.append(_build_match(
                        f_stem, f_page, f_entry, doc_rec, doc.heat_key,
                        finished_pages, routing,
                    ))
            doc_rec["matches"] = matches
            if not matches:
                doc_rec["unmatched"] = True
                seen: set[tuple[str, str]] = set()
                same_stem: list[dict] = []
                for f_stem, _f_page, f_entry in finished_pages:
                    if f_stem != stem:
                        continue
                    f_header = f_entry.get("header") or {}
                    pair = (str(f_header.get("heat_no") or ""),
                            str(f_header.get("grade") or ""))
                    if pair in seen:
                        continue
                    seen.add(pair)
                    same_stem.append({"heat_no": pair[0], "grade": pair[1]})
                doc_rec["same_stem_finished"] = same_stem
            mill_docs.append(doc_rec)

        mill_cert_runs.append({
            "stem": stem,
            "pages": run_pages,
            "page_range": rec.get("page_range", ""),
            "mill_docs": mill_docs,
        })

    pack = {
        "schema_version": "1.0",
        "case_id": str(case_id),
        "applicable": bool(mill_cert_runs),
        "mill_cert_runs": mill_cert_runs,
        "issues": issues,
    }

    output_path = case_cache / f"{case_id}{MILL_CERT_SUFFIX}"
    case_cache.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pack["output_path"] = str(output_path).replace("\\", "/")
    return pack


__all__ = [
    "MILL_CERT_SUFFIX",
    "values_equal",
    "scale_suspect",
    "is_forging",
    "compare_tensile",
    "compare_chemistry",
    "build_mill_cert_pack",
]
