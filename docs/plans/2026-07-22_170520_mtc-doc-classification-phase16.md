# MTC 혼입 문서 페이지 분류(Phase 1.6 doc-classify) 및 비교 제외 — 1단계 구현 계획

- **작성**: 2026-07-22 17:05 (전담 플래닝 에이전트, Fable 5, dh-dev Step 1-c)
- **상태**: Pending Review (사용자 검토 대기 — dh-dev Step 2)
- **대상**: `plugin/ReportReviewer` (cert-review 스킬 + agents)
- **참조문서**: 실물 조사 `D:\001_Work\2026\033_성적서 검토\Cert_Auto_examine\MTC`(30개 PDF 전수, 읽기 전용) + 기존 케이스 자산 PU2601233(manifest 47케이스), case 10, case 53

> **배경(검증 결과 요약)**: 접수 MTC 성적서 PDF 30개 중 15개(50%, 페이지 기준 771p 중 약 77%)에서 완제품 성적서 외 문서(원자재 Mill Cert, PMI/NDE/외관치수/이화학/조직시험 보고서, 열처리로 온도차트 등)가 임의 위치에 혼입되어 있음을 확인. 혼입은 공급사별 체계적 패턴(동림=항상 순수, 중국 LS룽산=대부분 혼재). 현재 파이프라인은 파일 내 전 페이지를 완제품 성적서로 간주해 화학/기계/열처리/NDE 비교 및 GRADE_MAP 라우팅 인벤토리 오염 위험이 존재. 사용자 확정 스코프: **1단계는 비교 대상 제외만 구현**(요구사항 대비 첨부 여부 자동판정은 후속 과제로 분리), UNKNOWN은 보수적으로 MTC_FINISHED로 취급.

대상 저장소: `plugin/ReportReviewer` (단일 소스, `git@github.com:Donghun1q2w/ReportReviewer.git`, main). 모든 경로는 저장소 루트 기준. 스킬 디렉토리 = `skills/cert-review/` (이하 SKILL_DIR).

---

## 1. Requirements Summary

### 1.1 문제 (검증됨)

접수되는 MTC 성적서 PDF 안에 완제품 성적서 외 문서(원자재 Mill Cert, PMI 보고서, 외관·치수검사보고서, NDE 보고서, 이화학시험성적서, 열처리로 온도차트 등)가 임의 위치(중간/말미)에 혼입되는 사례가 실물 30개 중 15개(50%)에서 확인되었다. 현재 파이프라인은 파일 내 모든 페이지를 완제품 성적서로 간주한다:

- `scripts/prep_inputs.py:158-159` — 케이스 폴더의 `*.pdf` 전량을 성적서로 렌더.
- `scripts/cli.py:84-144` (`cmd_build_manifest`) — 내용 기반 문서 유형 판별 없음.
- `agents/page-aligner.md` — Phase 1.5는 **회전만** 감지 (`<stem>_orientation.json`).
- `scripts/extraction_check.py:49-129` — 페이지 수 커버리지만 검증, 혼입 무증상 통과.
- `scripts/refpack.py:78-104` (`collect_inventory`) — **모든** page header의 (grade, class, spec)을 인벤토리에 수집 → 원자재 grade(예: SA516 후판)가 완제품 라우팅/materials[]를 오염. 원자재 밀시트는 완제품과 **동일 heat_no**를 공유하는 경우가 많아(모재 heat) 유령 material 행이 생긴다.

### 1.2 확정 스코프 (1단계 — 변경 불가)

- 비-완제품으로 분류된 페이지는 화학/기계/열처리/NDE/형식 **비교 대상에서 제외**한다.
- 리포트에는 **"제외됨: <분류 유형>" 메모만** 남긴다.
- **요구사항 대비 첨부 여부 자동판정(MPS가 PMI·NDE 요구 시 실제 첨부됐는지 대조)은 범위 외** — 향후 과제로만 명시하고 설계하지 않는다.
- `UNKNOWN`은 **보수적으로 MTC_FINISHED로 취급**(기존 파이프라인 그대로 진행) — false negative로 성적서 결함을 놓치는 것을 방지.

### 1.3 핵심 설계 결정 (이 계획이 확정 — executor 재량 없음)

**결정 1 — 아키텍처: 별도 신규 전담 에이전트 `doc-classifier` (page-aligner 확장 기각).**
근거:
- page-aligner는 blind A/B로 95.89% 정확도가 확정된 회귀-critical 컴포넌트(`agents/page-aligner.md:9`, `docs/orient-model-selection-2026-07-09.md`). 프롬프트/출력 스키마를 바꾸면 그 실측 provenance가 무효화되고 회전 감지 회귀 위험이 생긴다. page-aligner 코드·문서는 **한 줄도 수정하지 않는다**.
- 입력이 본질적으로 다르다: 회전 감지는 **정렬 전**(회전 상태) 컨택트시트를 읽어야 하고, 문서 유형 판별(발행사 letterhead, 표제, 제품형태/규격 문자열)은 **정렬 후**(정립 상태) 이미지를 읽어야 신뢰할 수 있다. PU2601233은 73페이지 중 51페이지가 90° 회전 상태 — 같은 pass 통합이 불가능한 구조적 이유.
- 추가 비용이 작다: 정립 시트 재합성은 결정적 Pillow CLI(수 초), 에이전트 pass는 ~12p당 시트 1 Read + 경계 페이지 소수 정밀 Read.
- 모델은 **claude-opus-4-8 고정, 모델 A/B 미실시** (프로젝트 확정 관례 — haiku/sonnet은 방향감지·OCR 실측 탈락 이력).

**결정 2 — 삽입 지점: Phase 1.6 "doc-classify"** — `align-inputs`(Phase 1.5 종료) → `tile-inputs` → **Phase 1.6(classify-sheets → doc-classifier 위임 → check-doctype 게이트)** → `prep-mps` → Phase 2 OCR 위임. tile-inputs **이후**인 이유: 분류의 정밀판별(원자재 vs 완제품 MTC — 헤더의 제품형태·규격 문자열 판독)이 헤더 타일 `r0c0`/`r0c1`을 재사용하기 때문. 게이트 계약: **check-doctype exit 0 이전에 ocr-extractor 위임 금지** (align-inputs 게이트와 동일 패턴, `scripts/align_inputs.py:153-271` 참조).

**결정 3 — compare 제외 메커니즘: 5중 방어 (핵심은 결정적 코드 2곳).**

