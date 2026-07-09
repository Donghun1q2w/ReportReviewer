# 페이지 회전 정렬(문서 정렬 에이전트) — OCR 이전 단계 페이지별 방향 교정

- **작성**: 2026-07-09 08:56 · **Rev.1**: 2026-07-09 (사용자 검토 반영)
- **상태**: Completed (2026-07-09 13:36 — pytest 145/145, PU2601233 E2E 검증, page-aligner=opus 4.8 확정)
- **대상**: `plugin/ReportReviewer` (cert-review 스킬 + agents)
- **참조문서**: `standard inspection Cert cleanup data/PU2601233/PU2601233-2-MTC.pdf` (73p)

> **Rev.1 변경 (사용자 검토 피드백)**
> 1. **MPS 정렬 제외** — 정렬 대상을 성적서(cert)로 한정. `orient-sheets`는 `png/`만 읽고, `align-inputs`의 MPS 타일 재생성 로직 삭제, `prep-mps` 무변경.
> 2. **모델 선정 벤치마크 추가** — page-aligner 모델을 고정하지 않고 opus 4.8 → sonnet 5 → haiku 4.5 순차 실측(동일 시트, GT 대비 정확도+비용)하여 성능·가격 최적 모델을 frontmatter에 확정.

## Summary

스캔 성적서 PDF가 페이지별로 회전된 상태로 입력되는 경우(참조문서 실측: 73p 중 다수 페이지가 90° 회전, 정상 페이지와 혼재), OCR(Phase 2) 이전에 **문서 정렬 에이전트(page-aligner)** 를 활성화하여 페이지별 회전각을 감지하고, 결정적 CLI(`align-inputs`)로 렌더링 PNG를 교정한다. 타일·crop·annotate가 모두 "정렬된 이미지 좌표계"에서 일관되게 동작하도록 파급 지점을 함께 수정한다. page-aligner의 모델은 opus~haiku 순차 실측으로 선정한다.

## Background

- **실증**: `PU2601233-2-MTC.pdf`는 메타데이터 회전값이 전 페이지 0이지만 스캔 내용 자체가 회전됨 — p1~5·p10·p20·p40·p50 등은 90° 회전, p30·p60·p68·p73 등은 정상. **파일 내 혼재**이므로 페이지 단위 감지·교정이 필수.
- **현재 파이프라인의 취약점**:
  - `tile_inputs.py`의 2×2 타일 의미론(`r0`=헤더+상단표)이 회전 페이지에서 붕괴 → ocr-extractor의 식별필드 확정(r0 기반)·전사 정확도 저하.
  - `crop.py:crop_region`(`scripts/crop.py:112`)과 `annotate_pdf.py`는 **원본 PDF에서 직접 렌더** → 정렬된 타일 기준으로 산출된 fractional bbox와 좌표계 불일치.
- **제약**: C1(Python OCR 라이브러리 금지 — tesseract OSD 사용 불가) → 방향 감지는 Claude Vision(에이전트), 회전 적용은 결정적 CLI(Pillow lossless transpose)로 역할 분리. 기존 "에이전트=판단, CLI=결정적 처리" 아키텍처와 동일 패턴.

## Goals (Step 3 활성 목표 — 각 항목이 측정 가능해야 함)

