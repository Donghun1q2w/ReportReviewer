# ReportReviewer

파이프 자재 **MTC(Mill Test Certificate / 성적서) 자동 검토** Claude Code 플러그인.

스캔된 성적서 PDF를 **Claude Vision으로 OCR**하고, **MPS(구매시방서)** 및 **ASTM/ASME 코드** 기준값과 대조하여 PASS/FAIL/지적사항을 판정, **6시트 한글 Excel 리포트**를 생성한다. 모든 기준값은 ref_code/MPS 원문에서 인용하며(출처 4종 메타 검증) **LLM이 기준값을 생성하지 않는다**.

> 사내 전용(Proprietary). [LICENSE](LICENSE) 참조.

## 핵심 특징

- **Hybrid 아키텍처**: 결정적(Python) 비교 엔진 + Claude Vision OCR + LLM 보조 판정
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
/cert-review --all          # 작업 폴더 전체 검토
/cert-review <case_id>       # 단일 케이스
```

또는 Python CLI를 직접 실행 (Windows PowerShell):

```powershell
cd skills/cert-review
$env:PYTHONIOENCODING="utf-8"
$env:CERT_REVIEW_WORKDIR="<성적서/MPS/ref_code가 있는 작업 폴더>"
python -m scripts.cli build-manifest
python -m scripts.cli prep-inputs --case <id>   # PDF→PNG, 주석/이메일/zip 추출
#  -> Claude Vision으로 PNG OCR (SKILL.md Phase 2)
python -m scripts.cli compare --case <id>       # 결정적 비교
python -m scripts.cli build-report --case <id>  # 6시트 Excel
python -m scripts.cli evaluate --all            # GT 평가(있을 시)
```

전체 절차(Phase 0~7)는 [`skills/cert-review/SKILL.md`](skills/cert-review/SKILL.md) 참조.

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
├── skills/cert-review/
│   ├── SKILL.md                      # Claude 오케스트레이션 절차서 (Phase 0~7)
│   ├── scripts/                      # 결정적 Python 모듈 (CLI/엔진/평가)
│   ├── data/*.csv                    # 참조 기준값 7종 (출처 4종 메타 검증)
│   ├── references/                   # review-criteria / conventions / extraction-schema
│   └── tests/                        # 28개 단위 테스트
├── docs/eval-summary.md              # 평가 결과·잔여 분석
├── requirements.txt
└── LICENSE
```

## 검증 (개발)

```powershell
cd skills/cert-review; $env:PYTHONIOENCODING="utf-8"

# 단위 테스트 — 데이터셋 없이도 실행 (이식성 테스트 12개 통과, 데이터셋 의존 16개 skip).
# 데이터셋이 있으면 CERT_REVIEW_WORKDIR 지정 시 28개 전부 실행.
python -m pytest tests/ -q

# 참조 CSV 출처 검증 — ref_code/MPS 원문이 있는 데이터셋 필요 (CI/testbed 작업).
$env:CERT_REVIEW_WORKDIR="<ref_code/, MPS/가 있는 데이터셋 폴더>"
python -m scripts.cli validate-refs    # 7 CSV / 566행 / 0 failures
```

> `validate-refs` / `build-manifest` / `evaluate`는 **소스 데이터셋**(ref_code OCR, MPS 스캔, GT)을 참조하므로 `CERT_REVIEW_WORKDIR`로 데이터셋 폴더를 가리켜야 한다. 배포본에 포함된 `data/*.csv`는 testbed에서 **이미 출처 검증을 통과한 산출물**이다 (대용량 원문은 배포 미포함).

## 평가 결과 (standard-inspection 46 케이스)

| recall | full-recall cases | precision | dropped | tests |
|---|---|---|---|---|
| 91/104 = 87.5% | 36/46 | 91.0% | 0 | 28/28 |

매칭 정의(content+grade+page+severity-tier, Issue 매칭)와 잔여 10건 분석: [`docs/eval-summary.md`](docs/eval-summary.md).