| 층 | 위치 | 메커니즘 |
|---|---|---|
| L1 | `agents/ocr-extractor.md` | 제외 페이지는 minimal-entry 전사(표 전사 생략), 전 entry에 `doc_type` 스탬프, (Grade,Class,Heat) 인벤토리에서 제외 |
| L2 (결정적) | `scripts/refpack.py:collect_inventory` | `<stem>_doctype.json` 기준으로 제외 페이지 header를 인벤토리에서 스킵 → `limits.json`/materials 오염을 코드로 차단 |
| L3 | 5개 reviewer 에이전트 문서 | 제외 페이지 데이터 비교·materials[] 등록 금지 규칙 1줄씩 |
| L4 (결정적) | `scripts/merge_reviews.py:merge_case` | `<stem>_doctype.json`을 읽어 review.json에 top-level `excluded_documents[]` 주입 (findings 미오염 — 기준 17.7 "정보성 분리" 정합, eval precision 무영향) |
| L5 (결정적) | `scripts/compliance_report.py` | 검토 총괄 시트에 "제외됨: <유형>" 블록 렌더 |

제외 판정의 **단일 결정적 권위는 `<stem>_doctype.json`**이다(에이전트가 doc_type 스탬프를 빠뜨려도 L2/L4가 sidecar 기준으로 동작). 제외는 **whitelist 방식**: `INCLUDED = {MTC_FINISHED, UNKNOWN}` — sidecar 부재/필드 부재/미지 라벨은 전부 "검토 포함"으로 폴백(구버전 캐시 하위호환 = 현재 동작 그대로).

**결정 4 — UNKNOWN·오탐 방지 게이트** — 3절 Step 1·4 및 6절 참조. 대표 실패 모드: 완제품 MTC **내부의** PMI 결과 표 페이지를 별도 PMI_REPORT로 오분류 → 해당 페이지의 NDE/PMI 기재가 검토에서 빠져 "PMI 미수행" 오탐 또는 실제 결함 미검출. 방어: ① 분류 단위는 페이지가 아니라 **문서 run**(연속된 동일 letterhead/양식은 한 문서 — 완제품 MTC 문서 내부 섹션은 분리 금지), ② 케이스의 어떤 stem이 MTC_FINISHED+UNKNOWN 0페이지면 check-doctype **exit 1**(전량 제외 비정상 — 사람 확인 요청), ③ 제외율 >60% 시 WARNING + 오케스트레이터가 경계 페이지 full-page 재확인, ④ UNKNOWN→포함 폴백.

### 1.4 Taxonomy (확정)

코드 상수 단일 소스: 신규 `scripts/doctype.py`의 `DOC_TYPES`. `references/review-criteria.md` 기준 17.1(330행)의 기존 용어 "별도 문서(동봉 문서)"와 정합되도록 한국어 라벨에 "동봉" 계열 표현을 사용한다.

| 코드 | 한국어 라벨 (`DOC_TYPE_LABELS_KO`) | 판정 단서 | 처리 |
|---|---|---|---|
| `MTC_FINISHED` | 완제품 성적서 | 파이프/피팅/플랜지 완제품 형태 + 규격(A106/A234/A335/A182 등) | 검토 (기존 동일) |
| `UNKNOWN` | 미상(완제품 성적서로 간주) | 판별 불확실 | 검토 (보수 폴백) |
| `MTC_RAW_MATERIAL` | 원자재 성적서(동봉 Mill Cert) | 제품형태가 plate/billet/bar/coil 등 소재 (예: SA516 Gr.70 후판) | 제외 |
| `PMI_REPORT` | PMI 보고서(동봉) | PMI/합금 판독표 단독 문서 | 제외 |
| `APPEARANCE_DIMENSION_REPORT` | 외관·치수검사보고서(동봉) | 치수 실측표·외관 판정 양식 | 제외 |
| `NDE_REPORT` | 비파괴검사 보고서(동봉) | MT/PT/UT/RT 시험성적 양식 | 제외 |
| `PHYSICAL_CHEMICAL_TEST_REPORT` | 이화학시험성적서(동봉) | 시험소 발행 이화학 성적 양식 | 제외 |
| `MICROSTRUCTURE_REPORT` | 금속조직시험 보고서(동봉) | 조직 사진 중심 | 제외 |
| `HEAT_TREATMENT_CHART` | 열처리로 온도차트(동봉) | 그래프/수기 차트 | 제외 |
| `REVIEWED_ANNOTATED_COPY` | 검토 주석본(입력 배제 대상) | 수기 검토 코멘트가 있는 사본 | 제외 + WARNING |
| `COVER_LETTER` | 송부문서/커버레터 (예약) | — | 제외 |
| `MPS_COPY` | MPS 사본 (예약) | — | 제외 |
| `DRAWING` | 도면 (예약) | — | 제외 |

이 목록은 `scripts/doctype.py`(권위) / `agents/doc-classifier.md` / `references/extraction-schema.json`의 `doc_type` enum / `references/review-criteria.md` 기준 19 — 4곳에 동일하게 기재하며, 4곳 동시 갱신을 DoD에 포함한다.

### 1.5 향후 과제 (명시만 — 이번 범위 아님)

- MPS/규격 요구 대비 동봉 문서 첨부 여부 자동판정 (excluded_documents + mps_digest.document_requirements 대조).
- "첫 페이지부터 혼입" 실물 케이스(PU2601565 등, harness 밖) 반입 및 케이스화.
- 배포본(작업폴더 `.claude/skills`) KO 동기화 — 기존 후속 과제(46케이스 재추출)와 함께.

---

## 2. Acceptance Criteria

Before 베이스라인에 관한 확정 사실 (이번 조사에서 직접 검증):

- `.cache/PU2601233/PU2601233-2-MTC_extracted.json`은 `page_extraction: []`인 **빈 스켈레톤** — Phase 2 OCR이 수행된 적 없어 "혼입을 잘못 처리한 extracted.json" before 베이스라인은 **존재하지 않는다**. 따라서 PU2601233은 after-state 검증(AC-3~6) 전용으로 쓰고, before/after 회귀는 partial 5종+review.json이 완비된 **case 10**의 결정적 merge 재실행으로 검증한다(LLM 재실행 없이 코드 수준 불변성 입증).
- GT(`standard inspection GT data/`)에 PU2601233 폴더가 없어 `evaluate --case PU2601233`은 불가 — 분류 정답 검증은 AC-3의 육안 대조로 수행.