| # | Goal | 성공 측정 |
|---|---|---|
| G1 | 페이지별 회전각(0/90/180/270) 감지용 입력을 결정적으로 생성하는 `orient-sheets` CLI 신설 (**cert `png/` 전용**) | `orient-sheets --case PU2601233` 실행 시 `.cache/PU2601233/orient/`에 컨택트시트 PNG + `sheets_index.json` 생성, pytest 단위테스트 통과 |
| G2 | 문서 정렬 에이전트 `agents/page-aligner.md` 신설 — 시트를 읽고 stem별 `<stem>_orientation.json`(페이지→회전각) 산출 | PU2601233 실측에서 육안 확인된 회전 페이지(p1~5·10·20·40·50)와 정상 페이지(p30·60·68·73)가 오분류 0으로 감지됨 |
| G3 | `align-inputs` CLI 신설 — orientation.json을 소비해 cert `png/` PNG를 in-place 회전(Pillow transpose, lossless), 적용 기록으로 **멱등성** 보장 | 재실행 시 이중 회전 0(픽셀 diff 테스트), 회전 페이지 read-back 육안 확인 시 전부 정방향 |
| G4 | 좌표계 일관성 — `crop.py`·`annotate_pdf.py`가 orientation 기록을 참조해 렌더 후 회전을 적용, 리뷰어가 보는 정렬 이미지와 동일 좌표계 유지 | 회전 페이지 대상 crop/annotate 단위테스트 통과(마커 픽셀 위치 검증), 기존 테스트 111개 회귀 0 |
| G5 | 오케스트레이션 통합 — SKILL.md Phase 1.5로 정렬 단계 편입(에이전트 표 7→8종, 흐름도·디렉토리 레이아웃 갱신), 캐시 게이트(fresh/legacy 스킵)와 정합 | SKILL.md 갱신 + prep-inputs 재렌더 시 orientation 기록 리셋 로직 테스트 통과 |
| G6 | E2E 실검증 — PU2601233 케이스로 prep→orient→align→tile까지 실행, 정렬 결과 육안 검증(한글 무결성 포함) | 샘플 페이지(회전 4+정상 2 이상) read-back에서 방향·한글 모두 정상 |
| G7 | **모델 선정 벤치마크** — 동일 시트·동일 지침으로 opus 4.8 / sonnet 5 / haiku 4.5 순차 감지 실행, GT(오케스트레이터 육안 확정 73p 회전각) 대비 정확도 + 비용 실측 → 성능·가격 최적 모델을 page-aligner frontmatter에 확정 | 3개 모델 정확도/토큰 비용 표 산출, **오분류 0인 최저가 모델** 선정(전 모델 오분류 시 최고 정확도 모델), 결과 문서 `docs/`에 기록 |

## Proposal (Implementation Steps)

### Step 1 — `scripts/orient_sheets.py` 신설 + CLI `orient-sheets --case <id>`
- `.cache/<case>/png/`(**cert 전용 — MPS 제외**) 페이지 PNG를 썸네일(장변 ~360px)로 축소, **3×4 그리드 컨택트시트** 합성 (73p → 시트 7장; ≤12p 문서는 1장).
- 각 셀 상단에 흰 라벨바 + 검정 페이지번호(`p01`) — 라벨은 항상 정방향으로 그려 에이전트가 페이지 참조 가능. 폰트는 `annotate_pdf.py:51`의 `CERT_REVIEW_FONT`/malgun.ttf 해석 패턴 재사용(숫자 전용).
- 출력: `.cache/<case>/orient/<stem>__sheet01.png` … + `orient/sheets_index.json`(시트→[stem, page] 매핑).
- `cli.py`에 서브커맨드 등록(`--case` 필수, prep-inputs와 동일 관례).

### Step 2 — `agents/page-aligner.md` 신설 (문서 정렬 에이전트, model: **벤치마크로 확정** — Step 8 참조, 초기값 claude-opus-4-8)
- 입력: SKILL_DIR 절대경로 + case id. `orient/sheets_index.json`과 시트 PNG를 Read.
- 판단 규칙: 문자 진행 방향·표 구조·레터헤드/도장 위치로 각 페이지의 **정방향 복원에 필요한 시계방향 회전각**(0/90/180/270) 결정. 애매한 페이지는 원본 풀페이지 PNG(`png/<stem>_pNN.png`)를 직접 Read하여 확정. 그래도 불확실하면 0으로 두고 `uncertain_pages`에 보고(보수적 무회전).
- 출력: stem별 `.cache/<case>/<stem>_orientation.json` — `{"schema_version":"1.0","stem":...,"pages":{"1":90,...},"uncertain_pages":[...]}`.
- 회전 적용은 하지 않음(결정적 CLI 담당). 중첩 에이전트 금지·입력 화이트리스트·C1~C8 준수 명시. 완료 보고: 회전 페이지 수/불확실 페이지 목록.

