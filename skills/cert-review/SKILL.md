---
name: cert-review
description: Inspection Certificate (MTC/성적서) review for piping materials. Compares scanned PDF certificates against MPS (구매시방서) and ASTM/ASME reference codes, emits a 6-sheet Korean Excel report, and evaluates against ground-truth. Use for MTC review, 성적서 검토, 자재 성적서, material test report verification.
argument-hint: "<case_id | --all>"
---

# cert-review-skill — Claude 오케스트레이션 절차서

본 문서는 **Claude Code CLI 에이전트가 직접 따르는** MTC(자재 성적서) 검토 실행 절차이다.
Phase 0–7을 순서대로 수행한다. Python 결정적 모듈(`scripts/`)과 Claude Vision 판단을 명확히 구분한다.

---

## Constraints (불변 제약)

| ID | 내용 |
|---|---|
| **C1** | Python OCR 라이브러리 사용 금지 — `pytesseract`, `easyocr`, `paddleocr`, `pymupdf`, `fitz`, `pdfplumber`, `openai`(vision), `anthropic`(vision), `google.cloud.vision` 등 일체. `pypdf` 텍스트 추출과 `pypdfium2` 렌더링은 허용. |
| **C2** | 모든 finding의 `evidence` 항목은 4종 출처 메타 필수: `source_file` / `anchor` / `snippet` / `sha256`. `source_validator`가 부재 항목을 `dropped_findings.json`으로 격리. |
| **C3** | ref_code 연도가 MPS 명시 연도와 다를 경우 비고에 명시. |
| **C4** | `standard inspection GT data/` 디렉토리는 Phase 7 / `eval_harness.py` 전용. 다른 모든 Phase에서 접근 금지 (패키지 audit hook이 위반 즉시 `PermissionError` 발생). |
| **C7** | 실행 환경은 Windows PowerShell + Python. 모든 명령은 plugin dir에서 `PYTHONIOENCODING=utf-8`을 앞에 붙여 `python -m scripts.cli ...` 형식으로 실행. |
| **C8** | CSV 기준값 row는 4종 출처 메타 없으면 로딩 단계에서 거부 (`validate-refs` exit 0 필수). |

---

## Directory Layout (디렉토리 구조)

```
testbed/1. Standard Inspection/                ← Work Dir (기준 상대 경로 앵커)
├── rawdata/<case>/                            ← 원본 PDF / .msg / .zip (주석 포함 원본)
├── standard inspection Cert cleanup data/<case>/   ← 주석 FLATTENED 성적서 PDF (body OCR 대상)
├── standard inspection MPS cleanup data/<case>/    ← MPS PDF
├── standard inspection GT data/              ← [C4] Phase 7 전용 — 절대 직접 접근 금지
├── ref_code/                                 ← ASTM/ASME 코드 원문 OCR (read-only)
├── output/                                   ← 보고서 산출물 및 평가 결과
└── plugin/cert-review-skill/                 ← Plugin Dir (CLI 실행 기준)
    ├── SKILL.md                              ← 본 문서
    ├── manifest.json                         ← build-manifest 산출물 (자동 생성)
    ├── .cache/<case>/                        ← 중간 산출물 (PNG, JSON)
    │   ├── png/                              ← Phase 1 렌더링 PNG
    │   ├── <stem>_extracted.json             ← Phase 2 Vision OCR 산출물
    │   ├── <case>_findings.json              ← Phase 4/5 findings
    │   └── <case>_dropped.json              ← 출처 검증 탈락 findings
    ├── data/                                 ← 기준값 CSV (출처 4종 메타 필수)
    │   ├── chemistry_limits.csv
    │   ├── mechanical_limits.csv
    │   ├── heat_treatment.csv
    │   ├── nde_rules.csv
    │   ├── grade_routing.csv
    │   ├── mps_overrides.csv
    │   └── code_edition_map.csv
    ├── references/
    │   ├── extraction-schema.json            ← Phase 2 산출 JSON 스키마 (schema_version: "2.0")
    │   └── review-criteria.md               ← Claude 보조 판정 시점 참조 도메인 규칙
    └── scripts/                              ← Python 결정적 모듈
        ├── cli.py                            ← 진입점
        ├── pdf_split.py                      ← pypdfium2 렌더러 (C1 준수)
        ├── pdf_annotations.py               ← pypdf /Annots 추출 (C1 준수)
        ├── msg_loader.py                     ← .msg 이메일 파서
        ├── zip_unpacker.py                   ← zip 첨부 해제
        ├── source_validator.py              ← C2/C8 출처 검증기
        ├── compare_engine.py               ← Phase 4 결정적 비교
        ├── report_builder.py               ← Phase 6 Excel 보고서
        └── eval_harness.py                  ← [C4] GT 전용 — Phase 7만 사용
```

