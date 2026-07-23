# 2026-07-23 — 동봉 원자재 성적서(MILL CERT) 검증 도메인·에이전트 추가(기준 21/22) — v1.7.0

**Summary**: Phase 1.6에서 `MTC_RAW_MATERIAL`로 분류된 동봉 원자재 성적서(MILL CERT)를 전량 전사(전사 예외)하고, 신규 결정적 CLI `mill-cert`가 연결성(Heat/MILL CERT NO./grade 계열)·단조 술어·인장 동일성 상태기계·화학 공통원소 비교를 산출, 신규 조건부 에이전트 `mill-cert-reviewer`가 기준 21(검증·연결성)·기준 22(교차비교)를 판정한다. 핵심 규칙: 화학성분 불일치는 원소별 '주의'(동일은 정상 — 제강사 성적 인용 관행), **단조품 인장 4값이 MILL CERT와 소수점까지 전부 동일하면 FAIL**(완제품 시험 미실시·전사 복제 의심 — PU2601564 실측 동인).

**Plan**: [2026-07-23_183734_mill-cert-review-domain](../plans/2026-07-23_183734_mill-cert-review-domain.md) (dh-dev 승인 완료, 적대 검증 24건 전건 반영)

## Rationale

실측 동인: `testbed/1. Standard Inspection/ref/PU2601564.pdf` — 단조 엘보(A182-F22 CL.3) MTC(p3)의 인장 4값(YS 447.77 / TS 582.71 / EL 30.94 / RA 75.64)이 동봉 SeAH MILL CERT(p4)와 소수점 둘째 자리까지 완전 동일. 완제품 시험 미실시·원자재 성적 전사 복제가 의심되는 사례이나, 기존 파이프라인은 `MTC_RAW_MATERIAL` 페이지를 최소 엔트리로만 기록해(기준 19.2) 교차비교가 불가능했다. 사용자 요구 3건: (1) MILL CERT 별도 분류·검증 에이전트, (2) 화학성분 불일치 시 '주의', (3) 단조품 인장 동일 시 FAIL.

## Changed Files (커밋 `008b357`, 14 files, +1884/-58)

### 신설

| 파일 | 설명 |
|---|---|
| `skills/cert-review/scripts/mill_cert.py` | 기준 21/22 결정적 교차비교 팩 빌더 — `values_equal`(Decimal 정확 일치)·`scale_suspect`(×100/×1000 함정 가드)·`is_forging`(spec regex→remark 키워드→라우팅 3단 술어)·`compare_tensile`(상태기계, n=1 보수 규칙)·`compare_chemistry`(공통 원소만, `_ELEMENT_ALIASES`·`_CE_FAMILY` 제외)·`_grade_probe`(A182형 S 누락·하이픈 정규화)·런→heat/cert 변화 기준 `mill_docs[]` 서브그룹 분할(G-H1)·완제품 페이지별 `matches[]`(G-H2) → `<case>_mill_cert.json` |
| `agents/mill-cert-reviewer.md` | 신규 조건부 에이전트(claude-opus-4-8) — 기준 21a/b/c + 기준 22.1/22.2, 1-g 판정 매핑표 전재, crop 재판독 2경우 한정(scale_suspect 원소 셀·병합 키 결정 셀), 기준 20 첨부판정 발행 금지(format 소유), 재-OCR 금지 |
| `skills/cert-review/tests/test_mill_cert.py` | 적대 시나리오 T1~T18·T24~T31 단위 테스트 36건 (tmp_path 자급자족) |
| `skills/cert-review/tests/test_compliance_report_mill_cert.py` | T21/T22 렌더 테스트 3건 — 조건부 시트 생성·FAIL 색·한국어 read-back·legacy 미생성 |

### 수정

