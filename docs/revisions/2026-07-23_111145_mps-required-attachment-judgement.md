# 2026-07-23 — MPS 요구사항 대비 동봉 문서 첨부 자동판정(기준 20) — v1.5.0

**Summary**: Phase 1.6이 분류·제외한 동봉 문서(원자재 Mill Cert, PMI/NDE/치수/이화학/조직/열처리차트)에 heat/PO 식별자를 추가로 판독해, MPS가 요구하는 별도 시험보고서가 실제로 첨부·해당 heat를 커버하는지 heat 단위로 자동판정 — 신규 기준 20, A/B/C/D 우선순위 사다리(본문 인쇄값 > 첨부 확인 > 확인 불가 > 미첨부).

**Plan**: [2026-07-23_091508_mps-required-attachment-judgement](../plans/2026-07-23_091508_mps-required-attachment-judgement.md) (dh-dev 승인 완료)

## Rationale

Phase 1.6(v1.4.0)의 향후 과제로 분리했던 "MPS 요구 대비 동봉 문서 첨부 여부 자동판정"의 후속 구현. 현재까지는 별도 문서 존재를 확인할 수 없으면 finding을 생략(기준 17.1)해 요구 문서 통누락이 무증상 통과했고, 반대로 nde-reviewer의 본문 인쇄값 판정과 충돌하면 오탐 위험이 있었다. 실물 케이스(PU2601565-01, LS룽산 발행, Tallgrass 프로젝트) 조사로 MTC-MPS 페어링을 확정해 실동 E2E 검증까지 포함했다.

## Rationale (하드닝 후속)

주 구현(커밋 `4dcd924`)에 대해 독립 code-reviewer 패스(oh-my-claudecode:code-reviewer)를 실행한 결과 critical/high 결함은 0건이었으나, 안전-critical 도메인 특성상 의미 있는 medium-confidence 권고 2건을 오케스트레이터가 직접 반영했다: (1) `sidecar_present`가 케이스 내 단 하나의 stem만 분류되어도 true가 되는 문제 — 부분 분류 케이스에서 미분류 stem의 동봉 문서가 `attachments[]`에 보이지 않는데도 "판정 안전"으로 오인될 위험을 차단, (2) nde/format-reviewer 프롬프트에 상태 B/D 구분 기준이 `heat_coverage`가 아니라 `attachments[]` 존재 여부임을 명시 — `heat_coverage`는 low-confidence·PO-only 첨부를 의도적으로 제외하므로, 이를 "0건"과 혼동하면 실제로는 존재하는 첨부를 미첨부로 오판정(허위 미첨부)할 위험이 있었다.

## Changed Files

### 주 구현 (커밋 4dcd924, 21 files, +1353/-32)

| 파일 | 상태 | 설명 |
|---|---|---|
| `skills/cert-review/scripts/attachments.py` | added | 기준 20 결정적 대조 CLI — heat 정규화 완전일치 매칭, `heat_coverage`(high confidence만), `unmatched_heat_nos`(자동 FAIL 금지), `sidecar_present` |
| `skills/cert-review/tests/test_attachments.py` | added | 대조 로직·CLI exit code 매트릭스 단위 테스트 |
| `docs/plans/2026-07-23_091508_...md` | added | 구현 계획 |
| `skills/cert-review/scripts/doctype.py` | modified | `_advisory_documents`/`_match_run_meta` — sidecar `documents[]`의 related 식별자를 `excluded_documents[]` 각 run에 결정적 join(doc_type 동일+페이지 교집합 최대), 1.0 사이드카는 안전 폴백 |
| `agents/doc-classifier.md` | modified | EXCLUDED run별 Heat No./P.O NO. 열 verbatim 판독 절차(step 6.5), 1.1 스키마 |
| `agents/nde-reviewer.md` · `agents/format-reviewer.md` | modified | 기준 20 A/B/C/D ladder, 유형별 단일 소유(중복 finding 구조적 차단), 미첨부=ActionRequired 상한 |
| `skills/cert-review/references/review-criteria.md` | modified | 기준 17.1 개정(확인 가능 시 기준 20 판정), 기준 19.3 개정("범위 외"→"기준 20 관계"), 기준 20 신설(20.1~20.5) |
| `skills/cert-review/scripts/compliance_report.py` | modified | "검토 제외 문서" 블록에 관련 Heat/품목 컬럼 |
| `skills/cert-review/scripts/merge_reviews.py` | modified | docstring — excluded_documents 필드 목록에 related 3필드 추가(코드 변경 없음, 자동 relay) |
| `skills/cert-review/scripts/cli.py` | modified | `attachments` 서브커맨드 |
| `SKILL.md` · `README.md` · `marketplace.json` | modified | Phase 4 절차·Domain-boundary·시간예산·v1.5.0 |
| `agents/{chemistry,mechanical,mps-extractor}-reviewer.md` | modified | 부수 수정 — "§" 리터럴 제거만(AC-9 문자 검사 충족용, 의미 변경 없음) |
| 기존 테스트 3종 확장 | modified | doctype/merge_reviews/compliance_report 회귀 |