### Step 3 — `scripts/align_inputs.py` 신설 + CLI `align-inputs --case <id>`
- 케이스 캐시의 모든 `<stem>_orientation.json` 로드 → 회전각≠0 페이지의 cert PNG(`png/`)를 `PIL.Image.transpose(ROTATE_90/180/270)`로 in-place 교정 (90° 배수는 무손실). **MPS(`mps_png/`)는 대상 아님.**
- **멱등성**: `<stem>_alignment.json`에 적용 맵(`{"applied":{"1":90,...}}`) 기록, 이미 적용된 페이지는 스킵 → 재실행해도 이중 회전 없음.
- cert sidecar(`<stem>_prep.json`)에 `rotations` 요약 병기(캐시 진단용). 요약 출력: stem별 회전 페이지 수.

### Step 4 — `scripts/prep_inputs.py` 정합: 재렌더 시 정렬 기록 리셋
- `prep_case`가 PDF를 **재렌더**하는 경로(stale/force)에서 해당 stem의 `<stem>_orientation.json`·`<stem>_alignment.json` 삭제 — 새 렌더 PNG는 미정렬 상태이므로 감지부터 다시. 캐시 히트(skip) 시엔 보존(정렬 완료 상태 유지 → fresh 스킵 의미론과 정합).

### Step 5 — 좌표계 일관성: `crop.py`·`annotate_pdf.py` 회전 인지
- `crop_region`: 렌더 후 `<stem>_orientation.json`(cert)을 참조해 해당 페이지 회전 적용 → fractional bbox를 **정렬 좌표계**에서 해석(리뷰어가 타일에서 본 좌표와 일치). 기록 없으면 기존 동작(하위호환).
- `annotate_pdf.render_annotated_pdf`: 주석 대상 페이지 렌더 후 동일하게 회전 적용 → bbox(정렬 좌표계) 드로잉. 회전 원본의 주석 면은 결과 PDF에서 정방향 래스터로 삽입됨(가독성 향상 — copy-through 원칙은 비주석 면에만 해당, 문서화).

### Step 6 — SKILL.md·문서·매니페스트 갱신
- 에이전트 표 7→**8종**(`page-aligner` 추가), Phase 1 시퀀스에 **1.5 정렬 단계** 삽입: `prep-inputs → orient-sheets → [delegate page-aligner] → align-inputs → tile-inputs → prep-mps(무변경, 정렬 대상 아님)`. 흐름도·디렉토리 레이아웃(orient/·orientation.json·alignment.json)·시간예산(정렬 위임 1회, 시트 ~N/12장 Read) 반영.
- 캐시 게이트 규칙 명시: fresh/legacy는 Phase 1·2 전체(정렬 포함) 스킵 — 기존 의미론 그대로.
- `agents/ocr-extractor.md`에 1줄: 타일은 사전 정렬됨; 그래도 회전된 타일 발견 시 전사하지 말고 보고.
- `.claude-plugin/marketplace.json` version 1.2.0→1.3.0, description에 정렬 에이전트 반영. 루트 `README.md` 파이프라인 서술 갱신.

### Step 7 — 테스트
- `tests/test_orient_sheets.py`: 그리드 배치·라벨·index JSON (합성 PNG, 폰트 없는 환경 skipif는 annotate 테스트 관례 따름).
- `tests/test_align_inputs.py`: 마커 픽셀 회전 검증(90/180/270), **멱등성**(2회 실행 픽셀 동일), alignment.json 기록.
- `tests/test_prep_cache.py` 확장: 재렌더 시 orientation/alignment 리셋.
- `tests/test_crop.py`·`test_annotate_pdf.py` 확장: 회전 페이지 좌표계 검증.
- `test_no_python_ocr.py` C1 가드가 신규 모듈 자동 포함하는지 확인.

