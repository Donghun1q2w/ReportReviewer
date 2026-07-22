# 2026-07-22 — 혼입 문서 페이지 분류(Phase 1.6 doc-classify) 및 비교 제외 — v1.4.0

**Summary**: 접수 MTC PDF에 임의 위치로 혼입되는 완제품 성적서 외 문서(원자재 Mill Cert·PMI·NDE·외관치수·이화학·조직시험·열처리차트 등)를 페이지 단위로 분류해 화학/기계/열처리/NDE/형식 비교 대상에서 제외 — 신규 전담 에이전트 `doc-classifier`(Phase 1.6), page-aligner 무수정.

**Plan**: [2026-07-22_170520_mtc-doc-classification-phase16](../plans/2026-07-22_170520_mtc-doc-classification-phase16.md) (dh-dev 승인 완료)

## Rationale

실물 조사(`Cert_Auto_examine\MTC`, 30개 PDF 전수) 결과 15개(50%, 페이지 기준 771p 중 약 77%)에서 완제품 성적서와 비-완제품 문서가 한 PDF에 혼재됨을 확인 — 공급사별 체계적 패턴(동림=순수, 중국 LS룽산=대부분 혼재). 현재 파이프라인은 파일 내 전 페이지를 완제품 성적서로 간주해 화학/기계/열처리/NDE 비교 및 GRADE_MAP 라우팅 인벤토리 오염 위험이 있었음. 사용자 확정 스코프(dh-dev Step 1-b 인터뷰): 1단계는 비교 대상 제외만 구현, MPS 요구사항 대비 첨부 여부 자동판정은 후속 과제로 분리.

## Changed Files

| 파일 | 상태 | 설명 |
|---|---|---|
| `skills/cert-review/scripts/doctype.py` | added | taxonomy 단일 소스(13종 DOC_TYPES) + whitelist 판정(`INCLUDED={MTC_FINISHED,UNKNOWN}`) + `check_doctype_case` 게이트 로직 |
| `agents/doc-classifier.md` | added | Phase 1.6 전담 에이전트(claude-opus-4-8) — 정립 시트 기반 페이지 문서유형 분류(분류만; 제외는 결정적 코드가 적용) |
| `skills/cert-review/tests/test_doctype.py` | added | `excluded_pages_map`/`compress_pages`/`excluded_documents_for_case`/`check_doctype_case` 매트릭스(합성 fixture) |
| `skills/cert-review/tests/test_compliance_report_excluded.py` | added | xlsx "제외됨" 블록 렌더 검증(합성 review.json) |
| `skills/cert-review/scripts/refpack.py` | modified | `collect_inventory`에 L2 결정적 필터 — doctype sidecar 기준 제외 페이지 header를 인벤토리에서 스킵(원자재 grade 오염 차단) |
| `skills/cert-review/scripts/merge_reviews.py` | modified | L4 결정적 주입 — review.json에 `excluded_documents[]` 추가(findings 미오염, 기준 17.7 정합), sidecar 없으면 `[]` |
| `skills/cert-review/scripts/compliance_report.py` | modified | L5 — 검토 총괄 시트에 "제외됨: <한국어 유형>" 블록 렌더 |
| `agents/ocr-extractor.md` | modified | L1 — doctype sidecar 소비, minimal-entry 전사 규칙, (Grade,Class,Heat) 인벤토리를 MTC_FINISHED/UNKNOWN 페이지로 한정 |
| `agents/{chemistry,mechanical,heat-treatment,nde,format}-reviewer.md` | modified | L3 — EXCLUDED 페이지 데이터 비교·materials[] 등록·근거 인용 금지 1줄 |
| `skills/cert-review/scripts/cli.py` | modified | `classify-sheets`/`check-doctype` 서브커맨드 |
| `skills/cert-review/scripts/orient_sheets.py` | modified | `build_orient_sheets`에 `sheets_dirname` 파라미터화(기본 경로 바이트 단위 불변) |
| `skills/cert-review/scripts/prep_inputs.py` | modified | 재렌더 시 doctype sidecar·classify 시트 삭제(멱등성) |
| `skills/cert-review/references/extraction-schema.json` | modified | `doc_type` optional enum 필드 추가(schema_version 2.0 유지) |
| `skills/cert-review/references/review-criteria.md` | modified | 기준 19 신설(동봉 문서 분류·제외 원칙) |
| `skills/cert-review/SKILL.md` | modified | 에이전트 표 9종, Phase 1.6 절(classify-sheets→doc-classifier→check-doctype 게이트) 삽입, 흐름도·시간예산·위임 스펙 갱신 |
| `skills/cert-review/README.md` · `.claude-plugin/marketplace.json` | modified | Phase 1.6 반영, v1.3.0→**1.4.0**, 테스트 수 145→184 정정 |
| `skills/cert-review/tests/test_{merge_reviews,orient_sheets,prep_cache,refpack}.py` | modified | 하위호환·시트 파라미터화·재렌더 정리·인벤토리 필터 회귀 |

