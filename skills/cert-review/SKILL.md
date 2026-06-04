---
name: cert-review
description: Inspection Certificate (MTC/성적서) review for piping materials. Compares scanned PDF certificates against MPS (구매시방서) and ASTM/ASME reference codes, emits a 6-sheet Korean Excel report, and evaluates against ground-truth. Use for MTC review, 성적서 검토, 자재 성적서, material test report verification.
argument-hint: "<case_id | --all>"
---

# cert-review — Claude 오케스트레이션 절차서

본 문서는 **Claude Code CLI 에이전트가 직접 따르는** MTC(자재 성적서) compliance 검토 실행 절차이다.
입력은 3폴더(`ref_code/`, cert cleanup, MPS cleanup)만 사용하며, Python 결정적 모듈(`scripts/`)과
Claude Vision/판단 단계를 명확히 구분한다.

---

## Constraints (불변 제약)

| ID | 내용 |
|---|---|
| **C1** | Python OCR 라이브러리 사용 금지 — `pytesseract`, `easyocr`, `paddleocr`, `pymupdf`, `fitz`, `pdfplumber`, `openai`(vision), `anthropic`(vision), `google.cloud.vision` 등 일체. `pypdf` 텍스트 추출과 `pypdfium2` 렌더링은 허용. OCR은 Claude Vision(`Read` 툴로 PNG 판독)으로만 수행. |
| **C2** | 모든 finding의 `evidence` 항목은 출처 메타(`source_file` / `anchor` / `snippet` / `sha256` 등) 필수. `source_validator`가 부재 항목을 격리. |
| **C3** | ref_code 연도가 MPS 명시 연도와 다를 경우 비고에 명시. |
| **C7** | 실행 환경은 Windows PowerShell + Python. 모든 명령은 플러그인(skill) 디렉토리에서 `PYTHONIOENCODING=utf-8`을 앞에 붙여 `python -m scripts.cli ...` 형식으로 실행. |
| **C8** | CSV 기준값 row는 출처 4종 메타 없으면 로딩 단계에서 거부 (`validate-refs` exit 0 필수). |

---

## 입력 화이트리스트 (3폴더만)

> **동작(검토) 단계는 아래 3개 입력 폴더만 읽는다. 그 외 폴더는 입력 가드가 차단한다.**

| 입력 폴더 | 용도 |
|---|---|
| `ref_code/` | ASTM/ASME 코드 원문 OCR (read-only, 기준값 출처) |
| `standard inspection Cert cleanup data/<case>/` | 검토 대상 성적서 PDF (PNG 렌더링 → Vision OCR) |
| `standard inspection MPS cleanup data/<case>/` | MPS(구매시방서) PDF (식별·적합성 대조) |

`scripts/__init__.py`가 패키지 로드 시 `sys.addaudithook`으로 파일 open을 감사한다. 동작 중
`rawdata/`(전 모듈)와 `standard inspection GT data/`(평가 모듈 `eval_harness` 외)를 열면 즉시
`PermissionError`가 발생한다. 즉 가드는 **rawdata와 GT를 동시에 차단**하여, 검토 경로가 정답(GT)이나
원본 주석 데이터에 의존하지 않도록 강제한다. Claude 에이전트가 `Read` 툴로 직접 접근하는 것도 금지된다.
평가(`evaluate`)는 `eval_harness.py`가 내부적으로 케이스별 `comments.md`를 읽으므로 직접 접근 불필요.

---

## Directory Layout (디렉토리 구조)

```
<WORK>/  (= 데이터셋 루트, 입력 상대 경로 앵커)
├── ref_code/                                       ← ASTM/ASME 코드 OCR (read-only)
├── standard inspection Cert cleanup data/<case>/   ← 성적서 PDF (body OCR 대상)
├── standard inspection MPS cleanup data/<case>/    ← MPS PDF
├── standard inspection GT data/<case>/comments.md  ← 평가 전용 (eval_harness만 접근)
├── output/                                         ← 보고서 산출물 및 평가 결과
└── ... plugin/.../skills/cert-review/              ← 플러그인(skill) 디렉토리 (CLI 실행 기준)
    ├── SKILL.md                                    ← 본 문서
    ├── manifest.json                               ← build-manifest 산출물 (자동 생성)
    ├── .cache/<case>/                              ← 중간 산출물
    │   ├── png/                                    ← prep-inputs 렌더링 PNG
    │   ├── <stem>_extracted.json                   ← Vision OCR 산출물 (channels: body)
    │   └── <case>_review.json                      ← compliance 검토 findings
    ├── data/                                       ← 기준값 CSV (출처 4종 메타 필수)
    │   ├── chemistry_limits.csv
    │   ├── mechanical_limits.csv
    │   ├── heat_treatment.csv
    │   ├── nde_rules.csv
    │   ├── grade_routing.csv
    │   ├── mps_overrides.csv
    │   └── code_edition_map.csv
    ├── references/
    │   ├── extraction-schema.json                  ← 추출 JSON 스키마
    │   └── review-criteria.md                      ← Claude 판정 시 참조 도메인 규칙
    └── scripts/                                     ← Python 결정적 모듈
        ├── cli.py                                  ← 진입점
        ├── prep_inputs.py                          ← cert PDF → PNG 렌더러 (C1 준수)
        ├── source_validator.py                     ← C2/C8 출처 검증기
        ├── compare_engine.py                       ← 순수 도메인 헬퍼 (grade route, A106 Mn, 단위 변환)
        ├── compliance_report.py                    ← 6시트 한글 Excel 보고서
        └── eval_harness.py                         ← 평가 전용 (comments.md 읽기)
```