| ID | 기준 (이진 판정) |
|---|---|
| **AC-1** | `python -m pytest` 전체 통과. 기존 153개 수집 기준 실패 0 + 신규 테스트(6절 T-1~T-8) 전부 통과. |
| **AC-2 (하위호환 before/after)** | doctype sidecar가 없는 case 10에서 `merge-reviews --case 10` 재실행 결과가 기존 `.cache/10/10_review.json` 대비 `materials[]`/`findings[]` **deep-equal**이고, 신규 필드는 `"excluded_documents": []`뿐이다. |
| **AC-3 (분류 정확성)** | PU2601233에 Phase 1(캐시 재사용)→1.5→1.6 실행 후 `<stem>_doctype.json`이 73페이지 전부에 라벨을 부여하고, 사람이 컨택트시트로 대조한 결과 **완제품 MTC 페이지의 비-MTC 오분류(false exclude) 0건**(불확실 페이지는 UNKNOWN 허용), Wuyang 원자재 Mill Cert 블록과 자분탐상 보고서 블록이 각각 `MTC_RAW_MATERIAL`/`NDE_REPORT`로 식별된다. |
| **AC-4 (게이트)** | `check-doctype`가 4개 시나리오에서 명세된 exit code: ① 정상 혼재(PU2601233) → 0, ② stem 하나 doctype 부재 → 1 + `uncovered_stems`, ③ 페이지 누락/무효 라벨(합성) → 1, ④ 전 페이지 비-MTC(합성) → 1 + "사람 확인" 메시지. 제외율 >60% 합성 케이스는 exit 0 + WARNING 라인. |
| **AC-5 (인벤토리 차단)** | PU2601233 Phase 2 완료 후 `limits --case PU2601233` 산출 `PU2601233_limits.json`의 inventory에 원자재 grade(SA516 계열)가 **존재하지 않는다**. (doctype sidecar를 소급 적용한 합성 단위 테스트 T-4로도 동일 검증.) |
| **AC-6 (제외 메모)** | PU2601233 merge-reviews 산출 review.json에 `excluded_documents[]`가 존재하고 각 항목의 pages가 doctype sidecar와 일치하며, `findings[]`에는 제외 관련 항목이 **추가되지 않는다**. `compliance_report` 산출 xlsx의 "검토 총괄" 시트에 "제외됨: <한국어 유형>" 행이 렌더되고 한글이 깨지지 않는다(read-back 확인). |
| **AC-7 (OCR 커버리지 계약 유지)** | 제외 페이지가 minimal-entry로 기록된 상태에서 `check-extraction --case PU2601233`이 exit 0 (extraction_check.py 무수정). |
| **AC-8 (page-aligner 무회귀)** | `agents/page-aligner.md`와 `scripts/align_inputs.py` diff 0줄. `tests/test_orient_sheets.py` 기존 테스트가 무수정 통과(시트 빌더 파라미터화의 기본 경로 불변 입증). |
| **AC-9 (문서 동기화)** | SKILL.md(에이전트 표 9종·Phase 1.6 절·흐름도·시간예산·위임 스펙), README.md, `references/review-criteria.md` 기준 19, `references/extraction-schema.json`, 5개 reviewer 에이전트 문서, `.claude-plugin/marketplace.json`(1.4.0) 갱신 완료. |
| **AC-10 (데이터 위생)** | 커밋 diff에 고객 PDF/PNG/JSON 산출물 없음 (`.cache/`·`manifest.json`·`output/`은 기존 .gitignore로 차단 확인됨 — `git status`로 재확인). |

---

## 3. Implementation Steps

구현 순서 = 아래 Step 순서. 최종적으로 1개 feature 커밋(`feat(cert-review): 혼입 문서 페이지 분류(Phase 1.6) 및 비교 제외 — v1.4.0`)으로 묶는 것을 권장.

### Step 1 — `skills/cert-review/scripts/doctype.py` (신규, taxonomy 단일 소스 + 게이트 로직)

```python
"""doctype.py — Phase 1.6 per-page document-type classification support.

doc-classifier 에이전트가 기록한 <stem>_doctype.json을 결정적으로 검증·소비한다.
제외는 whitelist 방식: INCLUDED_DOC_TYPES 외 라벨만 제외하고, sidecar 부재·
필드 부재·미지 라벨은 전부 '검토 포함'으로 폴백한다(구버전 캐시 하위호환).
Constraint C1: JSON 읽기만. C7: pathlib + encoding='utf-8'.
"""
DOCTYPE_SUFFIX = "_doctype.json"

DOC_TYPES = (
    "MTC_FINISHED", "UNKNOWN",
    "MTC_RAW_MATERIAL", "PMI_REPORT", "APPEARANCE_DIMENSION_REPORT",
    "NDE_REPORT", "PHYSICAL_CHEMICAL_TEST_REPORT", "MICROSTRUCTURE_REPORT",
    "HEAT_TREATMENT_CHART", "REVIEWED_ANNOTATED_COPY",
    "COVER_LETTER", "MPS_COPY", "DRAWING",
)
INCLUDED_DOC_TYPES = frozenset({"MTC_FINISHED", "UNKNOWN"})
EXCLUDED_DOC_TYPES = frozenset(DOC_TYPES) - INCLUDED_DOC_TYPES
DOC_TYPE_LABELS_KO = {...}  # 1.4절 표 그대로

WARN_EXCLUDED_RATIO = 0.6  # 초과 시 경고(차단 아님)

def doctype_path(case_cache: Path, stem: str) -> Path: ...
def load_doctype(case_cache: Path, stem: str) -> dict | None:
    # align_inputs._load_json과 동일 관용구: 부재/파싱실패/비-dict → None
def excluded_pages_map(case_cache: Path, stem: str) -> dict[int, str]:
    # {page:int -> doc_type}, EXCLUDED_DOC_TYPES에 속한 라벨만.
    # sidecar 부재/무효 → {} (전 페이지 포함 폴백).
    # 페이지 키는 int() 변환 실패 시 스킵, 라벨이 DOC_TYPES 밖이면 '포함' 취급(스킵).
def compress_pages(pages: list[int]) -> str:
    # [30,31,55] -> "p.30-31, p.55" (정렬·연속 구간 압축)
def excluded_documents_for_case(case_cache: Path) -> list[dict]:
    # case_cache.glob(f"*{DOCTYPE_SUFFIX}") 순회, stem별 excluded_pages_map을
    # (연속 페이지 + 동일 doc_type) run으로 묶어:
    # {"stem", "doc_type", "doc_type_ko", "pages": [int,...], "page_range": "p.30-31",
    #  "note": f"제외됨: {ko} — 완제품 성적서가 아닌 동봉 문서로 분류되어 비교 검토에서 제외"}
    # 정렬: (stem, 첫 페이지). sidecar 없으면 [].
def check_doctype_case(case_id: str, cache_root: Path) -> dict:
    # tile_inputs._stems_in_png_dir(png_dir)로 렌더된 stem 인벤토리 확보
    #   (align_inputs.align_case:263과 동일 소스 — 커버리지 기준 일치).
    # stem별:
    #   sidecar 부재 -> uncovered_stems (게이트 실패)
    #   pages 맵 커버리지: PNG 페이지 집합과 gaps/extras 비교
    #   라벨 유효성: DOC_TYPES 밖 -> issue (게이트 실패)
    #   이상 게이트 A: included(MTC_FINISHED+UNKNOWN) == 0 -> issue
    #     "전 페이지가 비-완제품으로 분류됨 — 비정상, 사람 확인 필요" (게이트 실패)
    #   이상 게이트 B: pages_total >= 4 이고 excluded/pages_total > WARN_EXCLUDED_RATIO
    #     -> warnings에 추가 (exit 0 유지)
    # 반환: {"case_id","stems":[{stem,pages_total,included,excluded,by_type,
    #        uncertain_pages,issues,warnings,ok}],"uncovered_stems","warnings","ok"}
```