---

## PowerShell 사용 예시

```powershell
# plugin dir로 이동 후 환경 변수 설정
$env:PYTHONIOENCODING = "utf-8"
Set-Location "D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection\plugin\cert-review-skill"

# Phase 0: 매니페스트 빌드
python -m scripts.cli build-manifest

# Phase 1: 단일 케이스 입력 준비 (예: case 4)
python -m scripts.cli prep-inputs --case 4

# Phase 3: 참조 CSV 출처 검증
python -m scripts.cli validate-refs

# Phase 4: 결정적 비교
python -m scripts.cli compare --case 4

# Phase 6: Excel 보고서 빌드
python -m scripts.cli build-report --case 4

# Phase 7: 단일 케이스 평가
python -m scripts.cli evaluate --case 4

# Phase 7: 전체 케이스 평가
python -m scripts.cli evaluate --all
```

---

## GT Data Isolation (GT 데이터 격리 원칙)

> **Phase 0–6은 `standard inspection GT data/` 디렉토리를 읽거나 참조해서는 안 된다.**

`scripts/__init__.py`가 패키지 로드 시 `sys.addaudithook`으로 파일 open 감사를 등록한다.
`eval_harness` 이외의 코드 경로에서 해당 경로를 열면 즉시 `PermissionError`가 발생한다.
Claude 에이전트가 `Read` 툴로 직접 접근하는 것도 동일하게 금지된다.
Phase 7(`evaluate` 명령)은 `eval_harness.py`가 내부적으로 GT를 읽으므로 직접 접근 불필요.

---

## Phase 0: build-manifest

**목적**: Work Dir 전체를 스캔하여 46개 케이스 인덱스(`manifest.json`)를 생성한다.

```powershell
python -m scripts.cli build-manifest
```

- `standard inspection Cert cleanup data/`, `standard inspection MPS cleanup data/`, `rawdata/` 세 디렉토리를 스캔한다.
- `standard inspection GT data/`는 **스캔하지 않는다** (C4).
- 산출물: `plugin/cert-review-skill/manifest.json` (schema_version: "2.0", case_count: 46).
- 성공 기준: exit 0, `case_count = 46` 출력.

---

## Phase 1: prep-inputs

**목적**: 케이스별로 4-채널 입력(PNG body / PDF 주석 / 이메일 / zip)을 준비한다.

```powershell
python -m scripts.cli prep-inputs --case <case_id>
```

### 1-A. PDF → PNG 렌더링 (pdf_split)

`standard inspection Cert cleanup data/<case>/*.pdf`를 `pypdfium2`로 렌더링하여
`.cache/<case>/png/<stem>_p01.png`, `_p02.png`, … 를 생성한다 (DPI 200).

### 1-B. PDF 주석 추출 (pdf_annotations) — rawdata 원본 대상

> **[중요] 주석 추출은 반드시 `rawdata/<case>/*.pdf` 원본을 대상으로 해야 한다.**
>
> `standard inspection Cert cleanup data/<case>/`의 `_cert.pdf` 파일들은 검토자 주석이
> **FLATTENED(소각/소멸) 처리**된 버전이다. 이 파일들의 PDF 내부에는 `/Annots` 딕셔너리가
> **존재하지 않으며** (zero /Annots), 검토자가 기입한 메모·하이라이트·스탬프 정보가
> 페이지 콘텐츠 스트림에 이미지로 구워져 있어 `pypdf`로는 읽을 수 없다.
>
> **살아있는 검토자 주석(live annotations)은 `rawdata/<case>/*.pdf` 원본에만 존재한다.**
> Phase 1에서 `pdf_annotations.extract_case_annotations`를 호출할 때 반드시
> `rawdata/<case>/` 경로를 대상으로 지정한다.

