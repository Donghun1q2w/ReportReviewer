# ReportReviewer

파이프 자재 **MTC(Mill Test Certificate / 성적서) 자동 검토** Claude Code 플러그인.

스캔된 성적서 PDF를 **Claude Vision으로 OCR**하고, **MPS(구매시방서)** 및 **ASTM/ASME 코드** 기준값과 대조하여 PASS/FAIL/지적사항을 판정, **6시트 한글 Excel 리포트**를 생성한다. 모든 기준값은 ref_code/MPS 원문에서 인용하며(출처 4종 메타 검증) **LLM이 기준값을 생성하지 않는다**.

> 사내 전용(Proprietary). [LICENSE](LICENSE) 참조.

## 핵심 특징

- **2차원 병렬 아키텍처**: 오케스트레이터(SKILL.md)가 케이스 × 도메인 에이전트를 직접 스케줄링 (동시 6~10). 케이스 래퍼 에이전트 없음 — 서브에이전트는 중첩 스폰 불가이므로 모든 fan-out을 오케스트레이터가 직접 수행한다.
- **역할 분리 서브에이전트**: OCR 전용(`ocr-extractor`, claude-opus-4-8) + 도메인별 검토 5종(`claude-opus-4-8`) — 전사(판독)와 판정을 역할로 분리.
- **결정적 병합 단계**: 검토 5에이전트가 각자 부분 산출물을 쓰고, `merge-reviews` CLI가 전역 재채번 및 verdict 최악값으로 결정적 병합. 하류 Phase 5/6 계약 불변.
- **Claude Vision OCR 강제**: Python OCR 라이브러리 일체 미사용 (`pytesseract`/`easyocr`/`pymupdf` 등 금지, AST 회귀로 검증). PDF는 `pypdfium2` 렌더링 + `pypdf` 주석 메타만
- **출처 강제(provenance)**: 모든 판정 근거에 `source_file`/`anchor`/`snippet`/`sha256` 4종 메타. 미검증 근거는 자동 격리
- **4-채널 입력**: cert 본문 OCR + PDF 주석 + 이메일(.msg) + zip 첨부 (+ MPS PDF 주석)
- **6시트 한글 리포트**: 검토 총괄 / 화학성분 / 기계적성질 / 열처리 / 표기·형식 / 지적사항 종합

## 설치

### 1) Claude Code 플러그인으로 등록 (마켓플레이스)

```
/plugin marketplace add git@github.com:Donghun1q2w/ReportReviewer.git
/plugin install cert-review@ReportReviewer
```

### 2) Python 런타임 의존성

```powershell
pip install -r requirements.txt
```

## 사용

플러그인 설치 후 Claude Code 세션에서:

```
/cert-review                # 작업 폴더의 3개 카테고리 입력(참조코드·성적서·MPS)을 검토
# (`--all` / `<case_id>` 형태의 케이스 선택은 플러그인 테스트 하니스 회귀 전용)
```

또는 Python CLI를 직접 실행 (Windows PowerShell):

```powershell
cd skills/cert-review
$env:PYTHONIOENCODING="utf-8"
$env:CERT_REVIEW_WORKDIR="<성적서/MPS/ref_code가 있는 작업 폴더>"
python -m scripts.cli build-manifest           # Phase 0: cert/MPS 인덱스
python -m scripts.cli validate-refs            # Phase 3: CSV 출처 검증
python -m scripts.cli prep-inputs --case <id>  # Phase 1: PDF→PNG
#  -> ocr-extractor(claude-opus-4-8)로 PNG Vision OCR 위임 (SKILL.md Phase 2)
#  -> chemistry/mechanical/heat-treatment/nde/format-reviewer 병렬 위임 (Phase 4)
python -m scripts.cli merge-reviews --case <id>  # 부분 산출 결정적 병합
python -m scripts.cli evaluate --all             # Phase 6: GT 평가(있을 시)
```

전체 절차(Phase 0~6)는 [`skills/cert-review/SKILL.md`](skills/cert-review/SKILL.md) 참조.

### 작업 폴더 레이아웃 / 환경변수

런타임은 작업 디렉토리를 다음 우선순위로 찾는다: `CERT_REVIEW_WORKDIR` → (testbed 자동감지) → 현재 디렉토리(CWD).

입력 폴더명은 환경변수로 재정의 가능 (기본값은 standard-inspection 데이터셋 레이아웃):

| 환경변수 | 기본값 |
|---|---|
| `CERT_REVIEW_WORKDIR` | (CWD) |
| `CERT_REVIEW_CERT_DIR` | `standard inspection Cert cleanup data` |
| `CERT_REVIEW_MPS_DIR` | `standard inspection MPS cleanup data` |
| `CERT_REVIEW_RAWDATA_DIR` | `rawdata` |
| `CERT_REVIEW_REF_CODE_DIR` | `ref_code` |

## 저장소 구조