에러 처리: PNG 디렉토리 부재 시 `FileNotFoundError`(prep-inputs 먼저 실행 안내 — orient_sheets.py:129와 동일 관용구).

### Step 2 — `scripts/orient_sheets.py` 파라미터화 + `classify-sheets` CLI

`build_orient_sheets(case_id, cache_root, cols=3, rows=4, thumb_long=360, sheets_dirname=SHEETS_DIRNAME)`로 시그니처 확장 (orient_sheets.py:111). 함수 본문에서 `sheets_dir = case_cache / SHEETS_DIRNAME` (135행)을 `sheets_dirname` 인자로 치환 — **기본값 경로는 바이트 단위로 기존과 동일** (AC-8). `CLASSIFY_SHEETS_DIRNAME = "classify"` 상수를 `doctype.py`에 둔다.

`scripts/cli.py`에 서브커맨드 추가 (cli.py:741-747의 orient-sheets 등록 블록과 동일 패턴):

```python
def cmd_classify_sheets(args):
    """Phase 1.6: compose upright contact sheets for document-type classification."""
    from scripts.orient_sheets import build_orient_sheets
    from scripts.doctype import CLASSIFY_SHEETS_DIRNAME
    # align-inputs 이후 실행 전제 — 정립된 png/에서 합성
    summary = build_orient_sheets(case_id=args.case, cache_root=CACHE_DIR,
                                  sheets_dirname=CLASSIFY_SHEETS_DIRNAME)
    ...  # cmd_orient_sheets와 동일한 출력 형식
```

주의: orient 시트는 **정렬 전** 픽셀로 합성된 기존 산출물이므로 재사용 금지 — 반드시 align-inputs 이후 `classify/`에 새로 합성한다(회전 썸네일로는 letterhead/표제 판독 불가 — PU2601233 51/73p 회전).

### Step 3 — `check-doctype` CLI 게이트

`cmd_check_doctype(args)` — `cmd_align_inputs`(cli.py:478-510)의 출력·exit 관용구를 그대로 따른다: stem별 요약 라인, `uncovered_stems` 안내("re-delegate doc-classifier"), WARNING 라인은 `[WARN]` 프리픽스, `return 0 if summary["ok"] else 1`. 파서 등록은 `--case` 필수 단일 인자.

### Step 4 — `agents/doc-classifier.md` (신규 에이전트)

frontmatter:

```yaml
---
name: doc-classifier
description: Dedicated agent for cert-review Phase 1.6 that classifies each rendered 성적서 page into a document-type taxonomy (finished-product MTC vs enclosed non-MTC documents) from upright contact sheets and emits <stem>_doctype.json — explicitly invoked by the cert-review skill orchestrator after page alignment and before OCR; not subject to automatic delegation.
model: claude-opus-4-8
---
```

본문 구성 (page-aligner.md의 절 구조를 템플릿으로):

1. **Context Received**: case id, SKILL_DIR 절대경로.
2. **Constraints**: C1(Read 도구로 PNG만), 3-카테고리 whitelist, rawdata/GT 금지, `pNN` 라벨바가 아닌 페이지 콘텐츠로 판단.
3. **Procedure**:
   - `.cache/<case>/classify/sheets_index.json` 읽기 → 모든 시트 Read (누락 금지, 메시지당 복수 배치).
   - **1차 coarse 분류(시트 썸네일)**: 레이아웃·표제·사진/차트 유무로 후보 라벨. PMI/외관치수/NDE/온도차트/조직사진은 썸네일 수준에서 판별 가능.
   - **문서 run 연속성 규칙**: 연속 페이지에서 letterhead·발행자·양식이 동일하면 같은 문서로 취급하고 run 단위로 라벨 부여. **완제품 MTC 문서 내부의 PMI/NDE/치수 기재 섹션·페이지는 별도 문서가 아니다** — 문서 경계(발행자/양식 변화)에서만 라벨이 바뀐다.
   - **2차 정밀판별(MTC류 run 경계만)**: MTC형 표가 있는 run의 첫 페이지(및 양식 변화 지점)에 한해 헤더 타일 `.cache/<case>/tiles/<stem>_pNN_r0c0.png`(필요 시 `r0c1`)을 Read하여 제품형태·규격 문자열로 `MTC_FINISHED` vs `MTC_RAW_MATERIAL` 판별. 판별 기준: 제품형태가 plate/billet/bar/coil 등 소재이면 원자재, 파이프/피팅/플랜지 완제품이면 완제품. **MPS는 읽지 않는다**(Phase 1.6 시점에 digest 미존재).
   - **보수 원칙**: 확신이 없으면 해당 페이지 full render(`png/<stem>_pNN.png`)를 1회 재확인, 그래도 불확실하면 `UNKNOWN` + `uncertain_pages` 기록. **비-MTC 라벨은 명확한 근거가 있을 때만** 부여(page-aligner의 "불확실→0"과 동일 철학).
   - taxonomy 표(1.4절 그대로, 판정 단서 포함) 수록.
4. **Output** — `SKILL_DIR\.cache\<case>\<stem>_doctype.json` (UTF-8):

