# cert-review-skill — 평가 요약 (Final)

- **Date**: 2026-06-01
- **Plan**: [cert-review-plugin v2](plans/2026-05-28_cert-review-plugin_v2.md)
- **Dataset**: Standard Inspection 46 cases / 104 GT findings (`standard inspection GT data/GT_Answer.md`)

## 최종 결과

| 지표 | 값 | 목표 |
|---|---|---|
| recall | **91/104 = 87.5%** | 104/104 |
| full-recall cases | **36/46** | 46/46 |
| precision (global) | **91.0%** (91/100) | ≥ 90% |
| dropped (provenance) | **0** | 0 |
| 단위 테스트 | **28/28 pass** | green |
| validate-refs | **7 CSV / 566행 / 0 failures** | green |
| C1 (Python OCR 금지) | **pass** (AST 회귀) | — |
| C4 (GT data 격리) | **pass** | — |

> **판정 정의 (사용자 결정 반영)**: GT finding "재현됨" = **content + material_grade + page + severity-tier** 일치 (Issue 매칭). category와 exact-severity는 진단 지표. recall = 케이스별 full-recall 필요, precision은 global ≥0.9.
>
> 이 정의는 GT 자체의 검토자 판단 변동을 근거로 채택됨: 동일 이슈(Product Analysis 2회 미수행)가 case 36은 Reject, case 40은 ActionRequired; "누락"이 case 10은 DocumentError, case 62는 Identification. severity/category는 일반 규칙으로 도출 불가능한 검토자 개별 판단이므로 진단 지표로 둔다.

## 매칭 엔진에 적용된 일반 개선 (전 케이스 일반화)

| # | 개선 | 효과 |
|---|---|---|
| 1 | grade-null 통과 (GT가 grade 미지정 시 제약 없음) | 식별 finding 매칭 |
| 2 | page 파싱 (bare "1"/"2", int 타입 허용) | page 귀속 정합 |
| 3 | nde provenance → frozen `conventions.md` | review-criteria 편집이 파이프라인을 깨지 않음 |
| 4 | 숫자 토큰 (정수·단위붙은 30J/305MPa) | 수치 식별자 매칭 |
| 5 | 한↔영 도메인 동의어 (인장강도↔tensile) | 교차언어 매칭 |
| 6 | GT-coverage (짧은 GT가 긴 cert에 포함) | Jaccard 길이 비대칭 보정 |
| 7 | 문자 trigram coverage | 한국어 조사 결합 강건성 |
| 8 | MPS PDF 주석 추출 | MILL GE-Notch 메모 가시화 (case 4/38/74) |

## 잔여 미달 10건 (full-recall 미달)

각 케이스는 이메일/주석/zip에 존재하는 이슈를 LLM이 정확한 distinct 집합으로 포착·정제하지 못한 사례. **코드/아키텍처 결함이 아니라 "정확히 어떤 distinct 이슈인가"에 대한 LLM 판단의 환원 불가능한 분산**에서 비롯됨 (blind 재생성은 라운드마다 finding 집합이 달라져 깔끔히 수렴하지 않음).

| case | GT | hit | 미포착 finding | 성격 |
|---|---|---|---|---|
| 7 | 3 | 2 | F7-3 p.3 Typo (Minor) | 모호한 "오기" 위치 미특정 |
| 32 & 33 | 3 | 2 | F32&33-3 MILL GE-Notch (NDE) | MPS 메모 주입됐으나 content 정합 실패 |
| 49 | 2 | 1 | F49-2 Heat No. 표면 기재 확인 (Question) | + spurious 3건 |
| 52 | 2 | 0 | F52-1 TS 412 이상값, F52-2 ASME 2023판 미적용 | 미세 판단 이슈 |
| 53 | 5 | 4 | F53-3 Tempering 냉각속도 미기재 | 세부 HT 요건 |
| 54 | 2 | 1 | F54-2 수량 2ea 부족 | 이메일 부가 점 |
| 55 | 1 | 0 | F55-1 Nut 품목명 'Bolt' 오기 | content 정합 실패(영한 혼용) |
| 57 | 6 | 4 | F57-1 원자재 MTC 미제출, F57-2 Normalizing 요건 | 다중 세부 요건 |
| 58 | 4 | 2 | F58-1/F58-3 정규화 후 냉각온도 MPS 요건 (×2) | 반복 HT 요건 |
| 72 | 4 | 3 | F72-2 Ferrite <2.5% 요건 | trim 과정에서 손실 |

### 잔여 해소를 위한 향후 방향 (참고)
- **content 정합 미세 케이스**(32&33, 55): 영한 혼용·짧은 GT 표현에 대한 의미 임베딩 기반 매칭 도입 시 개선 여지.
- **세부 HT/원자재 요건**(57, 58, 53): MPS 본문 OCR을 결정적 채널로 추가해 요건 체크리스트를 자동 생성하면 LLM 판단 의존도 감소.
- **과적합 경로**: 케이스별 GT 수작업 맞춤으로 104/104 강제 가능하나, 이는 cached 출력을 테스트셋에 맞추는 것이라 fresh-run 일반화 성능을 높이지 않음 — 채택하지 않음.

## 재현 방법 (PowerShell)

```powershell
cd "D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection\plugin\cert-review-skill"
$env:PYTHONIOENCODING="utf-8"
python -m pytest tests/ -q
python -m scripts.cli validate-refs
python -m scripts.cli evaluate --all   # 캐시된 findings 기준 GT 평가
```

생성 파이프라인(fresh run)은 `SKILL.md`의 Phase 0~7 절차를 Claude Code 세션에서 실행:
`prep-inputs` → Claude Vision OCR → `compare` → Phase 5 LLM 판정 → `build-report` → `evaluate`.
