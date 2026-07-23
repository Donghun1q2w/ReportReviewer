# 동봉 원자재 성적서(MILL CERT) 검증 도메인·에이전트 추가(기준 21/22) — 구현 계획

- **작성**: 2026-07-23 18:37 (전담 플래닝 에이전트, Fable 5, dh-dev Step 1-d — 적대 검증 1회 반영판)
- **상태**: Completed (커밋 008b357, pytest 280/280, DoD-a 10/10 + DoD-b E2E 5/5 — PU2601564 규칙 22.2 FAIL 재현·22.1 무주의·렌더 assert 통과)
- **대상**: `plugin/ReportReviewer` (단일 소스, `git@github.com:Donghun1q2w/ReportReviewer.git`, main). 스킬 디렉토리 = `skills/cert-review/` (이하 SKILL_DIR). 이하 경로는 특기 없으면 SKILL_DIR 기준.
- **동인**: `testbed/1. Standard Inspection/ref/PU2601564.pdf` 실측 — 단조 엘보(A182-F22 CL.3) MTC(p3)의 인장 4값(YS 447.77/TS 582.71/EL 30.94/RA 75.64)이 동봉 SeAH MILL CERT(p4)와 소수점 둘째 자리까지 완전 동일(완제품 시험 미실시·전사 복제 의심 사례). 사용자 요구 3건: (1) MILL CERT 별도 분류·검증 에이전트, (2) 화학성분 불일치 시 '주의', (3) 단조품 인장 동일 시 FAIL.
- **적대 검증**: contrarian/gap_hunter 2레인 완료 — 발견 24건(HIGH 8·MEDIUM 10·LOW 6) 전건 반영, 미해소 0건. 처분표는 아래.

## 검증 발견 처분표

| ID | 처분 | 반영 위치 (요지) |
|---|---|---|
| C-H1 | 반영 | 1-i `_grade_family`에 "A<3자리>→SA-<3자리>" + "숫자-하이픈-영문→공백" 정규화 프로브 추가, 1-g에 `grade_family_match=None → N/A` 행 신설, T31. `is_forging` CSV 경로에도 동일 프로브 |
| C-H2 | 반영(정보성 축소로 확정) | 1-h 팩에 `en10204` 결정적 필드(regex) 신설, 1-g에 found→PASS/미검출→N/A(무 finding) 행 신설, 기준 21.3 문구 확정, T30 |
| G-H1 | 반영 | 1-h step 3을 "런 → heat_no/cert_no 변화 기준 mill_docs[] 서브그룹 분할" 알고리즘으로 교체(PU2601233 p15-50 실측 36p 단일런 재확인), T26 |
| G-H2 | 반영 | 1-h step 4-5를 "매칭 완제품 페이지별 match 레코드" 방식으로 변경(헤더 verbatim 동반), Step 7 material 산출 규칙 보강, T27 |
| G-H3 | 반영 | Step 7 Input Artifacts에 "매칭 완제품 페이지의 extracted 엔트리(header+remarks)에서 item_name/size/qty verbatim 확보" 절차 명시 + crop 권한을 "scale_suspect 원소 + 병합 키 결정 셀"로 확장 확정 |
| G-H4 | 반영 | Step 12 신설: `docs/revisions/` 문서 + `docs/revision_history.md` 색인. 계획서의 docs/plans 저장은 오케스트레이터 몫임을 명기 |
| G-H5 | 반영 | Step 10에 README.md 갱신(실측 라인 기반) 추가, DoD-a8 grep 대상에 README 포함 |
| G-H6 | 반영 | 인용 정정(원형은 tests/test_attachments.py:25-37) + 6절에 mill_cert 전용 `_write_extracted` 최소 스키마 코드블록 명시 |
| C-M1 | 반영 | Step 3.6 정정: merge_reviews.py L3-4·L6-7·L17-23(INVARIANT)·L18 |
| C-M2 | 반영 | 편집 범위 확장(SKILL.md L3/L378/L380/L384/L395-396, compliance_report.py:1, merge_reviews.py:18) + DoD-a8에 `6-sheet|6시트` 잔존 grep |
| C-M3 | 반영 | 1-h aux.hardness를 `.get("value")` 스칼라 추출로 명시 |
| C-M4 | 반영 | Phase 4-2 문구 확정: 5 리뷰어와 같은 단일 메시지 병렬(케이스당 최대 6, 총 캡 6–10 내) |
| C-M5 | 반영 | `_grade_family` 반환 `keys[0] if keys else None` 가드 |
| C-M6 | 반영(유지+사용처 확정) | mill_maker/starting_material은 match.header verbatim → 리뷰어 note 서술 전용(판정·fuzzy 매칭 금지) |
| G-M1 | 반영 | `_ELEMENT_ALIASES`(ALT→AL 등) + CE류 비교 제외 `excluded_keys` + `one_sided_elements` 노출, T28/T29 |
| G-M2 | 반영 | 커밋 예시를 본문+Co-Authored-By+Claude-Session 트레일러 형식으로 교체 |
| G-M3 | 반영 | 6절 표에 T32(문서 grep)·T33(git diff) 비-pytest 검증 행 추가 |
| G-M4 | 반영 | DoD-b4를 openpyxl 인라인 assert(이진)로 대체 |
| C-L1 | 반영 | `TENSILE_PROPS = ("TS_MPa","YS_MPa","EL_pct","RA_pct")` |
| C-L2 | 반영 | schema_version const 위치 L10 정정 |
| C-L3 | 반영 | Step 9-8 범위 L366-371 정정 |
| C-L4 | 반영 | D1/D2 근거에 ocr-extractor.md:112-113 인용 보강 |
| G-L1 | 반영 | AC-2를 `values_equal("582.70", 582.7) is True`(문자열 인자)로 교체 |
| G-L2 | 반영 | Step 6 말미 fragment 모드 무영향 1문장 명문화 |

(미반영 0건.)

- 기준 커밋: 계획 실행 직전 `git rev-parse HEAD`로 캡처 (Step 0)
- 베이스라인: pytest **238개 수집·통과** (실측: `python -m pytest --collect-only -q` → "238 tests collected")

---

## 1. Requirements Summary

### 1.1 확정 목표 (재진술)

cert-review 플러그인에, Phase 1.6에서 `MTC_RAW_MATERIAL`로 분류된 동봉 원자재 성적서(MILL CERT)를 **전사하고 검증하는 신규 리뷰 도메인 `mill_cert`와 신규 서브에이전트 `mill-cert-reviewer`**를 추가한다. 산출 판정은:

1. **기준 21 (검증·연결성)**: MILL CERT의 (a) 분류 확인, (b) 연결성 — Heat No. 일치, MTC 본문의 MILL CERT NO. 참조 일치, grade 계열 일치, (c) 자체 규격 유효성 — 배율(×100/×1000) 정규화된 화학성분·인장·경도가 **문서 자체 인쇄 spec 한계** 내인지, EN10204 타입 표기(정보성).
2. **기준 22.1 (화학 교차비교)**: 배율 정규화 후 **양쪽 모두 보고된 공통 원소만** MTC Heat(H) 분석 ↔ MILL CERT Ladle 분석 비교. 수치 불일치 시 **해당 원소별 '주의'**.
3. **기준 22.2 (단조품 인장 전사 FAIL)**: 단조품에서 양쪽 모두 보고된 인장시험 값(YS·TS·EL·RA) **전체가 수치 동일하면 FAIL**, **일부만 동일하면 '주의'**.

성공 기준: PU2601564 샘플에서 규칙 22.2의 FAIL(4개 값 소수점 둘째 자리까지 동일: YS 447.77 / TS 582.71 / EL 30.94 / RA 75.64) 재현 + 기존 pytest 238개 회귀 없이 통과.

### 1.2 사용자 인터뷰 확정 사항 (재론 금지 — 그대로 구현)

1. **규칙 22.2 트리거**: 인장 4항목 중 양쪽 공통 보고분 **전체 동일 → FAIL / 일부 동일 → 주의**. 경도·열처리 사이클 동일은 FAIL 트리거가 아니라 **보조 근거(Info)로만 기록**.
2. **규칙 22.1**: 공통 원소만, H분석↔Ladle 분석, Product(P) 분석 비교 제외, 한쪽에만 있는 원소(Cu/Ni/As/Sn/Sb 등) 무시, 불일치 시 원소별 '주의'. **화학성분 '동일'은 정상**(heat 분석은 제강사 값 인용이 원칙) — 인장 '동일'만 위반이라는 대비를 기준 문서(기준 22)에 명시.
3. **신규 에이전트 범위**: 분류확인 + 연결성 + 자체검증 + 교차비교 데이터 산출 전부.

### 1.3 핵심 설계 결정 (본 계획서에서 확정 — 실행자 재량 없음)