```
ReportReviewer/
├── .claude-plugin/marketplace.json   # 플러그인 마켓플레이스 매니페스트
├── agents/                           # 플러그인 서브에이전트 (frontmatter model 포함)
│   ├── ocr-extractor.md              # Phase 2 Vision 전사 (claude-opus-4-8, full/fragment 모드)
│   ├── chemistry-reviewer.md         # Phase 4 화학성분 검토 (claude-opus-4-8)
│   ├── mechanical-reviewer.md        # Phase 4 기계적 성질 검토 (claude-opus-4-8)
│   ├── heat-treatment-reviewer.md    # Phase 4 열처리 검토 (claude-opus-4-8)
│   ├── nde-reviewer.md               # Phase 4 NDE/특별요구 검토 (claude-opus-4-8)
│   └── format-reviewer.md            # Phase 4 문서·식별·인쇄기준 검토 (claude-opus-4-8)
├── skills/cert-review/
│   ├── SKILL.md                      # Claude 오케스트레이션 절차서 (Phase 0~6)
│   ├── scripts/                      # 결정적 Python 모듈 (CLI/엔진/평가)
│   │   ├── merge_reviews.py          # 검토 5에이전트 부분 산출 결정적 병합
│   │   └── ...
│   ├── data/*.csv                    # 참조 기준값 7종 (출처 4종 메타 검증)
│   ├── references/                   # review-criteria / conventions / extraction-schema
│   └── tests/                        # 84개 단위 테스트 (test_merge_reviews.py 11개 포함)
├── docs/eval-summary.md              # 평가 결과·잔여 분석
├── requirements.txt
└── LICENSE
```

## 서브에이전트 (`agents/`)

오케스트레이터(SKILL.md)가 위임하는 **6개 플러그인 서브에이전트**. 각자 부분 산출물만 작성하고, 오케스트레이터가 결정적 CLI(`merge-reviews`)로 병합한다.

| 에이전트 | model | 담당 | 부분 산출물 |
|---|---|---|---|
| `ocr-extractor` | claude-opus-4-8 | Phase 2 Vision 전사 (full / fragment 두 모드) | `<stem>_extracted.json` |
| `chemistry-reviewer` | claude-opus-4-8 | 화학성분 검토 + Cev 역산·crop 확정 | `<case>_review_chemistry.json` |
| `mechanical-reviewer` | claude-opus-4-8 | 기계적 성질 검토 | `<case>_review_mechanical.json` |
| `heat-treatment-reviewer` | claude-opus-4-8 | 열처리 검토 (±10°C 룰) | `<case>_review_heat_treatment.json` |
| `nde-reviewer` | claude-opus-4-8 | NDE/특별요구 (δ-ferrite·PMI·Code Case) | `<case>_review_nde.json` |
| `format-reviewer` | claude-opus-4-8 | 표기형식·식별 (기준 11/14/15/16, doc_checks) | `<case>_review_format.json` |

**모델 원칙**: 전 에이전트 claude-opus-4-8(정확도 우선 — 다품목 MTC 식별·수치 판독, 300 DPI 필수). OCR(전사)과 검토(판정)는 모델이 아니라 역할로 분리되며, 복잡도별 차등 예산(단순 ≤30분 / 표준 ≤60분 / 복합 60~90분, 정확도 최우선)으로 운용한다. `CLAUDE_CODE_SUBAGENT_MODEL` 환경변수가 설정돼 있으면 각 에이전트 frontmatter의 model을 덮어쓰므로 **해제 상태**로 실행한다.

## 병합 CLI (`merge-reviews`)

검토 5에이전트가 각자 `.cache/<case>/<case>_review_<domain>.json`(domain: `chemistry` / `mechanical` / `heat_treatment` / `nde` / `format`)을 작성한 뒤, 아래 명령으로 단일 `<case>_review.json`으로 결정적 병합한다:

```powershell
python -m scripts.cli merge-reviews --case <id>   # 단일 케이스
python -m scripts.cli merge-reviews --all          # 전 케이스
```

병합 결과는 전역 finding 재채번·verdict 최악값을 보장하며, 하류 Phase 5(보고서)·Phase 6(평가) 계약은 불변이다.

## 검증 (개발)

```powershell
cd skills/cert-review; $env:PYTHONIOENCODING="utf-8"

# 단위 테스트 — 데이터셋 없이도 실행 (이식성 테스트 포함, 데이터셋 의존 테스트는 skip).
# 데이터셋이 있으면 CERT_REVIEW_WORKDIR 지정 시 84개 전부 실행.
python -m pytest tests/ -q

# 참조 CSV 출처 검증 — ref_code/MPS 원문이 있는 데이터셋 필요 (CI/testbed 작업).
$env:CERT_REVIEW_WORKDIR="<ref_code/, MPS/가 있는 데이터셋 폴더>"
python -m scripts.cli validate-refs    # 7 CSV / 566행 / 0 failures
```

> `validate-refs` / `build-manifest` / `evaluate`는 **소스 데이터셋**(ref_code OCR, MPS 스캔, GT)을 참조하므로 `CERT_REVIEW_WORKDIR`로 데이터셋 폴더를 가리켜야 한다. 배포본에 포함된 `data/*.csv`는 testbed에서 **이미 출처 검증을 통과한 산출물**이다 (대용량 원문은 배포 미포함).

## 평가 결과 (standard-inspection 46 케이스)

| recall | full-recall cases | precision | dropped | tests |
|---|---|---|---|---|
| 91/104 = 87.5% | 36/46 | 91.0% | 0 | 84/84 |

매칭 정의(content+grade+page+severity-tier, Issue 매칭)와 잔여 10건 분석: [`docs/eval-summary.md`](docs/eval-summary.md).
