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
| **C2** | 모든 finding의 `evidence` 항목은 출처 메타(`source_file` / `anchor` / `snippet`) 필수. `source_validator`가 부재 항목을 격리. |
| **C3** | ref_code 연도가 MPS 명시 연도와 다를 경우 비고에 명시. |
| **C7** | 실행 환경은 Windows PowerShell + Python. 모든 명령은 플러그인(skill) 디렉토리에서 `PYTHONIOENCODING=utf-8`을 앞에 붙여 `python -m scripts.cli ...` 형식으로 실행. |
| **C8** | CSV 기준값 row는 출처 메타 3종 없으면 로딩 단계에서 거부 (`validate-refs` exit 0 필수). |

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

## 병렬 실행 규칙 (다중 케이스 fan-out)

> **[MANDATORY — 다중 케이스 실행 시 본 절을 먼저 적용한다.]** 단일 케이스 실행은 기존 Phase 0→6 순차 흐름을 그대로 따른다.

지배적 비용은 Phase 2 Claude Vision OCR(케이스당 약 11~12분)이며, 케이스 간에는 의존이 없다. 따라서 다중 케이스(`--all` 또는 케이스 묶음) 실행 시 **케이스 단위 서브에이전트 fan-out**으로 wall-clock을 단축한다. 토큰량·절차·품질 의무는 단일 케이스와 동일하다 — 병렬화는 속도 규칙일 뿐 어떤 품질 의무도 대체하지 않는다.

| 단계 | 실행 위치 | 사유 |
|---|---|---|
| **Phase 0 build-manifest** | **fan-out 이전에 1회** | `manifest.json`은 공유 단일 파일 — 동시 쓰기 충돌 방지 |
| **Phase 3 validate-refs** | **fan-out 이전에 1회** | `data/*.csv` 출처 검증은 전 케이스 공통, exit 0 선결 게이트 |
| **Phase 1→2→2.5→4** | **케이스별 서브에이전트가 자기완결 수행** | 산출물이 `.cache/<case>/`로 분리되어 충돌 없음 |
| **게이트 수합** | **본 루프** | 각 케이스 에이전트의 Phase 2.5 / Phase 4 게이트 결과만 모아 집계 |

### 절차

1. **공유 단계 선실행**: fan-out 이전에 `build-manifest`(Phase 0)와 `validate-refs`(Phase 3)를 **각각 1회** 실행한다. `validate-refs` exit 0이 아니면 fan-out을 시작하지 않는다.
2. **케이스 단위 fan-out**: manifest의 케이스를 **동시성 6~10**으로 케이스별 서브에이전트에 배분한다. 각 서브에이전트는 자기 케이스의 Phase 1→2→2.5→4를 자기완결로 수행한다. 케이스별 산출물(`.cache/<case>/png/`, `<stem>_extracted.json`, `<case>_review.json` 등)은 경로가 분리되어 있어 쓰기 충돌이 없다.
3. **게이트만 수합**: 본 루프는 각 케이스 에이전트로부터 Phase 2.5(check-extraction)·Phase 4(review.json 산출) 결과만 수합해 집계한다. 케이스 내부의 전사·판독 세부는 서브에이전트 책임이다.
4. **케이스 에이전트 전달 컨텍스트(최소)**: 다음만 전달하면 자기완결 실행이 가능하다.
   - **케이스 id** (예: `--case 4`)
   - **플러그인(skill) 디렉토리 경로** (CLI 실행 기준, `scripts/cli.py`의 부모)
   - **준수 제약**: 불변 제약 C1~C8, 입력 3폴더 화이트리스트, 본 SKILL.md의 Phase 1→2→2.5→4 절차 전체(전 페이지 의무·verbatim 전사·evidence 필수 포함)