| # | 결정 | 근거 |
|---|---|---|
| D1 | **추출 경로**: `ocr-extractor`에 `MTC_RAW_MATERIAL` 전사 예외를 추가한다(해당 라벨 페이지는 최소 엔트리 대신 **전량 전사**). 신규 `mill-cert-reviewer`는 재-OCR하지 않고 전사 결과·doctype sidecar·attachments·신규 `<case>_mill_cert.json` 팩을 입력으로 **검증·판정만** 수행 | 배율 해석이 검증된 단일 OCR 경로 유지(메모리·docs/revision_history.md:57 실측: sonnet 배율 미적용 11원소 오류로 탈락), 리뷰어 재-OCR 금지 원칙(SKILL.md:340, ocr-extractor.md:112-113), check-extraction 페이지 커버리지 계약 불변(ocr-extractor.md:67) |
| D2 | **결정적 비교는 스크립트, 판정 서술은 에이전트**: 신규 모듈 `scripts/mill_cert.py`가 수치 동일성·단조 술어·연결성 매칭·서브그룹 분할을 결정적으로 계산해 `<case>_mill_cert.json`으로 산출, 에이전트는 이를 근거로 verdict/finding을 한국어로 서술 | pytest 가능성, C1 AST 가드(tests/test_no_python_ocr.py:16-36) 준수, 검증 책임 경계(ocr-extractor.md:112-113) |
| D3 | **도메인 이름 `mill_cert`**, 부분 산출 `<case>_review_mill_cert.json`. `merge_reviews._DOMAIN_ORDER` 6번째 + **선택적(optional) 도메인** — 부재 시 경고/이슈 미발생 | mill cert 없는 케이스 다수에서 "missing partial" 노이즈 방지. 기존 5도메인 누락 경고(merge_reviews.py:148-154) 불변 |
| D4 | **에이전트 위임은 조건부**: `<case>_mill_cert.json`의 `applicable: true`일 때만 위임하며, **5 리뷰어와 같은 단일 메시지에 병렬**(케이스당 최대 6 동시, 총 동시 캡 6–10 SKILL.md:182 내). 부재 시 위임 생략 | opus 위임 비용 절약 + 동시성 규칙 정합(C-M4). mill-cert-reviewer 입력은 팩+extracted뿐이라 타 부분 산출에 무의존 → 병렬 안전 |
| D5 | **인벤토리·attachments 오염 없음**: `refpack.collect_inventory`(refpack.py:93-99)·`attachments.collect_finished_heats`(attachments.py:65-74)는 sidecar `pages` 맵 기준 제외이므로 mill cert 전량 전사에도 완제품 인벤토리/heat 목록 불변 (실측 확인) | 회귀 없음의 구조적 근거 |
| D6 | **기준 20의 '첨부 여부' 판정 소유는 format-reviewer 유지**(review-criteria.md:434). mill-cert-reviewer는 미첨부/첨부확인 finding 발행 금지 — 내용 검증·교차비교만 | 중복 발행 구조적 방지(기준 20.1 단일 소유) |
| D7 | **Excel 렌더**: `mill_cert` 행이 하나라도 있으면 조건부 7번째 시트 "원자재 MILL CERT 검토"를 `_grouped_sheet` 재사용으로 추가. 구버전 review.json(키 없음)은 시트 미생성 | compliance_report.py:285-305 하위호환 철학, `or []` 관용구(L288) |
| D8 | **스키마 가산 확장만**: `header`에 `mill_cert_no`/`mill_maker`/`starting_material`(소비처: 팩 linkage/match.header → 리뷰어 note 서술 전용 — C-M6 확정), `analysis_type` enum에 `"Ladle"`. 인스턴스 `schema_version` const `"2.0"`(extraction-schema.json:10) 유지 | 46케이스 캐시 재추출 강제 금지(메모리) |
| D9 | 버전 v1.6.0 → **v1.7.0**(.claude-plugin/marketplace.json:8), 에이전트 수 9종→10종 표기 동기화(marketplace + README + SKILL.md) | 지시사항 9, G-H5 |
| D10 | **EN10204 검증은 정보성으로 확정(C-H2)**: 결정적 regex 추출 + doc-check 행(PASS/N/A)만, finding 금지. MPS의 3.1 요구 충족 판정은 format-reviewer 문서요구 교차검토 소유(format-reviewer.md:114) | 범위 팽창 방지, 기준 17.4 정합 |

---

## 2. Acceptance Criteria

**베이스라인 캡처 (Step 0 선행, 결과를 작업 로그에 기록)**:
```powershell
cd "<SKILL_DIR>"; $env:PYTHONIOENCODING="utf-8"
git -C ..\.. rev-parse HEAD            # 기준 커밋 기록
python -m pytest -q                    # 기대: 238 passed — 실제 출력 문자열 저장
python -m pytest --collect-only -q | Select-Object -Last 1   # "238 tests collected"
```

| # | 기준 (이진 판정) | Before | After |
|---|---|---|---|
| AC-1 | `python -m pytest -q` 전체 그린 | 238 passed | 238 + 신규(30 이상) passed, 0 failed |
| AC-2 | `values_equal("582.70", 582.7) is True`, `values_equal(15, 0.15) is False` (단위 테스트) | 모듈 없음 | 통과 |
| AC-3 | 합성 PU2601564형 fixture(인장 4항목 동일 + 단조 A182-F22 + heat B14339)에서 `build_mill_cert_pack` 결과 match의 `tensile.state == "all_identical"`, `is_forging.forging is True`, `linkage.grade_family_match is True` | 불가 | 통과 |
| AC-4 | 인장 4항목 중 2개만 동일 fixture → `state == "partial_identical"` | 불가 | 통과 |
| AC-5 | `merge_case`에 `<case>_review_mill_cert.json` 존재 시 병합 material에 `mill_cert` 섹션 유입 + verdict worst 집계(FAIL 우선); **부재 시** `missing_domains`/`issues`에 `mill_cert` 미등장 | 키 없음 | 통과 |
| AC-6 | 5개 기존 부분만으로 병합 시 material 키 집합 = 기존 12키 + `mill_cert`(빈 배열), top-level 키 집합 불변(test_merge_reviews.py:25-48 갱신 후 그린) | 12키 | 13키 |
| AC-7 | `mill_cert` 행 포함 review.json → xlsx에 "원자재 MILL CERT 검토" 시트 생성, 한국어 read-back 무결(U+FFFD·`占` 부재); 키 없는 legacy → 시트 미생성 + 기존 렌더 불변 | 시트 없음 | 통과 |
| AC-8 | `python -m scripts.cli mill-cert --case <id>`: mill cert 런 없는 케이스에서도 exit 0 + `applicable: false` 팩 기록(attachments 관용구, cli.py:640-663 준거) | 서브커맨드 없음 | 통과 |
| AC-9 | `tests/test_no_python_ocr.py` 그린 (신규 모듈은 json/re/decimal/pathlib + scripts 내부 import만) | 그린 | 그린 유지 |
| AC-10 | `review-criteria.md`에 기준 21·22 신설, 19.2·20.5에 "기준 21/22 한정 예외" 문구, 기준 19 표 MTC_RAW_MATERIAL 행 예외 표기 | 없음 | grep 확인 |
| AC-11 | `marketplace.json` version == "1.7.0" + description 10종 / README·SKILL.md 에이전트 수·시트 수 표기 동기화 | 1.6.0 / 9종 / 6시트 | 1.7.0 / 10종 / 6+1시트 |
| AC-12 | (E2E — 오케스트레이터 사후) PU2601564 실PDF에서 `PU2601564_review_mill_cert.json`의 대상 material verdict == "FAIL", 기준 22.2 finding 존재, 화학 공통원소(C/Si/Mn/P/S/Cr/Mo) 전부 equal(주의 0건), 보조근거(경도 185·900°C/99min AC·730°C/150min AC 동일) note 기록 | 불가 | 재현 |
| AC-13 | 기존 판정 로직 파일(refpack/attachments/doctype/eval_harness/compare_engine) 무변경 — `git diff --stat` | — | diff 없음 |
| AC-14 | 다중 heat 연속 런 fixture(1런 내 heat 2종 + 무헤더 연속 페이지)에서 `mill_docs` 2개로 분할, 각자 자기 heat로만 매칭 | 불가 | 통과 |
| AC-15 | 동일 heat 공유 완제품 2페이지(품목 2종) fixture에서 match 레코드 2개(페이지별) 생성 | 불가 | 통과 |

---

## 3. Implementation Steps (구현 지침)

> 실행 순서 고정: Step 0 → 1 → … → 12. Step 1~4는 코드+테스트를 같은 스텝에서 완결(테스트 없는 중간 커밋 금지). 모든 스텝 후 `python -m pytest -q` 그린 확인.

### Step 0 — 베이스라인 캡처

2절의 명령 실행, 출력 기록. 이후 모든 스텝의 회귀 판단 기준.

---

### Step 1 — 신규 모듈 `scripts/mill_cert.py` (결정적 비교 엔진 + 팩 빌더)

**신규 파일**. 모듈 docstring에 기준 21/22 결정적 입력임과 C1(JSON 읽기 전용)/C7(pathlib+utf-8) 준수를 명기(attachments.py:1-18 문체 준거).

**허용 import**: `from __future__ import annotations`, `json`, `re`, `decimal.Decimal/InvalidOperation`, `pathlib.Path`, `from scripts.doctype import load_doctype, excluded_documents_for_case`, `from scripts.attachments import _norm_heat`, `from scripts.compare_engine import _grade_route, _resolve_grade_keys` (private 교차 import 선례: attachments.py:26-31).

#### 1-a. 상수

```python
MILL_CERT_SUFFIX = "_mill_cert.json"
TENSILE_PROPS = ("TS_MPa", "YS_MPa", "EL_pct", "RA_pct")   # extraction-schema.json:70-73 서술 순서와 집합 일치
# 단조 계열 술어 (분류 상수 — 수치 한계 아님, C8 비저촉. grade_routing.csv asme_spec 열과 동기)
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
# 원소 키 동의어 정규화 (실측 근거: case 53 완제품 "Al" vs mill "Alt") — 확장 가능 최소 테이블
_ELEMENT_ALIASES = {"ALT": "AL", "SOLAL": "AL", "SAL": "AL"}
# 탄소당량류는 측정 원소가 아닌 산출값 — per-element 비교에서 제외
_CE_FAMILY = frozenset({"CE", "CEV", "CEQ", "CEF", "PCM", "CEIIW"})
```

#### 1-b. 수치 동일성 술어 (결정적 정의)

