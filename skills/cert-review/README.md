# cert-review

자재 성적서(MTC) 자동 검토 Claude Code 플러그인. compliance 단일 경로.

## 빠른 사용 (Windows PowerShell)

```powershell
# 플러그인(skill) 디렉토리 = 본 README가 있는 곳에서 실행
$env:PYTHONIOENCODING="utf-8"
# (선택) 데이터셋 루트 명시. 미지정 시 상위 폴더에서 자동 탐색.
$env:CERT_REVIEW_WORKDIR="<WORK>"
python -m scripts.cli build-manifest
python -m scripts.cli evaluate --all
```

## 입력 (3폴더만)

| 입력 | 출처 | 도구 | 산출물 |
|---|---|---|---|
| cert body | `standard inspection Cert cleanup data/<case>/*.pdf` | pypdfium2 + Claude Vision | `<stem>_extracted.json` (channels: body) |
| MPS | `standard inspection MPS cleanup data/<case>/*.pdf` | Claude Vision | 식별·적합성 대조 |
| ref_code | `ref_code/` (read-only) | CSV 기준값 출처 | `data/*.csv` |

`standard inspection GT data/<case>/comments.md`는 **평가 단계에서만** 접근(코드 가드 적용).
`rawdata/`는 동작 중 접근 금지(가드가 차단).

## 파이프라인 (compliance 단일)

```
build-manifest → prep-inputs (PNG body) → Claude Vision OCR(cert+MPS)
 → compliance 검토 (CSV/ref_code/MPS 비교 + 도메인 규칙) → review.json
 → compliance_report (6시트 한글 xlsx) → evaluate (comments.md 기준)
```

## 불변 제약 (Hard Constraints)

- **C1**: OCR은 Claude Vision만 사용. Python OCR 라이브러리 import 금지 (회귀 테스트로 검증).
- **C2**: 모든 판정 row와 finding은 출처 메타 보유(`source_file`/`anchor`/`snippet`). 누락 시 출력에서 폐기.
- **C3**: ref_code 연도 불일치 시 비고에 명시.
- **C7**: PowerShell + python으로 모든 명령 동작.
- **C8**: CSV row는 출처 메타 3종 없으면 로딩 거부 (`validate-refs` exit 0 필수).

## 디렉토리

```
skills/cert-review/        # 플러그인(skill) 루트 — CLI 실행 기준
├── SKILL.md               # Claude 오케스트레이션
├── manifest.json          # 자동 생성된 케이스 인덱스
├── data/                  # 참조 CSV (출처 메타 3종 필수)
├── scripts/               # Python 결정적 모듈 (prep/validate/eval + 도메인 헬퍼)
├── references/            # 도메인 규칙 + JSON 스키마
└── tests/                 # pytest 회귀
```

## 평가 기준 (match 정의)

검토자 지적(`comments.md`, 페이지×주제 클러스터) "재현됨" = **content + material_grade + page + severity-tier** 일치.
- severity-tier: major{Reject,ActionRequired} / minor{Question,Minor}
- category·exact-severity는 **진단 지표** (동일 이슈에 검토자 판단 변동이 있을 수 있음)
- recall은 케이스별 full-recall, precision은 global, dropped = 0
