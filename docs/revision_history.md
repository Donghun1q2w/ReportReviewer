# Revision History

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
