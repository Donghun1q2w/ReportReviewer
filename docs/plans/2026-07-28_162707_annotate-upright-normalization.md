# annotate 직전 페이지별 업라이트 정규화 전처리 (Acrobat 핸들 UI 불일치 구조적 제거) — 구현 계획 Rev.1

- **작성**: 2026-07-28 16:27 (전담 플래닝 에이전트, dh-dev Step 1-e — 단일 재수정 사이클 산출물)
- **상태**: Draft — Step 2 사용자 승인 대기 (Step 1-e 적대 검증 완료: contrarian/gap_hunter findings 18건 전건 처리, HIGH 3건 코드·테스트·AC·DoD 반영. 구조 체크 통과, 단일 재수정 사이클 소진 — 이후 레인 재실행 없음)
- **대상 저장소**: `C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer` (main, HEAD `45bc2ee`, pypdf 6.6.2 — 오케스트레이터가 직접 재확인: 예외 계층·`transfer_rotation_to_content` 존재 모두 실측 일치)
- **대상 파일**:
  - 신규: `skills/cert-review/scripts/upright_pdf.py`, `skills/cert-review/tests/test_upright_pdf.py`
  - 수정: `skills/cert-review/scripts/annotate_pdf.py` (annotate_case + import + 모듈 독스트링만), `skills/cert-review/tests/test_annotate_pdf.py`, `skills/cert-review-annotate/SKILL.md`, `.claude-plugin/marketplace.json`(버전), `README.md`(변경이력)
  - **무변경 보장**: `write_annotated_pdf` 및 그 하위 전 함수(좌표변환·라벨·Square/Popup 빌더), `scripts/align_inputs.py`, `scripts/cli.py`의 서브커맨드 등록부, OCR/리뷰 파이프라인 전체, `data/*.csv`

---

## 0. Findings 반영 현황 (Rev.1 disposition — 침묵 처리 0건)

| Finding | Sev | Disposition | 반영 위치 |
|---|---|---|---|
| contrarian#1 | **HIGH** | **수정** — `ensure_upright_pdf`에 metadata 접근 **전** `is_encrypted` 조기 검사(`ValueError`, "encrypted" 포함) 추가 + `annotate_case` 캐치를 `(OSError, ValueError, PyPdfError)`로 확장 + 실제 암호화·손상 PDF가 목킹 없이 `annotate_case`를 통과하는 A7 신설 | Step 2, Step 3, A7, AC-13/14/21, DoD-12/21 |
| contrarian#2 | MED | 수정 — 캐시 유효 조건에 `pypdf_version`·`schema_version` 일치 추가 | Step 2, U8, AC-23, DoD-23 |
| contrarian#3 | MED | 수정 — U4에 legacy 대비 픽셀 bbox 동등성(±2px) 어설션 추가(리터럴 Rect 대신 픽셀 방식 채택 — CropBox 원점 오프셋 수식을 계획 단계에서 날조하지 않기 위함) | U4, AC-15, DoD-13 |
| contrarian#4 | MED | 수정 — SKILL.md 문구를 폴백 발생 가능성으로 헤지 | Step 6 |
| contrarian#5 | MED | 수정 — V7 실패 분기(V7-F 프로토콜) 신설 + 리스크 R12 | Section 8, R12, DoD-19 |
| contrarian#6 | LOW-MED | 수정 — 1.4 폰트 주장 완화("이미지 XObject 실측, 폰트는 표본 부재") + V4에 실PDF 폰트 스트림 존재 시 조건부 바이트 대조 추가 | 1.4, V4 |
| contrarian#7 | LOW | 수정 — 불변식을 "직접 PIL/pypdfium2 import 없음"으로 정확히 재서술(전이적 PIL 로드 인정) | Step 2 주석, U14 |
| contrarian#8 | LOW | 수정 — 결정 1의 해석(summary는 추가 키만 소폭 확장) 의도임을 명기 | 1.6 D5 |
| gap_hunter#1 | **HIGH** | **수정** — 결합 회전 실파일 `2026-246#-7.21.pdf`(원 버그 발견 파일)로 V4.3 신설 + V7 필수 포함 | 1.5, V4.3, AC-22, DoD-22, V7 |
| gap_hunter#2 | **HIGH** | **수정** — 멀티-stem 선택적 실패 격리 테스트 A8 신설(+stem 단위 2단 폴백 구조로 격리 자체를 코드로 보장) | Step 3, A8, AC-20, DoD-20 |
| gap_hunter#3 | MED | 수정 — turns 소멸 시 해당 stem의 스테일 캐시 제거 구현 | Step 2, U9, AC-23, DoD-23 |
| gap_hunter#4 | MED | 수정 — D4에 unresolved-stem 상류 배제 명문화 + A9 저비용 어설션 | 1.6 D4, A9, AC-24, DoD-24 |
| gap_hunter#5 | MED | 수정 — U1에 r=45(무효)+a=90 하위 케이스 추가 | U1 |
| gap_hunter#6 | MED | 수정 — contrarian#1과 동일 근본 지점, A7(실제 암호화 PDF 무목킹 E2E, note "encrypted" 확인)로 함께 해소 | A7, AC-21 |
| gap_hunter#7 | MINOR | 수정 — DoD-2 괄호를 `[U2 = AC-1/2; U9/A4 = AC-3]`으로 정정 | DoD-2 |
| gap_hunter#8 | MINOR | 수정 — "정규화는 페이지-회전 기준, 주석-유무 기준 아님"을 허용된 트레이드오프로 명문화 | 1.7 |
| gap_hunter#9 | LOW | 수정 — 방어 가드 유지 + 범위 밖 turns 직접 호출 실증 테스트 U15 추가(제거 대신 실증 선택) | U15, DoD-25 |
| gap_hunter#10 | LOW | **미수정(명시적 disposition)** — A1/A3/A8/V4가 `annotate_case` 경유로 실제 `applied_rotations()`를 이미 통과하고 align_inputs는 무변경·기존 테스트 보유이므로 U계열 추가 통합 테스트는 비용 대비 이득 없음. 허용된 트레이드오프로 수용 | 1.6 D4 비고 |
| 미결(a) 캐시 스캐닝 유틸 | — | 범위 밖 후속 확인으로 명기(cli.py는 무영향 확인됨; mill_cert.py/refpack.py는 후속) | 1.7 |
| 미결(b) add_metadata의 /Info 덮어쓰기 | — | Step 1 스파이크 #3으로 구현 전 확인 절차 추가 | Step 1 |

---

## 1. Requirements Summary

### 1.1 해결할 문제

커밋 `9e3cd1f`(NoRotate 앵커)로 회전 페이지의 FreeText 라벨이 리사이즈 후에도 항상 가로를 유지하게 됐으나, Adobe Acrobat의 **선택/리사이즈 핸들 오버레이 UI**는 NoRotate를 무시하고 페이지 회전 추종 좌표로 그려져, `/Rotate≠0` 페이지에서 핸들 박스가 실제 라벨과 점대칭(XY 양축 반전) 위치에 나타난다(실기기 확인, 커밋 `45bc2ee`로 Known limitation 문서화·종결). 이는 뷰어 내부 크롬이므로 PDF 저작 측에서 좌표를 고칠 수 없다.

### 1.2 해결 방향 (1-c 사용자 승인 완료 — 재논의 금지)

annotate 단계 **직전에만** 적용되는 "페이지별 업라이트 정규화" 전처리를 신설한다. 실제 페이지 `/Rotate`(=r)≠0 또는 align-inputs 적용 회전(=a)≠0인 페이지만 콘텐츠를 **무손실 matrix 전사(bake-in)** 로 회전시켜 `/Rotate=0`으로 정규화하고, 이미 업라이트인 페이지는 바이트 그대로 보존한 정규화 PDF를 만들어 annotate의 입력만 교체한다.