```json
{
  "schema_version": "1.0",
  "stem": "<cert_stem>",
  "pages": {"1": "MTC_FINISHED", "30": "MTC_RAW_MATERIAL"},
  "uncertain_pages": [17],
  "documents": [
    {"doc_type": "MTC_RAW_MATERIAL", "pages": [30, 31], "issuer": "<보이는 대로>", "evidence": "판단 근거 1줄"}
  ]
}
```

`pages`는 stem의 **전 페이지** 포함(누락 금지), 값은 `DOC_TYPES` 13종만. `documents`는 run 단위 근거(권장, 게이트 비검증 대상).
5. **Self-check**: pages 커버리지 = sheets_index 페이지 집합, 라벨 유효성, 전량 비-MTC이면 스스로 재검토 후 그래도 같으면 완료 보고에 명시.
6. **Completion report**: stem별 유형 분포, uncertain 목록+사유, 산출 파일 절대경로.

### Step 5 — `scripts/prep_inputs.py` 재렌더 시 doctype 무효화

prep_inputs.py:188-194 (재렌더 직전 orientation/alignment 삭제 블록)에 `doctype_path(case_cache, cert_stem).unlink(missing_ok=True)` 추가. `_purge_stem_renders`(prep_inputs.py:51-55)의 targets 튜플에 classify 시트 패턴 추가:

```python
(case_cache / "classify", re.compile(re.escape(cert_stem) + r"__sheet\d+\.png\Z")),
```

cache-status(`extraction_check.py`)는 **수정하지 않는다** — doctype 부재를 stale 사유로 삼지 않는다(레거시 fresh 캐시는 분류 없이 fresh 유지, whitelist 폴백으로 현재 동작과 동일). stale/missing 재수행 경로에서의 Phase 1.6 수행은 SKILL.md 절차가 담당.

### Step 6 — `references/extraction-schema.json` `doc_type` 추가

`page_extraction.items.properties`(29-121행)에 optional 필드 추가 — `schema_version` const "2.0" 유지(additive optional, 기존 파일 호환):

```json
"doc_type": {"enum": ["MTC_FINISHED", "UNKNOWN", "MTC_RAW_MATERIAL", "PMI_REPORT",
  "APPEARANCE_DIMENSION_REPORT", "NDE_REPORT", "PHYSICAL_CHEMICAL_TEST_REPORT",
  "MICROSTRUCTURE_REPORT", "HEAT_TREATMENT_CHART", "REVIEWED_ANNOTATED_COPY",
  "COVER_LETTER", "MPS_COPY", "DRAWING", null]}
```

### Step 7 — `agents/ocr-extractor.md` 개정 (L1)

full mode 절(57-81행)과 fragment mode 절(84-95행)에 동일하게 추가:

- **입력 추가**: 위임 시작 시 `.cache/<case>/<stem>_doctype.json`을 읽는다(부재 시 전 페이지를 MTC_FINISHED로 간주 — 기존 동작).
- **minimal-entry 규칙**: `EXCLUDED` 라벨 페이지는 표 전사를 생략하고 다음 entry만 기록: `{"page": N, "header": {}, "doc_type": "<라벨>", "remarks": ["문서 유형: <한국어 라벨> — 완제품 성적서가 아닌 동봉 문서로 분류, 비교 검토 제외 대상"], "confidence": "high"}`. 기존 "표 없는 페이지도 entry+remarks" 규칙(66행)의 확장이므로 check-extraction 계약 불변.
- **doc_type 스탬프**: MTC_FINISHED/UNKNOWN 페이지도 entry에 `doc_type`을 기록(전사 내용은 기존 그대로).
- **인벤토리 규칙 수정**(77행, step 7): (Grade, Class, Heat) 인벤토리는 **MTC_FINISHED/UNKNOWN 페이지의 헤더만으로** 구성.
- **정합 이상 보고**: 제외 페이지에서 완제품 run과 동일 heat·grade의 완전한 MTC 표가 보이면(오분류 의심) 전사하지 말고 completion report에 "분류 재확인 요청"으로 보고(오케스트레이터가 doc-classifier 재위임 판단).

### Step 8 — `scripts/refpack.py` 인벤토리 필터 (L2, 결정적)

`collect_inventory`(78-104행) 수정 — diff 스케치:

```python
from scripts.doctype import excluded_pages_map   # 파일 상단 import

def collect_inventory(case_cache: Path) -> list[dict]:
    ...
    for jp in sorted(case_cache.glob("*_extracted.json")):
        ...
        stem = jp.name[: -len("_extracted.json")]
        excluded = excluded_pages_map(case_cache, stem)   # 부재 시 {}
        for entry in data.get("page_extraction") or []:
            if not isinstance(entry, dict):
                continue
            page = entry.get("page")
            try:
                page_no = int(page)
            except (TypeError, ValueError):
                page_no = None
            if page_no is not None and page_no in excluded:
                continue                                   # 제외 페이지 header 스킵
            header = entry.get("header") or {}
            ...
```

entry의 `doc_type` 필드는 여기서 판정에 쓰지 않는다(권위는 sidecar 단일) — 문서화 주석 1줄.

### Step 9 — `scripts/merge_reviews.py` `excluded_documents` 주입 (L4, 결정적)

`merge_case`(122행) 마지막 review dict 조립부(286-293행)에 `"excluded_documents": excluded_documents_for_case(case_cache)` 추가. 반환 summary에 `"n_excluded_docs"` 추가, `cmd_merge_reviews`의 `_print_case`(cli.py:591-604)에 `excluded docs: N` 라인 추가. findings에는 어떤 항목도 추가하지 않는다(기준 17.7 정합, `eval_harness.load_predictions`(435행) 무영향). 모듈 docstring의 "merged JSON schema INVARIANT" 문구(19-23행)를 신규 필드 포함으로 갱신.

### Step 10 — `scripts/compliance_report.py` 검토 총괄 제외 블록 (L5)

`build_compliance_report`의 검토 총괄 materials 루프 종료 지점(283행 `r += 1` 루프 이후, 285행 화학 시트 이전)에 삽입:

```python
    excluded_docs = review.get("excluded_documents") or []
    if excluded_docs:
        r += 1
        hc = ws.cell(row=r, column=1)
        hc.value = "검토 제외 문서 (완제품 성적서 아님 — 동봉 문서)"
        hc.font = Font(bold=True)
        r += 1
        for d in excluded_docs:
            ws.cell(row=r, column=1).value = "제외됨"
            ws.cell(row=r, column=2).value = d.get("doc_type_ko", d.get("doc_type", ""))
            ws.cell(row=r, column=3).value = d.get("stem", "")
            ws.cell(row=r, column=4).value = d.get("page_range", "")
            ws.cell(row=r, column=5).value = d.get("note", "")
            r += 1
```