> **경로 표기**: 플러그인(skill) 디렉토리는 본 문서가 있는 현재 디렉토리(`scripts/cli.py`의 부모)다.
> CLI는 이 플러그인 디렉토리에서 실행한다. 데이터셋 루트(`<WORK>`)는 `CERT_REVIEW_WORKDIR` 환경변수로
> 지정하거나, 미지정 시 CWD/플러그인 위치에서 위로 올라가며 `standard inspection Cert cleanup data`
> 폴더를 가진 디렉토리를 자동 탐색한다.

---

## PowerShell 사용 예시

```powershell
# 플러그인(skill) 디렉토리로 이동 후 환경 변수 설정
$env:PYTHONIOENCODING = "utf-8"
# (선택) 데이터셋 루트를 명시 지정. 미지정 시 자동 탐색.
$env:CERT_REVIEW_WORKDIR = "<WORK>"
Set-Location "<플러그인 디렉토리: 본 SKILL.md가 있는 곳>"

# Phase 0: 매니페스트 빌드 (cert/MPS 인덱스)
python -m scripts.cli build-manifest

# Phase 1: 단일 케이스 입력 준비 (cert cleanup → PNG body)
python -m scripts.cli prep-inputs --case 4

# Phase 3: 참조 CSV 출처 검증
python -m scripts.cli validate-refs

# Phase 6: 단일 케이스 평가 (comments.md 기준)
python -m scripts.cli evaluate --case 4

# Phase 6: 전체 케이스 평가
python -m scripts.cli evaluate --all
```

---

## Phase 0: build-manifest

**목적**: cert/MPS cleanup 두 디렉토리를 스캔하여 케이스 인덱스(`manifest.json`)를 생성한다.

```powershell
python -m scripts.cli build-manifest
```

- `standard inspection Cert cleanup data/`, `standard inspection MPS cleanup data/`를 스캔한다.
- `rawdata/`와 `standard inspection GT data/`는 **스캔하지 않는다** (입력 가드).
- 산출물: 플러그인 디렉토리 `manifest.json` (schema_version: "2.0").
- 성공 기준: exit 0, `case_count` 출력.

---

## Phase 1: prep-inputs (cert cleanup → PNG body)

**목적**: 케이스별 성적서 PDF를 페이지별 PNG로 렌더링하여 body 채널 입력을 준비한다.

```powershell
python -m scripts.cli prep-inputs --case <case_id>
```

- `standard inspection Cert cleanup data/<case>/*.pdf`를 `pypdfium2`로 렌더링하여
  `.cache/<case>/png/<stem>_p01.png`, `_p02.png`, … 를 생성한다 (DPI 200).
- 케이스별 추출 스켈레톤 JSON(`<stem>_extracted.json`)을 함께 작성한다 (Phase 2 Vision이 채움).
- **cert cleanup 폴더만 읽는다.** rawdata 원본은 가드가 차단한다.

---

## Phase 2: Claude Vision OCR (cert + MPS 스캔)

> **[MANDATORY — 모델이 직접 수행하는 OCR]**
>
> **Python OCR 라이브러리는 사용 금지. 모델(Claude CLI 에이전트)이 PNG 이미지를 `Read` 툴로 직접
> 열어 판독한다. `pytesseract`, `easyocr`, `paddleocr`, vision API 등 어떤 Python OCR도 호출 금지.**

### 절차