### Step 8 — E2E 실검증 + 모델 선정 벤치마크 (PU2601233)
- `build-manifest → prep-inputs → orient-sheets` 실행 후:
- **8-a. GT 확정**: 오케스트레이터가 컨택트시트 7장을 직접 육안 판독하여 73페이지 전체의 회전각 GT를 `scratchpad`에 기록(이미 확인된 12페이지 샘플과 교차검증).
- **8-b. 모델 순차 실측**: 동일 시트·동일 지침으로 page-aligner 위임을 **claude-opus-4-8 → claude-sonnet-5 → claude-haiku-4-5** 순으로 3회 실행(각각 별도 출력 파일 `<stem>_orientation__{opus,sonnet,haiku}.json`), GT 대비 페이지 단위 정확도 + 출력 토큰(비용 프록시) 집계.
- **8-c. 선정**: **오분류 0인 최저가 모델** 채택(전 모델 오분류 존재 시 최고 정확도 모델). `agents/page-aligner.md` frontmatter model 확정, 결과를 `docs/orient-model-selection-2026-07-09.md`에 기록(ocr-model-ab 문서 관례).
- **8-d. 정렬 적용 검증**: 선정 모델의 orientation.json으로 `align-inputs → tile-inputs` 실행 → ① 정렬 후 샘플 페이지·타일 read-back 육안 확인(방향+한글 무결성) ② pytest 전체 통과. (73p 전체 OCR/검토는 본 기능 범위 밖 — 사용자 별도 지시 시 수행.)

## Impact

| 파일 | 변경 | 위험도 |
|---|---|---|
| `scripts/orient_sheets.py` · `scripts/align_inputs.py` | 신설 | 낮음(독립 모듈) |
| `agents/page-aligner.md` | 신설 | 낮음 |
| `scripts/cli.py` | 서브커맨드 2개 추가 | 낮음 |
| `scripts/prep_inputs.py` | 재렌더 시 정렬기록 리셋 | 중간(캐시 게이트 정합) |
| `scripts/crop.py` | 렌더 후 회전 적용(하위호환) | 중간(좌표계) |
| `scripts/annotate_pdf.py` | 렌더 후 회전 적용(하위호환) | 중간(좌표계) |
| `skills/cert-review/SKILL.md` · `agents/ocr-extractor.md` · `README.md` · `marketplace.json` | 문서/버전 | 낮음 |
| `tests/*` | 신규 2 + 확장 3 | — |

### Risks & Mitigations
- **감지 오류(90↔270, 180 누락)** → 판단 규칙 명문화 + 불확실 페이지 풀페이지 재확인 + 보수적 무회전(0) 폴백 + 완료 보고로 오케스트레이터 검증 가능.
- **이중 회전** → alignment.json 적용 맵 멱등성 + 재렌더 시 리셋(픽셀 diff 테스트로 고정).
- **crop/annotate 좌표계 회귀** → 하위호환 설계(기록 없으면 무회전) + 기존 테스트 111개 회귀 확인.
- **배포본(.claude/skills, KO 에디션) 분기** → 본 계획은 플러그인(EN)만 수정. 코드 파일은 통째복사 동기화 가능하나 agents/SKILL은 KO 에디션 별도 반영 필요(후속 작업으로 분리, 통째복사 금지 원칙 준수).
- **모델 비용/성능** → 고정하지 않고 Step 8-b 벤치마크로 실측 선정(방향 감지는 화학 수치 전사보다 단순한 과업 — 기존 "OCR 모델 재비교 금지"는 전사 과업 한정이므로 저촉 없음). 시트 방식으로 Read 횟수 ~N/12로 압축(73p→7회).
- **MPS 회전** → 범위 제외(사용자 결정). MPS 스캔이 회전 입력되는 경우는 현행대로 mps-extractor가 원본 방향으로 읽음 — 필요 시 후속 확장.

## Verification Steps
1. `pytest tests/` — 기존 111 + 신규 전부 통과, C1 가드 통과.
2. PU2601233 E2E(Step 8) — 모델 3종 벤치마크 표 산출, 선정 모델 정렬 read-back 육안 확인(한글 무결성 포함).
3. `py_compile` 전 수정 모듈.

## Open Questions
- 배포본(KO) 동기화 시점 — 본 작업 완료 후 별도 진행 여부.