산출물: `.cache/<case>/<stem>_annotations.json`

### 1-C. 이메일 로드 (msg_loader)

`rawdata/<case>/*.msg` 파일을 `extract-msg` 라이브러리로 파싱하여
`.cache/<case>/emails.json`에 저장한다.

### 1-D. Zip 해제 (zip_unpacker)

`rawdata/<case>/*.zip` 파일을 해제한다. Case 70처럼 cert PDF가 없고 zip만 있는 케이스
(`is_zip_only: true`)는 zip 해제 후 내부 PDF/이미지를 동일 파이프라인으로 처리한다.

---

## Phase 2: Claude Vision OCR

> **[MANDATORY — 모델이 직접 수행하는 OCR]**
>
> **Python OCR 라이브러리는 사용 금지이다. 모델(Claude CLI 에이전트)이 PNG 이미지를
> `Read` 툴로 직접 열어 내용을 판독하는 방식으로 OCR을 수행한다.
> `pytesseract`, `easyocr`, `paddleocr`, `gemini` vision API, `openai` vision API,
> 기타 어떠한 Python OCR 패키지도 호출해서는 안 된다.**

### 절차

1. `.cache/<case>/png/` 아래의 모든 PNG를 `Read` 툴로 하나씩 연다.
2. 각 페이지에서 다음 항목을 판독하여 구조화 JSON으로 기록한다:
   - `header`: PO번호, 성적서번호, vendor, spec, grade, heat_no, 치수(OD×WT), 수량, 길이
   - `chemistry`: Heat/Product Analysis 구분, 원소별 값 (단위: %)
   - `mechanical`: TS/YS(MPa), EL(%), RA(%), 경도(HBW/HRC), impact(J at °C)
   - `heat_treatment`: 각 단계별 온도(°C), 유지시간(min), 냉각 방법
   - `nde`: UT/MT/PT/PMI 등 수행 여부, notch 규격, 결과
   - `remarks`: 특기사항 텍스트 목록
   - `confidence`: `high` / `medium` / `low`
3. 산출물 형식은 `references/extraction-schema.json` (schema_version: "2.0")을 따른다.
   파일명: `.cache/<case>/<cert_stem>_extracted.json`
4. `channels` 섹션에 아래 세 채널을 통합한다:
   - `body.engine = "claude-vision"`, `body.pages = [1, 2, ...]`
   - `annotations.engine = "pypdf"`, `annotations.items = [...]` (Phase 1-B 결과)
   - `emails.engine = "extract-msg"`, `emails.items = [...]` (Phase 1-C 결과)
5. **화학성분 컬럼 정합성 검증** (OCR 직후 수행):
   - 각 원소값이 해당 grade의 통상 범위와 물리적으로 부합하는지 확인한다
     (예: P91의 Cr ≈ 8–9%, P22의 Cr ≈ 2%, A106의 C < 0.35%).
   - 성적서에 Cev가 표기되어 있으면 역산으로 일치 여부를 확인한다:
     `Cev = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15`
   - 불일치가 발견되면 OCR을 재시도하지 말고 **해당 PNG를 다시 `Read` 툴로 열어
     명시적으로 값을 재판독**하고 `confidence: "low"`로 기록한다.

---

## Phase 3: validate-refs

**목적**: `data/*.csv`의 모든 row가 C2/C8 준수(4종 출처 메타 완비)임을 검증한다.

```powershell
python -m scripts.cli validate-refs
```

- `source_validator.validate_csv_file`이 각 CSV row의 `source_file` 존재, `sha256` 일치,
  `snippet` 포함 여부를 확인한다.
- **exit 0이 아니면 이후 Phase를 진행하지 않는다.** CSV를 수정하거나 `data/_seeds/`의
  시드 스크립트를 다시 실행하여 출처 메타를 보완한 후 재검증한다.
- 검증 대상 CSV: `chemistry_limits.csv`, `mechanical_limits.csv`, `heat_treatment.csv`,
  `nde_rules.csv`, `grade_routing.csv`, `mps_overrides.csv`, `code_edition_map.csv`.

---

## Phase 4: compare (결정적 비교)

