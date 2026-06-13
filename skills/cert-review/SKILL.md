---
name: cert-review
description: Inspection Certificate (MTC/성적서) review for piping materials. Compares scanned PDF certificates against MPS (구매시방서) and ASTM/ASME reference codes, emits a 6-sheet Korean Excel report, and evaluates against ground-truth. Use for MTC review, 성적서 검토, 자재 성적서, material test report verification.
argument-hint: "<case_id | --all>"
---

# cert-review — Claude 오케스트레이션 절차서

본 문서는 **Claude Code CLI 에이전트(오케스트레이터=메인 루프)가 직접 따르는** MTC(자재 성적서)
compliance 검토 실행 절차이다. 입력은 3폴더(`ref_code/`, cert cleanup, MPS cleanup)만 사용하며,
Python 결정적 모듈(`scripts/`)과 서브에이전트 위임 단계를 명확히 구분한다.

오케스트레이터는 결정적 CLI 실행·게이트 판정·병렬 위임 스케줄링·산출물 수합을 담당하고, 전사(Vision OCR)와
영역별 compliance 판정은 플러그인 서브에이전트(`agents/`)에 위임한다. **서브에이전트는 중첩 스폰이
불가하므로, 모든 병렬화·게이트는 본 스킬이 직접 수행한다.**

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
`PermissionError`가 발생한다 — 가드는 **rawdata와 GT를 동시에 차단**하여 검토 경로가 정답(GT)이나
원본 주석에 의존하지 않도록 강제한다. Claude 에이전트(오케스트레이터·서브에이전트 모두)의 `Read` 직접
접근도 금지된다. 평가는 `eval_harness.py`가 케이스별 `comments.md`를 내부에서 읽으므로 직접 접근 불필요.

---

## 서브에이전트 (`agents/`)

검토 작업은 **7개 플러그인 서브에이전트**에 위임한다. 각자 부분 산출물만 작성하고 오케스트레이터가 결정적 CLI로 병합한다. **세부 절차(전사 규칙·영역별 판정 룰)는 각 에이전트 문서 소관 — 본 SKILL.md에 중복 기재하지 않는다.**

| 에이전트 | model | 역할 | 부분 산출물 |
|---|---|---|---|
| `ocr-extractor` | claude-opus-4-8 | Phase 2 Vision **타일 판독** 전사 전용 (full / fragment 두 모드) | `<stem>_extracted.json` 또는 `parts/<stem>__pSSS-EEE.json` |
| `mps-extractor` | claude-opus-4-8 | Phase 4 직전 MPS 스캔 **1회 추출** → 검토 5에이전트가 소비하는 공유 digest 산출 | `<case>_mps_digest.json` |
| `chemistry-reviewer` | claude-opus-4-8 | Phase 4 화학성분 검토 | `<case>_review_chemistry.json` |
| `mechanical-reviewer` | claude-opus-4-8 | Phase 4 기계적 성질 검토 | `<case>_review_mechanical.json` |
| `heat-treatment-reviewer` | claude-opus-4-8 | Phase 4 열처리 검토 | `<case>_review_heat_treatment.json` |
| `nde-reviewer` | claude-opus-4-8 | Phase 4 NDE/특별요구 검토 | `<case>_review_nde.json` |
| `format-reviewer` | claude-opus-4-8 | Phase 4 문서·식별·인쇄기준 검토 | `<case>_review_format.json` |

