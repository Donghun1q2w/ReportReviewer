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

## 속도 최적화 서브커맨드 (반복 루프용)

```powershell
# 캐시 게이트: 추출 신선도 판정 (fresh | legacy | stale | missing)
#   fresh/legacy = Phase 1·2 스킵(기존 추출 재사용), stale/missing = 재추출
python -m scripts.cli cache-status --all

# prep-inputs: PDF sha256+dpi 사이드카 기록, 무변경 시 렌더 스킵 (--force로 강제, --dpi로 해상도 지정)
python -m scripts.cli prep-inputs --case 4 --dpi 200

# crop: 모호 셀 영역만 고DPI 재렌더 (bbox는 0.0~1.0 분수 좌표, 좌상단 원점)
python -m scripts.cli crop --case 4 --stem <stem> --page 2 --bbox 0.10,0.42,0.55,0.50 --dpi 300

# limits: 케이스별 관련 기준값 행만 provenance 포함으로 추출 (Phase 4 컨텍스트 다이어트)
python -m scripts.cli limits --case 4
```

> 다중 케이스(`--all`)는 Phase 0(build-manifest)·Phase 3(validate-refs)을 1회 선실행한 뒤,
> 케이스 단위 서브에이전트로 동시성 6~10 fan-out하여 wall-clock을 단축한다. 자세한 규칙은 `SKILL.md`의
> **병렬 실행 규칙** 절 참조. 품질 의무(전 페이지 의무·verbatim 전사·evidence 필수)는 그대로 유지된다.

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