`Font`는 상단 openpyxl import 확인 후 없으면 추가. 구버전 review.json(필드 부재)은 `or []`로 무변화. 다른 시트 무수정.

### Step 11 — `skills/cert-review/SKILL.md` 개정

1. **에이전트 표**(55-64행): `doc-classifier | claude-opus-4-8 | Phase 1.6 per-page document-type classification (classification only — exclusion applied by deterministic CLI/merge) | <stem>_doctype.json` 행 추가. "8 plugin subagents" → 9.
2. **Directory Layout**(96-115행): `classify/` 디렉토리, `<stem>_doctype.json`, agents 목록에 doc-classifier.md 추가.
3. **Phase 절 신설** — 기존 "2.5) tile-inputs" 다음: `2.6) classify-sheets`(결정적) / `2.7) doc-classifier delegation`(Phase 1.6, MANDATORY before OCR — 위임 컨텍스트: case id·SKILL_DIR 절대경로·산출 의무(전 페이지)·준수사항(C1, 3-카테고리 whitelist, 문서 run 연속성, UNKNOWN 보수 원칙, 라벨바 아닌 콘텐츠 판단); 상세 절차는 agents/doc-classifier.md 보유, SKILL.md 중복 금지) / `2.8) check-doctype` — **[GATE] exit 0 필수**, exit 1 사유(미산출 stem 재위임/커버리지·라벨 오류/전량 비-MTC → 사람 확인 요청·진행 중단), WARNING(제외율>60%) 시 경계 페이지 2~3장 full-page 재확인 후 진행. 기존 "2.6) prep-mps" → "2.9)" renumber.
4. **ocr-extractor 위임 컨텍스트 스펙**(255-259행): doctype 맵 소비·minimal-entry·인벤토리 규칙 항목 추가.
5. **5개 reviewer 위임 컨텍스트**(300-305행): "doc_type이 EXCLUDED인 페이지 데이터는 비교·재료 등록·근거 인용 금지(제외 메모는 결정적 경로 담당)" 1줄 추가.
6. **흐름도**(378-407행): Phase 1.5와 2 사이 `Phase 1.6 classify-sheets → [delegate doc-classifier/opus] → <stem>_doctype.json → check-doctype (exit 0 required)` 추가.
7. **시간예산 절**(150-158행): 구조 장치 ⑦ — 비용 단순 +2~4분 / 표준 +3~5분 / 복합(73p) +10~15분, 제외 페이지 minimal-entry OCR로 상쇄(혼재 복합 순증 ≈ 0±5분), 티어 목표(≤30/≤60/60~90분) 불변.
8. **Parallel-execution rules**: doc-classifier 케이스당 1회, 동시 에이전트 총량 6-10 캡 포함.

### Step 12 — `references/review-criteria.md` 기준 19 신설 + reviewer 문서 5종

- 기준 18 이후에 **"## 19. 동봉 문서(비-완제품 성적서) 페이지 분류 및 검토 제외"** 신설: taxonomy 표, whitelist 원칙(UNKNOWN 포함), "제외 페이지의 값은 어떤 도메인 비교에도 사용하지 않는다", "제외 사실은 findings가 아니라 review.json `excluded_documents`로 보고(기준 17.7 정합)", 기준 17.1의 별도 문서 규칙과의 관계(첨부 존재/부재 판정은 범위 외 — 향후 과제) 명시.
- 5개 reviewer 에이전트 문서 "Input Artifacts"/"Input/Output Contract" 절에 각 1-2줄: "Page entries whose `doc_type` is an EXCLUDED type (see 기준 19) are enclosed non-MTC documents: do not compare their values, do not register their grades/heats into materials[], do not cite them as evidence. The exclusion memo is emitted deterministically by merge-reviews — do not raise findings about them."
- `format-reviewer.md` 기준 16 절(89-92행)에 1줄: 커버리지 검증 대상은 `<case>_limits.json`의 inventory(이미 doctype 필터 적용) 기준 — 제외된 원자재 grade의 미커버리지를 지적하지 말 것.

### Step 13 — `README.md`(스킬)·`.claude-plugin/marketplace.json`

- README 파이프라인 다이어그램(56-62행)에 Phase 1.6 삽입, 에이전트 표에 doc-classifier 추가, Inputs 절에 "혼입 동봉 문서는 Phase 1.6에서 페이지 단위 분류·제외" 1문 추가, 테스트 수 갱신.
- marketplace.json: version `1.3.0` → `1.4.0`(8행), description(14행)에 분류 기능 반영, "에이전트 8종" → "9종".

### Step 14 — 테스트 (합성 fixture만, 고객 데이터 커밋 금지)

6절의 T-1~T-8. 기존 관례(tmp_path 합성 캐시, conftest.py dataset-coupled skip)를 따르되 신규 테스트는 전부 dataset 비의존(portable).

### 엣지 케이스 총괄 (구현 시 반드시 처리)

| # | 케이스 | 처리 |
|---|---|---|
| E1 | 멀티 stem 케이스(예: case 4 — PDF 2개) | doctype는 stem별 파일. check-doctype는 stem 단위 커버리지(`_stems_in_png_dir`) |
| E2 | doctype sidecar 부재(레거시 fresh 캐시) | 전 경로 whitelist 폴백 = 현재 동작. cache-status 무수정 |
| E3 | 혼입 문서가 파일 첫 페이지 | run 경계 로직은 위치 무관. 단위 테스트 T-2로 커버 |
| E4 | 전 페이지 UNKNOWN | included > 0이므로 게이트 통과, 전량 검토(보수) |
| E5 | 전 페이지 EXCLUDED | check-doctype exit 1 + 사람 확인 |
| E6 | 제외 페이지 대상 crop/annotate | bbox 공간은 alignment 기준으로 불변 — 무영향 |
| E7 | fragment mode에서 세그먼트 전체가 제외 페이지 | minimal-entry fragment 정상 산출, merge-parts 무수정 |
| E8 | 원자재 heat_no == 완제품 heat_no | 제외로 유령 material 방지. merge 키 `(heat_no, grade_cert)` verbatim 규약 무변경 |
| E9 | doctype pages에 PNG에 없는 페이지(extra) | check-doctype issue → exit 1 |
| E10 | `page` 필드가 문자열 숫자인 extracted entry | refpack 필터에서 int() 변환 후 비교 (extraction_check.py:94-95 관용구) |

---

## 4. Code Writing Guide