- **모델**: 전 에이전트 claude-opus-4-8 — 다품목 MTC 식별·수치 판독 정확도 우선. OCR(전사)과 검토(판정)는 모델이 아니라 역할로 분리된다(300 DPI 필수).
- **타일 판독**: `ocr-extractor`는 전체 페이지 PNG 대신 페이지당 **2×2 중첩 타일**(`.cache/<case>/tiles/`)을 판독한다. 모델이 PNG를 Read할 때 긴 변 ~1568px로 다운샘플되어 전체 페이지(~3500px)는 작은 숫자가 뭉개지지만, 2×2 타일은 긴 변 ~1957px라 다운샘플 후에도 ~1.8배 선명해 **crop 없이** 판독된다.
- **주의**: `CLAUDE_CODE_SUBAGENT_MODEL` 환경변수가 설정돼 있으면 frontmatter의 model을 덮어쓴다 — 의도한 모델을 적용하려면 **이 환경변수를 해제한 상태로 실행**한다.
- **화학 정합성 책임 경계**: `ocr-extractor`는 1차 물리범위 스크리닝(원소값이 grade 통상범위에 부합하는지)만 수행하고, Cev 역산·crop 확정 재판독은 `chemistry-reviewer`가 책임진다.
- **MPS digest 공유**: MPS PDF는 스캔이라 검토자가 각자 Vision-OCR하면 중복·저속이다. `mps-extractor`가 MPS를 **1회 추출**해 영역별 블록(`chemistry`/`mechanical`/`heat_treatment`/`nde_microstructure`/`document_requirements`, 각 항목에 원문 source+verbatim 인용)으로 `<case>_mps_digest.json`에 저장하면, 검토 5에이전트는 자기 영역 블록만 읽고 **원본 MPS PDF/PNG를 열지 않는다**(digest에 해당 grade 요구가 없을 때만 폴백). 수치 기준값은 여전히 `<case>_limits.json`(CSV 유래) 우선이고, MPS 특별요구 텍스트만 digest에서 인용한다.

---

## Directory Layout (디렉토리 구조)

```
<WORK>/  (= 데이터셋 루트, 입력 상대 경로 앵커)
├── ref_code/                                       ← ASTM/ASME 코드 OCR (read-only)
├── standard inspection Cert cleanup data/<case>/   ← 성적서 PDF (body OCR 대상)
├── standard inspection MPS cleanup data/<case>/    ← MPS PDF
├── standard inspection GT data/<case>/comments.md  ← 평가 전용 (eval_harness만 접근)
├── output/                                         ← 보고서 산출물 및 평가 결과
└── ... plugin/ReportReviewer/                      ← 플러그인 루트
    ├── agents/                                     ← 플러그인 서브에이전트 (frontmatter model 포함)
    │   ├── ocr-extractor.md                        ← Phase 2 Vision 전사 (opus 4.8)
    │   ├── chemistry-reviewer.md                   ← Phase 4 화학 (claude-opus-4-8)
    │   ├── mechanical-reviewer.md                  ← Phase 4 기계 (claude-opus-4-8)
    │   ├── heat-treatment-reviewer.md              ← Phase 4 열처리 (claude-opus-4-8)
    │   ├── nde-reviewer.md                         ← Phase 4 NDE (claude-opus-4-8)
    │   └── format-reviewer.md                      ← Phase 4 문서/식별 (claude-opus-4-8)
    └── skills/cert-review/                         ← 본 스킬 디렉토리 (CLI 실행 기준)
        ├── SKILL.md  ·  manifest.json (build-manifest 산출)
        ├── .cache/<case>/                          ← 케이스별 중간 산출물
        │   ├── png/                                ← prep-inputs 렌더링 PNG
        │   ├── tiles/                              ← tile-inputs 2×2 중첩 타일 (페이지당 4 타일, <stem>_pNN_rRcC.png)
        │   ├── mps_png/                            ← prep-mps 렌더링 MPS PNG
        │   ├── mps_tiles/                          ← prep-mps MPS 2×2 중첩 타일 (mps-extractor 판독용)
        │   ├── <stem>_prep.json                    ← 사이드카 (PDF sha256+dpi, 캐시 게이트용)
        │   ├── parts/<stem>__pSSS-EEE.json         ← fragment 모드 구간 추출 (merge-parts 입력)
        │   ├── crops/                              ← crop CLI 고DPI 영역 PNG (모호 셀 재판독)
        │   ├── <stem>_extracted.json               ← Vision OCR 산출 (channels: body)
        │   ├── <case>_mps_digest.json              ← mps-extractor 산출 (영역별 MPS 특별요구 + 원문 인용, 검토 5에이전트 공유)
        │   ├── <case>_limits.json                  ← limits CLI 산출 (관련 기준값 + provenance)
        │   ├── <case>_review_<domain>.json         ← 검토 에이전트 부분 산출 (chemistry|mechanical|heat_treatment|nde|format)
        │   └── <case>_review.json                  ← merge-reviews 병합 결과 (Phase 5/6 입력)
        ├── .cache/cache_status.json                ← cache-status 산출 (fresh/legacy/stale/missing)
        ├── data/*.csv                              ← 기준값 CSV 7종 (아래 "도메인 규칙 참조 위치" 표)
        ├── references/                             ← extraction-schema.json · review-criteria.md
        └── scripts/                                ← Python 결정적 모듈 (cli·prep_inputs·source_validator·compare_engine·compliance_report·eval_harness)
```