**구조적 근거(코드로 도출)**: `annotate_pdf.py:372`의 `label_rect_for_norotate(..., r)`은 `_aligned_to_user_frac(u, v, r)`(`269-284`)을 호출하며, `r == 0`이면 항등변환(`276-277`)이다. 정규화 후 페이지는 항상 r=0이므로 NoRotate 앵커 계산은 순수 스케일로 축소되고, Acrobat 핸들 UI가 따르는 "페이지 회전 추종" 변환도 회전각 0에서 무회전이 된다. 두 경로가 갈라질 지점 자체가 소멸하므로, 핸들-라벨 불일치는 정규화가 실제로 적용된 산출물에서는 Acrobat 내부 구현과 무관하게 **구조적으로 재현 불가**가 된다. (이 가설의 실기기 확증 및 반증 시 대응은 V7/V7-F가 담당 — contrarian#5 대응.)

### 1.3 확정된 4가지 설계 결정 (1-b 인터뷰, 재논의 금지)

1. **적용 범위**: 정규화 PDF는 annotate 단계의 입력만 교체. OCR/Vision 리뷰 파이프라인(prep-inputs/tile-inputs/OCR)과 review.json, annotation-locator bbox 좌표계(정렬 렌더 픽셀 공간, `T=(R+A)%360` 역변환 관례)는 일절 불변.
2. **적용 조건**: r≠0 또는 a≠0인 페이지만 처리. r=0·a=0 페이지는 바이트 그대로 보존(전량 무조건 정규화 금지).
3. **기존 NoRotate 앵커 로직**: `label_rect_for_norotate`/`_aligned_bbox_to_display_box` 등은 삭제하지 않고 방어적 fallback으로 유지. `write_annotated_pdf`는 **diff 0줄**.
4. **기존 산출물**: 이미 발급된 `<stem>_annotated.pdf`는 재생성하지 않음. 신규/재실행 케이스부터만 적용.

### 1.4 "burn-in 재도입"이 아님 — 명시적 구분 (향후 리뷰어 혼동 방지)

메모리 규칙 "burn-in 재제안 금지"(v1.6.0 전환 사유: **이미지 래스터 주석은 사용자가 편집/삭제 불가**)와 이번 전처리는 다음 세 가지 점에서 다르다.

| 구분 | (금지된) burn-in | (이번) 업라이트 정규화 |
|---|---|---|
| 대상 | 주석 자체를 페이지 픽셀로 굽기 | 주석 부착 **이전**의 페이지 회전 표현만 조정 |
| 방식 | 페이지 재래스터화(pypdfium2 렌더 → 이미지 재삽입) | content stream 앞에 회전 matrix 1개 전사 + 페이지 박스 조정. **픽셀 재생성 0회** — 임베딩 **이미지 XObject** 원시 스트림 바이트 불변(스파이크 S2로 실측). 임베딩 **폰트** 스트림은 스파이크/테스트 표본에 존재하지 않아 별도 실측하지 않았으며, 동일 clone 경로상 재인코딩이 없음이 구조상 기대된다 — V4에서 실PDF에 폰트 스트림 존재 시 전후 바이트 대조로 확인, 부재 시 "표본 없음"으로 기록한다(contrarian#6 대응: 실측 안 된 것을 실측된 것처럼 서술하지 않음) |
| 주석 | 편집/삭제 불가 | 여전히 사후에 네이티브 벡터 객체(Square/Popup/FreeText)로 추가 — 편집/삭제 가능성 완전 보존 |

즉 v1.6.0의 "네이티브 주석 + 개별 편집 가능" 원칙은 그대로이고, 모듈 독스트링(`annotate_pdf.py:34-39`)의 verbatim 보존 근거도 훼손되지 않는다. verbatim 문구는 "annotate 라이터는 입력을 verbatim 보존하며, 회전 페이지는 그 입력이 업라이트 정규화 파생본"으로 갱신한다(Step 6).

### 1.5 계획 단계 스파이크·실데이터로 실측 확정한 사실 (실행 에이전트는 그대로 신뢰, 단 Step 1에서 재확인)

환경: pypdf **6.6.2**, `PageObject.transfer_rotation_to_content()` 존재. 스크립트: 스크래치패드 `spike_upright_normalize.py` — 12개 체크 ALL PASS.

| ID | 확인 내용 | 결과 |
|---|---|---|
| S1 | `PdfWriter(clone_from=reader)` 후 `writer.pages[i].rotation = t` → `transfer_rotation_to_content()` | `/Rotate`=0으로 리셋, t=90에서 MediaBox 400x300 → **300x400 스왑** |
| S2 | 임베딩 이미지 XObject의 **인코딩된 원시 스트림 바이트**(`._data`) 전처리 전후 비교 | **바이트 동일** (FlateDecode 필터·W/H 포함 동일) — 무손실 입증 |
| S3 | 같은 문서의 무변환 페이지 `/Contents` 바이트 | clone_from + write 경유 후에도 **바이트 동일** |
| S4 | pdfium 렌더: 원본(`/Rotate=90`) vs 정규화본(r=0) | 크기 동일(300x400), **픽셀 diff 비율 0.0** |
| S5 | a-only 케이스(r=0, 콘텐츠만 옆으로 누움)에 t=90 bake | `render(정규화본) == rotate_cw(render(원본), 90)` 픽셀 diff 0.0 |
| S6 | t=(r+a)%360==0 이지만 r=90인 엣지(a=270) | `page.rotation = 0`만으로 충분: `/Rotate` 스트립, **콘텐츠 바이트 불변**, 박스 스왑 없음 |
| S7 | CropBox≠MediaBox(10,20,390,280) + t=90 | CropBox도 일관 변환·스왑 — `transfer_rotation_to_content`가 5종 박스를 모두 변환(pypdf 소스 확인) |

**적대 검증 레인이 추가로 실측 확정한 사실(Rev.1에서 신뢰 대상에 편입, 오케스트레이터가 재확인 완료)**:

- **예외 타입(contrarian 레인 재현, 오케스트레이터가 재확인)**: 암호화 PDF에 `PdfReader(path).metadata` 접근 시 `pypdf.errors.FileNotDecryptedError`, 손상/잘린 PDF에 `PdfReader()` 생성 시 `pypdf.errors.PdfStreamError` — 둘 다 `OSError`/`ValueError`의 서브클래스가 **아니며**(`issubclass()` 확인) `pypdf.errors.PyPdfError`의 서브클래스다.
- **결합 회전 실파일(gap_hunter 레인 실측)**: `2026-246#-7.21.pdf`(케이스 **PU2601233-03**, cert cleanup data 코퍼스, 7페이지, 페이지별 `/Rotate` 값 `{0, 90}` **혼재**). 메모리(`cert-review-annotate-norotate-acrobat-handle-limit.md`) 기록상 **사용자가 실제 Acrobat에서 결합 T=180 수동 테스트로 원래 핸들-불일치 버그를 발견한 바로 그 파일**이다. V4.3의 필수 입력이며, 사용 전 pypdf로 페이지별 /Rotate를 재확인한다.
- **CropBox 비대칭 시나리오(contrarian 레인 실측)**: 비대칭 CropBox `(30,5,390,250)` + MediaBox 400x300 + `/Rotate=90`에서 FAIL 마커 렌더 픽셀 bbox가 정규화 전후 동일 — 현재 pypdf 동작 올바름. U4가 이 시나리오를 회귀 고정한다(contrarian#3 대응).

실데이터: `PU2601565-1-MTC.pdf` = 23페이지 전부 /Rotate=90(r≠0 실사례), `PU2601233-2-MTC.pdf` = 73페이지 전부 /Rotate=0(a≠0 실사례, 합성 캐시 사용). 기존 발급본이 `output\reports\` 하위에 존재하므로 검증 시 반드시 `--out` 스크래치 경로 사용(결정 4).

### 1.6 계획이 확정하는 6가지 설계 세부사항 (실행자는 그대로 따를 것)

**D1. 모듈 위치/이름 = 신규 `scripts/upright_pdf.py`.** (파이프라인 단계당 1모듈 관례, 독립 테스트 파일 분리.)

**D2. 무손실 bake-in 구현 = pypdf 6.6.2 `transfer_rotation_to_content()` + 회전값 선치환.** 절차(페이지별): `pg.rotation = t` (t=(r+a)%360) → `t % 360 != 0`이면 `pg.transfer_rotation_to_content()` / `t == 0`이면 rotation=0 설정만으로 종료(S6). 수동 구현 대안은 pypdf가 API를 제거한 미래에만 필요(pseudocode: t별 cm 행렬 `90:(0,-1,1,0,0,w) / 180:(-1,0,0,-1,w,h) / 270:(0,1,-1,0,h,0)` prepend + 5종 박스 스왑 + `/Rotate` 삭제). Step 1에서 API 존재 재확인.

**D3. 재결합 절차 = 단일 `PdfWriter(clone_from=reader)` 내 차등 처리.** 별도 파일 분리는 하지 않는다(S3: 무변환 페이지 바이트 동일, 중간 파일 0개).

**D4. 통합 지점/캐시 규칙**: `annotate_case`의 그룹 루프에서 `applied_rotations(...)` 취득 직후 `ensure_upright_pdf(pdf_path, case_cache, rotations)` 호출.
- 캐시 경로: `.cache/<case>/upright/<stem>_upright.pdf` + 사이드카 `.cache/<case>/upright/<stem>_upright.json`.
- **캐시 유효 조건(모두 충족 시 재사용)**: 정규화 PDF·사이드카 존재 AND `sidecar["schema_version"] == UPRIGHT_SCHEMA_VERSION` AND **`sidecar["pypdf_version"] == pypdf.__version__`**(contrarian#2 대응: pypdf 업그레이드 시 구버전 산출물 자동 재생성 — 기록만 하고 강제하지 않던 공백 제거) AND `sidecar["source_sha256"] == compute_sha256_fresh(원본)` AND `sidecar["rotations"] == 현재 applied 맵(문자열 키 직렬화)`.
- **스테일 캐시 제거(gap_hunter#3 대응)**: turns가 비었는데(정규화 불필요로 전환) 해당 stem의 캐시 PDF/사이드카가 존재하면 제거하고 note를 남긴다. 제거 실패(Windows 잠금)는 note만 남기고 원본 경로 반환을 계속한다.
- **예외 계약(contrarian#1 대응)**: `ensure_upright_pdf`는 reader 생성 직후·**metadata 접근 전에** `is_encrypted`를 검사해 `ValueError`("encrypted" 포함)를 던진다(조기 검사 없이는 `reader.metadata`가 `FileNotDecryptedError`를 먼저 던져 잘못된 타입으로 탈출). 손상 PDF는 `PdfReader()` 생성에서 `PdfStreamError` 등 `PyPdfError` 계열이 자연 전파된다. caller(`annotate_case`)의 폴백 캐치는 `(OSError, ValueError, PyPdfError)` 3종이다.
- **unresolved-stem 배제 명문화(gap_hunter#4 대응)**: `resolve(ann.stem)`이 `None`인 주석은 상류(annotate_pdf.py:750-754)에서 이미 제외되어 `groups`에 들어가지 않으므로 `ensure_upright_pdf`에 도달하지 않는다 — `upright/` 산출물은 resolve된 stem에 대해서만 생성된다(A9가 저비용 어설션으로 고정).
- 커밋 순서: PDF `.tmp` + `os.replace` → 사이드카 마지막 기록(commit marker). `align_inputs._write_json_atomic` 재사용.
- 정규화 불필요면 파일 미생성, 원본 경로 반환.
- 비고(gap_hunter#10 disposition): `applied_rotations()` 실함수 경유 검증은 A1/A3/A8/V4의 `annotate_case` 경로가 담당하며, U계열은 `rotations` dict 직접 구성으로 충분하다(align_inputs 무변경·자체 테스트 보유) — 허용된 트레이드오프.

**D5. CLI 노출 = 신규 서브커맨드 없음(annotate 내부 캡슐화).** 관찰성은 (a) stem별 정규화/폴백/스킵 note 라인, (b) summary `outputs[*]`의 `upright`/`skipped` 필드, (c) 사이드카 JSON으로 확보. **결정 1 해석 명기(contrarian#8 대응): "annotate 입력만 교체"는 PDF 데이터 흐름에 대한 결정이며, 반환 summary dict에 추가 키(`upright`, `skipped`)를 얹는 소폭·추가-전용(additive-only) 확장은 의도된 범위다** — 기존 키 제거/개명은 없다(A6이 형태 고정).

**D6. 90/270 크기 스왑 파급 = AC로 명시 검증.** 정규화 PDF에서 `t = 0` → Square 매핑은 순수 스케일, 라벨 앵커는 항등. AC-6/AC-7과 U13/A1/A2가 리터럴로 고정.

### 1.7 범위 밖 (scope creep 금지) 및 허용된 트레이드오프

- `write_annotated_pdf` 본문, Square/Popup/FreeText 빌더, 좌표변환 함수 6종: **diff 0줄**.
- OCR/리뷰 파이프라인, review.json/annotations.json 계약, 색상, PASS 제외 규칙: 불변.
- 기존 발급 PDF 재생성 금지: 검증 중 `annotate --all` 실행 금지, 실케이스 검증은 반드시 `--out` 스크래치 경로.
- NoRotate 앵커 로직 단순화/제거: 범위 밖(결정 3).
- Acrobat 핸들 UI 좌표 보정 재조사: 금지(메모리 합의) — 이번 작업은 보정이 아니라 **전제 제거**다. 단, V7 실기기 확증이 실패하면 V7-F 프로토콜(8절)을 따른다.
- **허용된 트레이드오프(gap_hunter#8 대응)**: 정규화 트리거는 **페이지 회전 기준이지 주석 유무 기준이 아니다** — 회전 페이지는 그 페이지의 verdict가 전부 PASS여서 주석이 하나도 그려지지 않더라도 정규화된다. 규칙을 단순·결정적으로 유지하고 캐시 키가 주석 내용에 의존하지 않게 하기 위한 의도된 선택이며, 시각 결과는 동등하다(U5).
- **후속 확인(미결 a)**: `.cache/<case>/*`를 순회하는 다른 유틸(`mill_cert.py`, `refpack.py` 등)이 신규 `upright/` 서브디렉토리에 영향받는지는 범위 밖 — cli.py는 무영향 확인됨. 커밋 후 후속 태스크로 1회 점검.
- 배포 캐시 동기화/push: 기존 후속 과제로 별도(이번 커밋 범위 밖).

---

## 2. Acceptance Criteria

기준 페이지: 400x300pt, CropBox 없음(별도 명시 시 제외). bbox는 (0.25, 0.25, 0.5, 0.5).

| ID | 시나리오 | 변경 전 (현행) | 변경 후 (요구) | 검증 |
|---|---|---|---|---|
| **AC-1** | r=90 페이지 정규화 후 메타데이터 | `/Rotate=90`, MediaBox 400x300 | **`/Rotate=0`(또는 키 부재), MediaBox 300x400** | U2 |
| **AC-2** | 임베딩 이미지 XObject 원시(인코딩) 스트림 바이트 | — | 전처리 전후 **바이트 완전 동일** — 재래스터화 0회 | U2 |
| **AC-3** | r=0·a=0 페이지(및 그런 페이지만 있는 stem) | verbatim | **`/Contents` 바이트 동일**, `upright/` 파일 미생성, 원본 경로 그대로 사용 | U9, A4 |
| **AC-4** | t==0이지만 r=90(a=270)인 페이지 | — | `/Rotate`만 0으로 스트립, **콘텐츠 바이트 불변**, 박스 스왑 없음 | U3 |
| **AC-5** | pdfium 렌더 동등성: r∈{90,180,270}(a=0) | 뷰어가 /Rotate로 회전 표시 | `render(정규화본) == render(원본)` — 크기 동일, 픽셀 diff 비율 < 0.5% | U5 |
| **AC-6** | pdfium 렌더 동등성: a∈{90,180,270}(r=0) | 정렬 PNG만 회전 | `render(정규화본) == rotate_cw(render(원본), a)` — 픽셀 diff < 0.5% | U6 |
| **AC-7** | 정규화본을 `write_annotated_pdf(rotations={})`로 주석 | — | wp,hp=300,400(스왑 반영), Square `/Rect` == **(75, 200, 150, 300)**(t=0 순수 스케일) | U13 |
| **AC-8** | `annotate_case` + `applied={"1": 90}`(a≠0 경로, 기존 테스트 갱신) | MediaBox 400x300 유지, Square `/Rect`=(100,75,200,150)(T=90 역변환) | **MediaBox 300x400**, Square `/Rect`=(75,200,150,300), FreeText `/F`=20·`/AP /N`에 `/Matrix` 부재·`/Rect`≡`/BBox` 크기, `upright/` 캐시 생성, `outputs[0]["upright"] is True`·`["skipped"] is False` | A1 |
| **AC-9** | `annotate_case` + 원본 `/Rotate=90`(정렬 기록 없음) | 출력 페이지 `/Rotate=90` 유지 | 출력 **전 페이지 `/Rotate==0`**, Square `/Rect`=(75,200,150,300), 라벨 칩이 표시 공간에서 박스와 비겹침·인접 | A2 |
| **AC-10** | 신·구 경로 시각 동등성 | — | legacy 렌더(a 케이스는 `rotate_cw(a)` 후)와 신경로 렌더의 **verdict 색 픽셀 bbox 위치 ±2px 이내 일치** | A3 |
| **AC-11** | 캐시 재사용/무효화 | — | 동일 입력 재실행 시 재기록 없음(바이트/mtime 불변). 원본 sha256 변경 또는 rotations 맵 변경 시 재생성 | U8 |
| **AC-12** | 멱등성/이중 회전 방지 | — | 정규화 출력물(메타데이터 마커 보유) 재입력 시 **재회전 0회**(`(입력 그대로, False)` 반환) | U10 |
| **AC-13** | 손상/비정상 회전값/암호화 방어 **[findings 대응: contrarian#1 HIGH]** | annotate는 `/Rotate=45`를 r=0으로 강제(`635-636`) | 전처리도 **동일 규칙**(r∉{0,90,180,270} → r=0; a와 결합 전에 클램프 — r=45·a=90이면 t=90). 암호화 PDF는 `ensure_upright_pdf`가 **metadata 접근 전** `ValueError`("encrypted" 포함) — `FileNotDecryptedError` 탈출 경로 봉쇄. 손상 PDF의 `PdfStreamError` 등은 `PyPdfError`로서 annotate_case 캐치 `(OSError, ValueError, PyPdfError)`에 포섭 | U1, U12, A5, A7 |
| **AC-14** | 전처리/산출 실패 시 2단 폴백 | — | **(1단)** 전처리 실패 → note 남기고 원본+기존 rotations로 폴백, 주석 산출 성공. **(2단)** legacy 산출조차 불가능한 판독불능 PDF → **해당 stem만** `skipped=True`+note로 스킵, 형제 stem과 케이스 반환은 정상(전처리가 새 실패 모드를 추가하지 않으며, 종전 "케이스 전체 크래시"보다 개선) | A5, A7 |
| **AC-15** | CropBox≠MediaBox **[contrarian#3 반영]** | — | (a) 케이스 46형 리터럴 CropBox=(3.96001, 2.88, 599.76001, 845.28): t=90 정규화 후 w/h 스왑(842.4 x 595.8, ±0.01) + `write_annotated_pdf` 체인 정상. (b) 비대칭 CropBox=(30,5,390,250)/MediaBox 400x300/r=90: legacy 대비 **FAIL 마커 픽셀 bbox ±2px 동등**(레인 실측 시나리오의 회귀 고정) | U4 |
| **AC-16** | 기존 테스트 회귀 | annotate 67개 / 전체 스위트 통과 | **의도적 갱신 1건**(`test_annotate_case_consumes_alignment_record` → AC-8 기대값) 제외 전 기존 테스트 무수정 통과, 전체 0 failed / 0 error | V1~V3 |
| **AC-17** | 기존 발급 PDF | 존재 | `output/reports/**/*_annotated.pdf` **바이트/mtime 불변** | V4, V6 |
| **AC-18** | SKILL.md 고정 문자열 | `test_skillmd_no_stale_wording` 통과 | 갱신 후에도 통과: 소문자 기준 "burn-in"/"burn in"/"--dpi" **부재**, "norotate"·"resize" **존재** | V2 |
| **AC-19** | (자동 검증 불가) 실제 Acrobat 확인 | 핸들 박스 점대칭 위치 표시 | V4 산출물 **3종 전부**(결합 회전 원 재현 파일 포함)에서 핸들 박스가 라벨 실위치와 일치, 리사이즈 후 가로 유지. 실패 시 V7-F 프로토콜 실행 | V7 |
| **AC-20** | 멀티-stem 격리 **[findings 대응: gap_hunter#2 HIGH]** | — | 한 케이스에 cert PDF 2개일 때, stem A의 정규화 실패(선택적 실패)가 stem B에 전파되지 않음: outputs 2건이 **독립 상태**(A: `upright False`+폴백 note+legacy 좌표, B: `upright True`+`/Rotate==0`+정규화 좌표), B의 upright 캐시만 존재 | A8 |
| **AC-21** | 실제 판독불능 PDF E2E **[findings 대응: contrarian#1 HIGH / gap_hunter#6]** | (구현 전) 케이스 전체 크래시 | **목킹 없이** 실제 암호화(`PdfWriter.encrypt("pw")`)·실제 손상(잘린 바이트) PDF를 그룹에 포함해 `annotate_case` 실행: 정상 반환, 해당 stem `skipped=True`+note(암호화는 "encrypted" 포함), 형제 stem 정상 산출 | A7 |
| **AC-22** | 결합 회전 실파일(r≠0 AND a≠0) E2E **[findings 대응: gap_hunter#1 HIGH]** | — | `2026-246#-7.21.pdf`(7p, /Rotate {0,90} 혼재) + 합성 alignment(r=90 페이지에 a=90 → **t=180**, r=0 페이지에 a=90 → t=90): 출력 **전 페이지 `/Rotate==0`**, turns 밖 페이지 `/Contents` 바이트 verbatim, 렌더 정상 | V4.3 |
| **AC-23** | 캐시 위생 | — | (a) 사이드카 `pypdf_version` 또는 `schema_version` 불일치 시 재생성. (b) turns 소멸 시(원본이 업라이트본으로 교체 등) 해당 stem의 스테일 `upright/` 캐시 제거 + note | U8, U9 |
| **AC-24** | unresolved stem | 상류에서 제외(750-754) | 동작 불변 + 해당 stem에 대해 `upright/` 산출물 **미생성** | A9 |

---

## 3. Implementation Steps (구현 지침)

작업 디렉토리: `C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer\skills\cert-review`(pytest·CLI 모두 여기서, `PYTHONIOENCODING=utf-8`).

### Step 0 — 베이스라인 고정

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pytest tests/ -q          # 전체 통과 수 기록 (기준: annotate 67개 포함 전체 green)
git -C ..\.. log --oneline -1        # HEAD 45bc2ee 확인
```

### Step 1 — pypdf 버전/API/예외·메타데이터 스파이크 재확인 (필수 선행)

```powershell
python -c "import pypdf; from pypdf._page import PageObject; print(pypdf.__version__, hasattr(PageObject, 'transfer_rotation_to_content'))"
# 기대: '6.6.2 True' (API 부재 시 중단, D2 수동 구현 대안으로 계획 재검토 요청)

python -c "from pypdf.errors import PyPdfError, FileNotDecryptedError, PdfStreamError; print(issubclass(FileNotDecryptedError, PyPdfError), issubclass(PdfStreamError, PyPdfError))"
# 기대: 'True True' — Step 3 캐치 튜플의 전제(오케스트레이터가 dh-dev Step 1-e에서 이미 재확인함: 6.6.2, True/True)
```

추가 5분 스파이크(스크래치 스크립트, 커밋 금지) 3건:
1. `PdfWriter(clone_from=...)` 페이지에 `pg.rotation = 90; pg.transfer_rotation_to_content()` → `/Rotate`=0, MediaBox 스왑(S1 재현).
2. `writer.add_metadata({"/CertReviewUpright": "1.0"})` 후 재독으로 커스텀 키 왕복 확인. 실패 시 마커 판정을 사이드카 존재+sha 일치 기반으로 대체하고 계획 주석에 기록.
3. **[미결(b) 대응]** 기존 `/Info`가 있는 PDF(예: `/Producer` 수동 삽입)를 clone_from 후 `add_metadata({마커})` — 기존 키가 **보존(merge)** 되는지 확인. 덮어쓰기(clobber)라면 `writer.add_metadata({**{k: str(v) for k, v in (reader.metadata or {}).items()}, UPRIGHT_META_KEY: UPRIGHT_SCHEMA_VERSION})`로 수동 병합하도록 Step 2 코드를 조정하고 그 사실을 커밋 메시지에 기록.

### Step 2 — 신규 모듈 `scripts/upright_pdf.py`

아래 골격을 그대로 구현한다(독스트링·주석은 기존 모듈 문체로 확장). **[findings 대응: contrarian#1 HIGH — `is_encrypted` 조기 검사 / contrarian#2 — 버전 키 캐시 강제 / gap_hunter#3 — 스테일 캐시 제거]**

```python
"""upright_pdf.py — annotate 직전 페이지 업라이트 정규화 (무손실 회전 matrix 전사).

The page-aligner/align-inputs pair makes the *rendered PNGs* upright for the
reviewers; this module makes the *annotate input PDF itself* upright, page by
page, so the NoRotate anchor math collapses to the identity (r == 0) and a
viewer's rotation-following edit chrome can no longer diverge from the label.

Only pages with page ``/Rotate`` != 0 or an align-inputs applied rotation != 0
are re-encoded (lossless: one rotation matrix transferred into the content
stream via pypdf's ``transfer_rotation_to_content``; embedded image XObject
streams are byte-identical). Already-upright pages pass through verbatim
(``PdfWriter(clone_from=...)``). This is NOT the banned raster burn-in: the
page is never rasterised and annotations stay native vector objects.

Error contract: encrypted sources raise ValueError (checked BEFORE any
metadata access -- pypdf would otherwise raise FileNotDecryptedError, which is
neither OSError nor ValueError); corrupt sources let pypdf's PyPdfError
family propagate. annotate_case owns the fallback for all three.

Cache: ``.cache/<case>/upright/<stem>_upright.pdf`` + sidecar json keyed by
schema_version + pypdf_version + source sha256 + applied-rotation map;
sidecar-last commit. Stale cache files are removed once a stem no longer
needs normalization. No direct PIL/pypdfium2 import (PIL loads transitively
via scripts.align_inputs; this module itself never rasterises).
Constraint C1: pypdf only, no OCR. C7: pathlib + encoding='utf-8'.
"""
from __future__ import annotations

import os
from pathlib import Path

import pypdf
from pypdf import PdfReader, PdfWriter

from scripts.align_inputs import VALID_ROTATIONS, _load_json, _write_json_atomic
from scripts.source_validator import compute_sha256_fresh

UPRIGHT_DIRNAME = "upright"
UPRIGHT_PDF_SUFFIX = "_upright.pdf"
UPRIGHT_SIDECAR_SUFFIX = "_upright.json"
UPRIGHT_META_KEY = "/CertReviewUpright"
UPRIGHT_SCHEMA_VERSION = "1.0"


def upright_paths(case_cache: Path, stem: str) -> tuple[Path, Path]:
    """(정규화 PDF 경로, 사이드카 경로) for a cert stem."""
    d = Path(case_cache) / UPRIGHT_DIRNAME
    return d / f"{stem}{UPRIGHT_PDF_SUFFIX}", d / f"{stem}{UPRIGHT_SIDECAR_SUFFIX}"


def page_upright_turns(reader: PdfReader, rotations: dict[int, int] | None) -> dict[int, int]:
    """정규화가 필요한 페이지의 {1-based page: t=(r+a)%360} 맵 (없으면 빈 dict).

    r 판정은 write_annotated_pdf(634-636)와 자구까지 동일해야 한다
    (r∉VALID_ROTATIONS → 0) — 클램프는 a와 결합하기 **전에** 적용한다
    (r=45·a=90 → t=90, U1이 고정). t==0(r=90,a=270)도 r≠0이므로 포함(/Rotate 스트립).
    """
    turns: dict[int, int] = {}
    for p, page in enumerate(reader.pages, start=1):
        r = int(page.get("/Rotate") or 0) % 360
        if r not in VALID_ROTATIONS:
            r = 0
        a = (rotations.get(p, 0) if rotations else 0) % 360
        if a not in VALID_ROTATIONS:   # applied_rotations가 이미 거르지만 이중 방어
            a = 0
        if r == 0 and a == 0:
            continue
        turns[p] = (r + a) % 360
    return turns


def write_upright_pdf(src: Path | str, dst: Path | str, turns: dict[int, int]) -> dict:
    """turns의 페이지만 t를 content로 전사(t==0은 /Rotate 스트립만)한 PDF를 원자적으로 기록.

    반환: {"n_pages": int, "baked": int, "stripped": int}
    암호화 PDF는 ValueError (defense in depth — ensure_upright_pdf가 먼저 거르지만
    이 함수 단독 공개 API 계약으로도 유지; U12가 직접 호출로 고정).
    """
    src, dst = Path(src), Path(dst)
    reader = PdfReader(str(src))
    if reader.is_encrypted:
        raise ValueError(f"encrypted PDF cannot be upright-normalized: {src.name}")
    writer = PdfWriter(clone_from=reader)
    baked = stripped = 0
    for p, t in sorted(turns.items()):
        if not 1 <= p <= len(writer.pages):
            continue  # 방어 — 현 호출 계약상 도달하지 않으나(U15가 직접 호출로 실증) 유지
        pg = writer.pages[p - 1]
        pg.rotation = t
        if t % 360 != 0:
            pg.transfer_rotation_to_content()   # /Rotate=0, 박스 스왑(90/270), matrix 전사
            baked += 1
        else:
            pg.rotation = 0                      # 스파이크 S6: 콘텐츠 불변, 스트립만
            stripped += 1
    writer.add_metadata({UPRIGHT_META_KEY: UPRIGHT_SCHEMA_VERSION})
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    with open(tmp, "wb") as fh:
        writer.write(fh)
    os.replace(tmp, dst)
    return {"n_pages": len(writer.pages), "baked": baked, "stripped": stripped}


def _remove_stale_cache(up_pdf: Path, up_scar: Path) -> list[str]:
    """정규화가 더는 불필요한 stem의 고아 캐시 제거 (gap_hunter#3 대응).

    잠금 등으로 제거 실패해도 호출자는 원본 경로 반환을 계속한다(note만 남김).
    """
    removed: list[str] = []
    for stale in (up_pdf, up_scar):
        try:
            if stale.exists():
                stale.unlink()
                removed.append(stale.name)
        except OSError:
            return [f"stale upright cache could not be removed (locked?): {stale.name}"]
    if removed:
        return [f"stale upright cache removed: {', '.join(removed)}"]
    return []


def ensure_upright_pdf(
    pdf_path: Path | str, case_cache: Path | str, rotations: dict[int, int] | None
) -> tuple[Path, bool, list[str]]:
    """캐시 게이트 래퍼. 반환: (annotate가 읽을 경로, 정규화 사용 여부, 노트들).

    - 암호화 소스 → ValueError("encrypted" 포함) — metadata 접근 **전에** 검사
      (contrarian#1: FileNotDecryptedError는 OSError/ValueError가 아님).
    - 손상 소스 → PdfReader에서 PyPdfError 계열 자연 전파 (caller 폴백).
    - 마커 보유 소스(정규화 출력물 재입력) → (입력, False) — 이중 회전 차단.
    - 정규화 불필요(turns 빔) → (입력, False); 스테일 캐시가 있으면 제거.
    - 캐시 유효(schema+pypdf 버전+sha256+rotations 일치) → (캐시, True), 재기록 없음.
    - 그 외 → 재생성 후 사이드카 최종 기록(commit marker), (캐시, True).
    """
    pdf_path, case_cache = Path(pdf_path), Path(case_cache)
    reader = PdfReader(str(pdf_path))            # 손상 PDF → PdfStreamError 등 (caller 폴백)
    if reader.is_encrypted:
        raise ValueError(f"encrypted PDF cannot be upright-normalized: {pdf_path.name}")
    meta = reader.metadata
    if meta is not None and meta.get(UPRIGHT_META_KEY):
        return pdf_path, False, ["source carries upright marker; normalization skipped"]
    turns = page_upright_turns(reader, rotations)
    up_pdf, up_scar = upright_paths(case_cache, pdf_path.stem)
    if not turns:
        return pdf_path, False, _remove_stale_cache(up_pdf, up_scar)
    src_sha = compute_sha256_fresh(pdf_path)
    rot_ser = {str(k): int(v) for k, v in sorted((rotations or {}).items())}
    sidecar = _load_json(up_scar)
    if (
        sidecar
        and up_pdf.exists()
        and sidecar.get("schema_version") == UPRIGHT_SCHEMA_VERSION
        and sidecar.get("pypdf_version") == pypdf.__version__   # contrarian#2: 기록을 강제로 승격
        and sidecar.get("source_sha256") == src_sha
        and sidecar.get("rotations") == rot_ser
    ):
        return up_pdf, True, [f"upright cache hit ({len(turns)} page(s) normalized)"]
    summary = write_upright_pdf(pdf_path, up_pdf, turns)
    _write_json_atomic(up_scar, {
        "schema_version": UPRIGHT_SCHEMA_VERSION,
        "stem": pdf_path.stem,
        "source_path": str(pdf_path).replace("\\", "/"),
        "source_sha256": src_sha,
        "rotations": rot_ser,
        "turns": {str(k): int(v) for k, v in sorted(turns.items())},
        "n_pages": summary["n_pages"],
        "pypdf_version": pypdf.__version__,
    })
    return up_pdf, True, [
        f"upright normalized {summary['baked']} page(s)"
        + (f" (+{summary['stripped']} rotate-strip)" if summary["stripped"] else "")
    ]


__all__ = [
    "UPRIGHT_DIRNAME", "UPRIGHT_PDF_SUFFIX", "UPRIGHT_SIDECAR_SUFFIX",
    "UPRIGHT_META_KEY", "UPRIGHT_SCHEMA_VERSION",
    "upright_paths", "page_upright_turns", "write_upright_pdf", "ensure_upright_pdf",
]
```

주의: `_load_json`/`_write_json_atomic` private import는 기존 선례를 따른 것. 새 JSON 유틸 중복 구현 금지. **import 규율은 "직접 import 없음"이다(contrarian#7 대응)**: 이 모듈은 PIL/pypdfium2를 직접 import하지 않지만, `scripts.align_inputs` 경유로 PIL이 전이적으로 로드되는 것은 알려진 사실이며 기능 불변식은 "이 모듈 자체는 래스터화 호출 경로가 없다"이다(U14는 직접 import만 검사).

### Step 3 — `annotate_pdf.py` 통합 (annotate_case만 수정) **[findings 대응: contrarian#1 HIGH — 캐치 확장 / gap_hunter#2 HIGH — stem 단위 격리]**

(1) import 추가(93줄 인근):

```python
from pypdf.errors import PyPdfError

from scripts.upright_pdf import ensure_upright_pdf
```

(2) 그룹 루프(현행 759-772줄)를 다음으로 교체. **out 파일명과 summary `stem`은 항상 원본 stem**. 2단 폴백 구조: 1단 = 전처리 실패 시 legacy 경로 폴백, 2단 = legacy 산출조차 불가능한 stem은 해당 stem만 스킵하고 형제 stem을 계속 처리한다(구현 전 현행은 케이스 전체 크래시였으므로 격리는 순수 개선이며, contrarian#1의 "케이스 전체 실패" 해악과 gap_hunter#2/#6의 격리 요구를 함께 해소하는 **의도된 동작 계약 변경**이다 — A7/A8이 고정):

```python
    # Preprocessing/annotation failures must never take sibling PDFs down with
    # them. pypdf raises its own PyPdfError family (FileNotDecryptedError,
    # PdfStreamError, ...) which is NOT a subclass of OSError/ValueError.
    _FALLBACK_EXC = (OSError, ValueError, PyPdfError)

    for pdf_path, by_page in groups.items():
        out_pdf = out_dir / f"{pdf_path.stem}_annotated.pdf"
        rotations = applied_rotations(cache_root / str(case_id), pdf_path.stem)
        # Tier 1 — upright preprocessing: pages with /Rotate != 0 or an applied
        # align rotation != 0 are baked upright so the NoRotate anchor math
        # becomes the identity (r == 0). On failure fall back to the original
        # PDF + the legacy NoRotate path (the defensive-fallback decision).
        src_pdf: Path = pdf_path
        eff_rotations: dict[int, int] = rotations
        upright_used = False
        try:
            up_path, upright_used, up_notes = ensure_upright_pdf(
                pdf_path, cache_root / str(case_id), rotations
            )
            notes.extend(f"{pdf_path.stem}: {n}" for n in up_notes)
            if upright_used:
                src_pdf = up_path
                eff_rotations = {}   # 정규화본은 r=0·정렬 이미 반영 — 이중 적용 금지
        except _FALLBACK_EXC as e:
            notes.append(
                f"{pdf_path.stem}: upright normalization failed ({e}); "
                f"falling back to NoRotate anchoring on the original PDF"
            )
        # Tier 2 — per-stem isolation: a PDF the legacy path cannot read either
        # (really encrypted / truncated) is skipped with a note; siblings and
        # the case summary survive. write_annotated_pdf itself is unchanged.
        try:
            _, drawn, pages, oob = write_annotated_pdf(
                src_pdf, by_page, out_pdf, rotations=eff_rotations, font_path=font_path
            )
        except _FALLBACK_EXC as e:
            n_rows = sum(len(v) for v in by_page.values())
            rows_skipped += n_rows
            notes.append(
                f"{pdf_path.stem}: annotation failed ({e}); "
                f"{n_rows} annotation(s) skipped for this PDF"
            )
            outputs.append({
                "stem": pdf_path.stem, "pages": 0, "boxes": 0,
                "upright": upright_used, "out_path": str(out_pdf), "skipped": True,
            })
            continue
        boxes_drawn += drawn
        if oob:
            rows_skipped += oob
            notes.append(f"{pdf_path.stem}: {oob} annotation(s) out of page range 1..{pages}")
        outputs.append({
            "stem": pdf_path.stem, "pages": pages, "boxes": drawn,
            "upright": upright_used, "out_path": str(out_pdf), "skipped": False,
        })
```

핵심 불변식: **정규화가 사용되면 반드시 `rotations={}`** — alignment.json의 a는 원본 렌더 기준 값이므로 정규화본에 다시 적용하면 이중 회전이다. `write_annotated_pdf`와 그 하위 함수는 한 줄도 수정하지 않는다(호출부 try 래핑은 본문 수정이 아님).

### Step 4 — 기존 테스트 1건 의도적 갱신(`tests/test_annotate_pdf.py`)

`test_annotate_case_consumes_alignment_record`(772-801줄) — a≠0 경로가 이제 정규화를 타므로 기대값이 **의도적으로** 바뀐다. 갱신 내용:
- `page.mediabox == [0, 0, 300, 400]`(주석: "upright 정규화로 90도 bake — w/h 스왑, 래스터 아님")
- Square `/Rect` == `pytest.approx([75, 200, 150, 300], abs=0.01)`
- FreeText `/F == 20`, `/Matrix` 부재, `_assert_rect_matches_bbox` 유지
- 추가 어설션: `(tmp_path / "9" / "upright" / "certA_upright.pdf").exists()`, 출력 페이지 `/Rotate == 0`, `summary["outputs"][0]["upright"] is True`, `["skipped"] is False`
- 이름을 `test_annotate_case_normalizes_alignment_rotation`으로 변경, docstring에 "구 기대값(100,75,200,150)/400x300은 fallback 경로 전용이 되었고 write_annotated_pdf 직접 호출 테스트들이 계속 고정한다"를 명기.

이 1건 외의 기존 66개는 **무수정 통과**해야 한다.

### Step 5 — 신규 테스트(Section 6의 사양대로)

- 신규 파일 `tests/test_upright_pdf.py`: U1~U15.
- `tests/test_annotate_pdf.py` 말미에 A2~A9 추가(기존 헬퍼 `_make_pdf`/`_annots`/`_square`/`_freetext`/`_display_chip`/`_assert_rect_matches_bbox`/`_render_first_page`/`_has_color`/`_dark_pixel_bbox` 재사용; 이미지 XObject 임베딩 헬퍼는 test_upright_pdf.py에 신설하고 A계열이 import).

### Step 6 — 문서 갱신 **[contrarian#4 반영: 무조건 서술 금지]**

(1) `annotate_pdf.py` 모듈 독스트링(34-39줄 인근): copy-through 문단에 1문장 추가 — "Pages that needed rotation are annotated on their upright-normalized derivative (`scripts.upright_pdf`, lossless matrix transfer, `/Rotate=0`); already-upright pages and the legacy fallback path remain verbatim as before." `annotate_case` 독스트링에 전처리·2단 폴백(stem 격리)·캐시 경로를 1문단 기술.

(2) `skills/cert-review-annotate/SKILL.md`:
- "Annotation scope & style" 표의 Method 행(44줄): "every page is preserved verbatim"을 "already-upright pages are preserved verbatim; pages with a nonzero page `/Rotate` or align rotation are first upright-normalized (lossless rotation matrix transfer into the content stream — never rasterised) so annotations attach at `/Rotate=0`"로 조정.
- Phase C 좌표 관례 불릿(125-131줄): 전처리 후 신경로에서는 T=0 항등이 됨을 추가.
- **Known Acrobat limitation 블록(139-149줄) 개정 — 헤지 필수**: 한계 서술은 유지하되 적용 범위를 "outputs produced before the upright normalization, or via the fallback path"로 한정하고, 다음 취지의 **조건부** 문장을 쓴다: "Newly produced outputs attach annotations at `/Rotate=0`, so the handle-overlay mismatch cannot arise on them — **unless the run notes record an upright-normalization fallback for that file, in which case the legacy NoRotate path (and this limitation) still applies**." 계획 자신의 fail-open 설계(D4/R2/R7/AC-14)와 모순되는 무조건 서술 금지. NoRotate·resize 서술 문장은 삭제 금지(AC-18 고정 문자열).
- **금지어 준수**: 소문자 기준 "burn-in"/"burn in"/"--dpi" 문자열을 새 문안에 절대 넣지 말 것. 편집 직후 `python -m pytest tests/test_annotate_pdf.py -k skillmd -q` 실행.

(3) 버전: `.claude-plugin/marketplace.json` `1.7.0` → `1.8.0`. `README.md` 변경이력에 1행 추가(기존 행 서식 모방).

### Step 7 — 커밋

수정 파일 전부 스테이징 후 **1커밋**(관례: `feat(annotate): ...` 한국어 제목). 예: `feat(annotate): 주석 직전 페이지 업라이트 정규화 전처리 추가(Acrobat 핸들 불일치 구조 제거)`. **단일 커밋 유지는 V7-F(실기기 반증 시 revert 용이) 요건이기도 하다.** push는 범위 밖.

---

## 4. Code Writing Guide(코드 작성 가이드)

- **인코딩**: 모든 파일 I/O `encoding="utf-8"` 명시. 진입 셸 명령은 `PYTHONIOENCODING=utf-8` 프리픽스. 한국어 문자열을 다룬 뒤에는 산출물을 읽어 되돌려 mojibake(U+FFFD, `占쏙옙` 등) 부재를 확인 후 보고(글로벌 규칙).
- **경로**: pathlib 전면 사용(C7). 문자열 결합 금지. 사이드카에 기록하는 경로는 `str(p).replace("\\", "/")`. V4.3의 실파일명에 `#`이 포함되므로 셸에서 반드시 따옴표로 감쌀 것.
- **원자적 쓰기**: JSON은 `align_inputs._write_json_atomic`, PDF는 `.tmp` + `os.replace`.
- **결정성**: `upright_pdf.py`는 wall-clock을 읽지 않는다(사이드카에 created_at 금지; 신선도 키는 schema+pypdf 버전+sha256+rotations로 충분).
- **독스트링 문체**: 기존 모듈처럼 영어, 첫 줄 요약 + 근거/불변식 서술. 모듈 독스트링에 C1/C7 준수와 **예외 계약(ValueError/PyPdfError)** 명시.
- **import 규율**: `upright_pdf.py`는 `pypdf` + stdlib + `scripts.align_inputs`/`scripts.source_validator`만. **PIL/pypdfium2 직접 import 금지**(U14가 고정). 전이적 PIL 로드(align_inputs 경유)는 알려진 사실로 독스트링에 명기(contrarian#7). 함수명에 `render`/`draw`/`burn` 계열 단어 사용 금지.
- **에러 처리**: 라이브러리처럼 좁게 — `write_upright_pdf`/`ensure_upright_pdf`는 암호화만 `ValueError`, I/O는 `OSError` 자연 전파, pypdf 내부 오류는 `PyPdfError` 자연 전파. 광역 `except Exception` 금지. 폴백/격리 판단은 `annotate_case` 한 곳(`_FALLBACK_EXC = (OSError, ValueError, PyPdfError)`)에서만. 이 튜플에서 어느 하나라도 빼지 말 것 — 빠지면 contrarian#1의 케이스 전체 크래시가 재발한다.
- **기존 함수 스타일 모방**: 요약 dict 반환, 튜플 반환 순서 문서화, 방어 가드에 근거 줄 번호 주석(예: "annotate 634-636과 동일").
- **테스트 스타일**: `tests/test_annotate_pdf.py`의 확립된 패턴 — 합성 PDF 헬퍼, pypdf 파싱 어설션, pdfium 픽셀 검증은 `@requires_font`/`_render_first_page`/`_dark_pixel_bbox` 스타일, 리터럴 기대값은 `pytest.approx(..., abs=0.01)`.
- **금지**: `write_annotated_pdf` 및 하위 함수 수정, `cli.py` argparse 등록부 수정, 새 외부 의존성 추가, 문서에 섹션 기호 특수문자 사용.

---

## 5. Definition of Done(개발 완료조건)

전 항목 바이너리 판정. [] 안은 Section 6/8의 검증 수단 매핑.

- **DoD-1**: `scripts/upright_pdf.py`가 존재하고 `__all__` 8개 심볼을 노출하며 pypdf+stdlib+지정 2모듈 외 **직접** import가 없다. [U14]
- **DoD-2**: r=90 합성 PDF 정규화 후 `/Rotate==0`, MediaBox 300x400, 임베딩 이미지 XObject 원시 바이트 동일, 무변환 페이지 `/Contents` 바이트 동일. [U2 = AC-1/2; U9/A4 = AC-3] (gap_hunter#7 정정 반영)
- **DoD-3**: t==0·r=90 엣지에서 콘텐츠 바이트 불변 + `/Rotate` 스트립. [U3 = AC-4]
- **DoD-4**: pdfium 렌더 동등성 3계열(r-only, a-only, 복합) 픽셀 diff < 0.5%. [U5/U6/U7 = AC-5/6]
- **DoD-5**: 정규화본 → `write_annotated_pdf(rotations={})` 체인에서 Square `/Rect`=(75,200,150,300) 리터럴 일치. [U13 = AC-7]
- **DoD-6**: `annotate_case` a≠0 경로가 정규화를 사용하고 갱신된 기대값(AC-8) 전부 통과. [A1]
- **DoD-7**: `annotate_case` r≠0 경로 출력의 전 페이지 `/Rotate==0` + Square/라벨 기대값(AC-9). [A2]
- **DoD-8**: 신·구 경로 시각 동등성 ±2px. [A3 = AC-10]
- **DoD-9**: r=0·a=0 stem에서 `upright/` 미생성 + 출력 콘텐츠 바이트 verbatim. [U9/A4 = AC-3]
- **DoD-10**: 캐시 히트 시 재기록 없음, sha256/rotations 변경 시 재생성, `.tmp` 잔존물 0개. [U8/U11 = AC-11]
- **DoD-11**: 마커 보유 입력 재정규화 0회(이중 회전 불가). [U10 = AC-12]
- **DoD-12**: r=45 소스는 r=0 취급(fallback 판정과 일치, **a와 결합 전 클램프 포함**), 암호화 PDF에 대해 `ensure_upright_pdf`가 metadata 접근 전 `ValueError`("encrypted" 포함)를 던지고, 시뮬레이션 폴백(A5)이 `OSError`와 `PyPdfError` 서브클래스 **양쪽**에서 동작. [U1/U12/A5 = AC-13]
- **DoD-13**: CropBox≠MediaBox 케이스 정상 — 치수 스왑 리터럴 + **legacy 대비 픽셀 bbox ±2px 동등**. [U4 = AC-15]
- **DoD-14**: `git diff`에서 `write_annotated_pdf` 본문·Square/Popup/FreeText 빌더·좌표변환 함수 변경 0줄. [V5]
- **DoD-15**: 전체 `tests/` 0 failed/0 error, 기존 테스트 의도적 갱신은 정확히 1건. [V1~V3 = AC-16]
- **DoD-16**: SKILL.md 갱신 후 `test_skillmd_no_stale_wording` 통과 + Known limitation 문구가 폴백 조건부(헤지)로 서술됨. [V2 = AC-18]
- **DoD-17**: `output/reports/**` 기존 발급 PDF의 mtime/바이트 불변. [V6 = AC-17]
- **DoD-18**: marketplace.json 1.8.0 + README 변경이력 1행. [V5]
- **DoD-19**: (사용자 위임) V4 산출물 **3종 전부**(V4.3 결합 회전 파일 포함)를 Acrobat에서 열어 핸들-라벨 일치·리사이즈 후 가로 유지 확인, **또는** 실패 시 V7-F 프로토콜(8절)의 조치 3건이 실행·기록됨. [V7 = AC-19]
- **DoD-20** **[findings 대응: gap_hunter#2 HIGH]**: 멀티-stem 케이스에서 stem A만 선택적으로 정규화 실패 시, outputs 2건이 독립 상태(A: upright False+legacy 좌표+폴백 note / B: upright True+`/Rotate==0`+정규화 좌표), B의 upright 캐시만 존재. [A8 = AC-20]
- **DoD-21** **[findings 대응: contrarian#1 HIGH / gap_hunter#6]**: 실제 암호화 PDF와 실제 손상 PDF를 **목킹 없이** `annotate_case`에 통과시켜 케이스가 정상 반환되고, 해당 stem은 `skipped=True`+note(암호화는 "encrypted" 포함), 형제 stem은 정상 산출된다. [A7 = AC-21/14]
- **DoD-22** **[findings 대응: gap_hunter#1 HIGH]**: `2026-246#-7.21.pdf` 결합 회전(r=90 페이지 + a=90 → t=180 포함) E2E에서 출력 전 페이지 `/Rotate==0`, turns 밖 페이지 verbatim. [V4.3 = AC-22]
- **DoD-23**: 사이드카 `pypdf_version`/`schema_version` 불일치 시 재생성 + turns 소멸 시 스테일 캐시 제거·note. [U8/U9 = AC-23]
- **DoD-24**: unresolved stem에 대해 `upright/` 산출물 미생성(기존 제외 note 동작 불변). [A9 = AC-24]
- **DoD-25**: `write_upright_pdf`를 범위 밖 turns로 직접 호출 시 조용히 스킵하고 유효한 PDF를 산출(방어 가드 실증). [U15]

---

## 6. Adversarial Test Environment(적대적 테스트 환경)

### 6.1 공용 픽스처(tests/test_upright_pdf.py 내)

`_make_pdf_with_image(path, rotate=0, cropbox=None, pages=2)`: 1페이지째에 60x30 비대칭 RGB 이미지 XObject(`/FlateDecode`) + 사각형 스트로크, 2페이지째는 이미지 없는 상이한 콘텐츠(무변환 바이트 검증용). `annotate_pdf._image_xobject` 패턴을 테스트 헬퍼로 복제(프로덕션 모듈에 넣지 말 것). `_image_raw(page)`: 원시 스트림 바이트 + 필터/W/H 튜플 반환. 추가 헬퍼: `_make_encrypted_pdf(path)`(`PdfWriter.encrypt("pw")`), `_make_corrupt_pdf(path)`(예: `b"%PDF-1.4\n1 0 obj\n<<"` 잘린 바이트 직접 기록).

### 6.2 신규 파일 `tests/test_upright_pdf.py` — U1~U15

| ID | 테스트명 | 시나리오/어설션(리터럴 포함) | DoD |
|---|---|---|---|
| U1 | `test_page_upright_turns_selection` | **(gap_hunter#5 반영)** 5페이지 PDF(/Rotate=[0,90,0,45,45]) + rotations={3:270, 4:0, 5:90}: 결과 == `{2:90, 3:270, 5:90}` — p1 제외, p4는 r=45→0·a=0 → 제외, **p5는 r=45→0으로 클램프 후 a=90과 결합 → 90**(클램프되지 않은 45 파생값 금지). 추가 케이스 r=90&rotations={1:270} → `{1:0}` 포함(t=0이어도 스트립 대상) | 1,12 |
| U2 | `test_write_upright_metadata_rotation_lossless` | `_make_pdf_with_image(rotate=90)` → turns={1:90}: 출력 p1 `/Rotate`∈{0,None}, MediaBox (300,400); `_image_raw` 전후 **완전 동일**; p2 `/Contents` 바이트 동일; 반환 `{"baked":1,"stripped":0}` | 2 |
| U3 | `test_write_upright_t0_strips_rotate_only` | rotate=90, turns={1:0}: `/Rotate`==0, p1 콘텐츠 바이트 원본과 동일, MediaBox(400,300) 유지, 반환 stripped==1 | 3 |
| U4 | `test_write_upright_cropbox_offset` | **(contrarian#3 반영)** (a) rotate=90 + CropBox=(3.96001, 2.88, 599.76001, 845.28)(케이스 46형 리터럴): 정규화 후 cropbox(width,height) == approx (842.4, 595.8, abs=0.01), `write_annotated_pdf(rotations={})` 체인 예외 없음. (b) rotate=90 + MediaBox 400x300 + **비대칭 CropBox=(30,5,390,250)**(레인 실측 시나리오) + FAIL bbox: legacy 경로(`write_annotated_pdf(원본, rotations={1:0}...)` — r은 파일 자체 90) 렌더와 신경로(정규화 후 rotations={}) 렌더의 **FAIL 색 픽셀 bbox 각 좌표 차 ≤ 2px** — 미래 pypdf의 박스 변환 수식 회귀를 감지 | 13 |
| U5 | `test_render_equivalence_metadata_rotation`(parametrize r∈{90,180,270}) | pdfium `scale=1.0` 렌더: 크기 동일 AND 픽셀 불일치 비율(2px 스트라이드, 채널합 차>30) < 0.005 | 4 |
| U6 | `test_render_equivalence_content_rotation`(parametrize a∈{90,180,270}) | rotate=0 원본, turns={1:a}: `render(정규화본) == rotate_cw(render(원본), a)`(PIL 매핑: 90→`ROTATE_270`, 180→`ROTATE_180`, 270→`ROTATE_90`) diff < 0.005 | 4 |
| U7 | `test_render_equivalence_combined` | rotate=90 + rotations={1:90} → t=180: `render(정규화본) == rotate_cw(render(원본), 90)` diff < 0.005 | 4 |
| U8 | `test_ensure_upright_cache_hit_and_invalidation` | **(contrarian#2 반영)** 1회차: `(경로, True, _)` + 파일 생성. 2회차: 동일 경로·바이트/mtime 불변. 원본 1바이트 append → 재생성. rotations {1:90}→{1:180} → 재생성. **사이드카의 `pypdf_version`을 "0.0.0"으로 변조 → 재생성. `schema_version`을 "0.9"로 변조 → 재생성.** 사이드카 필드(`rotations`/`source_sha256`/`turns`/`pypdf_version`==`pypdf.__version__`) 값 검증 | 10,23 |
| U9 | `test_ensure_upright_noop_when_already_upright` | **(gap_hunter#3 반영)** (a) rotate=0·rotations={}: `(원본 경로, False, [])`, `upright/` 디렉토리 미생성. (b) `upright_paths` 위치에 더미 스테일 PDF+사이드카를 선배치 후 flat PDF로 재호출: 두 파일 **제거됨**, note에 "stale upright cache removed" 포함, 반환 `(원본, False, [note])` | 9,23 |
| U10 | `test_double_normalization_guard` | U2 출력물을 다시 `ensure_upright_pdf(출력물, cache2, {1:90})`에 입력: 마커 감지 → `(입력 그대로, False, [마커 노트])`, cache2에 파일 미생성 | 11 |
| U11 | `test_upright_write_atomic_no_tmp_residue` | 정상 실행 후 `upright/` 안 `*.tmp` glob == 빈 리스트; 사이드카 삭제 후 재실행 시 재생성 확인 | 10 |
| U12 | `test_encrypted_source_raises` | `_make_encrypted_pdf`: `write_upright_pdf` → `pytest.raises(ValueError)` **그리고** `ensure_upright_pdf` → `pytest.raises(ValueError, match="encrypted")` — 후자가 실제로 타는 경로(contrarian#1 지적: 종전 U12는 실경로 미커버였음; 실전 E2E는 A7이 담당) | 12 |
| U13 | `test_upright_chains_into_write_annotated_pdf` | rotate=90 정규화본 + bbox(0.25,0.25,0.5,0.5), `rotations={}`: Square `/Rect` == approx **(75, 200, 150, 300)**; FreeText `/F`==20, `_assert_rect_matches_bbox` 상당 검증 | 5 |
| U14 | `test_upright_module_import_discipline` | **(contrarian#7 반영)** `_imported_top_level(upright_pdf 소스)`가 {"pypdf","pathlib","os","scripts","__future__"} 부분집합 — **직접 import 기준**(전이적 PIL 로드는 align_inputs 경유로 허용된 알려진 사실, 독스트링 명기 확인); 소스에 "PIL"/"pypdfium2"/"render_"/"burn" 문자열 부재 | 1 |
| U15 | `test_write_upright_out_of_range_turns_guard` | **(gap_hunter#9 반영)** 2페이지 PDF에 `write_upright_pdf(src, dst, {99: 90})` 직접 호출: 예외 없음, 반환 `{"n_pages":2,"baked":0,"stripped":0}`, 출력 PDF 판독 가능·양 페이지 콘텐츠 바이트 원본 동일 — 방어 분기의 의도 동작 실증 | 25 |

### 6.3 `tests/test_annotate_pdf.py` 추가/갱신 — A1~A9

| ID | 테스트명 | 시나리오/어설션 | DoD |
|---|---|---|---|
| A1 | (갱신) `test_annotate_case_normalizes_alignment_rotation` | Step 4 사양 그대로 — 구 `test_annotate_case_consumes_alignment_record` 대체. MediaBox [0,0,300,400], Square(75,200,150,300), `/F`==20, `/Matrix` 부재, upright 캐시 존재, `outputs[0]["upright"] is True`·`["skipped"] is False`, 전 페이지 `/Rotate`==0 | 6 |
| A2 | `test_annotate_case_normalizes_metadata_rotation` | `_make_pdf(... rotate=90)`(정렬 기록 없음) → annotate_case: 출력 전 페이지 `/Rotate`==0(구조적 증명의 전제 어설션); Square(75,200,150,300); `_display_chip(ft, rotate=0, wp=300, hp=400)`로 칩-박스 비겹침·간격 ≤ `LABEL_GAP_PT + 2*LABEL_BOX_PAD` | 7 |
| A3 | `test_annotate_case_visual_equivalence_with_legacy_path`(parametrize `(rotate, rotations)` ∈ {(90,None), (0,{1:90})}) | legacy = `write_annotated_pdf`(무변경 함수) 직접 호출, new = `annotate_case`. 각 출력 pdfium 렌더에서 `_FAIL_RGB` 색 픽셀 bbox 추출; a≠0 파라미터는 legacy 렌더를 `rotate_cw(a)` 후 비교. 두 bbox 각 좌표 차 ≤ 2px | 8 |
| A4 | `test_annotate_case_skips_upright_when_flat` | rotate=0·정렬 기록 없음: `upright/` 미생성, 출력 페이지 `/Contents` 바이트 == 원본, `outputs[0]["upright"] is False`·`["skipped"] is False` | 9 |
| A5 | `test_annotate_case_falls_back_when_normalization_fails`(parametrize exc ∈ {`OSError("cache dir unwritable")`, `PdfStreamError("truncated")`}) | **(contrarian#1 캐치 확장 검증)** `monkeypatch.setattr("scripts.annotate_pdf.ensure_upright_pdf", raise exc)`: annotate_case 성공, `boxes_drawn`==1, note에 "falling back" 포함, 출력은 legacy 기대값(rotate=90 원본이면 Square(100,75,200,150)·페이지 `/Rotate`==90 유지), `outputs[0]["skipped"] is False` — `PyPdfError` 서브클래스도 1단 폴백에 잡힘을 확인 | 12 |
| A6 | `test_summary_upright_field_backward_shape` | summary `outputs[*]` 키 집합 == 기존 4키 + {`upright`, `skipped`} — 추가만 허용, 제거/개명 없음(D5의 의도된 additive 확장 고정) | 6 |
| A7 | `test_annotate_case_survives_unreadable_pdf_real`(parametrize ∈ {("encrypted", `_make_encrypted_pdf`, "encrypted"), ("corrupt", `_make_corrupt_pdf`, "annotation failed")}) | **[findings 대응: contrarian#1 HIGH + gap_hunter#6 — 목킹 없음]** `case_cert_dir`에 certA(`rotate=90`, 정상, FAIL bbox 1건) + certB(판독불능 파라미터, bbox 1건): `annotate_case`가 **예외 없이 반환**. certB: outputs 항목 `skipped is True`·`boxes==0`, `certB_annotated.pdf` 미생성, notes에 기대 문자열 포함(암호화 파라미터는 폴백 note에 "encrypted" — `ensure_upright_pdf`의 조기 ValueError 문구). certA: `upright is True`, 출력 전 페이지 `/Rotate`==0, Square(75,200,150,300) — 실제 `FileNotDecryptedError`/`PdfStreamError` 경로가 케이스를 죽이지 못함을 실증 | 21 |
| A8 | `test_annotate_case_isolates_upright_failure_per_stem` | **[findings 대응: gap_hunter#2 HIGH]** `case_cert_dir`에 certA·certB 모두 `rotate=90` 정상 PDF + 각 1건 FAIL bbox. `scripts.annotate_pdf.ensure_upright_pdf`를 wrapper로 monkeypatch: `pdf_path.stem == "certA"`이면 `raise OSError("boom")`, 아니면 **실제 `upright_pdf.ensure_upright_pdf` 호출**. 어설션: outputs 2건 — certA `{upright: False, skipped: False}` + legacy 좌표(Square(100,75,200,150), `/Rotate`==90 유지) + "falling back" note, certB `{upright: True, skipped: False}` + 정규화 좌표(Square(75,200,150,300), `/Rotate`==0); `upright/certB_upright.pdf` 존재·`upright/certA_upright.pdf` 부재 — stem별 캐시·상태 격리 실증 | 20 |
| A9 | `test_unresolved_stem_produces_no_upright_artifact` | **(gap_hunter#4 반영)** annotations에 실존 certA(flat)와 비실존 stem "ghost" 참조 혼재: 기존 unresolved 제외 note 동작 불변 + `upright/` 하위에 "ghost" 관련 파일 0개(케이스가 flat이면 디렉토리 자체 미생성) | 24 |

### 6.4 실측 리터럴 근거(실행자는 재도출 불필요, 검산만)

- (75,200,150,300): `aligned_bbox_to_user_rect((0.25,0.25,0.5,0.5), 0, 0, 300, 400, 0)` = 코너(75,300),(150,200) → minmax.
- (100,75,200,150): 동일 bbox, T=90, 400x300 — 기존 테스트가 이미 고정한 legacy 값(A5/A8 폴백 앵커로 재사용).
- 렌더 동등성 tolerance 0.005: 스파이크 실측 diff 0.0에 여유를 둔 값.
- PIL 회전 매핑: `align_inputs._CW_TO_TRANSPOSE`와 동일 관례.
- 예외 계층: `FileNotDecryptedError`/`PdfStreamError` ⊂ `PdfReadError` ⊂ `PyPdfError`이며 `OSError`/`ValueError`와 무관(레인 실측 + 오케스트레이터 재확인 완료).
- CropBox 픽셀 동등성(U4b): 비대칭 CropBox (30,5,390,250) 시나리오는 레인이 현재 pypdf에서 바이트 단위 동일 렌더를 실측한 구성 — 테스트는 그 결과의 회귀 고정이다.

---

## 7. Risks and Mitigations

| # | 리스크 | 발생 조건 | 완화책 |
|---|---|---|---|
| R1 | pypdf 버전 차이로 `transfer_rotation_to_content` 부재/시그니처 변화 | 환경의 pypdf가 6.6.2가 아님 | Step 1 게이트에서 중단·보고. 사이드카 `pypdf_version`은 기록에 그치지 않고 **캐시 유효 조건으로 강제**되어(contrarian#2), 업그레이드 후 구버전 산출물이 조용히 재사용되는 일이 없다 |
| R2 | `add_transformation`이 content stream 재직렬화 중 희귀 연산자 훼손 | 비전형 생성기 PDF | 스캔 성적서는 페이지당 대형 이미지 XObject 구조(S2·S4). U5~U7 픽셀 동등성 + V4 실PDF 3종 렌더 검증. 실패 시 2단 폴백: **정규화 실패는 legacy 경로로 폴백해 산출 성공, legacy조차 판독 불가능한 PDF는 해당 stem만 스킵하고 케이스는 정상 반환** — "산출 자체는 항상 성공"의 정확한 범위는 "전처리가 새 실패 모드를 추가하지 않고, 판독불능 입력도 케이스를 죽이지 못한다"이다(AC-14, 원판의 과대 서술 정정) |
| R3 | CropBox≠MediaBox·비영점 원점 케이스 좌표 틀어짐 | 케이스 46/62형 | 5종 박스 동일 변환(S7). U4가 리터럴 치수 + **픽셀 bbox ±2px**(contrarian#3)로 이중 고정 |
| R4 | 캐시 무효화 누락 → 스테일 정규화본 사용 | 원본 교체·page-aligner 재실행·pypdf 업그레이드 | schema+pypdf 버전+sha256+rotations 4중 키(U8). 사이드카-마지막 커밋. turns 소멸 시 고아 캐시 제거(U9, gap_hunter#3) |
| R5 | 이중 회전(정규화본 재정규화) | 캐시 경로 오인 입력 | 원본만 전달하는 배선(Step 3) + 메타데이터 마커 가드(U10) |
| R6 | `rotations={}` 전달 누락 → 정규화본에 a 재적용 | 통합 코드 실수 | Step 3 불변식 주석 + A1/A3/A8이 좌표 리터럴로 즉시 검출 |
| R7 | Windows 파일 잠금(`os.replace`/출력 쓰기 실패) | 수동 디버깅 중 뷰어로 파일 열어둠 | 캐시 쓰기 잠금 → 1단 폴백+note. 출력 쓰기 잠금 → 2단 stem 스킵+note(종전엔 케이스 크래시 — 개선). 다음 실행에서 재생성 |
| R8 | SKILL.md 갱신이 고정 문자열 테스트를 깨뜨림 | 금지어 혼입/필수어 삭제 | Step 6 체크리스트 + 편집 직후 `-k skillmd` 즉시 실행(V2) |
| R9 | 기존 발급물 덮어쓰기 | 검증 중 `annotate --all`/기본 out_dir 실행 | `--out` 스크래치 강제(V4), V6 mtime 사후 확인 |
| R10 | 요약 스키마 변화로 CLI 출력/소비자 파손 | `outputs[*]` 키 제거·개명 | 추가만 허용(`upright`/`skipped`), A6이 형태 고정. D5에 의도 명기(contrarian#8) |
| R11 | 대형 PDF(73p)에서 sha256+정규화 비용 | PU2601233급 | sha256은 prep_inputs가 이미 쓰는 비용 수준. 정규화는 1회 후 캐시. V4에서 체감 시간 기록 |
| R12 | **(contrarian#5 반영)** DoD-1~18 전부 통과했는데 V7 실기기 확인에서 핸들 불일치가 정규화본(r=0)에서도 재현 — 구조 가설("불일치는 /Rotate 기반") 반증 | Acrobat 핸들 UI의 근본 원인이 페이지 회전이 아닌 다른 내부 상태일 가능성(계획이 자체 검증 불가능한 유일 가설) | **V7-F 프로토콜(8절)** — 조치 3건이 사전 정의됨: 문구 철회 커밋 + 메모리 반증 기록 + 사용자 에스컬레이션. 단일 커밋 유지(Step 7)로 전체 revert도 1명령 |
| R13 | 2단 캐치(`ValueError` 포함)가 `write_annotated_pdf` 내부의 진짜 로직 버그를 stem 스킵으로 오분류·은폐 | 좌표/입력 검증 로직의 회귀 버그 | 허용된 트레이드오프로 수용: 오류는 note와 `skipped=True`로 반드시 표면화되며(침묵 아님), 좌표 로직 자체는 기존 67개+신규 테스트가 직접 고정. 광역 `except Exception`은 여전히 금지 |
| R14 | PASS-only 회전 페이지도 정규화됨(주석 0개인데 재인코딩) | 회전 페이지의 전 verdict가 PASS | 허용된 트레이드오프(1.7, gap_hunter#8): 규칙의 결정성 유지 목적, 시각 결과 동등(U5)·무손실(U2)이므로 실해 없음 |

---

## 8. Verification Steps

모두 `skills/cert-review` 디렉토리, `PYTHONIOENCODING=utf-8`. V1~V6은 실행자가 직접 수행·증빙(출력 캡처)한다.

- **V1**: `python -m pytest tests/test_upright_pdf.py -v` → U1~U15 전부 pass.
- **V2**: `python -m pytest tests/test_annotate_pdf.py -v` → 기존(1건 갱신 포함)+A1~A9 전부 pass. `-k skillmd` 명시 재확인.
- **V3**: `python -m pytest tests/ -q` → 전체 0 failed/0 error(Step 0 베이스라인 대비 증가분 = 신규 테스트 수, 감소 0).
- **V4(실PDF E2E — 합성 캐시, 결정 4 준수)**: `.cache`에 정렬 기록이 현존하지 않으므로 스크래치에 캐시를 합성해 결정적으로 재현한다. 스크래치 디렉토리 `<SCRATCH>`에(파일명 `#` 포함 경로는 반드시 따옴표):
  1. **V4.1 — r-only 실사례**: `PU2601565-1-MTC.pdf`(23p 전부 `/Rotate=90` 실측). `<SCRATCH>/cache/PU2601565-01/`에 `PU2601565-01_annotations.json`(1페이지 FAIL bbox 1건) 수기 작성 → `annotate_case(case_id="PU2601565-01", cache_root=<SCRATCH>/cache, cert_dir=<실제 cert cleanup 루트>, out_dir=<SCRATCH>/out, ...)` 직접 호출.
  2. **V4.2 — a-only 실사례**: `PU2601233-2-MTC.pdf`(73p 전부 `/Rotate=0` 실측). 같은 방식 + `<SCRATCH>/cache/PU2601233/PU2601233-2-MTC_alignment.json` = `{"applied": {"1": 90}}` 수기 작성.
  3. **V4.3 — 결합(r≠0 AND a≠0) 실사례 [findings 대응: gap_hunter#1 HIGH]**: 케이스 **PU2601233-03**의 `2026-246#-7.21.pdf`(7p, `/Rotate` {0,90} 혼재 — 레인 실측; 메모리상 **사용자가 원 버그를 발견한 실기기 재현 파일**). 절차: (a) pypdf로 페이지별 `/Rotate` 재확인해 r=90인 페이지 p_r과 r=0인 페이지 p_f를 식별, (b) 합성 `<stem>_alignment.json` = `{"applied": {str(p_r): 90, str(p_f): 90}}` — p_r은 **t=180(원 버그의 결합 조합)**, p_f는 t=90, (c) 두 페이지에 FAIL bbox 각 1건의 annotations.json 작성, (d) `annotate_case` 직접 호출, (e) 어설션: 출력 **전 페이지 `/Rotate==0`**, applied/`/Rotate` 양쪽 모두 0인 페이지의 `/Contents` 바이트 verbatim(스팟 체크), pdfium 렌더 2페이지 저장·마커 위치 정상.
  4. 각 산출물 공통: 전 페이지 `/Rotate==0` 확인, pdfium 1페이지 렌더 저장, 라벨 한국어 무결성(FreeText `/Contents` 문자열 재독 + 렌더 글리프 존재) 확인. **(contrarian#6 반영)** 각 실PDF에서 임베딩 폰트 스트림(FontFile/FontFile2/FontFile3) 존재 여부를 확인하고, 존재하면 정규화 전후 원시 바이트 대조(동일 기대), 부재하면 "폰트 스트림 표본 없음"으로 기록.
- **V5**: `git -C ..\.. diff` 육안 검토 — `write_annotated_pdf`~빌더 함수군 diff 0줄(DoD-14), 버전/README 변경 포함(DoD-18) 확인.
- **V6**: 작업 전 기록해 둔 `output/reports/**/*_annotated.pdf`(특히 `output\reports\PU2601233\`, `output\reports\PU2601565-01\`)의 mtime/크기 목록과 작업 후 목록 diff == 공집합.
- **V7(사용자 위임 — 유일한 수동 항목)**: V4 산출물 **3개**(`<SCRATCH>/out/` 하위 — V4.3의 `2026-246#-7.21_annotated.pdf` **필수 포함**)를 Adobe Acrobat에서 열어, (a) FreeText 라벨 클릭 시 선택/리사이즈 핸들 박스가 라벨 실위치와 일치하는지, (b) 핸들로 리사이즈 후에도 텍스트가 가로 유지되는지, (c) 특히 V4.3의 t=180 결합 페이지(원 버그 재현 조합)에서 확인. 확인 파일 경로를 완료 보고에 명기할 것.
- **V7-F(V7 실패 시 프로토콜 — contrarian#5 반영, 사전 정의된 3조치)**: 정규화본(전 페이지 r=0)에서도 핸들-라벨 불일치가 재현되면 구조 가설이 반증된 것이다. 이 경우 다음을 순서대로 실행하고 각각을 완료 보고에 기록한다:
  1. **문구 철회 커밋**: SKILL.md의 Known limitation 블록을 `45bc2ee` 원문 취지(무조건적 한계 서술)로 되돌리는 후속 커밋 — 코드(정규화 전처리)는 유지한다(무손실·앵커 수학 단순화 이득은 독립적으로 유효). 사용자가 전체 철회를 원하면 Step 7의 단일 커밋을 `git revert`.
  2. **메모리 반증 기록**: `cert-review-annotate-norotate-acrobat-handle-limit.md`에 "업라이트 정규화(r=0)로도 핸들 불일치 미해소 — 근본 원인은 /Rotate 기반이 아님" 사실을 추가 기록(향후 동일 접근 재제안 방지).
  3. **사용자 에스컬레이션**: 기존 "Acrobat 근본원인 재조사 금지" 합의의 해제 여부는 사용자만 결정할 수 있으므로, 재조사 재개/한계 수용 중 택일을 명시적으로 질의한다. DoD-19는 "V7 확인 완료" 또는 "V7-F 3조치 실행 완료" 중 하나로만 종결된다 — 조용한 미충족 상태 금지.