- **인코딩**: 모든 파일 I/O `encoding="utf-8"`, CLI 예시는 `PYTHONIOENCODING=utf-8` 프리픽스. 한국어 문자열 작성 후 read-back으로 한글 무결성 확인(깨짐 발견 시 수정 전까지 완료 보고 금지). "§" 사용 금지 — "기준 N" 표기.
- **모델 고정**: 신규 에이전트 frontmatter `model: claude-opus-4-8`. haiku/sonnet A/B 제안·수행 금지. `CLAUDE_CODE_SUBAGENT_MODEL` 미설정 실행 주의 문구 유지.
- **캐시 sidecar 관례**: 에이전트 산출(`<stem>_doctype.json`) → 결정적 게이트(`check-doctype`, exit 0/1) 2단 구조. 픽셀 변형이 없으므로 2상 커밋 불필요 — "부재=구버전(전 페이지 검토 폴백)/존재=검증 대상" 2상태 명시. 재렌더 시 prep-inputs가 sidecar 삭제로 멱등성 보장.
- **whitelist 제외 원칙**: 제외 판정은 반드시 `EXCLUDED_DOC_TYPES` 멤버십으로만. `!= "MTC_FINISHED"` 식 blacklist 비교 금지.
- **taxonomy 단일 소스**: 코드에서는 `scripts.doctype` 상수만 import. 문자열 리터럴 재정의 금지.
- **기존 관용구 재사용**: JSON 로드 `align_inputs._load_json`, stem 인벤토리 `tile_inputs._stems_in_png_dir`, CLI 출력/exit `cmd_align_inputs`, 시트 합성 `orient_sheets` 파라미터화(복붙 금지).
- **불변 영역 (수정 금지)**: `agents/page-aligner.md`, `scripts/align_inputs.py`, `scripts/orient_sheets.py` 기본 경로 동작, `scripts/extraction_check.py`, `scripts/eval_harness.py`, `hermes-loop/`, `ref_code`/`rawdata`/GT 데이터, 실물 조사 폴더 `Cert_Auto_examine\MTC`(읽기 전용).
- **문서 언어 규약**: 플러그인 agents/SKILL 문서는 영어 본문 + 한국어 키워드/출력 예시 보존. 리포트 산출물·remarks 한국어.
- **네이밍**: `doc-classifier`(kebab), `_doctype.json`, CLI `classify-sheets`/`check-doctype`, 디렉토리 `classify/`, 필드 `excluded_documents`.
- **커밋**: 고객 데이터는 .gitignore로 차단 — 커밋 전 `git status` 재확인. conventional commit(한국어 요약).
- **금지 패턴**: 기존 계약 변경(check-extraction 전 페이지 커버리지, merge 키 verbatim, findings 스키마), findings에 제외 메모 주입(기준 17.7 위반 + eval precision 오염), MPS를 Phase 1.6에서 읽기, 임시 스크립트로 Vision OCR 대체(C1).

---

## 5. Definition of Done

전 항목 이진 판정:

1. `python -m pytest` exit 0 (기존 153 + 신규 전부, 실패·에러 0).
2. `git diff --stat`에 `agents/page-aligner.md`, `scripts/align_inputs.py`, `scripts/extraction_check.py`, `scripts/eval_harness.py` 미포함.
3. AC-2 성립 (case 10 merge 재실행 deep-equal + `excluded_documents: []`).
4. AC-3 성립 (PU2601233 73페이지 전 라벨 + 육안 대조 false-exclude 0건 — 대조 기록을 완료 보고에 첨부).
5. AC-4의 exit code 매트릭스 4개 시나리오 + WARNING 시나리오 성립.
6. AC-5 성립 (PU2601233 limits inventory에 원자재 grade 부재).
7. AC-6 성립 (excluded_documents 주입 + findings 미오염 + xlsx "제외됨" 행 렌더 + 한글 read-back 무결).
8. AC-7 성립 (check-extraction exit 0, extraction_check.py 무수정 상태에서).
9. AC-9 문서 동기화 파일 전부 커밋 포함(doc-classifier.md 신규 포함 10개), taxonomy 4곳 목록 일치.
10. `git status` 클린(추적 외 고객 데이터 없음), main에 커밋+푸시 완료.

---

## 6. Adversarial Test Environment

### 6.1 자산 확정 (조사 결과)

- **PU2601233** (in-harness, manifest 47케이스 중 1): 73p 혼재 실물(LS룽산 완제품 MTC 다수 + Wuyang 원자재 Mill Cert + 자분탐상 보고서). `.cache`에 DPI300 렌더 73장·orientation·alignment 완비, extracted는 빈 스켈레톤. GT comments.md 없음 → evaluate 불가, 분류 검증은 육안 대조.
- **case 10** (순수, partial 5종 + `10_review.json` 완비): 결정적 merge 회귀 베이스라인.
- **case 53** (동림 F22/F91 — 동림 발행분은 전부 순수): extracted 완비 → Phase 1.6만 실행해 "순수 파일 100% 포함 분류" 검증.
- PU2601565-01/02, PU2601058-01, PU2600718-01, PU2601859-01 등 기타 혼재 실물은 manifest 대조 결과 **harness 부재** — 신규 반입 없이 향후 과제로 명시(1.5절). 경계 시나리오는 합성 단위 테스트로 커버.

### 6.2 단위 테스트 (신규, 전부 합성 fixture — tmp_path)

| ID | 파일 | 내용 | 검증 DoD |
|---|---|---|---|
| T-1 | `tests/test_doctype.py` | `excluded_pages_map`(부재→{}, 미지 라벨→포함, 문자열 키 변환), `compress_pages`, `excluded_documents_for_case`(run 묶음·한국어 라벨·정렬) | DoD-1 |
| T-2 | `tests/test_doctype.py` | `check_doctype_case` 매트릭스: 정상 혼재 ok / stem 부재 uncovered / gap·extra / 무효 라벨 / 전량 비-MTC → not ok / 제외율 70% → ok+warning / 혼입 p.1 합성 케이스 | DoD-5 |
| T-3 | `tests/test_orient_sheets.py` (확장) | `sheets_dirname="classify"` 시 `classify/` 생성, 기본 인자 기존 테스트 무수정 통과 | DoD-2 |
| T-4 | `tests/test_refpack.py` (확장) | 제외 페이지 SA516형 header 인벤토리 미포함, sidecar 없으면 기존 동일 | DoD-6 |
| T-5 | `tests/test_merge_reviews.py` (확장) | excluded_documents 주입·pages 일치·findings 불변, sidecar 없으면 `[]` | DoD-3·7 |
| T-6 | `tests/test_prep_cache.py` (확장) | 재렌더 시 doctype·classify 시트 삭제 | DoD-1 |
| T-7 | `tests/test_compliance_report_excluded.py` (신규) | excluded_documents 있는 합성 review.json → xlsx 검토 총괄 시트 "제외됨" 행·한국어 라벨 존재, 필드 부재 시 기존 렌더 동일 | DoD-7 |
| T-8 | `tests/test_no_python_ocr.py` (기존 자동 커버) | 신규 모듈 C1 금지 import 없음 | DoD-1 |