1. `.cache/<case>/png/` 아래의 모든 cert PNG를 `Read` 툴로 하나씩 연다.
2. 필요 시 `standard inspection MPS cleanup data/<case>/`의 MPS 스캔도 `Read`로 판독한다(식별·적합성 대조용).
3. 각 페이지에서 다음 항목을 판독하여 구조화 JSON으로 기록한다:
   - `header`: PO번호, 성적서번호, vendor, spec, grade, heat_no, 치수(OD×WT), 수량, 길이
   - `chemistry`: Heat/Product Analysis 구분, 원소별 값 (단위: %)
   - `mechanical`: TS/YS(MPa), EL(%), RA(%), 경도(HBW/HRC), impact(J at °C)
   - `heat_treatment`: 각 단계별 온도(°C), 유지시간(min), 냉각 방법
   - `nde`: UT/MT/PT/PMI 등 수행 여부, notch 규격, 결과
   - `remarks`: 특기사항 텍스트 목록
   - `confidence`: `high` / `medium` / `low`
4. 산출물 형식은 `references/extraction-schema.json`을 따른다.
   파일명: `.cache/<case>/<cert_stem>_extracted.json`. `channels` 섹션은 **`body`만** 사용한다:
   - `body.engine = "claude-vision"`, `body.pages = [1, 2, ...]`
5. **화학성분 컬럼 정합성 검증** (OCR 직후 수행):
   - 각 원소값이 해당 grade의 통상 범위와 물리적으로 부합하는지 확인
     (예: P91의 Cr ≈ 8–9%, P22의 Cr ≈ 2%, A106의 C < 0.35%).
   - Cev 표기가 있으면 역산 일치 확인: `Cev = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15`
   - 불일치 시 OCR 재시도 대신 **해당 PNG를 다시 `Read`로 열어 명시 재판독**하고 `confidence: "low"` 기록.

---

## Phase 3: validate-refs

**목적**: `data/*.csv`의 모든 row가 C2/C8 준수(출처 4종 메타 완비)임을 검증한다.

```powershell
python -m scripts.cli validate-refs
```

- `source_validator`가 각 CSV row의 `source_file` 존재, `sha256` 일치, `snippet` 포함을 확인한다.
- **exit 0이 아니면 이후 단계를 진행하지 않는다.**
- 검증 대상 CSV: `chemistry_limits.csv`, `mechanical_limits.csv`, `heat_treatment.csv`,
  `nde_rules.csv`, `grade_routing.csv`, `mps_overrides.csv`, `code_edition_map.csv`.

---

## Phase 4: compliance 검토 (review.json)

**목적**: Phase 2 추출값을 ref_code/CSV 기준값 및 MPS 한계와 비교하고, 도메인 규칙을 적용하여
findings를 생성한다. Claude가 직접 판단하는 compliance 단일 경로다.

### 비교 대상

- **화학성분** (`data/chemistry_limits.csv`): Heat/Product 각각, grade별 원소 min/max.
  MPS override(`data/mps_overrides.csv`)가 있으면 Code보다 MPS를 우선.
  A106 C/Mn 각주(기준 3.1)는 `compare_engine._a106_adjusted_mn_max` 헬퍼로 조정 Mn max 산정.
- **기계적 성질** (`data/mechanical_limits.csv`): TS/YS min, EL min, 경도 범위.
- **열처리** (`data/heat_treatment.csv`): 단계별 온도 범위, 유지시간. 이탈 ≤10°C → Warning, >10°C → Reject.
- **NDE** (`data/nde_rules.csv`): 수행 여부, notch 규격(MILL/STOCK).
- **Grade 라우팅** (`data/grade_routing.csv`): grade 문자열 → ASME spec(`compare_engine._grade_route`).
  `data/code_edition_map.csv`로 ref_code 연도 결정, 불일치 시 비고(C3).

### 도메인 규칙 (Claude 판단)

- **기준 3.1**: A106/SA-106 C/Mn 각주 조정 Mn max 적용 (오탐 금지).
- **기준 11.2**: cert.header.spec ↔ MPS 발주 spec 표준 계열 불일치(ASME SA vs ASTM A)는 `Identification` FAIL.
- **MPS 우선**: ASTM/ASME 기준과 MPS가 다르면 MPS 우선(`mps_overrides.csv`).
- 카테고리/severity/누락 vs 불일치 판정은 `references/review-criteria.md` 참조.

### 출처 인용 규칙 (C2)

> **evidence가 없으면 finding을 작성하지 않는다.**

- 각 finding의 `evidence` 배열에 최소 하나의 항목을 포함하고, `snippet`은 채널 원문(body/MPS)에
  literal로 존재해야 한다. `source_validator`가 부재 snippet finding을 격리한다.
- 산출물: `.cache/<case>/<case>_review.json`.
- **수치 기준은 CSV에서만 인용한다. 코드에 하드코딩된 수치를 사용하지 않는다.**

