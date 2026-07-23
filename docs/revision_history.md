# Revision History

## 2026-07-23 — MPS 요구사항 대비 동봉 문서 첨부 자동판정(기준 20) — v1.5.0

**Detail**: [revisions/2026-07-23_111145_mps-required-attachment-judgement](revisions/2026-07-23_111145_mps-required-attachment-judgement.md) · **Plan**: [2026-07-23_091508_mps-required-attachment-judgement](plans/2026-07-23_091508_mps-required-attachment-judgement.md)

- 신설: `scripts/attachments.py`(heat 단위 결정적 대조 CLI) · 테스트 신규 1종
- 수정: `doctype.py`(related 식별자 join) · `doc-classifier.md`(heat/PO verbatim 판독) · `nde/format-reviewer.md`(기준 20 A/B/C/D ladder, 단일소유) · `review-criteria.md`(17.1·19.3 개정, 기준 20 신설) · `compliance_report.py`(관련 Heat 컬럼) · SKILL/README/marketplace(v1.5.0)
- page-aligner·align_inputs·orient_sheets·extraction_check·eval_harness **무수정 보존**. pytest **209 passed**(오케스트레이터 독립 재검증). 실물 E2E PU2601565-01(LS룽산, Tallgrass 프로젝트)로 heat 판독 정확성·PMI 과잉판정 방지(finding 0건)·MT/PT 본문우선(상태 A) 검증. ladder A/B/C/D 시뮬레이션 4종 통과.
- **독립 code-reviewer 하드닝**: `sidecar_present`를 stem 전체 커버리지 기준으로 강화 + nde/format-reviewer에 "B/D 판정은 attachments[] 존재로, heat_coverage만으로 판단 금지" 명확화 — 오케스트레이터가 직접 반영.
- 선재 이슈 재확인(무관): `chemistry_limits.csv` SA-105 provenance 오류, 이번 커밋에 우회 코드 없음(data/*.csv 무변경).

## 2026-07-22 — 혼입 문서 페이지 분류(Phase 1.6 doc-classify) 및 비교 제외 — v1.4.0

**Detail**: [revisions/2026-07-22_221912_mtc-doc-classification-phase16](revisions/2026-07-22_221912_mtc-doc-classification-phase16.md) · **Plan**: [2026-07-22_170520_mtc-doc-classification-phase16](plans/2026-07-22_170520_mtc-doc-classification-phase16.md)

- 신설: `scripts/doctype.py`(taxonomy 단일소스+게이트) · `agents/doc-classifier.md`(Phase 1.6, opus 4.8) · 테스트 2종
- 수정: refpack(L2 인벤토리 필터) · merge_reviews(L4 excluded_documents 주입) · compliance_report(L5 렌더) · ocr-extractor(L1 minimal-entry) · 5개 reviewer(L3 규칙) · cli(classify-sheets/check-doctype) · orient_sheets(파라미터화) · prep_inputs(멱등) · SKILL/README/marketplace(v1.4.0, 9종)
- page-aligner·align_inputs·extraction_check·eval_harness **무수정 보존**(95.89% 실측 자산 회귀 방지). pytest **184 passed**(오케스트레이터 독립 재검증). PU2601233(73p 혼재) 육안 대조 false-exclude 0건, case 10 merge deep-equal(하위호환). 커밋 `8d38090`(push 보류, 사용자 확인 대기).
- 선재 이슈 발견(무관): `limits` CLI의 `chemistry_limits.csv` provenance 오류 — Phase 1.6 이전 커밋에서도 재현 확인, 별도 조사 필요.

## 2026-07-09 — 페이지 회전 정렬(Phase 1.5) 기능 추가 — v1.3.0

**Detail**: [revisions/2026-07-09_133645_page-orientation-alignment](revisions/2026-07-09_133645_page-orientation-alignment.md) · **Plan**: [2026-07-09_085623_page-orientation-alignment](plans/2026-07-09_085623_page-orientation-alignment.md)

- 신설: `orient_sheets.py`(컨택트시트) · `align_inputs.py`(2단계 커밋 회전 적용) · `agents/page-aligner.md`(방향 감지, opus 4.8 블라인드 A/B 채택 95.89%) · 테스트 2종(23개)
- 수정: cli(서브커맨드 2+게이트) · prep_inputs(재렌더 리셋/purge/rotations null) · extraction_check(alignment_pending→stale) · tile_inputs(100p+ 정규식) · crop/annotate(정렬 좌표계) · SKILL/README/marketplace(v1.3.0)
- 적대적 리뷰(53 에이전트) 확정 결함 6종 수정. pytest **145 passed**. PU2601233(73p, 51p 회전 혼재) E2E 정렬 read-back 검증 완료.

## 2026-07-01 — OCR 모델 A/B 벤치마크 (Sonnet 5 vs Opus 4.8) — 코드 무변경, Opus 유지

**Plan**: [2026-07-01_ocr-model-ab-sonnet5-vs-opus48](plans/2026-07-01_ocr-model-ab-sonnet5-vs-opus48.md) · **결과**: [ocr-model-ab-2026-07-01-results](ocr-model-ab-2026-07-01-results.md)

### 결정
- `agents/ocr-extractor.md` 모델을 **opus 4.8로 유지** (Sonnet 5 교체 안 함). frontmatter/SKILL 변경 없음.

### 근거 (실측)
- 8 cert stem(22p/88타일)에 동일 타일·동일 지침으로 opus/sonnet 격리 전사 후 결정적 필드 diff + PNG 육안 판정.
- 셀 일치율 **90.5%**(791/874), 출력 토큰 opus 255,254 / sonnet 249,136(≈동일). 불일치 대부분은 cosmetic(NDE 표현·구두점) 또는 키 명명 아티팩트(HT/NDE) — 실제 데이터 누락 아님.
- **결정적 차이 1건**: c4(SA106C)에서 sonnet이 화학 `×100`/`×1000` 배율 미적용 → 11개 원소 100×/1000× 오류(C=20%, Mn=116% 물리 불가). opus는 전 stem 배율 정확. hardness 분쟁은 다중 판독값 대표 선택 차이(TIE).
- 안전-critical 화학 정확도 도메인에서 배율 해석 실패는 disqualifying. 선행 근거("병목은 opus 숫자 검증", "sonnet 실측 탈락")를 Sonnet 5로 재확인.

### 산출물 (참조용, `.cache/`는 gitignore)
- 전사물 `.cache/<case>/<stem>_extracted__{opus,sonnet}.json`, diff `scratchpad/ocr_ab_diff.json`, 채점 `scratchpad/diff_extractions.py`.

## 2026-06-29 — cert-review-annotate 신규 스킬(검토 결과 PDF 주석 표기)

**Plan**: docs(workspace) plans/2026-06-29_160845_cert-review-annotate-skill.md

### 추가
- `skills/cert-review-annotate/SKILL.md` — 기존 cert-review를 포함(래핑)하고 **후순위로 PDF 주석 생성**하는 신규 스킬. Phase A(cert-review 무수정 실행) → Phase B(annotation-locator 위임) → Phase C(`annotate` CLI).
- `agents/annotation-locator.md` — Phase B 전용 Vision 에이전트(claude-opus-4-8). review.json의 **주의/N/A/FAIL**(PASS 제외) 항목을 캐시된 페이지에서 셀 bbox(Tier A, 물리 page=`crop --page`)로 산출 → `.cache/<case>/<case>_annotations.json`.
- `skills/cert-review/scripts/annotate_pdf.py` — 결정적 렌더러. **copy-through image burn-in**: 주석 면만 pypdfium 래스터+Pillow로 테두리 사각형(채우기 없음)+≤50자 한글 라벨, 나머지 면은 pypdf splice로 원본 보존. 색은 `compliance_report` 상수(`_WARN/_NA/_FAIL_FILL`) 재사용 → 엑셀과 100% 일치. 이중 게이트(verdict∈{주의,N/A,FAIL}+유효 bbox+page 범위), 페이지 범위 가드(oob 카운트), `CERT_REVIEW_FONT` override.
- `skills/cert-review/tests/test_annotate_pdf.py` — 순수 단위(always-run) + 폰트/렌더 통합(skipif) + C1 import 가드.

### 변경
- `skills/cert-review/scripts/cli.py` — `annotate` 서브커맨드(cmd_annotate, --case/--all/--dpi/--out) + `_manifest_case_ids()` 헬퍼(cmd_tile_inputs와 공유).
- `skills/cert-review/scripts/crop.py` — `resolve_stem(cert_root=...)` 옵션 추가(env-aware, 하위호환; 기존 호출 불변).
- `.claude-plugin/marketplace.json` — `cert-review-annotate` 스킬 등재, version 1.1.0→1.2.0.
- `requirements.txt` — annotate도 신규 의존성 0(pypdfium2/Pillow/pypdf) 명시.

### 무변경(분리 원칙)
- cert-review 검토 로직 일체 무수정: 5 reviewer 에이전트·`review-criteria.md`·`review.json` 스키마·`merge_reviews`·`compliance_report` 렌더 로직. 주석은 review.json을 읽기 전용 소비.

### 검증
- `pytest` **111 passed**(기존 95 + 신규 16, 회귀 0). 실케이스 시각 QA(case 4): 색·한글·테두리·copy-through·oob skip 정상, 모지바케 0. C1(test_no_python_ocr) 통과.
- 설계: 심층 병렬분석→초안→3렌즈 적대검증(GO-with-fixes) + /simplify 4렌즈(폰트 env override·효율(단일 open·resolve 메모이즈)·에러 일관성·manifest DRY·매직넘버 상수화).

> 배포 동기화: 코드(annotate_pdf.py/cli.py/crop.py) 통째복사 + 배포본 agents/SKILL은 EN/KO 에디션 분기 통째복사 금지.

## 2026-06-29 — 판정 문구 일원화 및 색상 미적용 해결

**Plan**: [2026-06-29_verdict-unify-color-fix](plans/2026-06-29_verdict-unify-color-fix.md)

### 변경
- `skills/cert-review/scripts/compliance_report.py`
  - 판정/심각도 **정규화 계층** 추가: `_VERDICT_ALIASES`(→ `PASS|FAIL|주의|N/A`), `_SEVERITY_ALIASES`(→ `Reject|ActionRequired|Question|Minor|Info`), `_canon_verdict()`/`_canon_severity()`/`_severity_fill()`.
  - `_fill_for()`를 캐노니컬 기반으로 교체 → **항상 색상 적용**(N/A·Info = 회색 `FFD9D9D9` 추가). 셀 값도 표준 문구로 치환(예: `합격`→`PASS`).
  - 6개 시트 전 verdict/severity 작성 지점에 정규화 적용.
  - (병합) 플러그인에 누락돼 있던 `_src_str()`(provenance dict→문자열) + dict-aware `_fmt()` 포팅 — 배포본과 parity 확보(없으면 dict `source` 셀에서 빌드 크래시).
  - docstring verdict 주석 `조건부 PASS` → `N/A` 정정.
- `agents/{chemistry,mechanical,heat-treatment,nde,format}-reviewer.md`
  - verdict 스키마를 `PASS | 주의 | FAIL | N/A` 4종으로 고정, `etc.` 제거, 자유 어휘 금지 명시(row-level 포함).
- `skills/cert-review/SKILL.md`
  - Phase 5에 표준 어휘(verdict 4종 / severity 5종) + 자동 정규화·색상 규칙 1줄 추가.

### 배포본 동기화
- `D:\test\mtctest\.claude\skills\cert-review\scripts\compliance_report.py` ← 플러그인 사본 복사(런타임 리포트가 이 복사본을 사용).
- 배포본 agents/SKILL.md는 **한국어 에디션**으로 플러그인(영어)과 분기 → 언어 교체 사고 방지를 위해 미복사(색상/문구 수정은 compliance_report.py만으로 완결).

### 검증
- 실제 `26_review.json` → `D:\test\mtctest\output\reports\26\26_MTC_Review.xlsx` 재생성: 무색 셀 **0개**, 판정 문구 `{PASS, FAIL, 주의, N/A}`·심각도 `{ActionRequired, Minor, ...}`로 통일, `합격`→`PASS` 치환, `N/A`=회색, 한글 무결성 read-back 확인.
- `py_compile` 양쪽 OK, `pytest tests/` **95 passed**.
