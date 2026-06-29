# Revision History

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