---

## Phase 5: compliance_report (6시트 한글 Excel)

**목적**: `review.json`의 findings를 6시트 한국어 Excel 보고서로 출력한다.

- `compliance_report.build_compliance_report`가 `review.json`을 읽어 보고서를 생성한다.
- 산출물: `output/reports/<case_id>/<case_id>_MTC_Review.xlsx`
- **6-시트 구성**:

  | # | 시트명 | 내용 |
  |---|---|---|
  | 1 | 종합 요약 | 케이스별 PASS/FAIL, finding 집계, 검토 일시 |
  | 2 | 화학성분 | Heat/Product 원소별 값 vs 기준, 판정 |
  | 3 | 기계적 성질 | TS/YS/EL/RA/경도 vs 기준, 판정 |
  | 4 | 열처리 | 단계별 온도·시간 vs 기준, 판정 |
  | 5 | NDE / 특별요구 | UT/MT/PT/PMI 수행 여부, notch 규격, δ-ferrite |
  | 6 | Finding 목록 | finding_id, category, severity, issue_summary, evidence 요약 |

- 보고서 문구에 절 기호(섹션 부호)를 사용하지 않는다. 기준 조항 참조는 `기준 3.1` 형식으로 표기한다.
- 파일 인코딩: `openpyxl` 기본(UTF-8). 한국어 폰트 폴백 사용.

---

## Phase 6: evaluate (comments.md 기준 평가)

**목적**: compliance `review.json` 예측을 케이스별 검토자 실제 지적(`comments.md`)과 비교하여
PASS/FAIL을 판정한다.

```powershell
# 단일 케이스
python -m scripts.cli evaluate --case <case_id>

# 전체 케이스
python -m scripts.cli evaluate --all
```

- `scripts/eval_harness.py`가 `standard inspection GT data/<case>/comments.md`를 읽는 **유일한 모듈**이다.
  이 명령 외 어느 경로에서도 GT 디렉토리를 직접 열지 않는다 (입력 가드).
- GT는 검토자 실제 지적을 **페이지×주제로 클러스터링**한 `comments.md`이며, 예측 finding과 매칭하여
  recall/precision/case_pass를 산출한다.
- 산출물: `output/eval/<case_id>_eval.json` 또는 `output/eval/all_eval.json`, 요약 markdown 리포트.

---

## 전체 실행 흐름 요약

```
Phase 0  build-manifest          → manifest.json (cert/MPS 인덱스)
Phase 1  prep-inputs --case <id> → .cache/<id>/png/*.png (body)
Phase 2  [CLAUDE VISION OCR]     → .cache/<id>/*_extracted.json (channels: body)
          Read PNG(cert+MPS) → transcribe  (Python OCR 금지)
Phase 3  validate-refs           → exit 0 필수
Phase 4  [COMPLIANCE 검토]        → .cache/<id>/<id>_review.json
          CSV/ref_code/MPS 비교 + 도메인 규칙(기준 3.1·11.2·MPS 우선), evidence 필수
Phase 5  [compliance_report]     → output/reports/<id>/<id>_MTC_Review.xlsx (6 시트)
Phase 6  evaluate --case <id>    → output/eval/<id>_eval.json
          (또는 --all)              comments.md 기준 recall/precision/case_pass
```

---

## 도메인 규칙 참조 위치

수치 판정 기준은 반드시 아래 위치에서 인용한다. 본 문서에 기재된 수치는 가독성을 위한 사본이며,
**런타임 판정에는 CSV만 사용**한다 (C2/C8).

| 판정 항목 | CSV 파일 | 비고 |
|---|---|---|
| 화학성분 범위 | `data/chemistry_limits.csv` | Heat/Product 구분, MPS override 별도 |
| MPS 우선 항목 | `data/mps_overrides.csv` | MPS > Code인 경우만 등재 |
| 기계적 성질 | `data/mechanical_limits.csv` | TS/YS/EL/RA/경도 |
| 열처리 조건 | `data/heat_treatment.csv` | 단계별 온도·시간, ±10°C 룰 |
| NDE 규칙 | `data/nde_rules.csv` | MILL/STOCK notch 구분 |
| Grade → Spec | `data/grade_routing.csv` | grade 문자열 → ASME spec 매핑 |
| ref_code 연도 | `data/code_edition_map.csv` | 연도 불일치 시 비고(C3) |

Claude 판정 시 세부 도메인 규칙(화학 복합 룰, NDE 특별요건, finding 카테고리 정의,
severity 결정 룰 등)은 `references/review-criteria.md`를 참조한다.
