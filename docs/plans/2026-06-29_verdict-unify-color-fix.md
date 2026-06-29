# Plan — 판정 문구 일원화 및 색상 미적용 해결

- **Date**: 2026-06-29
- **Status**: Awaiting Approval
- **Target plugin**: `plugin/ReportReviewer`
- **Reference report**: `D:\test\mtctest\output\reports\26\26_MTC_Review.xlsx`

## 1. 문제 (Problem)

리포트 판정 문구가 한 파일 안에서도 제각각이고, 상당수 셀에 색상이 적용되지 않는다.

26 리포트 실측:
- 화학성분 시트 판정 = `합격` (한글) → **무색** (23행 전부)
- 기계적성질·표기 시트 판정 = `PASS` (영문) → 초록
- 지적사항 심각도 = `Question` / `ActionRequired` / `Minor` (camelCase) → **무색**
- `N/A` → **무색**

전 케이스 집계로 확인된 판정 문구 변종(셀 축):
`PASS, FAIL, 주의, 합격, N/A, INFO, REVIEW, WARNING, 정보, 정보성, 참고, 확인 불가, ActionRequired, PASS_WITH_FINDINGS, QUESTION, DocumentError, None`
심각도 축: `Reject, ActionRequired, Question, Minor, FAIL, Info, 정보, 주의`

## 2. 근본 원인 (Root Cause)

1. **소스 드리프트** — 6개 reviewer 에이전트(`agents/*.md`)의 verdict 스키마가 `PASS|주의|FAIL, **etc.**` 처럼 "etc."로 열려 있어 모델이 자유 어휘를 생성.
2. **리포트 빌더 미정규화** — `compliance_report.py`의 `_fill_for()`가 `PASS / FAIL / 주의 / WARNING / 조건부 PASS`만 정확 매칭 → 그 외 어휘는 `PatternFill()`(무색)으로 떨어지고, 표시 문구도 그대로 출력.
3. 표준 셀 어휘는 이미 `merge_reviews.py`의 `_VERDICT_RANK = {"PASS":1,"주의":2,"FAIL":3}`로 합의되어 있음 → 리포트/에이전트만 이 표준에 정렬하면 됨.

## 3. 결정 사항 (Decisions — 사용자 확정)

- **셀 판정 표준 4종**: `PASS`(초록) · `FAIL`(빨강) · `주의`(노랑) · `N/A`(회색, 해당없음/정보)
- **수정 범위**: 리포트 빌더 정규화 + 6개 에이전트 프롬프트 + SKILL.md 스키마 주석 동시
- **심각도(지적사항) 축**: 문서/eval 정합을 위해 캐노니컬 영문 4종 유지(`Reject/ActionRequired/Question/Minor`) + 색상 부여. 누수 변종(`FAIL→Reject`, `주의→Question`, `Info/정보→Info`)은 정규화. 색상 티어: major{Reject,ActionRequired}→빨강, minor{Question,Minor}→노랑, Info→회색.

## 4. 구현 단계 (Implementation Steps)

### Step A — 리포트 빌더 정규화 (`skills/cert-review/scripts/compliance_report.py`)
1. 색상 팔레트에 `_NA_FILL = PatternFill("solid", fgColor="FFD9D9D9")`(회색) 추가.
2. `_VERDICT_ALIASES` 매핑 추가 → 모든 셀 verdict 변종을 `{PASS, FAIL, 주의, N/A}`로 정규화 (대소문자/공백 무시). 미인식·빈값 → `N/A`.
3. `_SEVERITY_ALIASES` 매핑 추가 → `{Reject, ActionRequired, Question, Minor, Info}`로 정규화.
4. `_canon_verdict(v)` / `_canon_severity(v)` 헬퍼 추가.
5. `_fill_for` / `_verdict_fill` 를 캐노니컬 기반으로 교체 → **항상 fill 반환**(N/A=회색). 셀에 기록되는 **값 자체도 캐노니컬 문구로 치환**(예: `합격→PASS`).
6. 적용 지점: `_grouped_sheet`(col6), 검토 총괄(col8), 표기·형식(col5 verdict), 지적사항(col2 severity)에서 `vc.value = _canon_*(...)` + `vc.fill = _fill_for(...)`.
7. 모듈 docstring 스키마 주석(line 25) `PASS | FAIL | 주의 | 조건부 PASS` → `PASS | FAIL | 주의 | N/A`.

### Step B — 에이전트 프롬프트 어휘 고정 (`agents/*.md`)
- `chemistry-reviewer.md`(L150) / `mechanical-reviewer.md`(L145): `(PASS|주의|FAIL, etc.)` → `(PASS | 주의 | FAIL | N/A)` ("etc." 제거).
- `heat-treatment-reviewer.md`(L122) / `nde-reviewer.md`(L144) / `format-reviewer.md`(L140): `PASS | 주의 | FAIL` → `PASS | 주의 | FAIL | N/A` 로 N/A 명시 + 자유 어휘 금지 1줄.
- 심각도 토큰은 `Reject|ActionRequired|Question|Minor` 유지(변경 없음).

### Step C — SKILL.md 동기화
- Phase 5 표(L317~332) 및 verdict 언급 부분에 표준 4종 명시(`PASS|주의|FAIL|N/A`)와 "리포트 빌더가 비표준 어휘를 자동 정규화" 1줄 추가.

## 5. 검증 (Acceptance Criteria)

패치 후 `build_compliance_report("26_review.json", tmp.xlsx)` 재생성하여 openpyxl로 read-back:
- [ ] 모든 판정/심각도 셀 `fill.patternType == "solid"` (무색 셀 0개)
- [ ] 화학성분 시트 판정 = `PASS` (이전 `합격` → 치환됨), 초록 적용
- [ ] `N/A`/정보성 셀 = 회색
- [ ] 지적사항 심각도 = 캐노니컬 4종 + 색상 적용
- [ ] 한글 깨짐 없음(read-back 육안 확인)
- [ ] 기존 테스트 `pytest skills/cert-review/tests/` 통과 (merge_reviews 등 회귀 없음)

## 6. 영향 범위 / 리스크

- 표시 계층(리포트) 중심 변경 → 저장된 `review.json` 불변 → `eval_harness` 영향 없음.
- `merge_reviews.py`는 범위 외(이미 PASS/주의/FAIL 표준). 단, 비표준 domain verdict가 worst-aggregation에서 누락될 수 있는 기존 엣지는 에이전트 어휘 고정으로 자연 완화.