5. **Phase 5·6은 수합 후**: 보고서(Phase 5)·평가(Phase 6)는 전 케이스 review.json이 모인 뒤 본 루프 또는 `evaluate --all`로 일괄 수행한다.

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
    │   ├── <stem>_prep.json                        ← prep-inputs 사이드카 (PDF sha256 + dpi, 캐시 게이트용)
    │   ├── crops/                                  ← crop CLI 고DPI 영역 PNG (모호 셀 재판독)
    │   ├── <stem>_extracted.json                   ← Vision OCR 산출물 (channels: body)
    │   ├── <case>_limits.json                      ← limits CLI 산출 (관련 기준값 행 + provenance)
    │   └── <case>_review.json                      ← compliance 검토 findings
    ├── .cache/cache_status.json                    ← cache-status 산출 (케이스별 fresh/legacy/stale/missing)
    ├── data/                                       ← 기준값 CSV (출처 메타 3종 필수)
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
#   PDF sha256+dpi 사이드카(<stem>_prep.json) 기록, 무변경 시 렌더 스킵
python -m scripts.cli prep-inputs --case 4
#   강제 재렌더 / DPI 지정
python -m scripts.cli prep-inputs --case 4 --dpi 200 --force

# 캐시 게이트: 케이스별 추출 신선도 판정 (fresh | legacy | stale | missing)
python -m scripts.cli cache-status --case 4
python -m scripts.cli cache-status --all

# 모호 셀 재판독: 고DPI 영역 crop (bbox는 0.0~1.0 분수 좌표, 좌상단 원점)
python -m scripts.cli crop --case 4 --stem <stem> --page 2 --bbox 0.10,0.42,0.55,0.50 --dpi 300

# Phase 3: 참조 CSV 출처 검증
python -m scripts.cli validate-refs

# Phase 4: 케이스별 관련 기준값 행만 추출 (provenance 3종 포함)
python -m scripts.cli limits --case 4

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

> **[MANDATORY — 캐시 게이트] Phase 1 이전에 `cache-status`를 먼저 실행한다.**
>
> ```powershell
> python -m scripts.cli cache-status --case <case_id>
> ```
>
> | 상태 | 의미 | 처리 |
> |---|---|---|
> | `fresh` | PDF sha256+dpi 일치, 추출 완전 | **Phase 1·2를 스킵**하고 기존 `<stem>_extracted.json`을 그대로 사용 |
> | `legacy` | 추출은 완전하나 구버전 사이드카(자동 backfill됨) | `fresh`와 **동일 취급** — Phase 1·2 스킵 |
> | `stale` | PDF sha256 불일치(원본이 바뀜) 또는 dpi 불일치 | Phase 1·2 **수행**(재렌더 + 재추출) |
> | `missing` | 추출 산출물 없음 | Phase 1·2 **수행** |
>
> - PDF가 바뀌면 `<stem>_prep.json`의 sha256과 현재 PDF가 불일치하여 자동으로 `stale`이 되고, 재추출이 강제된다. 즉 낡은 추출이 묵시 재사용되지 않는다.
> - **Phase 2.5 check-extraction 게이트는 캐시 히트(fresh/legacy) 여부와 무관하게 항상 실행한다.** 캐시 스킵이 완전성 검증을 면제하지 않는다.
> - 입력 무변경 재실행(evaluate 반복, 기준 개정 후 Phase 4만 재실행)에서는 전 케이스가 `fresh`/`legacy`가 되어 OCR Read가 0회로 떨어진다.

```powershell
python -m scripts.cli prep-inputs --case <case_id>
```

- `standard inspection Cert cleanup data/<case>/*.pdf`를 `pypdfium2`로 렌더링하여
  `.cache/<case>/png/<stem>_p01.png`, `_p02.png`, … 를 생성한다 (DPI 200, `--dpi`로 변경 가능).
- 케이스별 추출 스켈레톤 JSON(`<stem>_extracted.json`)을 함께 작성한다 (Phase 2 Vision이 채움).
- PDF의 `sha256`과 렌더 `dpi`를 사이드카 `.cache/<case>/<stem>_prep.json`에 기록한다. 동일 sha256+dpi이고 PNG가 모두 존재하면 재렌더를 스킵한다(`--force`로 강제 재렌더).
- **cert cleanup 폴더만 읽는다.** rawdata 원본은 가드가 차단한다.

---

## Phase 2: Claude Vision OCR (cert + MPS 스캔)

> **[MANDATORY — 모델이 직접 수행하는 OCR]**
>
> **Python OCR 라이브러리는 사용 금지. 모델(Claude CLI 에이전트)이 PNG 이미지를 `Read` 툴로 직접
> 열어 판독한다. `pytesseract`, `easyocr`, `paddleocr`, vision API 등 어떤 Python OCR도 호출 금지.**