### 하드닝 후속 (본 리비전에서 커밋 예정)

| 파일 | 상태 | 설명 |
|---|---|---|
| `skills/cert-review/scripts/attachments.py` | modified | `_all_stems_covered` 신설 — `sidecar_present`를 "케이스 내 임의 sidecar 존재"에서 "렌더된 전 stem이 sidecar를 가짐"으로 강화 |
| `skills/cert-review/tests/test_attachments.py` | modified | 부분 커버리지 시나리오 신규 테스트 1건 + 기존 2건 fixture에 `png/` 렌더 추가(강화된 판정 기준 반영) |
| `agents/nde-reviewer.md` · `agents/format-reviewer.md` | modified | "B vs D 판정은 `attachments[]` 존재 여부로, `heat_coverage`만으로 판단 금지" 명확화 문장 추가 |

## Details

### 핵심 설계 (계획 1.3절 결정 1~5)
- **매칭 정밀도 = heat 단위**: doc-classifier가 동봉 문서 표에서 Heat No./P.O NO.를 verbatim 판독(추측 금지) → `excluded_documents[]`에 relay → `attachments.py`가 완제품 인벤토리와 정규화 완전일치(fuzzy 금지)로 대조.
- **A/B/C/D 우선순위 사다리**: 본문 인쇄값 있으면(A) 기존 판정만, 미첨부 확정(B)은 ActionRequired 상한(자동 Reject 금지), 첨부+coverage 일치(C)는 PASS(값은 비교 안 함), coverage 불확실(D)은 Question까지만.
- **유형별 단일 소유**(nde-reviewer: PMI/NDE/Microstructure, format-reviewer: 나머지 4종)로 두 에이전트 간 중복·상충 finding을 구조적으로 차단.
- **요구 없는 첨부는 finding 금지**(정보성) — 과잉판정 방지.

### 검증
- `pytest` **209 passed**(기존 184 + 신규 24 + 하드닝 1, 오케스트레이터 독립 재실행 확인).
- **실물 E2E(PU2601565-01, 23p)**: build-manifest→...→doc-classifier(related 판독)→check-doctype→OCR/mps-extractor→attachments→5 reviewer→merge-reviews→compliance_report 전 구간 실행. 오케스트레이터가 직접 p.22/p.23 렌더를 육안 대조: p.22=NDE_REPORT(炉号 열 9종 실물 heat 일치), p.23=PMI_REPORT(P/O NO.만, Heat 열 없음 — 판독과 정확히 일치). 최종 판정: **PMI 관련 finding 0건**(MPS 양쪽 PMI 요구 없음 — 과잉판정 방지 실증), MT/PT는 본문 인쇄값 존재로 상태 A(첨부 중복 finding 0).
- **ladder 시뮬레이션**: `.cache` 사본 3종(simB/C/D) + case 4 사본(상태 A 무간섭)에 조작된 attachments/limits로 nde-reviewer 재위임 — B→ActionRequired, C→PASS(finding 0), D→주의+Question(FAIL 0), A는 기존 PASS 9/9 유지. 사본은 검증 후 삭제.
- **오케스트레이터 독립 검증**: `git show --stat 4dcd924`로 불변 영역(`page-aligner.md`/`align_inputs.py`/`orient_sheets.py`/`extraction_check.py`/`eval_harness.py`) 미포함 확인, `data/chemistry_limits.csv` 등 CSV 기준값 무변경 확인, harness 데이터셋 루트(`standard inspection * cleanup data/`)가 git 저장소 밖임을 `git rev-parse` 실패로 재확인(고객 데이터 미추적), "§" 문자는 딜리버러블에 0건(계획 문서 내 규칙 인용만) 확인.
- **독립 code-reviewer 패스**: critical/high 0건, 두 가지 위험 시나리오(허위 미첨부로 인한 공급사 분쟁 / 요구 없는데 과잉판정) 모두 구조적으로 차단됨을 데이터 흐름 추적으로 확인. medium-confidence 권고 2건은 본 리비전에서 반영.

### 선재 이슈 재확인 (Phase 1.6 리비전과 동일 — 이번 작업과 무관)
- `limits` CLI의 `chemistry_limits.csv` provenance 오류(SA-105 관련 7개 행)가 이번에도 재현됨. 실물 E2E는 임시 우회(무관 행 제외한 로컬 데이터로 해당 케이스 limits.json만 생성)로 완주했으며, **이 우회는 커밋에 포함되지 않았다**(data/*.csv 무변경 확인). 별도 조사 필요.

### 향후 과제
- MPS `document_requirements`/`nde_microstructure` 기반 요구사항의 자동 발견 확장(현재는 각 reviewer가 digest를 직접 판독).
- `chemistry_limits.csv` SA-105 provenance 재동기화(선재 이슈).
- 배포본(`.claude/skills`) 동기화 — 이번에도 확인 결과 활성 배포본 없음(플러그인 단일 소스), 불필요.

### 배포 동기화
- `Certification_Examine/.claude/skills/`는 비어 있음(활성 배포본 없음) — 동기화 불필요.