**목적**: Python만으로 수치 판정이 가능한 항목을 CSV 기준값과 대조하여 findings를 생성한다.

```powershell
python -m scripts.cli compare --case <case_id>
```

- `compare_engine.compare_case`가 Phase 2 산출 JSON을 읽어 다음 항목을 판정한다:
  - **화학성분** (`data/chemistry_limits.csv`): Heat/Product Analysis 각각, grade별 원소 min/max.
    MPS override(`data/mps_overrides.csv`)가 있으면 Code 기준보다 MPS를 우선 적용.
  - **기계적 성질** (`data/mechanical_limits.csv`): TS/YS min, EL min, 경도 범위.
  - **열처리** (`data/heat_treatment.csv`): 각 단계 온도 범위, 유지시간.
    이탈량 ≤ 10°C → severity: Warning 비고, > 10°C → severity: Reject.
  - **NDE** (`data/nde_rules.csv`): 수행 여부, notch 규격(MILL/STOCK 구분).
  - **Grade 라우팅** (`data/grade_routing.csv`): 성적서 grade 문자열 → ASME spec 매핑.
    `data/code_edition_map.csv`로 ref_code 연도를 결정하고, 불일치 시 비고(C3).
- 모든 finding은 `source_validator.filter_valid_findings`를 통과해야 출력에 포함된다.
  출처 검증 탈락 항목은 `.cache/<case>/<case>_dropped.json`에 격리된다.
- 산출물: `.cache/<case>/<case>_findings.json`
- **수치 기준은 CSV에서만 인용한다. 코드에 하드코딩된 수치를 사용하지 않는다.**

---

## Phase 5: Claude 보조 판정

**목적**: 결정적 비교로 판정할 수 없는 `Identification` / `DocumentError` / `Other` 카테고리와
NDE·Microstructure 일부를 Claude가 직접 판단한다.

### 판단 대상

| Category | 검토 내용 | 필수 evidence channel |
|---|---|---|
| Identification | PO번호·규격 불일치, 성적서-MPS 자재 미매칭 | annotations 또는 emails 또는 mps |
| DocumentError | 날짜·서명 누락, 인감 미확인, 단위 표기 오류 | annotations 또는 emails 또는 body |
| NDE (보완) | 시험 누락, notch 규격 미확인 (사진 첨부 여부 포함) | body 또는 annotations |
| Microstructure | δ-ferrite 사진 미첨부, 측정값 범위 이탈 (P91 ≤5%, P92 ≤2.5%) | body 또는 annotations |
| Other | 이메일·주석에 명시된 특이사항 | annotations 또는 emails (필수) |

### 출처 인용 규칙 (C2)

> **evidence가 없으면 finding을 작성하지 않는다.**

- 각 finding의 `evidence` 배열에 반드시 하나 이상의 항목을 포함해야 하며, 각 항목은
  `source_file`, `anchor`, `snippet`, `sha256` 4종을 모두 갖춰야 한다.
- `annotations.json` 인용 예시:
  ```json
  {
    "channel": "annotations",
    "source_file": "rawdata/4/PU2405873-W2411008-SEONGHWA-1-21PCS MTC REV.1 Draft.pdf",
    "anchor": "p.2#annot-3",
    "snippet": "??? please explain the Mn value",
    "sha256": "<64-hex>"
  }
  ```
- `emails.json` 인용 예시:
  ```json
  {
    "channel": "emails",
    "source_file": "rawdata/4/review_query.msg",
    "anchor": "subject:Re: MTC Query",
    "snippet": "Ni content exceeds MPS limit",
    "sha256": "<64-hex>"
  }
  ```
- `sha256`는 `source_validator.compute_sha256(path)`로 계산한다 (직접 파일을 읽어 계산).
- `references/review-criteria.md` Severity 결정 룰을 참고한다:
  - MPS/Code 한계 초과(수치) → `Reject`
  - 요구 시험·기재 누락 → `ActionRequired`
  - "??? please explain" 등 의문 표기 → `Question`
  - 단순 표기 오류, 서명 누락 → `Minor`

Phase 5 산출 findings를 Phase 4 findings에 병합하여 `.cache/<case>/<case>_findings.json`을
갱신한다. 병합 후 `source_validator.filter_valid_findings`를 재실행하여 탈락 항목을 격리한다.

