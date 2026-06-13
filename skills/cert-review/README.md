# cert-review

자재 성적서(MTC) 자동 검토 Claude Code 플러그인. compliance 단일 경로.

## 빠른 사용 (Windows PowerShell)

```powershell
# 플러그인(skill) 디렉토리 = 본 README가 있는 곳에서 실행
$env:PYTHONIOENCODING="utf-8"
# (선택) 데이터셋 루트 명시. 미지정 시 상위 폴더에서 자동 탐색.
$env:CERT_REVIEW_WORKDIR="<WORK>"
python -m scripts.cli build-manifest
# Phase 1~4 실행 후 검토 에이전트 부분 산출 병합
python -m scripts.cli merge-reviews --all
python -m scripts.cli evaluate --all
```

## 속도 최적화 서브커맨드 (반복 루프용)

```powershell
# 캐시 게이트: 추출 신선도 판정 (fresh | legacy | stale | missing)
#   fresh/legacy = Phase 1·2 스킵(기존 추출 재사용), stale/missing = 재추출
python -m scripts.cli cache-status --all

# prep-inputs: PDF sha256+dpi 사이드카 기록, 무변경 시 렌더 스킵 (--force로 강제, --dpi로 해상도 지정)
python -m scripts.cli prep-inputs --case 4 --dpi 300

# crop: 모호 셀 영역만 고DPI 재렌더 (bbox는 0.0~1.0 분수 좌표, 좌상단 원점)
python -m scripts.cli crop --case 4 --stem <stem> --page 2 --bbox 0.10,0.42,0.55,0.50 --dpi 300

# limits: 케이스별 관련 기준값 행만 provenance 포함으로 추출 (Phase 4 컨텍스트 다이어트)
python -m scripts.cli limits --case 4
```

> 다중 케이스(`--all`)는 Phase 0(build-manifest)·Phase 3(validate-refs)을 1회 선실행한 뒤,
> 오케스트레이터(SKILL.md)가 **케이스 × 도메인 에이전트 2차원 스케줄링**(동시 6~10 상한)으로
> wall-clock을 단축한다. 케이스 래퍼 서브에이전트는 없으며, fan-out을 오케스트레이터가 직접 수행한다.
> 자세한 규칙은 `SKILL.md`의 **병렬 실행 규칙** 절 참조. 품질 의무(전 페이지 의무·verbatim 전사·evidence 필수)는 그대로 유지된다.

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
build-manifest → prep-inputs (PNG body) → [ocr-extractor/claude-opus-4-8] Vision OCR
 → check-extraction 게이트 → limits 조회
 → [chemistry/mechanical/heat-treatment/nde/format-reviewer 병렬 위임]
 → merge-reviews (부분 산출 결정적 병합 → review.json)
 → compliance_report (6시트 한글 xlsx) → evaluate (comments.md 기준)
```

### 검토 에이전트와 부분 산출물

오케스트레이터는 Phase 4에서 도메인별 검토 에이전트 5종을 **한 메시지에 병렬 위임**한다. 각 에이전트는 `.cache/<case>/`에 부분 산출물을 기록한다:

| 에이전트 | model | 부분 산출 파일 |
|---|---|---|
| `chemistry-reviewer` | claude-opus-4-8 | `<case>_review_chemistry.json` |
| `mechanical-reviewer` | claude-opus-4-8 | `<case>_review_mechanical.json` |
| `heat-treatment-reviewer` | claude-opus-4-8 | `<case>_review_heat_treatment.json` |
| `nde-reviewer` | claude-opus-4-8 | `<case>_review_nde.json` |
| `format-reviewer` | claude-opus-4-8 | `<case>_review_format.json` (섹션 키: `doc_checks`) |

전 에이전트 완료 후 `merge-reviews` CLI가 5파일을 단일 `<case>_review.json`으로 결정적 병합한다 (전역 finding 재채번·verdict 최악값). `OCR`은 `ocr-extractor`(claude-opus-4-8)가 전담한다. 전 에이전트 claude-opus-4-8(정확도 우선)이며, OCR(전사)과 검토(판정)는 모델이 아니라 역할로 분리된다 — 복잡도별 차등 예산(단순 ≤30분 / 표준 ≤60분 / 복합 60~90분, 정확도 최우선).

> **모델 라우팅 주의**: `CLAUDE_CODE_SUBAGENT_MODEL` 환경변수가 설정돼 있으면 에이전트 frontmatter의 model을 덮어쓴다. 라우팅을 의도대로 적용하려면 **이 환경변수를 해제한 상태로 실행**한다.

## 불변 제약 (Hard Constraints)

- **C1**: OCR은 Claude Vision만 사용. Python OCR 라이브러리 import 금지 (회귀 테스트로 검증).
- **C2**: 모든 판정 row와 finding은 출처 메타 보유(`source_file`/`anchor`/`snippet`). 누락 시 출력에서 폐기.
- **C3**: ref_code 연도 불일치 시 비고에 명시.
- **C7**: PowerShell + python으로 모든 명령 동작.
- **C8**: CSV row는 출처 메타 3종 없으면 로딩 거부 (`validate-refs` exit 0 필수).

## 디렉토리

```
skills/cert-review/        # 플러그인(skill) 루트 — CLI 실행 기준
├── SKILL.md               # Claude 오케스트레이션 (Phase 0~6, 오케스트레이터 전용)
├── manifest.json          # 자동 생성된 케이스 인덱스
├── data/                  # 참조 CSV (출처 메타 3종 필수)
├── scripts/               # Python 결정적 모듈
│   ├── cli.py             # 서브커맨드 진입점
│   ├── merge_reviews.py   # 검토 5에이전트 부분 산출 결정적 병합
│   └── ...                # prep/validate/eval + 도메인 헬퍼
├── references/            # 도메인 규칙 + JSON 스키마
└── tests/                 # pytest 회귀 (84개, test_merge_reviews.py 11개 포함)
```

서브에이전트 파일(`agents/*.md`)은 **플러그인 루트**(본 디렉토리의 상위) 아래에 있다. CLI는 스킬 디렉토리에서 실행한다.

## 평가 기준 (match 정의)

검토자 지적(`comments.md`, 페이지×주제 클러스터) "재현됨" = **content + material_grade + page + severity-tier** 일치.
- severity-tier: major{Reject,ActionRequired} / minor{Question,Minor}
- category·exact-severity는 **진단 지표** (동일 이슈에 검토자 판단 변동이 있을 수 있음)
- recall은 케이스별 full-recall, precision은 global, dropped = 0