> **[캐시 게이트]** Phase 1의 `cache-status`가 `fresh`/`legacy`인 cert는 Phase 2를 **스킵**하고 기존 `<stem>_extracted.json`을 그대로 사용한다. `stale`/`missing`인 cert만 아래 절차를 수행한다. (스킵 여부와 무관하게 **Phase 2.5 게이트는 항상 실행**한다.)

### 절차

1. **[전 페이지 의무 + 배치 Read]** `.cache/<case>/png/` 아래의 **모든** cert 페이지 PNG(`<stem>_pNN.png`)를 `Read` 툴로 빠짐없이 연다. **PNG는 한 메시지에 4~6장씩 병렬 `Read`로 연다**(페이지당 왕복을 4~6페이지당 1회로 줄인다). 단, **전사(transcribe)는 페이지별 entry로 빠짐없이 기록**한다 — 배치로 열어도 페이지 단위 기록 의무는 그대로다. 표가 없는 페이지(사진·첨부·표지)도 건너뛰지 말고 entry를 만들고 `remarks`에 그 성격을 기록한다(예: `"(첨부 사진 페이지 — 표 데이터 없음)"`). **일부 페이지만 골라 읽는 대표 샘플링 금지** — 후반 페이지의 치수표·NDE 첨부·이종 grade 품목이 누락되는 주 원인이다.
2. **[대형 cert 분할]** 페이지가 8장을 넘으면 페이지 구간을 나눠 서브에이전트로 병렬 추출하고(구간당 ≤8p), 구간 결과를 `page_extraction`에 병합한다. 병합 후 페이지 수가 PNG 수와 일치해야 한다.
3. 필요 시 `standard inspection MPS cleanup data/<case>/`의 MPS 스캔도 `Read`로 판독한다(식별·적합성 대조용).
4. 각 페이지에서 다음 항목을 판독하여 구조화 JSON으로 기록한다:
   - `header`: PO번호, 성적서번호, vendor, spec, grade, heat_no, 치수(OD×WT), 수량, 길이
   - `chemistry`: Heat/Product Analysis 구분, 원소별 값 (단위: %)
   - `mechanical`: TS/YS(MPa), EL(%), RA(%), 경도(HBW/HRC), impact(J at °C)
   - `heat_treatment`: 각 단계별 온도(°C), 유지시간(min), 냉각 방법
   - `nde`: UT/MT/PT/PMI 등 수행 여부, notch 규격, 결과
   - `remarks`: 특기사항 텍스트 목록 — **Remark/각주/별표(①②·^주석)·범례(legend) 줄을 반드시 포함**한다. PMI·ferrite·Code Case·열처리 세부조건은 표가 아니라 Remark/각주에 기재되는 관행이 있다.
   - `confidence`: `high` / `medium` / `low`
5. **[spec 번호 verbatim 전사 — 자동 보정 금지]** 성적서에 인용된 모든 표준 규격 번호(제품 spec, 원소재 spec, 시험규격)는 **화면에 보이는 문자 그대로** 전사한다. 존재하지 않는 규격으로 보여도 사전지식으로 비슷한 유효 규격에 맞춰 고치지 말 것 — 오기 자체가 검토 대상 신호다. 추정 정규화가 필요하면 `remarks`에 `"표기 원문: <보이는 그대로> (<유효 규격> 오기 추정)"` 식으로 원문과 추정을 분리 기록한다.
6. **[(Grade, Class, Heat) 전수 인벤토리]** 추출 완료 후 전 페이지 header를 종합해 `(grade, class, heat_no)` 고유 조합 목록을 만든다. 멀티 품목 성적서에서 Grade가 같아도 Class가 다르면 별개 품목이다. 이 인벤토리는 Phase 4에서 materials[] 커버리지 검증에 사용한다.
7. 산출물 형식은 `references/extraction-schema.json`을 따른다.
   파일명: `.cache/<case>/<cert_stem>_extracted.json`. `channels` 섹션은 **`body`만** 사용한다:
   - `body.engine = "claude-vision"`, `body.pages = [1, 2, ...]` (= page_extraction이 커버하는 전 페이지)