| 파일 | 설명 |
|---|---|
| `skills/cert-review/scripts/cli.py` | `mill-cert` 서브커맨드 — 런 0건도 exit 0(`applicable: false` 팩 기록), grade_routing 로드 실패 시 regex/keyword 술어로 강등 |
| `skills/cert-review/scripts/merge_reviews.py` | 선택적 6도메인 — `_DOMAIN_ORDER`/`_DOMAIN_SECTION`/`_SECTION_KEYS`에 `mill_cert`, `_OPTIONAL_DOMAINS` 신설(부재 시 경고/이슈 미발생), docstring 정정(C-M1) |
| `skills/cert-review/scripts/compliance_report.py` | 조건부 7번째 시트 "원자재 MILL CERT 검토"(`_grouped_sheet` 재사용) — `mill_cert` 행이 있을 때만 생성, 구버전 review.json 하위호환 |
| `skills/cert-review/references/extraction-schema.json` | 가산 확장(문서 version 2.1, 인스턴스 const "2.0" 유지 — D8) — header에 `mill_cert_no`/`mill_maker`/`starting_material`, `analysis_type`에 `"Ladle"` |
| `agents/ocr-extractor.md` | `MTC_RAW_MATERIAL` 전사 예외(D1) — 전량 전사+배율 정규화 의무+Ladle 표기, 그 외 EXCLUDED 라벨은 최소 엔트리 불변, 인벤토리 불변 강화, 완제품 header 3필드 확장, fragment 모드 동일 적용(G-L2) |
| `skills/cert-review/references/review-criteria.md` | 기준 21(범위·연결성·자체 유효성·판정 경계)·기준 22(22.1 화학/22.2 단조 인장) 신설, 기준 19 표·19.2·20.1 표·20.5에 기준 21/22 한정 예외 문구 |
| `skills/cert-review/SKILL.md` | 10 서브에이전트 표기·에이전트 표·디렉토리 레이아웃·CLI 예시·Phase 4-1(mill-cert 상시 실행)·Phase 4-2(조건부 6번째 병렬 위임, C-M4)·기준 라우팅 표·도메인 경계 표·Phase 4-3(최대 6부분)·시간 예산 ⑨·흐름 요약·"6-sheet" 조건부 표기 일괄(C-M2) |
| `skills/cert-review/tests/test_merge_reviews.py` | `_MATERIAL_KEYS`/`_DOMAIN_SECTION` 갱신 + 신규 3건(T19/T20/단독 부분 보존) + optional 무경고 assert |
| `.claude-plugin/marketplace.json` | v1.6.0 → **v1.7.0**, 에이전트 10종·기준 21/22 문구 (D9) |
| `README.md` | 6시트(+조건부 시트)·10개 에이전트·mill-cert-reviewer 행·핵심 특징 bullet·mermaid·병합 도메인 목록·테스트 총계 280 (G-H5) |

### 무변경 (분리 원칙 — AC-13)

- `refpack.py` · `attachments.py` · `doctype.py` · `eval_harness.py` · `compare_engine.py` **무수정 보존** (`git diff --stat` 확인 — 기존 5도메인 판정 로직·인벤토리·기준 20 대조·평가 하니스 불변).
- `agents/doc-classifier.md` 무변경 — MTC_RAW_MATERIAL cue·EXCLUDED 런 식별자 판독이 이미 필요 입력을 산출.
- `data/*.csv` 기준값·`_VERDICT_ALIASES`·기준 1~20 수치 무변경.

## 검증