```python
def _dec(v) -> Decimal | None:
    """number/str -> Decimal(str(v)); None/''/변환불가 -> None."""
    if v is None or v == "": return None
    try: return Decimal(str(v))
    except InvalidOperation: return None

def values_equal(a, b) -> bool:
    """정규화 후 Decimal 정확 일치. 양쪽 non-None일 때만 True 가능.
    trailing zero: JSON number 582.70은 float 582.7로 파싱돼 자동 동치,
    문자열 '582.70' 입력도 Decimal('582.70') == Decimal('582.7') → True."""
    da, db = _dec(a), _dec(b)
    return da is not None and db is not None and da == db
```
- **단위 통일**: 인장은 추출 단계에서 `TS_MPa`/`YS_MPa`(MPa)·`EL_pct`·`RA_pct`로 정규화됨(extraction-schema.json:70-73, ocr-extractor.md:81) — 본 모듈 추가 변환 없음. 화학은 추출 단계 배율 정규화(%) 전제(Step 5·6) — 본 모듈은 검산만. **허용오차 없음** — 정확 일치만 "동일".

#### 1-c. 배율 함정 가드

```python
def scale_suspect(mtc_v, mill_v) -> int | None:
    """한쪽이 다른 쪽의 정확히 ×100/×1000 (양방향)이면 해당 배율 반환, 아니면 None. 0 값 제외."""
```
원소 비교 레코드에 `scale_suspect`로 실림 — 에이전트는 suspect 원소를 '주의' 확정 전 crop 재판독으로 배율 오류/실제 불일치 판별(Step 7).

#### 1-d. 단조품 술어 (결정적 정의)

```python
def is_forging(grade, spec, remarks, routing) -> dict:
    """{"forging": bool, "basis": str}. 판정 순서(첫 매치 채택):
    1) (spec or '')+' '+(grade or '') 에 _FORGING_SPEC_RE 매치 -> basis "spec: <매치>"
    2) remarks 결합 문자열에 _FORGING_KEYWORD_RE -> basis "remark keyword"
    3) routing 제공 시 _grade_route를 정규화 프로브(1-i)로 시도, asme_spec ∈ _FORGING_ASME_SPECS
    4) 불발 -> {"forging": False, "basis": "단조 계열 근거 없음"} """
```
- 근거: grade_routing.csv 중 단조 spec은 SA-105(L14)·SA-182(L8-13)뿐. CSV 패턴은 `SA-?182` 형이라 `A182`(S 없음) 미매치 — **1) regex가 1차**, CSV는 보강(테스트 양쪽 고정). PU2601564: spec "ASTM A182-F22 CL.3-2022a" → 1)에서 True, "R/BAR HOT FORGING…" remark → 2)로도 True.

#### 1-e. 인장 교차비교 상태기계 (규칙 22.2)

```python
def compare_tensile(mtc_mech, mill_mech) -> dict:
    per = []
    for p in TENSILE_PROPS:
        a = (mtc_mech or {}).get(p); b = (mill_mech or {}).get(p)
        both = a is not None and b is not None
        per.append({"property": p, "mtc": a, "mill": b, "both_reported": both,
                    "equal": values_equal(a, b) if both else None})
    n = sum(1 for r in per if r["both_reported"])
    k = sum(1 for r in per if r["equal"])
    if n == 0:              state = "insufficient"      # -> 기준 22.2 N/A
    elif k == n and n >= 2: state = "all_identical"     # 단조품이면 FAIL 근거
    elif k >= 1:            state = "partial_identical" # 단조품이면 주의 (n==1&k==1 포함)
    else:                   state = "distinct"          # PASS
    return {"per_property": per, "n_reported": n, "n_equal": k, "state": state}
```
- **경계 확정**: n=1·k=1은 "전체 동일"이 아니라 **partial_identical(주의)** — 단일 우연 일치 FAIL 방지 보수 규칙(기준 22.2·테스트에 명문화). 비단조품은 state 무관 FAIL/주의 금지(1-g).

#### 1-f. 화학 교차비교 (규칙 22.1)

```python
def compare_chemistry(mtc_elems, mill_elems) -> dict:
    """elements dict(extraction-schema.json:50-65). 키 정규화: upper + 비영숫자 제거 후
    _ELEMENT_ALIASES 적용. _CE_FAMILY 키는 비교 제외 -> excluded_keys에 기록.
    공통 원소(정규화 키 교집합, value 양쪽 non-None)만 per_element에.
    반환 {"per_element":[{"element","mtc","mill","equal","scale_suspect"}...],
          "n_common","n_equal","n_diff",
          "one_sided_elements": {"mtc_only":[...], "mill_only":[...]},  # 정보성 — 판정 비사용
          "excluded_keys":[...]}"""
```
- 편측 원소는 비교 안 하되 `one_sided_elements`로 노출(리뷰어가 Alt류 근접 오기를 note로 인지 — G-M1). MTC 채널: `analysis_type ∈ {"Heat","Heat+Product",None}` 페이지의 elements만, `"Product"` 단독 배제(호출부 1-h).

#### 1-g. 판정 매핑 참조표 (모듈 docstring + 기준 22에 동일 기재; 스크립트는 state 산출, verdict 발행은 에이전트)