8. **화학성분 컬럼 정합성 검증** (OCR 직후 수행):
   - 각 원소값이 해당 grade의 통상 범위와 물리적으로 부합하는지 확인
     (예: P91의 Cr ≈ 8–9%, P22의 Cr ≈ 2%, A106의 C < 0.35%).
   - Cev 표기가 있으면 역산 일치 확인: `Cev = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15`
   - 불일치 시 OCR 재시도 대신 **해당 PNG를 다시 `Read`로 열어 명시 재판독**하고 `confidence: "low"` 기록.
   - 한 글자가 판정을 가르는 값(H/N, 0/O, 1/I, 5/6 혼동, 컬럼 정렬)은 임시 스크립트를 작성하지 말고 **`crop` CLI로 해당 셀 영역만 고DPI 재렌더**하여 확정한다. bbox는 0.0~1.0 분수 좌표(좌상단 원점)다.
     ```powershell
     python -m scripts.cli crop --case <case_id> --stem <stem> --page <n> --bbox x0,y0,x1,y1 --dpi 300
     ```
     출력된 절대경로의 crop PNG(`.cache/<case>/crops/`)를 `Read`로 재판독하고, 재판독 결과와 `confidence`를 해당 셀에 기록한다.

---

## Phase 2.5: check-extraction (완전성 게이트)

**목적**: Phase 2가 모든 렌더 페이지를 실제로 추출했는지 결정적으로 검증한다. **이 게이트를 통과하기 전에는 Phase 4 검토를 시작하지 않는다.**

```powershell
python -m scripts.cli check-extraction --case <case_id>
# 전체 케이스
python -m scripts.cli check-extraction --all
```

- 각 cert PDF에 대해: `page_extraction`이 모든 렌더 페이지 번호를 커버하고, `channels.body.pages`가 커버 페이지와 일치해야 exit 0.
- 빈 추출(`page_extraction: []`) 또는 페이지 누락 시 exit 1 — **Phase 2로 돌아가 누락 페이지를 추출**한다.

---

## Phase 3: validate-refs

**목적**: `data/*.csv`의 모든 row가 C2/C8 준수(출처 메타 3종 완비)임을 검증한다.

```powershell
python -m scripts.cli validate-refs
```

- `source_validator`가 각 CSV row의 `source_file` 존재, `snippet` 포함을 확인한다.
- **exit 0이 아니면 이후 단계를 진행하지 않는다.**
- 검증 대상 CSV: `chemistry_limits.csv`, `mechanical_limits.csv`, `heat_treatment.csv`,
  `nde_rules.csv`, `grade_routing.csv`, `mps_overrides.csv`, `code_edition_map.csv`.

---

## Phase 4: compliance 검토 (review.json)

**목적**: Phase 2 추출값을 ref_code/CSV 기준값 및 MPS 한계와 비교하고, 도메인 규칙을 적용하여
findings를 생성한다. Claude가 직접 판단하는 compliance 단일 경로다.