## Details

### 아키텍처 결정 (계획 1.3절)
- **별도 신규 에이전트 채택, page-aligner 확장 기각**: page-aligner는 95.89% 실측 확정 회귀-critical 컴포넌트(코드·문서 무수정 보존). 회전 감지(정렬 전 이미지)와 문서유형 분류(정렬 후 이미지 필요 — letterhead/규격 문자열 판독)는 입력이 구조적으로 다름.
- **5중 방어**: L1(에이전트 minimal-entry) → L2(refpack 결정적 필터) → L3(reviewer 규칙) → L4(merge_reviews 결정적 주입) → L5(compliance_report 렌더). 판정의 단일 결정적 권위는 `<stem>_doctype.json` sidecar — 에이전트가 doc_type 스탬프를 빠뜨려도 L2/L4가 sidecar 기준으로 동작.
- **whitelist 폴백**: sidecar 부재·필드 부재·미지 라벨은 전부 "검토 포함"(구버전 캐시 하위호환 = 기존 동작 그대로).

### 검증
- `pytest tests/` **184 passed**(기존 145+신규 39, 회귀 0) — 오케스트레이터가 독립 재실행으로 재확인.
- **AC-2 하위호환**: doctype sidecar 없는 case 10에서 merge-reviews 재실행 결과가 기존 `10_review.json` 대비 materials/findings **deep-equal**, 신규 필드는 `excluded_documents: []`뿐.
- **AC-3 실물 검증(PU2601233, 73p 혼재)**: doc-classifier 위임 후 classify 시트 7장 전부 육안 대조 — p.1-14 완제품(Longshan) MTC_FINISHED, p.15-50 원자재 Mill Cert(Baoshan/Wuyang/JFE 등) MTC_RAW_MATERIAL, p.51-57 열처리차트 HEAT_TREATMENT_CHART, p.58-71 이화학시험 PHYSICAL_CHEMICAL_TEST_REPORT, p.72-73 자분탐상 NDE_REPORT. **완제품 오분류(false exclude) 0건**.
- **AC-5 인벤토리 차단**: `limits --case PU2601233` 산출 inventory에 원자재 grade(SA516 계열) 부재를 인과 통제실험(sidecar 유/무 비교)으로 확인.
- **부수 발견(case 53)**: 계획은 case 53을 "전부 순수"로 가정했으나 실제로는 F91 파일에 LAIGANG 원자재 환봉cert + MEISTERLAB 미세조직보고서가 동봉되어 있었음 — Phase 1.6이 이를 정확히 MTC_RAW_MATERIAL/MICROSTRUCTURE_REPORT로 식별, 완제품 2p는 정상 유지. 계획의 가정 오류를 기능이 실측으로 보정.
- **오케스트레이터 독립 재검증**: `git show --stat 8d38090`로 불변 영역(`page-aligner.md`/`align_inputs.py`/`extraction_check.py`/`eval_harness.py`) 미포함 확인, `refpack.py`/`merge_reviews.py` diff 육안 검토(whitelist·sidecar 권위·하위호환 폴백 로직 확인), `doc-classifier.md` frontmatter `model: claude-opus-4-8` 확인, `marketplace.json` 1.4.0/9종 확인.

### 선재 이슈 (이번 작업과 무관, 별도 조치 필요)
- `limits` CLI가 `chemistry_limits.csv` provenance 검증에서 `MissingProvenanceError`(7개 행의 snippet이 소스 텍스트에서 발견되지 않음)로 실패. **Phase 1.6 변경 전 커밋(6db5a12)에서도 동일하게 재현됨을 오케스트레이터가 직접 확인** — 이번 작업이 유발한 회귀가 아니라 `ref_code` 코퍼스/CSV provenance의 기존 불일치. 별도 조사 필요.

### 향후 과제
- MPS/규격 요구 대비 동봉 문서 첨부 여부 자동판정(범위 밖으로 명시)
- "첫 페이지부터 혼입" 실물 케이스(PU2601565 등, harness 밖) 반입·케이스화
- `chemistry_limits.csv` provenance 검증 실패(선재 이슈) 별도 조사

### 배포 동기화
- `Certification_Examine/.claude/skills/`는 현재 **비어 있음(활성 배포본 없음)** — 동기화 불필요. 플러그인이 marketplace 캐시를 통한 단일 활성 소스(오케스트레이터가 커밋 전 md5 대조로 확인).