---

## Phase 6: build-report

**목적**: Phase 4/5의 findings를 6-시트 한국어 Excel 보고서로 출력한다.

```powershell
python -m scripts.cli build-report --case <case_id>
```

- 산출물: `output/reports/<case_id>/<case_id>_MTC_Review.xlsx`
- **6-시트 구성**:

  | # | 시트명 | 내용 |
  |---|---|---|
  | 1 | 종합 요약 | 케이스별 PASS/FAIL, finding 집계, 검토 일시 |
  | 2 | 화학성분 | Heat/Product Analysis 원소별 값 vs 기준, 판정 |
  | 3 | 기계적 성질 | TS/YS/EL/RA/경도 vs 기준, 판정 |
  | 4 | 열처리 | 단계별 온도·시간 vs 기준, 판정 |
  | 5 | NDE / 특별요구 | UT/MT/PT/PMI 수행 여부, notch 규격, δ-ferrite |
  | 6 | Finding 목록 | finding_id, category, severity, issue_summary, evidence 요약 |

- 모든 finding은 `source_validator.filter_valid_findings` 통과 후 시트에 기입한다.
  탈락 항목은 시트 6 하단에 별도 행으로 표시하되 "[DROPPED - 출처 미확인]" 문구를 붙인다.
- 보고서 문구(issue_summary·note·doc_checks 등)에 절 기호(섹션 부호)를 사용하지 않는다. 기준 조항 참조는 `기준 3.1` 형식으로 표기한다.
- 파일 인코딩: `openpyxl`의 기본값(UTF-8 내부 저장). 한국어 폰트 폴백 사용.

---

## Phase 7: evaluate

**목적**: Phase 6 보고서 findings를 GT(정답)와 비교하여 PASS/FAIL을 판정한다.

```powershell
# 단일 케이스
python -m scripts.cli evaluate --case <case_id>

# 전체 46 케이스
python -m scripts.cli evaluate --all
```

- `scripts/eval_harness.py`가 `standard inspection GT data/`를 읽는 **유일한 모듈**이다.
  이 명령 외 어느 경로에서도 GT 디렉토리를 직접 열지 않는다 (C4).
- **PASS 기준 (4가지 동시 충족)**:
  1. GT finding 104건 전부 매칭 (`recall = 104/104 = 1.0`)
  2. 46개 케이스 각각에서 케이스 내 GT finding 100% 매칭
  3. Precision ≥ 0.90 (보고서 finding 중 GT 대응 없는 비율 ≤ 10%)
  4. `dropped = 0` (출처 검증 탈락 finding 없음)
- Rubric 점수(`references/review-criteria.md` 기반 8개 항목 가중치)는 진단 보조 지표로만 활용하며
  PASS/FAIL 판정에 사용하지 않는다.
- 산출물: `output/eval/<case_id>_eval.json` 또는 `output/eval/all_eval.json`

---

## 전체 실행 흐름 요약

```
Phase 0  build-manifest          → manifest.json (46 cases)
Phase 1  prep-inputs --case <id> → .cache/<id>/png/*.png
                                   .cache/<id>/*_annotations.json  [rawdata 원본 대상]
                                   .cache/<id>/emails.json
Phase 2  [CLAUDE VISION OCR]     → .cache/<id>/*_extracted.json
          Read PNG → transcribe    (Python OCR 금지)
Phase 3  validate-refs            → exit 0 필수
Phase 4  compare --case <id>     → .cache/<id>/<id>_findings.json (결정적)
Phase 5  [CLAUDE 보조 판정]       → findings 병합 (evidence 필수, 없으면 작성 금지)
Phase 6  build-report --case <id>→ output/reports/<id>/<id>_MTC_Review.xlsx (6 시트)
Phase 7  evaluate --case <id>    → output/eval/<id>_eval.json
          (또는 --all)              PASS = recall 104/104 & 46/46 & precision≥0.9 & dropped=0
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

Claude 보조 판정 시 세부 도메인 규칙(화학 복합 룰, NDE 특별요건, finding 카테고리 매핑,
severity 결정 룰 등)은 `references/review-criteria.md`를 참조한다.