> **[비교 기준값 조회] Phase 4 시작 시 `limits --case <id>`를 먼저 실행한다.**
>
> ```powershell
> python -m scripts.cli limits --case <case_id>
> ```
>
> - 케이스 추출 인벤토리(grade·class)를 기반으로 관련 CSV 행만 추려 provenance 3종(`source_file`/`anchor`/`snippet`) 포함 JSON으로 `.cache/<case>/<case>_limits.json`에 산출한다. **수치는 여전히 CSV 유래이며 snippet/anchor가 보존되어 C2/C8을 충족한다.** CSV 원본 전체(590줄)를 스캔할 필요가 없다.
> - 비교에는 `<case>_limits.json`의 행만 사용한다.
> - 산출 JSON의 `unrouted`에 grade 라우팅 실패가 명시되면, **그 grade에 한해서만** CSV 원본(`data/*.csv`)·`references/review-criteria.md`로 수동 라우팅한다. (라우팅 성공 grade는 CSV 원본 재스캔 불필요.)

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
- **기준 14 (자체 인쇄 기준 자기정합)**: 성적서가 스스로 인쇄한 기준값(Standard value/Spec min·max 행)이 있으면 **모든 결과값 행을 그 인쇄 기준과 행·열 단위로 1:1 대조**한다. 결과값이 자체 표기 기준을 벗어나면 — 외부 Code CSV 기준으로 합격이라도 — `기준 미달` 또는 `기준값 오기`로 FAIL/DocumentError 보고. 더 느슨한 Code 값으로 묵시 대체 판정 금지.
- **기준 15 (spec 표기 검증)**: 추출된 verbatim 규격 번호를 보유 카탈로그(`grade_routing.csv`, `code_edition_map.csv`)와 대조한다. 카탈로그·실존 표준 목록에 없는 규격 번호는 유사 규격으로 치환하지 말고 `DocumentError — 존재하지 않거나 확인 불가한 규격 표기(재발행 대상)`로 보고한다.
- **기준 16 (Class 제한 및 인벤토리 커버리지)**: Phase 2의 (Grade, Class, Heat) 인벤토리 전 조합이 materials[]에 매핑됐는지 검증한다. MPS의 Class 제한 문구('특정 Class만 허용' / '타 Class 불허' 류)와 수기/적색 개정 노트는 체크리스트로 승격해, 측정값뿐 아니라 품목의 Class 표기와 인쇄 수검기준 범위 자체를 MPS와 대조한다.
- **NDE 적용성 분리 보고**: NDE 요건이 제품 형상(단부 구성 등)으로 트리거되는 경우, (a) "해당 제품이 트리거 특성(예: butt welding end)을 가짐"이라는 적용성 판정과 (b) "요건 미이행"이라는 위반 판정을 **각각 별도 finding으로** 기재한다.
- **교차대조 인계 노트**: 보고서 헤더에 MTC/Cert No., PO, 발행일, Heat와 함께 Denoted/Detail List가 커버하는 **PO Item 번호 전체와 수량을 빠짐없이** 열거하고, `MTC 번호-커버 항목 매핑은 동일 PO의 타 MTC와 교차 대조 필요` INFO 노트를 출력한다 (단일 케이스 입력으로 잡을 수 없는 MTC 번호 중복·재사용을 사람이 잡을 수 있게).
- 카테고리/severity/누락 vs 불일치 판정과 **finding 발행 게이트(기준 17)·검토자 표준 어휘(기준 18)**는 `references/review-criteria.md` 참조.

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
[다중 케이스] Phase 0·3을 fan-out 이전에 1회 → 케이스별 서브에이전트 fan-out(동시성 6~10) → 게이트 수합
[단일 케이스] 아래 순차 흐름

Phase 0   build-manifest          → manifest.json (cert/MPS 인덱스)   ※ fan-out 전 1회
Phase 3   validate-refs           → exit 0 필수                        ※ fan-out 전 1회
──── 이하 케이스별(서브에이전트 자기완결) ────
[GATE]    cache-status --case <id> → fresh/legacy = Phase 1·2 스킵, stale/missing = 수행
Phase 1   prep-inputs --case <id> → .cache/<id>/png/*.png (body) + <stem>_prep.json (sha256+dpi)
Phase 2   [CLAUDE VISION OCR]     → .cache/<id>/*_extracted.json (channels: body)
           PNG 4~6장씩 배치 Read(cert+MPS) → 페이지별 transcribe  (Python OCR 금지, 대표 샘플링 금지)
           대형 cert(>8p) 구간 분할(≤8p) 병렬 추출 → 병합, 모호 셀은 crop CLI 고DPI 재판독
Phase 2.5 check-extraction        → exit 0 필수 (전 페이지 추출 게이트, 캐시 히트와 무관하게 항상 실행)
Phase 4   limits --case <id>      → .cache/<id>/<id>_limits.json (관련 기준값 행 + provenance)
          [COMPLIANCE 검토]        → .cache/<id>/<id>_review.json
           limits 행으로 비교 + 도메인 규칙(기준 3.1·11.2·14·15·16·MPS 우선)
           + finding 발행 게이트(기준 17) + 표준 어휘(기준 18), evidence 필수
──── 이하 수합 후 일괄 ────
Phase 5   [compliance_report]     → output/reports/<id>/<id>_MTC_Review.xlsx (6 시트)
Phase 6   evaluate --case <id>    → output/eval/<id>_eval.json
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