### 6.3 통합·적대 시나리오 (실데이터, 런타임 참조만 — 커밋 없음)

| ID | 시나리오 | 절차 | 판정 |
|---|---|---|---|
| AT-1 | 혼재 73p 실물 분류 | PU2601233: classify-sheets → doc-classifier 위임 → check-doctype | AC-3, AC-4-① |
| AT-2 | 완제품과 시각적으로 유사한 표 레이아웃 | Wuyang 원자재 Mill Cert(완제품과 동일한 밀시트 양식)가 `MTC_RAW_MATERIAL`로, LS룽산 완제품이 `MTC_FINISHED`로 분리되는지 — 헤더 타일 정밀판별 실측 | AC-3 |
| AT-3 | 파이프라인 관통 | PU2601233 Phase 2→2.5→limits→merge-reviews→compliance_report | AC-5·6·7 |
| AT-4 | 순수 파일 무영향 | case 53 두 stem Phase 1.6만 실행 → 전 페이지 MTC_FINISHED, `excluded_documents: []` | DoD-4 유사 |
| AT-5 | 하위호환 | case 10 (sidecar 없음) merge 재실행 deep-equal | AC-2 |

AT-3 비용 주의: PU2601233 전체 OCR은 opus 60분+ — 부담 시 fragment 2개 세그먼트(완제품 run 1 + 원자재/NDE run 1, 합계 ≤8p)만 OCR하고 잔여 페이지는 minimal-entry로 채운 후 AC-7 전체 exit 0 확인(축약 사용 시 완료 보고에 명시).

---

## 7. Risks and Mitigations

| # | 리스크 | 영향 | 완화 |
|---|---|---|---|
| R1 | **false exclude** — 완제품 페이지 오분류로 실제 결함 미검출 | 치명 | 문서 run 연속성 규칙 + "비-MTC는 명확한 근거 필수, 불확실=UNKNOWN" + check-doctype 전량제외 차단·60% 경고 + AT-1/AT-2 육안 검증 0건 게이트 |
| R2 | page-aligner 회귀 | 95.89% 실측 자산 훼손 | 코드·문서 무수정(DoD-2), 시트 빌더 기본 경로 불변(T-3) |
| R3 | 시간예산 초과 | 복합 90분 상한 압박 | coarse 시트 + run 경계만 정밀 Read(+10~15분), minimal-entry OCR 상쇄(순증 ≈ 0±5분), SKILL.md 정량 명시 |
| R4 | 구버전 캐시 비호환 | fresh 케이스 오동작 | whitelist 폴백(부재=현재 동작), cache-status 무수정, AC-2 입증 |
| R5 | eval 지표 오염 | 46케이스 회귀 지표 변동 | 제외 메모를 findings가 아닌 `excluded_documents`로 — load_predictions 무변경(코드 확인 완료) |
| R6 | 에이전트 L1 미준수 | 부분 오염 | 권위는 sidecar — L2/L4가 결정적 차단, L1은 시간 최적화로 격하 |
| R7 | 플러그인 vs 배포본 분기 | 배포 리포트 미반영 | 소스는 plugin repo 단일(커밋+푸시 → marketplace auto-update). 작업폴더 `.claude/skills` 사본 동기화 필요 여부를 구현 완료 시 확인·보고(통째 복사 금지) |
| R8 | taxonomy 4곳 표류 | 라벨 불일치 | 코드 단일 소스 + DoD-9 점검, 4곳 동시 갱신 규칙을 doctype.py docstring 명기 |

---

## 8. Verification Steps

SKILL_DIR에서 `$env:PYTHONIOENCODING="utf-8"` 설정 후 순서대로:

```powershell
# V1. 단위 회귀
python -m pytest -q                                     # exit 0, 실패 0

# V2. 하위호환 before/after (case 10, LLM 불필요)
Copy-Item .cache\10\10_review.json $env:TEMP\10_review_before.json
python -m scripts.cli merge-reviews --case 10
# → materials/findings deep-equal + excluded_documents == [] 파이썬 원라이너 비교

# V3. Phase 1.6 실물 (PU2601233 — 캐시 렌더 재사용)
python -m scripts.cli cache-status --case PU2601233
python -m scripts.cli classify-sheets --case PU2601233
# → doc-classifier 위임 → <stem>_doctype.json
python -m scripts.cli check-doctype --case PU2601233    # exit 0, 유형 분포 출력
# → 사람 육안 대조: classify 시트 vs doctype.json (false exclude 0건 기록)

# V4. 게이트 시나리오 (합성 doctype 임시 조작 → 원복)
#    stem 부재/무효 라벨/전량 비-MTC 각각 exit 1, 제외율 70%는 exit 0 + [WARN]

# V5. 파이프라인 관통 (AT-3 — 필요 시 축약 절차)
python -m scripts.cli check-extraction --case PU2601233 # exit 0 (minimal-entry 포함)
python -m scripts.cli limits --case PU2601233           # inventory에 SA516 부재 확인
python -m scripts.cli merge-reviews --case PU2601233
# → excluded_documents 페이지 == doctype sidecar 대조
# → compliance_report 실행 후 xlsx read-back: "제외됨" 행·한글 무결 확인

# V6. 순수 케이스 무영향 (case 53)
python -m scripts.cli classify-sheets --case 53
# → doc-classifier 위임 → check-doctype exit 0, 제외 0건 확인

# V7. 커밋 위생 및 배포
git status        # .cache/manifest/xlsx 미추적 확인
git diff --stat   # page-aligner/align_inputs/extraction_check/eval_harness 미포함 확인
# → 커밋 + push. 작업폴더 배포본 코드 동기화 필요 여부 확인·보고
```

각 V 단계는 실행 결과(exit code·출력 샘플·한글 read-back)를 완료 보고에 포함한다. V3의 육안 대조만 사람 확인이 필요하며, 그 외 전 단계는 executor가 직접 실행·검증한다.