- `pytest` **280 passed** (기존 238 + 신규 42: test_mill_cert 36 + test_compliance_report_mill_cert 3 + test_merge_reviews 신규 3), 실패 0. C1 AST 가드·입력 가드 그린(test_no_python_ocr + test_input_guard 8 passed).
- CLI 스모크(DoD-a4): mill cert 없는 합성 캐시(`.cache/TMPMC/`)에서 `mill-cert --case TMPMC` → exit 0 + `applicable: false` 팩 기록 확인 후 삭제.
- 문서 배선 grep(DoD-a8): SKILL.md `mill-cert-reviewer` 6곳 / review-criteria 기준 21·22 신설 + 19.2/20.5 예외 / marketplace "1.7.0" / README "10개"·mill-cert-reviewer 행 / 무자격 "6-sheet|6시트" 잔존 0건(SKILL·README·compliance_report.py·merge_reviews.py 전 표기 조건부 문구 동반).
- 한국어 무결성: 기준 21/22 신설 섹션·mill-cert-reviewer.md·README·커밋 메시지 read-back — U+FFFD·`占쏙옙`·`ï»¿` 부재 확인(테스트 파일 내 U+FFFD 리터럴은 의도된 검사 프로브 — 기존 test_compliance_report_excluded.py 동일 관례).
- **E2E(DoD-b, 2026-07-23 오케스트레이터 수행 — 전 항목 통과)**: PU2601564 실PDF 4p를 `CERT_REVIEW_WORKDIR` 스크래치 격리로 전체 파이프라인 구동(build-manifest→prep-inputs→orient-sheets→page-aligner→align-inputs→tile-inputs→classify-sheets→doc-classifier→check-doctype→ocr-extractor→check-extraction→mill-cert→mill-cert-reviewer→merge-reviews→compliance_report).
  - **b1**: 분류 p1-2=COVER_LETTER·p3=MTC_FINISHED·p4=MTC_RAW_MATERIAL(기대 일치), 게이트 전부 exit 0. p4 전량 전사(×100/×1000 정규화: C×100=15→0.15% 등, `analysis_type: "Ladle"`), p3 header에 `mill_cert_no`/`mill_maker`/`starting_material` 기록.
  - **b2 (규칙 22.2 FAIL 재현)**: 팩 tensile 4/4 equal(TS 582.71/YS 447.77/EL 30.94/RA 75.64)·state `all_identical`·`is_forging` True(basis: spec A182)·linkage heat B14339 match·mill_cert_no 201404-004866 match. 리뷰 material verdict **FAIL**, 기준 22.2 finding(ActionRequired/DocumentError) + 보조근거(HB 185=185·열처리 900°C/99min AC·730°C/150min AC 집합 동일) 병기, 10행 판정 매핑표 그대로 산출.
  - **b3 (규칙 22.1 무주의 재현)**: 화학 공통 7원소(C/Si/Mn/P/S/Cr/Mo) 전부 equal(n_diff 0) → 원소 '주의' 0건, PASS + "제강사 성적 인용 관행" note. 편측 원소(As/Sb/Sn·Cu/Ni) 무시 확인.
  - **b4 (렌더 openpyxl assert)**: 7시트 중 6번째 위치에 "원자재 MILL CERT 검토" 조건부 생성, FAIL 셀 존재, U+FFFD·`占` 부재 — 자동 assert OK.
  - **b5 (정리)**: `.cache/PU2601564/`·스크래치 삭제, 원 manifest(48케이스) 복원 확인.
  - 특이: 팩 `en10204` regex가 원문 "EN10204:2004, Type 3.1"의 쉼표를 미허용해 `found=false` — 에이전트가 전사 원문 근거로 doc-check 행 PASS 처리(기준 17.4/17.5, 정보성 항목이라 비차단). 아래 향후 과제 참조. 또한 격리 실행에서 grade_routing이 ref_code 부재로 로드 실패 → 계획된 regex/keyword 술어 강등 + `grade_family_match=None`→N/A 행(정상 폴백 경로 실증).

## 향후 과제

- **배포 캐시 동기화(R6)**: `C:\Users\donghun.lee\.claude\plugins\cache\ReportReviewer` 를 커밋 후 md5 일치 확인으로 동기화(메모리 '단일 소스 재통합' 절차) — 실행자 범위 밖.
- **46케이스 재추출 시 자동 활성(R2)**: 기존 캐시의 mill cert 페이지는 최소 엔트리(`transcription_missing` → N/A 우아 강등). 재추출 강제 금지 — 신규/재추출 케이스부터 기준 21/22 경로 자동 활성, 46케이스 재추출 시 활성 확인 필요.
- **다중 heat 단일 페이지 한계(R8)**: 1페이지에 복수 heat가 인쇄된 판재형 mill cert는 header 단일 필드 특성상 대표 heat만 실린다 — mill_doc note 한계 기재, 필요시 후속 논의(FAIL 미탐은 있어도 오탐 없음 — 보수).
- 대형 원자재 블록(실측 PU2601233 p15-50, 36p) 전량 전사 시 OCR 시간 증가(R12) — 시간 예산 ⑨ 명시, 복합 티어 내 수용. 필요시 "원자재 런 페이지 상한" 별도 논의.
- **`_EN10204_RE` 쉼표 허용 개선**: E2E 실측 — "EN10204:2004, Type 3.1"(연도 뒤 쉼표) 형식을 현재 regex가 미검출(`found=false`). 정보성 항목이라 판정 영향 없음(에이전트가 전사 원문으로 보정)이나, `(?:\s*[,，])?` 허용 추가가 바람직. 단위 테스트 T30에 쉼표 변형 케이스 추가 권장.