| 조건 | material row verdict | finding |
|---|---|---|
| 단조 & all_identical | 인장 비교 행 **FAIL** | 1건 **ActionRequired**/**DocumentError** — "MTC 인장값 N건이 MILL CERT와 소수점까지 동일 — 완제품 시험 미실시(전사 복제) 의심, 재시험·소명 요구" + 보조근거(경도·열처리 동일) note 병기 |
| 단조 & partial_identical | 행 **주의** | 1건 Question |
| 단조 & distinct | 행 **PASS** | 없음 |
| insufficient | 행 **N/A**("확인 불가") | 없음 (기준 17.4) |
| 비단조 & (all/partial) | 행 **PASS** + note "단조품 아님 — 기준 22.2 미적용, 참고: 값 동일 관찰" | 없음 |
| 화학 불일치(equal=False, scale_suspect=None) | 해당 원소 행 **주의** | 원소 묶어 1건 Question (기준 17.6 병합) |
| 화학 scale_suspect non-None | crop 재판독 후: 배율 오류면 PASS+note("crop 재판독: 배율 정규화 확인"), 실제 불일치면 주의 | 배율 오류면 없음 |
| 화학 전 원소 동일 | 행 **PASS** + note "동일 — heat 분석은 제강사 성적 인용 관행으로 정상 (기준 22.1)" | 없음 |
| Heat 불일치(연결성) | 연결성 행 **FAIL** | 1건 ActionRequired/Identification |
| MILL CERT NO. 참조 불일치 | 연결성 행 **주의** | 1건 Question |
| grade 계열 불일치(match=False) | 연결성 행 **FAIL** | 1건 ActionRequired/Identification |
| **grade 계열 판정 불가(match=None — 편측 라우팅 불발)** | 연결성 행 **N/A** + note "grade 라우팅 불가 — 계열 판정 확인 불가" | 없음 (기준 17.4) |
| MTC에 MILL CERT NO. 참조 없음 | 연결성 행 **N/A** + note (미기재 finding은 MPS 요구 시 format 소유 — 발행 금지) | 없음 |
| **EN10204 타입: `en10204.found` true** | doc-check 행 **PASS** + verbatim note (예: "EN10204:2004 Type 3.1") | 없음 (정보성 — D10) |
| **EN10204 타입: 미검출** | doc-check 행 **N/A** "EN10204 타입 표기 확인 불가" | 없음 (요구 충족 판정은 format 소유) |
| 자체 유효성: 정규화값이 문서 인쇄 spec 한계 밖 | 해당 행 **주의** (완제품 판정 아님 — FAIL 금지) | 1건 Question |
| 팩/mill_doc `transcription_missing: true` (legacy 캐시) | 해당 도메인 **N/A** | 없음, completion report에 재추출 필요 보고 |

- 판정 어휘 `PASS | 주의 | FAIL | N/A`만(SKILL.md:395), '주의'가 정본. finding severity 기존 5종만.

#### 1-h. 팩 빌더

```python
def build_mill_cert_pack(case_id: str, cache_root: Path,
                         routing: list[dict] | None = None) -> dict:
```
알고리즘:
1. `case_cache = cache_root/<case_id>`. `*_extracted.json` 없으면 `FileNotFoundError`(attachments.py:141-145 관용구).
2. `excluded_documents_for_case(case_cache)`(doctype.py:208-253)에서 `doc_type == "MTC_RAW_MATERIAL"` 런만 취득. 0건 → `{"schema_version":"1.0","case_id",...,"applicable": False,"mill_cert_runs": []}` 기록 후 반환.
3. **[G-H1] 런 → `mill_docs[]` 서브그룹 분할**: `_group_runs`(doctype.py:256-281)는 연속 동일 라벨을 1런으로 묶으므로(실측: `.cache/PU2601233/PU2601233-2-MTC_doctype.json` p15-50이 혼합 제강사·복수 heat의 **단일 36p 런**), 런 내부를 페이지 헤더 기준으로 재분할한다:
   ```
   docs = []; cur = None
   for page in sorted(run.pages):
       e = 해당 stem extracted의 page 엔트리 (없으면 skip + issues)
       heat_k = _norm_heat(e.header.heat_no) if e.header.get("heat_no") else None
       cert_k = 공백제거·대문자(e.header.cert_no) if e.header.get("cert_no") else None
       new = (cur is None) \
             or (heat_k and cur.heat_key and heat_k != cur.heat_key) \
             or (cert_k and cur.cert_key and cert_k != cur.cert_key)
       if new: cur = 새 mill_doc(첫 페이지=page); docs.append(cur)
       else:   cur.pages.append(page)   # 무헤더 연속 페이지는 현재 doc에 부속
       cur.heat_key = cur.heat_key or heat_k; cur.cert_key = cur.cert_key or cert_k
   ```
   각 mill_doc: `cert_no`/`vendor`/`heat_no`/`grade`/`spec`(첫 non-null header), chemistry(첫 non-null elements), mechanical(첫 non-null), heat_treatment, hardness, remarks(전 페이지 결합), `pages`/`page_range`, `en10204`(remarks+header 결합 문자열에 `_EN10204_RE` → `{"found","type","verbatim"}`), `transcription_missing`(그 doc 전 페이지가 `header=={}`이고 표 데이터 전무일 때 true — 구버전 최소 엔트리 캐시). **한계 명기**: 1페이지에 복수 heat가 인쇄된 판재형 mill cert는 header 단일 필드 특성상 대표 heat만 — note로 한계 기재(후속 과제).
4. **완제품 측 [G-H2]**: 모든 `*_extracted.json`의 **INCLUDED 페이지**(`excluded_pages_map` 기준 — attachments.py:65-74 관용구)에서 heat_no 보유 페이지 스캔. mill_doc마다 `matches[] = _norm_heat 일치하는 완제품 페이지 1개당 1레코드` (퍼지 금지 — attachments.py:38-44 승계):
   - 각 match: `{"stem","page","header": {...verbatim: grade, spec, heat_no, size_od_wt, quantity, po_number, cert_no, mill_cert_no, mill_maker, starting_material}, "linkage","is_forging","chemistry","tensile","aux"}`.
   - 매칭 0건 → `matches: []` + `"unmatched": true` + 같은 stem의 완제품 (heat,grade) 목록 `"same_stem_finished"` 동봉(리뷰어가 연결성 FAIL 행을 걸 대상).
5. match별 계산:
   - `linkage`: `heat_match: true`(매칭 자체), `mill_cert_no_ref`(그 완제품 페이지 `header.mill_cert_no`; null이면 그 페이지 remarks를 `_MILL_CERT_NO_RE` 스캔), `mill_cert_no_match`(공백제거·대문자 정확 일치; ref 없으면 null), `grade_family_match`(1-i; 편측 불발 시 null).
   - `is_forging(match.header.grade, match.header.spec, 완제품 페이지 remarks + mill_doc remarks, routing)`.
   - `chemistry = compare_chemistry(H채널 elements, mill_doc elements)` — MTC 채널 규칙: 그 페이지 chemistry의 `analysis_type`이 `"Product"` 단독이면 같은 heat의 다른 INCLUDED 페이지 중 Heat 채널 페이지를 탐색, 없으면 n_common=0.
   - `tensile = compare_tensile(match 페이지 mechanical, mill_doc mechanical)`.
   - `aux`: `hardness = {"mtc": (match 페이지 mechanical.get("hardness") or {}).get("value"), "mill": (mill_doc mechanical.get("hardness") or {}).get("value"), "equal": 양쪽 non-null 시 values_equal, 아니면 null}` (**dict 직접 비교 금지 — C-M3**; unit은 레코드 보존, note용). `heat_treatment`: 각 단계를 `(stage_norm, temp_C, hold_min)`으로 정규화(stage_norm: "NORM" 포함 또는 N 시작→"N", "TEMPER" 포함 또는 T 시작→"T", 그 외 대문자 verbatim) 후 **집합 동일** — cooling은 비교 제외·보존.
6. `<case>_mill_cert.json` 기록(`ensure_ascii=False, indent=2, encoding="utf-8"` — attachments.py:206-212 관용구), `output_path` 반환. 최상위: `{"schema_version","case_id","applicable","mill_cert_runs":[{"stem","pages","page_range","mill_docs":[...]}],"issues":[...]}`.

#### 1-i. grade 계열 비교 (C-H1 반영)

```python
def _grade_probe(s: str | None) -> str:
    """라우팅용 정규화 프로브: upper 후
    (1) S 미선행 'A<3자리>' -> 'SA-<3자리>'  (예: 'ASTM A182-F22' -> 'ASTM SA-182-F22')
    (2) 숫자-하이픈-영문 경계 -> 공백        ('SA-182-F22' -> 'SA-182 F22')
    -> grade_routing.csv 패턴('SA-?182\\s*F22', csv:10)이 매치 가능해짐."""

def _grade_family(grade, spec, routing) -> str | None:
    """후보 [grade, spec, _grade_probe(grade), _grade_probe(spec)] 순으로 _grade_route 시도.
    routed되면 keys = _resolve_grade_keys(routed, <해당 후보>) 후
    return keys[0] if keys else None   # C-M5 IndexError 가드
    전부 불발 -> None."""
```
`grade_family_match = (fa == fb) if (fa and fb) else None` — None은 1-g의 N/A 행. PU2601564: MTC "ASTM A182-F22 CL.3-2022a" ↔ mill "A182 F22 CL3" 모두 프로브로 `SA-182-F22` 계열 해석 → True (T31로 고정). `is_forging` 3)의 CSV 경로에도 동일 프로브 사용.

**오류 처리**: JSON 파손 파일 무시(skip)+`issues[]` 기록(doctype.py:99-103 관용구), 페이지 키 비정수 skip, 모든 open `encoding="utf-8"`.

**`__all__`**: `["MILL_CERT_SUFFIX","values_equal","scale_suspect","is_forging","compare_tensile","compare_chemistry","build_mill_cert_pack"]`.

**테스트 (신규 `tests/test_mill_cert.py`)** — 6절 표대로. fixture는 tmp_path 자급자족(conftest.py `_DATASET_COUPLED`(L27-30) 추가 금지), 스키마는 6절 코드블록 준수.

---

### Step 2 — CLI 서브커맨드 `mill-cert`

`scripts/cli.py`:
- `cmd_attachments`(L640-663) 아래 `cmd_mill_cert` 추가:

```python
def cmd_mill_cert(args: argparse.Namespace) -> int:
    """기준 21/22: MTC-MILL CERT 교차비교 팩 (<case>_mill_cert.json)."""
    from scripts.mill_cert import build_mill_cert_pack  # noqa: PLC0415
    from scripts.refdata_loader import load_csv  # noqa: PLC0415
    try:
        routing = load_csv(PLUGIN_DIR / "data" / "grade_routing.csv", WORK_DIR)
    except Exception as e:   # 라우팅 실패는 치명 아님 — regex/keyword 술어로 강등
        print(f"[WARN] grade_routing load failed ({e}); regex/keyword predicate only", file=sys.stderr)
        routing = None
    try:
        pack = build_mill_cert_pack(case_id=args.case, cache_root=CACHE_DIR, routing=routing)
    except FileNotFoundError as e:
        print(f"[ERROR] mill-cert: {e}", file=sys.stderr); return 1
    runs = pack["mill_cert_runs"]
    n_docs = sum(len(r["mill_docs"]) for r in runs)
    print(f"[OK] mill-cert --case {args.case}: {len(runs)} run(s), {n_docs} doc(s), "
          f"applicable={str(pack['applicable']).lower()}")
    # doc별 1줄 요약(heat, tensile state, heat_match 여부) + report 경로 (cmd_attachments 문체)
    return 0
```
- 파서 등록(`attachments` 파서 L873-875 아래):
```python
p = sub.add_parser("mill-cert", help="기준 21/22: MTC-MILL CERT cross-comparison pack (mill-cert-reviewer input)")
p.add_argument("--case", required=True)
p.set_defaults(func=cmd_mill_cert)
```
- **mill cert 런 0건도 exit 0** (attachments의 exit 0 관용구, SKILL.md:151).

---

### Step 3 — `merge_reviews.py` 배선 (선택적 도메인)

정확 변경 (실측 라인):
1. **L50**: `_DOMAIN_ORDER = ["chemistry", "mechanical", "heat_treatment", "nde", "format", "mill_cert"]`
2. L50 아래: `_OPTIONAL_DOMAINS = frozenset({"mill_cert"})  # 부재가 정상인 도메인 — 경고/이슈 미발생`
3. **L53-59** `_DOMAIN_SECTION`에 `"mill_cert": "mill_cert",`
4. **L62**: `_SECTION_KEYS = ["chemistry", "mechanical", "heat_treatment", "nde", "doc_checks", "mill_cert"]`
5. **L148**: `missing = [d for d in _DOMAIN_ORDER if d not in present and d not in _OPTIONAL_DOMAINS]` (L151-154 경고 루프 불변 — mandatory 5종에만 작동)
6. **docstring 정정(C-M1)**: **L3-4** "split across five domain subagents" → six("mill_cert는 optional — mill cert 동봉 케이스에만 존재") / **L6-7** domain 집합에 mill_cert / **L17-23** INVARIANT의 materials[] 키 나열에 `mill_cert[]` 추가 / **L18** "compliance_report.py's 6-sheet Excel" → "six-sheet (+1 conditional mill-cert sheet) Excel".

worst-verdict 집계(L67-69, L253-256)·병합 키(L114-120)·백업/재번호 **무변경**.

**테스트 갱신 `tests/test_merge_reviews.py`**:
- L35-48 `_MATERIAL_KEYS`에 `"mill_cert"`, L50-56 `_DOMAIN_SECTION`에 `"mill_cert": "mill_cert"`.
- 기존 `test_partial_domain_missing_warns_and_proceeds`(L194-209)에 `assert "mill_cert" not in result["missing_domains"]` 추가.
- 신규 3건: (a) 6부분(mill_cert FAIL) 병합 → 섹션 유입+verdict FAIL, (b) mill_cert 부재 → 경고·이슈 무발생+`mill_cert: []`, (c) mill_cert 단독 부분의 material 보존.

---

### Step 4 — `compliance_report.py` 렌더 (조건부 7번째 시트)

1. **L1 docstring**: "6-sheet Korean Excel" → "6-sheet (+1 conditional mill-cert sheet) Korean Excel" (C-M2). 스키마 주석(L26-31)에 `"mill_cert": [ {"item","source","mill_value","mtc_value","verdict","note"?} ]` 추가.
2. **L355(표기·형식 시트 완료)와 L357(지적사항 종합) 사이** 삽입:

```python
    # 5.5) 원자재 MILL CERT 검토 (기준 21·22) — mill_cert 행이 있을 때만 (하위호환)
    if any(m.get("mill_cert") for m in materials):
        _grouped_sheet(
            wb, "원자재 MILL CERT 검토",
            "원자재 성적서(MILL CERT) 검증·교차비교 (기준 21·22)",
            ["품명 / Heat", "항목", "출처", "MILL CERT 값", "MTC 값", "판정", "비고"],
            [22, 20, 26, 16, 16, 8, 34],
            materials, "mill_cert", ("item", "mill_value", "mtc_value"),
        )
```
(`_grouped_sheet` L171-193 실측 매핑: col2=row_fields[0], col3=source, col4=row_fields[1], col5=row_fields[2], col6=verdict+색, col7=note.)

3. `_finalize_cells`(L378-379)는 전 시트 순회 — 무변경.

**행 스키마 계약**: `{"item": "인장 TS(MPa) 교차비교" 등, "source": "MILL CERT p.4 / MTC p.3", "mill_value": "582.71", "mtc_value": "582.71", "verdict": "FAIL", "note": "..."}`.

**테스트 신규 `tests/test_compliance_report_mill_cert.py`** (test_compliance_report_excluded.py:1-95 스타일): 시트 존재 + 한국어 read-back(U+FFFD/`占` 부재) + FAIL 셀 색("FFFFC7CE") / legacy(키 없음) → 시트 미생성 + 기존 렌더 불변.

---

### Step 5 — `references/extraction-schema.json` 가산 확장

1. header properties(L38-48 블록)에 추가: `"mill_cert_no": {"type": ["string","null"]}, "mill_maker": {"type": ["string","null"]}, "starting_material": {"type": ["string","null"]}` — **소비처(C-M6)**: 팩 linkage(`mill_cert_no`)·match.header note 서술(`mill_maker`/`starting_material`, 판정 비사용).
2. **L53**: `"analysis_type": {"enum": ["Heat", "Product", "Heat+Product", "Ladle", null]}`
3. 문서 자체 `"version"`(L5) `"2.1"` + description 1문장. **인스턴스 `schema_version` const는 `"2.0"`(L10) 유지** (D8, C-L2).

---

### Step 6 — `agents/ocr-extractor.md` 전사 예외 (D1)

**full 모드 L62-70 블록** — "Excluded pages → minimal entry" 항목을 2단 분리:

- `**MTC_RAW_MATERIAL pages → FULL transcription (기준 21/22 예외)**`: 포함 페이지와 동일한 전량 전사(header/chemistry/mechanical/heat_treatment/nde/remarks + 인쇄 spec 행 verbatim). 추가 의무:
  - `doc_type: "MTC_RAW_MATERIAL"` 스탬프 + remarks 첫 줄 `"문서 유형: 원자재 성적서(동봉 Mill Cert) — 완제품 비교 제외, 기준 21/22 교차검증 전용 전사"`.
  - **배율 정규화**: ×100/×1000 배율 컬럼은 **정규화 %값**을 `chemistry.elements`에 기록, 인쇄 배율 표기 원문을 remarks에 verbatim 보존(예: `"화학성분 배율 표기 원문: C×100=15 → 0.15% 정규화"`). 컬럼별 배율 상이(P/S는 통상 ×1000) 주의.
  - `analysis_type`: Ladle 표기 시 `"Ladle"`. 인장 MPa/% 정규화(기존 규칙), 시험편 위치("1/2 radius") remarks 보존. EN10204 문구·열처리·경도·UT 결과·스탬프 remarks 보존.
- `**그 외 EXCLUDED 라벨 → 최소 엔트리 (기존 규칙 불변)**`.
- **Inventory(L69) 불변 강화**: "(Grade, Class, Heat) 인벤토리는 여전히 INCLUDED 페이지만 — MTC_RAW_MATERIAL 전량 전사 엔트리도 절대 미등록".
- **완제품 페이지 header 확장**: `STARTING MATERIAL:`/`MILL MAKER:`/`MILL CERT NO.:` 표기 시 신규 header 필드에 verbatim 기록(없으면 null), remarks 원문 보존 기존대로.

**fragment 모드 L99**: 위 예외 동일 적용 1문장 추가(full 모드 참조). **[G-L2] fragment 무영향 근거 명문화**: 전사 예외는 페이지 단위 규칙이므로 세그먼트 경계와 무관하며, `merge-parts`가 결정적으로 병합하므로(ocr-extractor.md:101-105) mill cert 런이 세그먼트에 걸쳐도 결과는 동일하다.

`agents/doc-classifier.md`는 **무변경** — MTC_RAW_MATERIAL cue(L48)·EXCLUDED 런 식별자 판독(L70)이 이미 필요 입력을 산출(실측: PU2601233 sidecar documents[]에 원자재 2런 분리 기록).

---

### Step 7 — 신규 에이전트 `agents/mill-cert-reviewer.md`

**신규 파일**. mechanical-reviewer.md(구조)·format-reviewer.md(기준 20 경계) 준거. frontmatter:

```
---
name: mill-cert-reviewer
description: Dedicated agent explicitly invoked by the cert-review skill orchestrator to verify enclosed raw-material Mill Certificates (MTC_RAW_MATERIAL runs) and cross-compare them against the finished-product MTC (기준 21·22), producing review_mill_cert.json. Not subject to automatic delegation.
model: claude-opus-4-8
---
```

섹션 구성(순서 고정):
1. **제목 + Language note** (출력 한국어 — mechanical-reviewer.md:9 준거).
2. **역할 경계**: 완제품 chemistry/mechanical/HT/NDE 판정 금지, 기준 20 첨부 유무 판정 금지(format 소유 — D6), 재-OCR 금지(전사·팩 소비 전용), 중첩 서브에이전트 금지.
3. **Context Received**: case id + SKILL_DIR 절대경로.
4. **Immutable Constraints C1/C2/C3/C7/C8 표** (C2: snippet은 `<stem>_extracted.json` 내 literal 필수).
5. **Input Whitelist** (3범주 + rawdata/GT 금지 표준 문안).
6. **Input Artifacts 표**:
   - `<case>_mill_cert.json` — 1차 입력(mill_docs·matches·state·linkage·is_forging·aux·en10204)
   - `<stem>_extracted.json` — mill_doc 페이지 엔트리(자체 유효성: 인쇄 spec 행 vs 정규화 실측) + **매칭 완제품 페이지 엔트리(header+remarks) — item_name/size/qty를 타 도메인과 동일한 verbatim 소스에서 도출(G-H3)**: PO Item No. 표기가 페이지에 인쇄돼 있으면 그 번호로 `"<품명> (PO Item No. NNN)"` 형식, 도출 불가 시 품명 + `size`(header.size_od_wt verbatim)만 — merge_reviews의 item 토큰 규칙(`_ITEM_NO_RE` L77, size fallback L98-100)과 정합. 최악의 경우에도 소리나는 행 분리일 뿐 값 오염은 없다(merge_reviews.py:102-104)
   - `<stem>_doctype.json` — 분류 확인(기준 21a)
   - `<case>_attachments.json` — 참고 열람만; **첨부 여부 finding 발행 금지**
   - MPS digest·limits.json — **불필요(읽지 않음)**: 자체 유효성은 문서 인쇄 spec 기준(기준 14 방식)
7. **Crop 재판독 권한** (기준 17.4/17.5, crop CLI 사용례 — mechanical-reviewer.md:72-80 준거): **(i) `scale_suspect` 원소 셀, (ii) 병합 키 결정 셀(완제품 페이지의 PO Item No. 표기)이 extracted에서 모호할 때** — 이 두 경우 한정. extracted.json 수정 금지 + note `"crop 재판독: <원값>→<확정값>"`.
8. **기준 21 검증 절차**: (a) 분류 확인 — 팩 `applicable`·doctype 라벨 교차, 오분류 의심 시 "분류 재확인 요청" 보고; (b) 연결성 — linkage 3항목 + `mill_maker`/`starting_material`은 note 서술 전용(판정·fuzzy 매칭 금지 — C-M6); (c) 자체 유효성 — 인쇄 spec 행 1:1 대조(주의 상한) + `en10204` doc-check 행(1-g 매핑).
9. **기준 22 교차비교 절차**: 22.1(공통 원소·scale_suspect crop 절차·`one_sided_elements` note 활용·**"화학 동일=정상/인장 동일=위반" 대비 명문**), 22.2(1-g 매핑표 전재, 보조근거는 FAIL/주의 finding의 content·note에 병기 — **별도 Info finding 금지**, 기준 17.7).
10. **판정 프로토콜**: 기준 17 게이트 전항, 기준 18 표준 어휘, verdict 4종만.
11. **Output Contract**: 경로 `SKILL_DIR\.cache\<case>\<case>_review_mill_cert.json`, 스키마:
```json
{
  "case_id": "...", "po_number": "...", "mps_files": [],
  "code_edition_note": "<mill_cert 범위 한정 리뷰 제약만>",
  "materials": [{
    "item_name": "...", "heat_no": "<완제품 화면 verbatim>", "grade_cert": "<verbatim>",
    "grade_spec": "...", "size": "...", "qty": "...",
    "verdict": "PASS | 주의 | FAIL | N/A",
    "mill_cert": [
      {"item": "연결성: Heat No.", "source": "MILL CERT p.4 / MTC p.3",
       "mill_value": "B14339", "mtc_value": "B14339", "verdict": "PASS", "note": "..."}
    ]
  }],
  "findings": [{"no": 1, "severity": "...", "category": "DocumentError|Identification|Mechanical|Chemistry|Other",
                "location": "...", "content": "...", "action": "..."}]
}
```
   + **material 산출 규칙(G-H2)**: 팩 matches는 완제품 **페이지별** 레코드 — (heat_no, grade_cert, item 식별자)가 동일한 페이지들은 하나의 material로 통합하고 페이지들을 source에 열거, 식별자가 다르면(품목 상이) **material을 각각 생성**해 각자 mill_cert 행을 채운다(동일 heat 다품목 케이스에서 빈 섹션 금지). + **병합 키 규약 문단**(heat_no/grade_cert verbatim — mechanical-reviewer.md:164 전재), 타 섹션 키 포함 금지, transcription_missing 시 verdict "N/A"+빈 행+completion report 보고.
12. **Execution Sequence** (8단계) + **Completion Report**(mill_docs 수/매칭 heat/state/finding 수/scale_suspect 처리/재추출 필요 여부).

---

### Step 8 — `references/review-criteria.md` 기준 21·22 신설 + 예외 문구

1. **기준 19 표(L396)**: `MTC_RAW_MATERIAL` 행 분류 셀 `제외` → `제외(기준 21·22 교차검증 전용 전사)`.
2. **19.2(L412-414)** 끝에: "**예외(기준 21/22 한정)**: `MTC_RAW_MATERIAL` 런은 Phase 2에서 전량 전사되며, 그 값은 기준 21(자체 검증)·기준 22(MTC와의 교차비교) 목적에 한해 사용한다. 완제품 materials[]의 Code/MPS/CSV 한계 판정 근거·인벤토리 등록·타 도메인 evidence 인용 금지는 여전히 유효하다."
3. **20.1 표 MTC_RAW_MATERIAL 행(L434)** 비고: "첨부 **여부** 판정은 format-reviewer 소유(불변); 첨부 문서의 **내용 검증·교차비교**는 기준 21/22(mill-cert-reviewer 소유)".
4. **20.5(L463-465)** 끝에: "**예외**: `MTC_RAW_MATERIAL`에 한해 기준 21/22가 정의하는 검증·교차비교는 허용된다(값을 완제품 합부 판정에 쓰는 것은 여전히 금지)."
5. **신설 기준 21**: 21.1 범위·입력(`<case>_mill_cert.json`, 소유 mill-cert-reviewer, 조건부 위임), 21.2 연결성(heat 정확일치·MILL CERT NO. 대조·grade 계열 — **1-g 매핑표 전재, grade 계열 None→N/A 행 포함**), 21.3 자체 유효성(인쇄 spec 한계 내 — 주의 상한, **EN10204 타입은 정보성 doc-check 행 한정 — 요구 충족 판정은 format 소유(D10)**), 21.4 판정 경계(기준 20 상호 배타, 완제품 판정 금지).
6. **신설 기준 22**: 22.1 화학(공통 원소·H↔Ladle·P 제외·원소별 주의·scale_suspect 절차·CE류 제외·동의어 정규화 + **"화학성분 동일은 정상(제강사 성적 인용 관행)이며 finding 대상이 아니다 — 아래 22.2의 인장 '동일'과 정반대"**), 22.2 단조 인장(단조 술어 — `S?A-105/S?A-182` 계열 spec 또는 FORGING/FORGED remark 또는 grade_routing asme_spec; 수치 동일 — 정규화 후 Decimal 정확 일치; 상태기계 n/k와 n=1 보수 규칙; FAIL=ActionRequired/DocumentError; 보조근거 병기 규칙).

"§" 금지·"기준 N" 인용 형식(review-criteria.md:5) 준수.

---

### Step 9 — `SKILL.md` 배선

1. **L53**: "9 plugin subagents" → "10 plugin subagents". **에이전트 표(L55-65)** 행 추가: `mill-cert-reviewer | claude-opus-4-8 | Phase 4 원자재 MILL CERT 검증·교차비교 (기준 21·22, mill cert 존재 케이스 한정 조건부) | <case>_review_mill_cert.json`.
2. **디렉토리 레이아웃(L113-116)**: `<case>_attachments.json` 아래 `<case>_mill_cert.json ← mill-cert CLI output (기준 21/22 교차비교 팩)`; `<case>_review_<domain>.json` 주석 `(chemistry|mechanical|heat_treatment|nde|format|mill_cert)`.
3. **PowerShell 예시(L151-152 사이)**: `python -m scripts.cli mill-cert --case 4   # Phase 4: 기준 21/22 교차비교 팩 (런 0건도 exit 0)`.
4. **Phase 4-1(L323-327)**: attachments 다음 "then run `mill-cert --case <id>`" (항상 실행, `applicable`이 위임 조건).
5. **Phase 4-2(L329-341)**: "**+ 조건부 6번째: `applicable: true`인 케이스는 `mill-cert-reviewer`를 5 리뷰어와 같은 단일 메시지에 병렬 위임(케이스당 최대 6 동시 — 총 동시 캡 6–10 내, C-M4)**. 위임 컨텍스트: case id · SKILL_DIR 절대경로 · 출력 의무(`<case>_review_mill_cert.json`) · 준수사항(C1–C8, 3범주 화이트리스트, 기준 20 첨부판정 발행 금지, 재-OCR 금지)".
6. **기준 라우팅 표(L342-351)**: `mill-cert-reviewer | 기준 21 (MILL CERT 검증·연결성), 기준 22 (22.1 화학 주의 / 22.2 단조 인장 전사 FAIL)`.
7. **도메인 경계 표(L354-364)**: `MILL CERT 자체 유효성·연결성·MTC 교차비교 (기준 21·22) | mill_cert` + `원자재 성적서 첨부 여부 판정 (기준 20) | format (불변)`.
8. **Phase 4-3 merge-reviews(L366-371, C-L3)**: "the 5 partial files" → "최대 6개 부분 파일(`<case>_review_mill_cert.json`은 선택적 — 부재 시 경고 없음)".
9. **"6-sheet" 표기 일괄(C-M2)**: frontmatter description(L3) · Phase 5 헤딩(L378) · Purpose(L380) · "**6-sheet structure**"(L384) · L395-396 — 각각 "6시트(+조건부 1시트: 원자재 MILL CERT 검토)" / 영문 위치는 "6-sheet (+1 conditional mill-cert sheet)"로. 시트 표(L386-393)에 `6.5 | 원자재 MILL CERT 검토 | (조건부) 기준 21·22 연결성·자체검증·교차비교 행` 추가.
10. **시간 예산(L166)**: ⑨ 추가 — "mill cert 전사 예외는 동봉 mill cert 보유 케이스에서만 페이지당 기존 OCR 동일 비용(+통상 1~2p), mill-cert-reviewer 1위임 추가 — 티어 목표 불변".
11. **흐름 요약(L438-443)**: `attachments → <id>_attachments.json` 뒤 `→ mill-cert → <id>_mill_cert.json`; 위임 줄 `5 reviewers (+ conditional mill-cert-reviewer)`.

### Step 10 — `.claude-plugin/marketplace.json` + `README.md` (G-H5)

**marketplace.json**: L8 `"1.6.0"` → `"1.7.0"`; L14 description "에이전트 9종(…표기형식)" → "에이전트 10종(…표기형식·원자재 MILL CERT 교차검증)" + "동봉 원자재 성적서(MILL CERT) 전사·연결성·교차비교(기준 21/22, 단조품 인장 전사복제 FAIL)" 문구 추가.

**README.md** (전부 실측 라인):
- L5 "6시트 한글 Excel 리포트" → "6시트(+조건부 원자재 MILL CERT 시트) 한글 Excel 리포트"
- L12 "도메인별 검토 5종" → "도메인별 검토 5종 + 조건부 원자재 MILL CERT 검증 1종"
- 핵심 특징에 bullet 1개 신설(기준 21/22 요약: 전사 예외·연결성·화학 주의·단조 인장 전사 FAIL)
- L20 "6시트 한글 리포트: …" → 시트 목록에 "(조건부) 원자재 MILL CERT 검토" 추가
- L180 "209개 단위 테스트" → 신규 총계로 갱신
- L190 "9개 플러그인 서브에이전트" → "10개", 표(L192-202)에 `mill-cert-reviewer` 행, L204 문구 유지 확인
- L210 병합 CLI 도메인 목록에 `mill_cert`(선택적) 추가
- mermaid 순서도·이하 본문에서 "검토 5" 표기를 grep으로 전수 확인 후 해당 위치 갱신

### Step 11 — 최종 회귀 + 커밋

- `python -m pytest -q` 전체 그린 (238 + 신규).
- 한국어 무결성 read-back: 신규 xlsx 테스트의 자동 assert + 실행자가 기준 21/22 신설 섹션·신규 에이전트 md를 `Read`로 재열람해 한글 정상 육안 확인, 보고에 명기.
- git 커밋 (G-M2 — 저장소 관행 트레일러):
```
feat(cert-review): add mill_cert review domain + mill-cert-reviewer agent (기준 21/22), v1.7.0

- scripts/mill_cert.py 신설(결정적 교차비교 팩) + cli mill-cert
- merge_reviews 선택적 6도메인 · compliance_report 조건부 7시트
- ocr-extractor MTC_RAW_MATERIAL 전사 예외 · 기준 21/22 신설(19.2/20.5 예외)
- pytest 238 -> <신규 총계> passed

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01GonggP4XQh3cbymwHMjAyb
```

### Step 12 — revision 문서 + 색인 (G-H4)

- `docs/revisions/<YYYY-MM-DD_HHMMSS>_mill-cert-review-domain.md` 신설 — 기존 양식(docs/revisions/2026-07-23_111145_*.md 및 revision_history.md:20-28 실측 구성) 준거: **신설/수정/무변경(분리 원칙)/검증(pytest 수치·E2E 예정)** 4구획 + 후속 과제(배포 캐시 동기화, 46케이스 재추출 시 자동 활성, 다중 heat 단일 페이지 한계).
- `docs/revision_history.md` **최상단**에 색인 엔트리 추가 — 형식: `## <날짜> — <제목> — v1.7.0` + `**Detail**: [revisions/...] · **Plan**: [plans/...]` + 요약 bullet 3-4개 (revision_history.md:20-22 형식 그대로. Plan 링크는 오케스트레이터가 저장한 본 계획서 파일명).
- 계획서 자체의 `docs/plans/` 저장·`plan_history.md` 색인은 **오케스트레이터 수행** — 실행자 스텝 아님.

---

## 4. Code Writing Guide

- **인코딩**: 모든 `open`/`read_text`/`write_text`에 `encoding="utf-8"`. JSON은 `ensure_ascii=False, indent=2`. 진입점·pytest는 `$env:PYTHONIOENCODING="utf-8"` 선행(C7). "§" 금지 — "기준 N" 형식.
- **의존성**: 신규 스크립트는 표준 라이브러리 + scripts 내부 import만. 금지 목록은 test_no_python_ocr.py:16-36이 AST 강제. openpyxl은 compliance_report에서만.
- **입력 가드**: 신규 코드는 `.cache/`·`data/*.csv`만 열람. `rawdata/`·GT 접근 금지(scripts/__init__.py audit hook). 문자열 `"standard inspection GT data"`를 eval_harness 외 파일에 금지(test_no_python_ocr.py:78-88).
- **관용구**: FileNotFoundError 메시지·`output_path`·`.replace("\\", "/")`(attachments.py:141-213), 관용적 무시(doctype.py:99-103), 하위호환 `or []`(compliance_report.py:288), 병합 키 verbatim(merge_reviews.py:87-120).
- **네이밍**: 도메인 `mill_cert`(snake), CLI `mill-cert`(kebab), 팩 `_mill_cert.json`, 에이전트 `mill-cert-reviewer.md`(kebab).
- **하드코딩 경계(C8)**: 수치 한계값 금지. `_FORGING_ASME_SPECS`·`TENSILE_PROPS`·`_ELEMENT_ALIASES`·`_CE_FAMILY` 같은 분류·필드명 상수는 허용(한계값 아님) — 모듈 주석 명시.
- **테스트**: 전부 tmp_path 자급자족, conftest `_DATASET_COUPLED`(L27-30) 추가 금지.
- **문서**: 에이전트 md 영어 본문 + 한국어 출력 규약, 기준 문서·SKILL 신규 문구는 기존 문체.
- **금지**: 기존 5도메인 판정 로직·기준 1~20 수치·`_VERDICT_ALIASES`·eval_harness 무변경. `<stem>_extracted.json` 리뷰어 수정 금지. burn-in 주석 재제안 금지(메모리).

---

## 5. Definition of Done

### (a) 실행자(executor) 자체 검증 가능 — 서브에이전트 불필요

| ID | 항목 (이진) | 검증 명령 |
|---|---|---|
| DoD-a1 | 전체 pytest 그린, 실패 0 | `python -m pytest -q` |
| DoD-a2 | 신규 테스트만 그린 | `python -m pytest tests/test_mill_cert.py tests/test_compliance_report_mill_cert.py tests/test_merge_reviews.py -q` |
| DoD-a3 | C1 AST 가드·입력 가드 그린 | `python -m pytest tests/test_no_python_ocr.py tests/test_input_guard.py -q` |
| DoD-a4 | CLI 스모크: mill cert 없는 합성 캐시에서 exit 0 + `applicable: false` | 임시 케이스 캐시 생성 후 `python -m scripts.cli mill-cert --case <tmp>`; `$LASTEXITCODE -eq 0` |
| DoD-a5 | 합성 PU2601564형 fixture → `all_identical`·forging True·grade family True·화학 n_diff 0 | DoD-a2 포함 (T5/T31) |
| DoD-a6 | 병합 material 키에 `mill_cert` + legacy 5부분 병합 시 빈 배열 + optional 무경고 | DoD-a2 포함 |
| DoD-a7 | xlsx 시트 조건부 생성 + 한국어 read-back assert | DoD-a2 포함 |
| DoD-a8 | 문서 배선 grep: SKILL.md `mill-cert-reviewer` 4곳 이상 / review-criteria `기준 21`·`기준 22`·19.2/20.5 예외 / marketplace "1.7.0" / **README "10개"·mill-cert-reviewer 행** / **무자격 "6-sheet|6시트" 잔존 0건**(SKILL.md·README·compliance_report.py·merge_reviews.py에서 조건부 문구 미동반 표기 없음) | Grep 도구 (6절 T32) |
| DoD-a9 | `git diff --stat`에 refpack.py/attachments.py/doctype.py/eval_harness.py/compare_engine.py 미포함 | `git diff --stat` (6절 T33) |
| DoD-a10 | revision 문서 + revision_history.md 색인 존재 (Step 12) | `Glob docs/revisions/*mill-cert*` + Grep 색인 |

### (b) 오케스트레이터 사후 E2E 스모크 — **Step 12 이후, 실행자 범위 밖** (서브에이전트 위임 필요)

| ID | 항목 | 절차 요약 |
|---|---|---|
| DoD-b1 | PU2601564 실PDF 파이프라인 구동 | 스크래치 스테이징: `<scratch>\e2e\standard inspection Cert cleanup data\PU2601564\PU2601564.pdf`(원본 `plugin\ReportReviewer\docs\PU2601564.pdf` 복사; **46케이스 데이터셋 폴더 추가 금지**) + 빈 MPS 폴더. `$env:CERT_REVIEW_WORKDIR="<scratch>\e2e"` 후 SKILL_DIR에서: build-manifest → prep-inputs → orient-sheets → [page-aligner] → align-inputs → tile-inputs → classify-sheets → [doc-classifier] → check-doctype(exit 0; 기대 p3=MTC_FINISHED, p4=MTC_RAW_MATERIAL, p1-2=COVER_LETTER 또는 UNKNOWN) → [ocr-extractor] → check-extraction → mill-cert CLI → [mill-cert-reviewer] |
| DoD-b2 | 규칙 22.2 FAIL 재현 | `PU2601564_mill_cert.json`: tensile 4/4 equal(447.77/582.71/30.94/75.64)·state "all_identical"·forging true·linkage heat B14339 match + mill_cert_no 201404-004866 match. `PU2601564_review_mill_cert.json`: verdict "FAIL" + 기준 22.2 finding(ActionRequired) + 보조근거 note(HB 185·900°C/99min AC·730°C/150min AC 동일) |
| DoD-b3 | 규칙 22.1 무주의 재현 | 공통원소 C/Si/Mn/P/S/Cr/Mo 전부 equal → 원소 '주의' 0건, PASS+정상 note |
| DoD-b4 | 렌더 자동 검증 (G-M4 — 이진) | merge-reviews + compliance_report 후 인라인 assert: `python -c "import openpyxl; wb=openpyxl.load_workbook(r'<xlsx>'); assert '원자재 MILL CERT 검토' in wb.sheetnames; ws=wb['원자재 MILL CERT 검토']; cells=[str(c.value) for r in ws.iter_rows() for c in r if c.value]; assert any(v=='FAIL' for v in cells); assert not any(('�' in v) or ('占' in v) for v in cells); print('OK')"` (PYTHONIOENCODING=utf-8 선행) |
| DoD-b5 | 정리 | `.cache/PU2601564/`·스크래치 삭제, 원 워크디렉토리에서 build-manifest 재생성 |

---

## 6. Adversarial Test Environment (적대적 테스트 환경)

**구축**: `tests/test_mill_cert.py`에 fixture 빌더 2개. `_write_doctype`은 tests/test_attachments.py:49-60 형태 준거. `_write_extracted`는 **본 테스트 전용 신규**(기존 tests/test_attachments.py:25-37의 원형은 header.heat_no만 생성 — G-H6 정정)이며 최소 스키마는 아래로 고정(실캐시 `.cache/53/PU2502684_*_extracted.json`의 실제 형태 — 다원소 elements·null 섞인 mechanical·비정형 HT — 를 표현 가능해야 함):

```python
def _write_extracted(case_cache: Path, stem: str, entries: list[dict]) -> None:
    """entries: page_extraction 엔트리 리스트를 그대로 기록.
    엔트리 형식(필요 필드만):
      {"page": 3,
       "header": {"heat_no": "B14339", "grade": "A182-F22 CL.3", "spec": "ASTM A182-F22 CL.3-2022a",
                  "cert_no": "DL-26-074-38", "size_od_wt": "DN15 SW", "quantity": 33,
                  "mill_cert_no": "201404-004866", "mill_maker": "SeAH Besteel",
                  "starting_material": "ROUND BAR(OD40)"},
       "doc_type": "MTC_FINISHED",
       "chemistry": {"analysis_type": "Heat",
                     "elements": {"C": {"value": 0.15, "unit": "%"}, "Si": {"value": 0.18, "unit": "%"}}},
       "mechanical": {"TS_MPa": 582.71, "YS_MPa": 447.77, "EL_pct": 30.94, "RA_pct": 75.64,
                      "hardness": {"value": 185, "unit": "HBW"}},
       "heat_treatment": [{"stage": "Normalizing", "temp_C": 900, "hold_min": 99, "cooling": "Air"}],
       "remarks": ["MILL CERT NO.: 201404-004866", "..."]}
    최소 엔트리(legacy)는 {"page": N, "header": {}, "doc_type": "...", "remarks": [...]}."""
    case_cache.mkdir(parents=True, exist_ok=True)
    (case_cache / f"{stem}_extracted.json").write_text(
        json.dumps({"stem": stem, "page_extraction": entries}, ensure_ascii=False),
        encoding="utf-8")
```

**실행**: `$env:PYTHONIOENCODING="utf-8"; python -m pytest tests/test_mill_cert.py -q` 등.

| # | 적대 시나리오 | 입력 구성 | 기대 결과 | 매핑 DoD |
|---|---|---|---|---|
| T1 | trailing zero | mtc 582.7 vs mill "582.70"(str) | `values_equal → True` | a2 |
| T2 | 배율 함정 ×100 | mtc C 0.15 vs mill 15 | equal False + `scale_suspect == 100` | a2 |
| T3 | 배율 함정 ×1000 | mtc P 0.015 vs mill 15 | `scale_suspect == 1000` | a2 |
| T4 | 일부만 동일 | YS·TS 동일, EL·RA 상이 (n=4,k=2) | `partial_identical` | a2/AC-4 |
| T5 | 전체 동일 (PU형) | 4항목 동일 + A182-F22 + heat 일치 | `all_identical` + forging True | a5/AC-3 |
| T6 | 공통 1건 우연 일치 | YS만 양쪽 보고·동일 (n=1,k=1) | `partial_identical` (보수 규칙) | a2 |
| T7 | 인장 결측 | mill mechanical 전무 (n=0) | `insufficient` | a2 |
| T8 | 편측 원소 | mill에만 Cu/Ni/As/Sn/Sb | per_element 미등장 + `one_sided_elements.mill_only`에 노출 | a2 |
| T9 | MILL CERT 부재 | doctype에 MTC_RAW_MATERIAL 없음 | `applicable False`, CLI exit 0 | a4 |
| T10 | heat 불일치 | mill "B99999" vs 완제품 "B14339" | `matches []`+`unmatched true`+same_stem_finished | a2 |
| T11 | heat 표기 변형 | " b14339 " vs "B14339" | `_norm_heat` 일치 → 매칭 | a2 |
| T12 | 비단조 + 값 동일 | SA-106 pipe + 4항목 동일 | forging False (기준 22.2 미적용 — 판정 매핑 문서 고정) | a2 |
| T13 | 단조 키워드 경로 | spec 무표기 + remark "HOT FORGING" | forging True (basis: keyword) | a2 |
| T14 | 단조 라우팅 경로 | routing rows 주입, grade "SA-182 F22" / routing None | True(csv) / True(regex) | a2 |
| T15 | legacy 최소 엔트리 | mill 페이지 `header:{}` | `transcription_missing True`, 비교 생략 | a2 |
| T16 | 파손 JSON | 잘린 `_extracted.json` | skip + issues, 예외 미전파 | a2 |
| T17 | MILL CERT NO. remark 폴백 | header 필드 null + remarks에만 표기 | regex 추출·match true | a2 |
| T18 | 참조 불일치 | ref 상이 mill cert_no | `mill_cert_no_match False` | a2 |
| T19 | 병합: mill_cert FAIL | 6부분 병합 | verdict FAIL(worst), 섹션 유입 | a6/AC-5 |
| T20 | 병합: 부분 부재 | 5부분만 | `mill_cert: []`, missing/issues 무등장 | a6/AC-6 |
| T21 | 렌더: 시트+색+한글 | mill_cert 행(FAIL) | 시트 존재, "FFFFC7CE", U+FFFD·`占` 부재 | a7/AC-7 |
| T22 | 렌더: legacy | 키 없는 review.json | 시트 미생성, 기존 렌더 불변 | a7/AC-7 |
| T23 | C1/입력 가드 | 기존 가드 재실행 | 위반 0 | a3/AC-9 |
| T24 | H/P 채널 | MTC 페이지 analysis_type "Product"만 | 화학 비교 n_common 0 | a2 |
| T25 | 열처리 보조 근거 | (N 900/99 + T 730/150) 동일 vs 상이 | `aux.heat_treatment.equal` True/False; hardness는 `.value` 스칼라 비교(dict 미비교 — C-M3) | a2 |
| T26 | **다중 heat 단일 런 (G-H1)** | 1런 6p: p1-2 heat A(+무헤더 p3), p4-6 heat B | `mill_docs` 2개, 각자 자기 heat만 매칭, 무헤더 페이지는 선행 doc 부속 | a2/AC-14 |
| T27 | **동일 heat 다품목 (G-H2)** | 완제품 2페이지(같은 heat, size/qty 상이) + mill 1doc | matches 2레코드(페이지별, header verbatim 동반) | a2/AC-15 |
| T28 | **원소 동의어 (G-M1)** | 완제품 "Al" vs mill "Alt" | 정규화로 공통 원소 처리·비교됨 | a2 |
| T29 | **CE류 제외 (G-M1)** | 양쪽에 CEV/CEF 존재 | per_element 미등장 + `excluded_keys` 기록 | a2 |
| T30 | **EN10204 (C-H2)** | remarks "EN10204:2004 Type 3.1" / 무표기 | `en10204.found True, type "3.1"` / `found False` | a2 |
| T31 | **grade 라우팅 정규화 (C-H1)** | MTC "ASTM A182-F22 CL.3-2022a" ↔ mill "A182 F22 CL3" (routing=실CSV 형식 합성 행) | `_grade_family` 양쪽 "SA-182-F22" → match True; 편측 라우팅 불발 → None | a2/AC-3 |
| T32 | 문서 배선 (비-pytest) | Grep: SKILL/criteria/marketplace/README/무자격 6-sheet | DoD-a8 전 항목 매치 | a8 |
| T33 | 무변경 파일 (비-pytest) | `git diff --stat` | 금지 5파일 미포함 | a9 |

모든 DoD-(a) 항목이 1개 이상의 검증 행에 매핑됨(a1=전체 합, a10=Glob/Grep). DoD-(b)는 5절 실PDF 절차.

---

## 7. Risks and Mitigations

| # | 위험 | 완화 |
|---|---|---|
| R1 | test_merge_reviews.py 정확 키집합 assert(L25-48) 적색 | Step 3에서 코드+테스트 동일 스텝 갱신, 중간 커밋 금지 |
| R2 | 46케이스 기존 캐시의 mill cert 페이지는 최소 엔트리 → `transcription_missing` | N/A 우아 강등(1-g). 재추출 강제 금지(메모리 후속 과제 정합). 신규/재추출 케이스부터 자동 활성 |
| R3 | doc-classifier가 PU2601564 p1-2(검사신청서)를 UNKNOWN 포함 처리 가능 | 무해(포함 전사일 뿐 mill_cert 경로 무관). check-doctype는 전량 제외 이상만 차단 |
| R4 | OCR 배율 오독 → 거짓 '주의' | 3중 방어: 추출 정규화 의무(Step 6) + `scale_suspect`(1-c) + crop 재판독 절차(Step 7) |
| R5 | eval(Phase 6) precision 영향 | 조건부 위임(D4) + 보수 게이트(화학 동일 무발행, n=1 보수 규칙, 기준 17). 46케이스 정규 회귀는 재추출 전까지 mill_cert 위임 미발생(R2) |
| R6 | 배포 캐시(`C:\Users\donghun.lee\.claude\plugins\cache\ReportReviewer`) 미동기화 | **커밋 후 후속 단계**로 동기화(md5 일치 확인 — 메모리 '단일 소스 재통합' 절차). 실행자 범위 밖임을 보고 명기 |
| R7 | grade_routing 패턴 `SA-?182`가 `A182` 미매치 | `_grade_probe` 정규화(1-i, C-H1) + regex 1차 술어(1-d), T31/T13/T14 고정 |
| R8 | 다중 시험편/재시험·1페이지 복수 heat mill cert | 페이지별 match(G-H2)로 다품목은 해소; 단일 페이지 복수 heat는 한계 note + 후속 과제(Step 12 revision 문서에 기재). FAIL 미탐은 있어도 오탐 없음(보수) |
| R9 | `Decimal(str(float))` 표현 | str()은 최단 표현 반환(582.71→"582.71") — T1 고정 |
| R10 | "6-sheet"/에이전트 수 표기 산재 불일치 | Step 9-9·Step 10에서 실측 위치 전수 수정 + DoD-a8 grep(무자격 표기 0건)으로 검증 (C-M2/G-H5) |
| R11 | E2E 스테이징의 46케이스 manifest 오염 | `CERT_REVIEW_WORKDIR` 스크래치 격리(cli.py:44-52 실측) + DoD-b5 정리 |
| R12 | 대형 원자재 블록(실측 PU2601233 p15-50, 36p) 전량 전사 시 OCR 시간 증가 | 시간 예산 ⑨(Step 9-10)에 명시. 복합 티어(60–90분) 내 수용, mill_docs 서브그룹은 결정적(비용 0). 필요시 후속에서 "원자재 런 페이지 상한" 별도 논의(본 범위 아님) |

---

## 8. Verification Steps

1. **정적**: `git diff --stat` — 변경 파일이 계획 목록(신설: mill_cert.py, mill-cert-reviewer.md, test_mill_cert.py, test_compliance_report_mill_cert.py, revisions 문서 / 수정: cli.py, merge_reviews.py, compliance_report.py, extraction-schema.json, ocr-extractor.md, review-criteria.md, SKILL.md, marketplace.json, README.md, test_merge_reviews.py, revision_history.md)과 일치, AC-13 금지 파일 부재.
2. **단위·회귀**: `$env:PYTHONIOENCODING="utf-8"; python -m pytest -q` → 전체 그린(238+신규). `python -m pytest tests/test_mill_cert.py -q -v`로 T1~T31 개별 확인.
3. **CLI 스모크**: DoD-a4 실행, exit code + 팩 JSON `Read` 확인.
4. **한국어 무결성**: 신규 xlsx 테스트 자동 assert + 실행자가 기준 21/22·에이전트 md·시트 셀 샘플을 직접 읽어 한글 정상(U+FFFD·`占쏙옙`·`ï»¿` 부재) 확인 — 보고서에 "무엇을 읽어 확인했는지" 명기.
5. **문서 배선 grep**: DoD-a8(T32) 전 항목 수행·기록 (README·무자격 6-sheet 포함).
6. **revision 기록**: Step 12 산출물 존재 확인(DoD-a10).
7. **커밋**: Step 11의 트레일러 포함 형식으로 1건.
8. **E2E (오케스트레이터, Step 12 이후)**: 5절 (b) — PU2601564 FAIL 재현(DoD-b2)·화학 무주의(DoD-b3)·렌더 자동 assert(DoD-b4) 후 정리(DoD-b5). 이 단계까지 통과해야 최종 수용.
9. **후속(커밋 후)**: 배포 캐시 동기화(R6), 46케이스 재추출 시 mill_cert 경로 자동 활성 확인 — Step 12 revision 문서의 후속 과제 항목과 일치시킬 것.
