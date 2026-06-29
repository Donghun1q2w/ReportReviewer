# ReportReviewer

파이프 자재 **MTC(Mill Test Certificate / 성적서) 자동 검토** Claude Code 플러그인.

스캔된 성적서 PDF를 **Claude Vision으로 OCR**하고, **MPS(구매시방서)** 및 **ASTM/ASME 코드** 기준값과 대조하여 PASS/FAIL/지적사항을 판정, **6시트 한글 Excel 리포트**를 생성한다. 모든 기준값은 ref_code/MPS 원문에서 인용하며(출처 3종 메타 검증) **LLM이 기준값을 생성하지 않는다**.

> 사내 전용(Proprietary). [LICENSE](LICENSE) 참조.

## 핵심 특징

- **2차원 병렬 아키텍처**: 오케스트레이터(SKILL.md)가 케이스 × 도메인 에이전트를 직접 스케줄링 (동시 6~10). 케이스 래퍼 에이전트 없음 — 서브에이전트는 중첩 스폰 불가이므로 모든 fan-out을 오케스트레이터가 직접 수행한다.
- **역할 분리 서브에이전트**: OCR 전용(`ocr-extractor`, claude-opus-4-8) + MPS 추출 전용(`mps-extractor`, claude-opus-4-8) + 도메인별 검토 5종(`claude-opus-4-8`) — 전사(판독)·MPS 추출·판정을 역할로 분리.
- **결정적 병합 단계**: 검토 5에이전트가 각자 부분 산출물을 쓰고, `merge-reviews` CLI가 전역 재채번 및 verdict 최악값으로 결정적 병합. 하류 Phase 5/6 계약 불변.
- **Claude Vision OCR 강제**: Python OCR 라이브러리 일체 미사용 (`pytesseract`/`easyocr`/`pymupdf` 등 금지, AST 회귀로 검증). PDF는 `pypdfium2`로 페이지를 렌더링하고, `pypdf`는 출처 검증용 임베디드 텍스트 추출에만 쓴다
- **출처 강제(provenance)**: 모든 판정 근거에 `source_file`/`anchor`/`snippet` 3종 메타. 미검증 근거는 자동 격리
- **단일 OCR 입력 채널**: cert 본문을 Claude Vision으로 전사하는 `channels.body` 하나만 사용한다. 입력은 3개 카테고리(① 참조 코드 ② 성적서 ③ MPS) 폴더로 인식하며, 이메일(.msg)·zip 첨부·PDF 주석을 입력 채널로 받지 않는다(원본 reviewer 주석은 입력 가드로 차단).
- **6시트 한글 리포트**: 검토 총괄 / 화학성분 / 기계적성질 / 열처리 / 표기·형식 / 지적사항 종합
- **검토 결과 PDF 주석(별도 스킬 `cert-review-annotate`)**: 검토 후 후순위 단계로 주의/N/A/FAIL 판정(PASS 제외)을 원본 cert PDF 위에 테두리 사각형(채우기 없음)+50자 한글 라벨로 **image burn-in**. 좌표는 전용 `annotation-locator` 에이전트가 review.json에서 산출하고 색은 리포트와 동일하며, cert-review 검토 로직은 무수정

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
/cert-review-annotate       # 위 검토 후, 결과(주의/N/A/FAIL)를 원본 PDF에 주석으로 표기
# (`--all` / `<case_id>` 형태의 케이스 선택은 플러그인 테스트 하니스 회귀 전용)
```

> `cert-review`·`cert-review-annotate` 두 스킬은 같은 플러그인에 포함되어 한 번의 설치로 함께 제공된다.

또는 Python CLI를 직접 실행 (Windows PowerShell):

```powershell
cd skills/cert-review
$env:PYTHONIOENCODING="utf-8"
$env:CERT_REVIEW_WORKDIR="<성적서/MPS/ref_code가 있는 작업 폴더>"
python -m scripts.cli build-manifest            # Phase 0: cert/MPS 인덱스
python -m scripts.cli validate-refs             # Phase 3: CSV 출처 검증 (fan-out 전 1회)
python -m scripts.cli cache-status --case <id>  # Phase 1: 캐시 게이트 (fresh/legacy면 OCR 스킵)
python -m scripts.cli prep-inputs --case <id>   # Phase 1: cert PDF→PNG (300 DPI)
python -m scripts.cli tile-inputs --case <id>   # Phase 1: 페이지 PNG→2×2 중첩 타일 (ocr-extractor 판독 입력)
python -m scripts.cli prep-mps   --case <id>    # Phase 1: MPS PDF→PNG+타일 (mps-extractor 입력)
#  -> ocr-extractor + mps-extractor(claude-opus-4-8) 병렬 위임 (SKILL.md Phase 2)
#     ocr-extractor: tiles 판독→<stem>_extracted.json (>6p는 fragment 위임 후 merge-parts)
#     mps-extractor: mps_tiles 1회 추출→<case>_mps_digest.json (검토 5에이전트 공유)
python -m scripts.cli check-extraction --case <id>  # Phase 2.5: 완전성 게이트 (통과 전 검토 금지)
#  -> limits 조회 후 chemistry/mechanical/heat-treatment/nde/format-reviewer 병렬 위임 (Phase 4)
python -m scripts.cli merge-reviews --case <id> # 부분 산출 결정적 병합
python -m scripts.cli evaluate --all            # Phase 6: GT 평가(있을 시)
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
│   ├── mps-extractor.md              # Phase 4 직전 MPS 스캔 1회 추출 (claude-opus-4-8) → <case>_mps_digest.json
│   ├── chemistry-reviewer.md         # Phase 4 화학성분 검토 (claude-opus-4-8)
│   ├── mechanical-reviewer.md        # Phase 4 기계적 성질 검토 (claude-opus-4-8)
│   ├── heat-treatment-reviewer.md    # Phase 4 열처리 검토 (claude-opus-4-8)
│   ├── nde-reviewer.md               # Phase 4 NDE/특별요구 검토 (claude-opus-4-8)
│   ├── format-reviewer.md            # Phase 4 문서·식별·인쇄기준 검토 (claude-opus-4-8)
│   └── annotation-locator.md         # (cert-review-annotate) review.json→주석 좌표 산출 (claude-opus-4-8)
├── skills/cert-review/
│   ├── SKILL.md                      # Claude 오케스트레이션 절차서 (Phase 0~6)
│   ├── scripts/                      # 결정적 Python 모듈 (CLI/엔진/평가)
│   │   ├── merge_reviews.py          # 검토 5에이전트 부분 산출 결정적 병합
│   │   ├── annotate_pdf.py           # (cert-review-annotate) 주석 PDF 렌더러 (copy-through burn-in)
│   │   └── ...
│   ├── data/*.csv                    # 참조 기준값 7종 (출처 3종 메타 검증)
│   ├── references/                   # review-criteria / conventions / extraction-schema
│   └── tests/                        # 111개 단위 테스트 (test_annotate_pdf.py 16·test_merge_reviews.py 12 포함)
├── skills/cert-review-annotate/      # 주석 표기 스킬 (cert-review 래핑 + 후순위 주석)
│   └── SKILL.md                      # Phase A(cert-review) → B(locator) → C(annotate CLI)
├── docs/eval-summary.md              # 평가 결과·잔여 분석
├── requirements.txt
└── LICENSE
```

## 서브에이전트 (`agents/`)

오케스트레이터(SKILL.md)가 위임하는 **7개 플러그인 서브에이전트**. 각자 부분 산출물만 작성하고, 오케스트레이터가 결정적 CLI(`merge-reviews`)로 병합한다.

| 에이전트 | model | 담당 | 부분 산출물 |
|---|---|---|---|
| `ocr-extractor` | claude-opus-4-8 | Phase 2 Vision 전사 (full / fragment 두 모드) | `<stem>_extracted.json` |
| `mps-extractor` | claude-opus-4-8 | Phase 4 직전 MPS 스캔 1회 추출 → 검토 5에이전트가 공유 소비하는 digest 산출 | `<case>_mps_digest.json` |
| `chemistry-reviewer` | claude-opus-4-8 | 화학성분 검토 + Cev 역산·crop 확정 | `<case>_review_chemistry.json` |
| `mechanical-reviewer` | claude-opus-4-8 | 기계적 성질 검토 | `<case>_review_mechanical.json` |
| `heat-treatment-reviewer` | claude-opus-4-8 | 열처리 검토 (±10°C 룰) | `<case>_review_heat_treatment.json` |
| `nde-reviewer` | claude-opus-4-8 | NDE/특별요구 (δ-ferrite·PMI·Code Case) | `<case>_review_nde.json` |
| `format-reviewer` | claude-opus-4-8 | 표기형식·식별 (기준 11/14/15/16, doc_checks) | `<case>_review_format.json` |

**모델 원칙**: 전 에이전트 claude-opus-4-8(정확도 우선 — 다품목 MTC 식별·수치 판독, 300 DPI 필수). OCR(전사)과 검토(판정)는 모델이 아니라 역할로 분리되며, 복잡도별 차등 예산(단순 ≤30분 / 표준 ≤60분 / 복합 60~90분, 정확도 최우선)으로 운용한다. `CLAUDE_CODE_SUBAGENT_MODEL` 환경변수가 설정돼 있으면 각 에이전트 frontmatter의 model을 덮어쓰므로 **해제 상태**로 실행한다.

> 별도 주석 스킬 `cert-review-annotate`는 위 7개와 독립적으로 `annotation-locator`(claude-opus-4-8) 1개를 위임해, 검토 후(후순위) review.json의 주의/N/A/FAIL 항목에 대한 주석 좌표 `<case>_annotations.json`을 산출한다.

## 병합 CLI (`merge-reviews`)

검토 5에이전트가 각자 `.cache/<case>/<case>_review_<domain>.json`(domain: `chemistry` / `mechanical` / `heat_treatment` / `nde` / `format`)을 작성한 뒤, 아래 명령으로 단일 `<case>_review.json`으로 결정적 병합한다:

```powershell
python -m scripts.cli merge-reviews --case <id>   # 단일 케이스
python -m scripts.cli merge-reviews --all          # 전 케이스
```

병합 결과는 전역 finding 재채번·verdict 최악값을 보장하며, 하류 Phase 5(보고서)·Phase 6(평가) 계약은 불변이다.

## 검토 결과 PDF 주석 (`cert-review-annotate`)

검토 결과를 **원본 MTC PDF 위에 주석으로 표기**하는 별도 스킬. 기존 `cert-review`를 포함(래핑)하고 **후순위 단계**로 주석을 생성한다 — cert-review의 검토 로직(5 reviewer·`review-criteria.md`·`review.json` 스키마·`merge-reviews`)은 **무수정**이며, review.json을 읽기 전용으로 소비한다.

```
Phase A  cert-review (무수정) ──→ <case>_review.json + 6시트 Excel
Phase B  annotation-locator 에이전트 ──→ <case>_annotations.json  (주의/N/A/FAIL 좌표)
Phase C  annotate CLI ──→ output/reports/<case>/<stem>_annotated.pdf
```

- **대상/형태**: verdict **주의 / N/A / FAIL**(PASS 제외)을 테두리 사각형(채우기 없음)+≤50자 한글 라벨로 표기. **색**: `compliance_report` 상수 재사용 → 주의 노랑·N/A 회색·FAIL 빨강(엑셀 리포트와 100% 일치).
- **좌표**: 전용 `annotation-locator`(Vision, claude-opus-4-8)가 review.json 대상 항목을 캐시된 페이지에서 셀 bbox(Tier A — 확정 좌표만)로 산출. 추정 좌표 박스 금지.
- **렌더**: `annotate_pdf.py`가 **copy-through image burn-in** — 주석 있는 면만 `pypdfium2` 래스터+`Pillow` 드로잉, 나머지 면은 `pypdf`로 원본 보존(텍스트 레이어·용량·메모리 최소). 신규 의존성 0, C1 준수(OCR 라이브러리 미사용).

```powershell
cd skills/cert-review; $env:PYTHONIOENCODING="utf-8"
python -m scripts.cli annotate --case <id>      # <case>_annotations.json 소비 → <stem>_annotated.pdf
python -m scripts.cli annotate --all            # annotations.json 있는 케이스 일괄
```

> 하위호환: `<case>_annotations.json`이 없으면 단일 케이스는 에러(1), `--all`은 해당 케이스 SKIP. 좌표가 없는 한 표기 0건으로 안전 동작한다. 폰트는 기본 `malgun.ttf`이며 `CERT_REVIEW_FONT`로 재정의한다. 전체 절차는 [`skills/cert-review-annotate/SKILL.md`](skills/cert-review-annotate/SKILL.md) 참조.

## 검증 (개발)

```powershell
cd skills/cert-review; $env:PYTHONIOENCODING="utf-8"

# 단위 테스트 — 데이터셋 없이도 실행 (이식성 테스트 포함, 데이터셋 의존 테스트는 skip).
# 데이터셋이 있으면 CERT_REVIEW_WORKDIR 지정 시 111개 전부 실행.
python -m pytest tests/ -q

# 참조 CSV 출처 검증 — ref_code/MPS 원문이 있는 데이터셋 필요 (CI/testbed 작업).
$env:CERT_REVIEW_WORKDIR="<ref_code/, MPS/가 있는 데이터셋 폴더>"
python -m scripts.cli validate-refs    # 7 CSV / 583행 / 0 failures
```

> `validate-refs` / `build-manifest` / `evaluate`는 **소스 데이터셋**(ref_code OCR, MPS 스캔, GT)을 참조하므로 `CERT_REVIEW_WORKDIR`로 데이터셋 폴더를 가리켜야 한다. 배포본에 포함된 `data/*.csv`는 testbed에서 **이미 출처 검증을 통과한 산출물**이다 (대용량 원문은 배포 미포함).

## 평가 결과 (standard-inspection 46 케이스)

| recall | full-recall cases | precision | dropped | tests |
|---|---|---|---|---|
| 91/104 = 87.5% | 36/46 | 91.0% | 0 | 111/111 |

매칭 정의(content+grade+page+severity-tier, Issue 매칭)와 잔여 10건 분석: [`docs/eval-summary.md`](docs/eval-summary.md).