> **경로 표기**: 플러그인(skill) 디렉토리는 본 문서가 있는 현재 디렉토리(`scripts/cli.py`의 부모)다.
> 서브에이전트(`agents/*.md`)는 그 상위 **플러그인 루트** 아래에 있다. CLI는 스킬 디렉토리에서 실행한다.
> 데이터셋 루트(`<WORK>`)는 `CERT_REVIEW_WORKDIR` 환경변수로 지정하거나, 미지정 시 CWD/플러그인 위치에서
> 위로 올라가며 `standard inspection Cert cleanup data` 폴더를 가진 디렉토리를 자동 탐색한다.

---

## PowerShell 사용 예시

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:CERT_REVIEW_WORKDIR = "<WORK>"   # (선택) 미지정 시 자동 탐색
Set-Location "<플러그인 디렉토리: 본 SKILL.md가 있는 곳>"

python -m scripts.cli build-manifest                    # Phase 0: cert/MPS 인덱스
python -m scripts.cli cache-status --case 4 | --all     # 캐시 게이트 (fresh|legacy|stale|missing)
python -m scripts.cli prep-inputs --case 4 [--dpi 300] [--force]   # Phase 1: PNG 렌더 + 사이드카
python -m scripts.cli tile-inputs --case 4 | --all      # Phase 1: 페이지 PNG → 2×2 중첩 타일 (페이지당 4)
python -m scripts.cli prep-mps --case 4 [--dpi 300]     # Phase 1: MPS PDF → mps_png + mps_tiles (mps-extractor 입력)
python -m scripts.cli merge-parts --case 4              # fragment(>6p) 구간 병합
python -m scripts.cli check-extraction --case 4 | --all # Phase 2.5: 완전성 게이트
python -m scripts.cli crop --case 4 --stem <stem> --page 2 --bbox 0.10,0.42,0.55,0.50 --dpi 300  # 모호 셀 재판독
python -m scripts.cli validate-refs                     # Phase 3: CSV 출처 검증
python -m scripts.cli limits --case 4                   # Phase 4: 관련 기준값 행 + provenance
python -m scripts.cli merge-reviews --case 4            # 검토 5에이전트 부분 산출 병합
python -m scripts.cli evaluate --case 4 | --all         # Phase 6: comments.md 기준 평가
```

---

## 시간 예산 (케이스 복잡도별 차등)

정확도를 시간을 위해 희생하지 않는다 — opus의 수치 셀 crop 정밀 판독은 케이스 복잡도가 요구하는 만큼 수행한다. 시간은 결과이지 상한이 아니다. 케이스 복잡도에 따라 목표 wall-clock을 차등 적용한다:

- **단순** (1~3페이지, 1~2 품목): 목표 **≤30분**.
- **표준** (4~6페이지, 수 개 품목): 목표 **≤60분**.
- **복합** (>6페이지 또는 7품목 이상 또는 다중 grade): **60~90분 허용**. 다중 케이스 동시 fan-out 시 opus 동시 호출 throttle로 더 늘 수 있다.

시간을 복잡도에 비례시키는 구조적 장치: ① 식별 확정은 ocr-extractor 1회로 단일화(검토자 재검증 금지) ② 검토자 crop은 판정 임계 셀 위주(무차별 전수 crop 금지) ③ 대형 cert(≤4p 구간) 병렬화(아래) ④ **타일링(tile-inputs)** — ocr-extractor가 2×2 중첩 타일을 판독하면 전체 페이지 대비 OCR이 **~2.6배 빨라지고 crop이 거의 0**으로 떨어진다(다운샘플로 뭉개지던 작은 숫자를 crop 없이 판독) ⑤ **MPS digest 공유(mps-extractor)** — MPS 스캔을 1회만 추출해 영역별 digest로 공유하면 검토 5에이전트의 MPS 중복 OCR이 제거되어 검토 wall이 **~3배 단축**된다(검토자별 각자 Vision-OCR ~95분 → digest 소비 ~32분, recall 회귀 없음). 다중 케이스 실행 시 케이스 내 5에이전트 병렬과 케이스 간 병렬이 겹치므로 총 동시 에이전트 6~10 상한을 유지한다.

---

## 병렬 실행 규칙 (2차원 오케스트레이션: 케이스 × 에이전트)

> **[MANDATORY] 본 루프(오케스트레이터)가 전 케이스의 에이전트 위임을 직접 스케줄링한다.**
> 케이스 래퍼 서브에이전트는 폐지한다 — 서브에이전트는 중첩 스폰이 불가하므로, 케이스 fan-out과
> 에이전트 fan-out을 모두 본 루프가 직접 수행한다.

병렬화는 속도 규칙일 뿐 어떤 품질 의무도 대체하지 않는다. 토큰량·절차·evidence 의무는 동일하다.

| 규칙 | 내용 |
|---|---|
| **Phase 0·3 선실행** | `build-manifest`·`validate-refs`는 fan-out 이전에 **각각 1회** 불변 실행. `validate-refs` exit 0 아니면 fan-out 시작 금지 |
| **동시 에이전트 총량** | 전체 합산 **6~10** 상한 (OCR·MPS 추출·검토 에이전트 합) |
| **케이스 파이프라인 중첩** | 케이스별로 OCR(Phase 1·2)·MPS 추출(`mps-extractor`, cert OCR과 병렬)·완전성 게이트(2.5)·검토(Phase 4)가 진행되며, **OCR 완료·2.5 통과·`<id>_mps_digest.json` 산출 케이스부터 검토 5에이전트를 투입**한다. 케이스 간 OCR 단계와 검토 단계의 중첩을 허용한다 (한 케이스가 OCR 중일 때 다른 케이스는 검토 중일 수 있음) |
| **Phase 5·6 일괄** | 보고서(Phase 5)·평가(Phase 6)는 **전 케이스 merge-reviews 완료 후** 본 루프 또는 `evaluate --all`로 일괄 수행 |

단일 케이스 실행은 아래 Phase 0→6 순차 흐름을 그대로 따른다 (fan-out 없이 동일 절차).

---

## Phase 0: build-manifest

**목적**: cert/MPS cleanup 두 디렉토리를 스캔하여 케이스 인덱스(`manifest.json`)를 생성한다 (`build-manifest`). **fan-out 이전에 1회만 실행한다** (공유 단일 파일 — 동시 쓰기 충돌 방지).

- `standard inspection Cert cleanup data/`, `standard inspection MPS cleanup data/`를 스캔한다.
- `rawdata/`와 `standard inspection GT data/`는 **스캔하지 않는다** (입력 가드).
- 산출물: 플러그인 디렉토리 `manifest.json` (schema_version: "2.0").
- 성공 기준: exit 0, `case_count` 출력.

---

## Phase 1·2·2.5: 입력 준비 + OCR 전사 (오케스트레이터 시퀀스)

케이스별로 아래 시퀀스를 수행한다. **결정적 CLI는 오케스트레이터가 직접 실행하고, Vision 전사만 `ocr-extractor`에 위임한다.**

### 1) 캐시 게이트 (오케스트레이터 실행)

> **[MANDATORY] 입력 준비 이전에 `cache-status --case <id>`를 먼저 실행한다.**
>
> | 상태 | 의미 | 처리 |
> |---|---|---|
> | `fresh` | PDF sha256+dpi 일치, 추출 완전 | **Phase 1·2를 스킵**하고 기존 `<stem>_extracted.json`을 그대로 사용 |
> | `legacy` | 추출은 완전하나 구버전 사이드카(자동 backfill됨) | `fresh`와 **동일 취급** — Phase 1·2 스킵 |
> | `stale` | PDF sha256 불일치(원본이 바뀜) 또는 dpi 불일치 | Phase 1·2 **수행**(재렌더 + 재위임) |
> | `missing` | 추출 산출물 없음 | Phase 1·2 **수행** |
>
> - PDF가 바뀌면 사이드카 sha256과 불일치하여 자동으로 `stale`이 되고 재추출이 강제된다 — 낡은 추출이 묵시 재사용되지 않는다.
> - **Phase 2.5 check-extraction 게이트는 캐시 히트(fresh/legacy) 여부와 무관하게 항상 실행한다.** 캐시 스킵이 완전성 검증을 면제하지 않는다.
> - 입력 무변경 재실행(evaluate 반복, 기준 개정 후 Phase 4만 재실행)에서는 전 케이스가 `fresh`/`legacy`가 되어 OCR Read가 0회로 떨어진다.

### 2) prep-inputs (오케스트레이터 직접 실행, 결정적) — `prep-inputs --case <id>`

- cert PDF를 `pypdfium2`로 렌더링하여 `.cache/<case>/png/<stem>_p01.png`, `_p02.png`, … 생성 (DPI 300, `--dpi`로 변경).
- **주의**: 기존 DPI 200 캐시는 dpi 불일치로 `stale` 처리되어 다음 실행 시 재렌더+재추출된다.
- 추출 스켈레톤 JSON(`<stem>_extracted.json`)과 사이드카(`<stem>_prep.json`, sha256+dpi)를 함께 작성한다.
- **실행 후 케이스의 PNG 수를 확인**하여 다음 단계 모드(full / fragment)를 결정한다.

### 2.5) tile-inputs (오케스트레이터 직접 실행, 결정적) — `tile-inputs --case <id>`

- prep-inputs 직후 실행한다. `.cache/<case>/png/` 의 각 페이지 PNG를 페이지당 **2×2 중첩 타일**(`.cache/<case>/tiles/<stem>_pNN_rRcC.png`, `r0`=상단·`r1`=하단, `c0`=좌·`c1`=우, 6% 중첩)로 분할한다.
- 이유: 모델이 PNG를 Read할 때 긴 변 ~1568px로 다운샘플되어 전체 페이지(~3500px)는 작은 숫자가 뭉개진다. 2×2 타일은 긴 변 ~1957px라 다운샘플 후에도 ~1.8배 선명해 ocr-extractor가 **crop 없이** 판독한다.
- 다음 단계 모드(full / fragment) 분기는 **여전히 PNG 수 기준**이며 타일링과 독립이다.

### 2.6) prep-mps (오케스트레이터 직접 실행, 결정적) — `prep-mps --case <id>`

- tile-inputs 직후 실행한다. `standard inspection MPS cleanup data/<case>/`의 MPS PDF를 `pypdfium2`로 렌더해 `.cache/<case>/mps_png/`에 PNG로, 이어서 페이지당 2×2 중첩 타일을 `.cache/<case>/mps_tiles/`에 생성한다(cert 타일링과 동일 원리 — 다운샘플로 뭉개지는 스캔 글자를 선명화).
- 이 산출물은 다음 단계의 `mps-extractor` 위임 입력이다. cert OCR 경로(prep-inputs/tile-inputs)와 독립적이므로 cert OCR 위임과 병렬로 진행할 수 있다.

### 3) ocr-extractor / mps-extractor 병렬 위임 (PNG 수에 따라 모드 분기, 타일 판독)

> cert 전사(`ocr-extractor`)와 MPS 추출(`mps-extractor`)은 **서로 독립적이므로 한 메시지에 병렬 위임**한다. `mps-extractor`는 `mps_tiles/`를 1회 판독해 영역별 블록(`chemistry`/`mechanical`/`heat_treatment`/`nde_microstructure`/`document_requirements`, 각 항목 원문 source+verbatim 인용)으로 `<case>_mps_digest.json`을 산출한다. 이 digest는 Phase 4 검토 5에이전트가 공유 소비한다(검토자는 원본 MPS를 다시 OCR하지 않는다).

- **PNG ≤ 6장 → full 모드**: `ocr-extractor` **1회 위임**. 에이전트가 케이스 전 페이지를 전사하여 `<stem>_extracted.json`을 직접 완성한다.
- **PNG > 6장 → fragment 모드**: 페이지를 **구간(≤4p)별로 분할**하여 `ocr-extractor`를 **병렬 위임**(한 메시지에 다중 위임)한다. 각 위임은 `parts/<stem>__pSSS-EEE.json` fragment를 저장한다. **전 구간 완료 후** 오케스트레이터가 `merge-parts --case <id>`로 병합한다 (스켈레톤 top-level 보존, 페이지 중복 시 결정적 우선순위·issue 보고).

**위임 컨텍스트 명세** (각 `ocr-extractor` 위임에 반드시 포함):
- 케이스 id
- 스킬 디렉토리 **절대경로**
- 모드(full / fragment) 및 fragment일 경우 담당 페이지 구간
- 준수 지시: **C1~C8, 입력 3폴더 화이트리스트, 타일 판독(페이지당 4 타일, crop 원칙적 생략), verbatim 전사, 전 페이지 의무**

> 전사 세부 절차(타일 배치 Read, 페이지별 entry, spec verbatim, (Grade,Class,Heat) 인벤토리, 화학 1차 스크리닝 등)는 `agents/ocr-extractor.md`가 보유한다 — **SKILL.md에 중복 기재 금지**.

**mps-extractor 위임 컨텍스트 명세** (`mps-extractor` 위임에 반드시 포함):
- 케이스 id
- 스킬 디렉토리 **절대경로**
- 산출 의무: `.cache/<case>/<case>_mps_digest.json` (영역별 블록 + 항목별 원문 source+verbatim 인용)
- 준수 지시: **C1~C8, 입력 3폴더 화이트리스트, MPS 타일 판독, verbatim 인용, 전 페이지 의무**

> MPS 추출 세부 절차(영역별 블록 분류, 요건 마크 판독, verbatim 인용 규칙 등)는 `agents/mps-extractor.md`가 보유한다 — **SKILL.md에 중복 기재 금지**.

### 4) check-extraction 게이트 (오케스트레이터 실행, 항상) — `check-extraction --case <id>`

- 각 cert PDF에 대해 `page_extraction`이 모든 렌더 페이지를 커버하고 `channels.body.pages`가 일치해야 **exit 0**.
- 빈 추출·페이지 누락 시 exit 1 — **누락 페이지 구간만 `ocr-extractor`에 재위임**(fragment 모드)하고 다시 게이트한다.
- **이 게이트 통과 전에는 Phase 4 검토를 시작하지 않는다.**

---

## Phase 3: validate-refs

**목적**: `data/*.csv`의 모든 row가 C2/C8 준수(출처 메타 3종 완비)임을 검증한다 (`validate-refs`). **fan-out 이전에 1회만 실행한다** (전 케이스 공통 선결 게이트).

- `source_validator`가 각 CSV row의 `source_file` 존재, `snippet` 포함을 확인한다.
- **exit 0이 아니면 이후 단계를 진행하지 않는다.**
- 검증 대상 CSV 7종: `chemistry_limits` · `mechanical_limits` · `heat_treatment` · `nde_rules` · `grade_routing` · `mps_overrides` · `code_edition_map`.

---

## Phase 4: compliance 검토 (오케스트레이터 시퀀스)

**목적**: Phase 2 추출값을 ref_code/CSV 기준값 및 MPS 한계와 비교하여 findings를 생성한다. 영역별 판정은 5개 검토 에이전트에 병렬 위임하고, 오케스트레이터가 결정적으로 병합한다.

### 1) limits 조회 (오케스트레이터 실행, 1회) — `limits --case <id>`

- 케이스 추출 인벤토리(grade·class)를 기반으로 관련 CSV 행만 추려 provenance 3종(`source_file`/`anchor`/`snippet`) 포함 JSON으로 `.cache/<case>/<case>_limits.json`에 산출한다. **수치는 여전히 CSV 유래이며 snippet/anchor가 보존되어 C2/C8을 충족한다.**
- 산출 JSON의 `unrouted`에 grade 라우팅 실패가 명시되면, **그 grade에 한해서만** CSV 원본·`review-criteria.md`로 수동 라우팅 정보를 확정하고, **위임 컨텍스트에 그 해소 정보를 첨부**한다. (라우팅 성공 grade는 추가 작업 불필요.)

### 2) 검토 5에이전트 병렬 위임 (한 메시지에 동시)

`limits` 완료 후(그리고 해당 케이스 `mps-extractor`가 `<case>_mps_digest.json`을 산출한 뒤), 아래 5개 에이전트를 **한 메시지에 병렬 위임**한다. 각 위임에 포함할 컨텍스트:
- 케이스 id
- 스킬 디렉토리 **절대경로**
- 자기 도메인 부분 산출 의무: `.cache/<case>/<case>_review_<domain>.json`
- (해당 시) unrouted grade 해소 정보
- **MPS 특별요구는 `<case>_mps_digest.json`의 자기 영역 블록에서 읽고 원본 MPS PDF/PNG는 열지 않는다**(digest에 해당 grade 요구가 없을 때만 폴백).

검토 에이전트는 ocr-extractor가 확정한 식별 필드(header의 grade/heat_no/cert_no/size/qty)를 재검증하지 않는다(시간 예산 절 참조).

**기준 번호 라우팅 표** (어떤 에이전트가 어떤 기준을 담당하는지만 — 판정 절차는 각 에이전트 문서 소관):

| 에이전트 | 담당 기준 |
|---|---|
| `chemistry-reviewer` | 기준 3.1 (A106 C/Mn 각주), MPS override, Cev 역산 |
| `mechanical-reviewer` | TS/YS/EL/RA/경도 범위 |
| `heat-treatment-reviewer` | 단계별 온도·시간, ±10°C 룰 |
| `nde-reviewer` | 기준 NDE 룰(MILL/STOCK notch), NDE 적용성 분리 보고, δ-ferrite·Code Case·PMI |
| `format-reviewer` | 기준 11.2 (식별 spec 계열), 기준 14 (자체 인쇄기준 자기정합), 기준 15 (spec 표기 검증), 기준 16 (Class 제한·인벤토리 커버리지) |

> 영역별 판정 세부(Cev 역산식, ±10°C 분기, 기준 11.2/14/15/16 적용 절차, finding 게이트(기준 17)·표준 어휘(기준 18))는 각 에이전트 문서 및 `references/review-criteria.md` 소관 — **SKILL.md에 중복 기재 금지**.

**도메인 경계 표 (중복 발행 방지)**:

| 항목 | 담당 도메인 |
|---|---|
| N / Al 수치 판정 | chemistry |
| δ-ferrite · Code Case · PMI | nde |
| 인쇄 기준 표기 오류 라벨(문서 결함) | format |
| 측정값 자체 판정(인쇄 기준 대비) | chemistry / mechanical (수치 소관 도메인) |
| 치수 / 수량 / Heat No | format |

### 3) merge-reviews (오케스트레이터 실행, 전원 완료 후) — `merge-reviews --case <id>`

검토 에이전트가 grade 정정(인벤토리와 상이)을 보고하면, 오케스트레이터는 해당 케이스의 `limits --case`를 재실행해 정정 grade의 기준값 행(MPS override 포함)을 재공급하고 영향 영역을 재위임하는 것이 원칙이다(에이전트의 CSV 원본 수동 보강은 보조 경로).

- 부분 5파일(`<case>_review_chemistry.json` … `_format.json`)을 단일 `<case>_review.json`으로 **결정적 병합**한다: 전역 finding 재채번, verdict 최악값 집계. **하류 Phase 5/6 계약 불변.**

### 출처 인용 규칙 (C2)

> **evidence가 없으면 finding을 작성하지 않는다.** 각 finding의 `evidence` 배열에 최소 하나의 항목을 두고, `snippet`은 채널 원문(body/MPS)에 literal로 존재해야 한다(`source_validator`가 부재 snippet을 격리). **수치 기준은 CSV에서만 인용 — 코드 하드코딩 수치 사용 금지.**

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
PASS/FAIL을 판정한다 (`evaluate --case <id>` / `--all`).

- `scripts/eval_harness.py`가 `standard inspection GT data/<case>/comments.md`를 읽는 **유일한 모듈**이다. 이 명령 외 어느 경로에서도 GT 디렉토리를 직접 열지 않는다 (입력 가드).
- GT는 검토자 실제 지적을 **페이지×주제로 클러스터링**한 `comments.md`이며, 예측 finding과 매칭하여 recall/precision/case_pass를 산출한다.
- 산출물: `output/eval/<case_id>_eval.json` 또는 `output/eval/all_eval.json`, 요약 markdown 리포트.

---

## 전체 실행 흐름 요약

```
[다중] Phase 0·3 fan-out 전 1회 → 본 루프가 케이스×에이전트 2차원 스케줄링
       (동시 6~10, OCR 완료·2.5 통과 케이스부터 검토 투입)   [단일] 아래 순차 (fan-out 없이 동일)

Phase 0   build-manifest    → manifest.json                                    ※ fan-out 전 1회
Phase 3   validate-refs     → exit 0 필수                                       ※ fan-out 전 1회
──── 이하 케이스별 (오케스트레이터 시퀀스) ────
[GATE]    cache-status      → fresh/legacy = Phase 1·2 스킵 / stale/missing = 수행
Phase 1   prep-inputs       → png/*.png + <stem>_prep.json (직접 실행) → PNG 수로 모드 결정
          tile-inputs       → tiles/*_pNN_rRcC.png (페이지당 2×2 중첩 타일, 직접 실행)
          prep-mps          → mps_png/*.png + mps_tiles/*.png (MPS 렌더+타일, 직접 실행)
Phase 2   [위임 ocr-extractor/opus]  ≤6p full 1회 → <stem>_extracted.json   ┐ 병렬
                                       >6p fragment 병렬(≤4p) → parts/*.json → merge-parts │
          [위임 mps-extractor/opus]  mps_tiles 1회 판독 → <id>_mps_digest.json           ┘
                            (타일 판독·C1·verbatim·전 페이지 의무, 세부 agents/ocr-extractor.md·mps-extractor.md)
Phase 2.5 check-extraction  → exit 0 필수 (항상 실행, 실패 시 누락 구간만 재위임)
──── OCR 완료·2.5 통과·mps_digest 산출 케이스부터 ────
Phase 4   limits → <id>_limits.json  → [위임 검토5/claude-opus-4-8 한 메시지 병렬]
            chemistry·mechanical·heat_treatment·nde·format → <id>_review_<domain>.json
            (MPS 특별요구는 <id>_mps_digest.json 자기 영역 블록 소비 — 원본 MPS 미개봉)
          merge-reviews → <id>_review.json (재채번·verdict 최악값, 하류 계약 불변)
──── 전 케이스 merge-reviews 후 일괄 ────
Phase 5   compliance_report → output/reports/<id>/<id>_MTC_Review.xlsx (6 시트)
Phase 6   evaluate --case <id> | --all → output/eval/*  (recall/precision/case_pass)
```

> **모델 주의**: 전 에이전트 claude-opus-4-8(OCR·검토 동일)은 각 에이전트 frontmatter의 model로
> 적용된다. `CLAUDE_CODE_SUBAGENT_MODEL`이 설정돼 있으면 이를 덮어쓰므로 **해제 상태로 실행**한다.

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
severity 결정 룰 등)은 각 검토 에이전트 문서(`agents/*-reviewer.md`)와
`references/review-criteria.md`를 참조한다.
