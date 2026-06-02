# cert-review-skill

자재 성적서(MTC) 자동 검토 Claude Code 플러그인.

## 빠른 사용 (Windows PowerShell)

```powershell
cd "D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection\plugin\cert-review-skill"
$env:PYTHONIOENCODING="utf-8"
python -m scripts.cli build-manifest
python -m scripts.cli evaluate --all
```

## 입력 채널 (rawdata 3-채널)

| # | 채널 | 출처 | 도구 | 산출물 |
|---|---|---|---|---|
| 1 | cert PDF body | `standard inspection Cert cleanup data/<case>/*.pdf` | pypdfium2 + Claude Vision | `<stem>_extracted.json` |
| 2 | PDF annotations | (동일) | pypdf | `<stem>_annotations.json` |
| 3 | Zip 첨부 | `rawdata/<case>/*.zip` | zipfile | 해제 후 1/2 반복 |

`standard inspection GT data/`는 평가 단계에서만 접근 (코드 가드 적용).

## 불변 제약 (Hard Constraints)

- **C1**: OCR은 Claude Vision만 사용. Python OCR 라이브러리 import 금지 (회귀 테스트로 검증).
- **C2**: 모든 판정 row와 finding은 4종 메타 보유: `source_file` + `anchor` + `snippet` + `sha256`. 누락 시 출력에서 폐기.
- **C3**: ref_code 연도 불일치 시 비고에 명시.
- **C4**: GT data는 평가 시에만 접근.
- **C7**: PowerShell + python으로 모든 명령 동작.

## 디렉토리

```
plugin/cert-review-skill/
├── SKILL.md              # Claude 오케스트레이션
├── manifest.json         # 자동 생성된 케이스 인덱스
├── data/                 # 참조 CSV (출처 4종 메타 필수)
├── scripts/              # Python 결정적 모듈
├── references/           # 도메인 규칙 + JSON 스키마
└── tests/                # pytest 회귀
```

## 평가 기준 (match 정의)

GT finding "재현됨" = **content + material_grade + page + severity-tier** 일치 (Issue 매칭).
- severity-tier: major{Reject,ActionRequired} / minor{Question,Minor}
- category·exact-severity는 **진단 지표** (GT 자체가 동일 이슈에 다른 category/severity를 부여하는 검토자 판단 변동 때문)
- recall은 케이스별 full-recall, precision은 global ≥ 0.9, dropped = 0

## 현재 결과 (Final)

| recall | full-recall cases | precision | dropped | tests |
|---|---|---|---|---|
| 91/104 = 87.5% | 36/46 | 91.0% | 0 | 28/28 |

상세 결과·잔여 10건 원인·일반화 개선 내역: [`docs/eval-summary.md`](../../docs/eval-summary.md)
