# Plan: cert-review-annotate — Phase C 네이티브 PDF 주석 오브젝트 전환 (v2 — Square+Popup 반영)

- **Date**: 2026-07-23 16:09:12
- **Status**: Proposed
- **Mode**: Direct (dh-dev 1-c 설계 확정 → 1-d 계획 → 1-e 적대적 검증 1회 수정 → **Step 2 Comment-loop 1회 수정**: 사용자가 참조 문서 `docs\PU2601564.pdf`(사내 실제 Acrobat 사각형 주석 사례)를 근거로 Square-Popup 동반 주석 추가를 요청, 반영)
- **Supersedes**: [v1](2026-07-23_154820_cert-review-annotate-native-pdf-annotations.md) — v1은 1-e 반영까지만 담았고 Square에 Popup 동반 주석이 없었음. v2는 색상/라벨 관련 핵심 설계는 변경 없이(사용자가 명시적으로 유지 확인) Square-Popup 양방향 링크만 추가.
- **Scope**: v1과 동일 5개 파일(전부 `plugin\ReportReviewer\` 하위, canonical/origin-main 동기화 경로). 마켓플레이스 클론·플러그인 캐시 수정 금지.
- **타당성 결론**: **가능**. Popup 추가에 필요한 두 기술 불확실성(`pypdf.annotations.Popup`의 정확한 kwarg명, `add_annotation`의 반환값·양방향 링크 자동 설정 여부)을 추가 스모크 테스트로 실측 확정(F16, F17)했다.

## 배경 — 이번 리비전의 계기

Step 2(사용자 검토) 단계에서, 사용자가 계획을 바로 승인하지 않고 `plugin\ReportReviewer\docs\PU2601564.pdf`(사내 검토자가 Adobe Acrobat의 "사각형" 도구로 실제 성적서에 주석을 단 사례)를 제시했다. 오케스트레이터가 pypdf로 이 파일의 실제 주석 구조를 직접 덤프한 결과, 순수 빨간색 테두리만 있는 `/Square` 주석과 그에 딸린 빈 `/Popup`(양방향 `/Popup`↔`/Parent` 링크)으로 구성되어 있음을 확인했다. 사용자에게 확인한 결과:

- **색상**: verdict별 색상 유지(변경 없음, 참조는 검토 무관)
- **라벨**: 항상 보이는 한글 텍스트 라벨 유지(변경 없음, 참조는 검토 무관)
- **반영 사항**: Square 주석에 Acrobat 네이티브 방식과 동일한 빈 `/Popup` 동반 주석(양방향 링크)을 추가 — 사내 검토자가 이미 Acrobat에서 이 패턴으로 작업하므로, 우리 산출물도 동일한 상호작용(박스 클릭 → 코멘트 스레드)을 지원하도록 함.

이 리비전은 1-e 적대적 검증(contrarian/gap_hunter)에서 확정된 모든 사항(FreeText 자체 `/AP` 벡터 칩+한글 글리프 라벨, verdict 색상, `T=(R+A)%360` 좌표 변환, CropBox 처리, T1~T8 테스트, `--dpi` 제거)을 그대로 유지한 채 Popup 동반 주석만 추가한 것이며, 1-e 패널은 재실행하지 않았다(Step 2 Comment-loop는 재패널 대상이 아님).

---

# cert-review-annotate Phase C 네이티브 PDF 주석 전환 — 구현 계획 (Step 2 Comment 반영 최종판)

작성: 계획 전담 에이전트. 이 최종판 = 1-e 개정판 + **Step 2 Comment(참조 `docs\PU2601564.pdf`의 Acrobat 네이티브 Square+Popup 패턴) 반영**. Popup 요청 사항의 두 기술 불확실성(pypdf `Popup` 시그니처, `add_annotation` 반환값)을 추가 실측으로 확정했다(F16~F17). 그 외 1-e에서 확정된 모든 내용(자체 /AP FreeText, verdict 색상, T=(R+A)%360, CropBox, T1~T8, --dpi 제거)은 그대로 유지.

## 0-A. Step 2 Comment 반영 내역 (이번 리비전)

| 요청 | 처리 |
|---|---|
| 1. `_build_popup` 신설 | 반영 — `pypdf.annotations.Popup` 존재·시그니처 실측 확정(F16): **kwarg명은 `parent_annotation`이 아니라 `parent`** (Step 3) |
| 2. 양방향 링크·순서 | 반영 + 실측 단순화(F16~F17): `add_annotation`은 **전달한 객체 그 자체를 등록해 반환**(`ret is sq == True`)하고 `.indirect_reference`를 부여하며, **Popup을 add하면 pypdf가 부모의 `/Popup` 역방향 링크까지 자동 설정**함을 확인. 순서는 Square 먼저 add → Popup(parent=sq) 생성·add → 방어적 명시 재설정(Step 4). 저장·재독 후 양방향 왕복 `True` 확인 |
| 3. /T·/Subj | 반영 — `/T="cert-review"`(도구 상수, `ANNOT_AUTHOR`), `/Subj=verdict`. **FreeText에도 동일 적용**(근거: /T는 Acrobat 코멘트 패널의 '작성자' 열이므로 두 주석이 같은 도구 산출물로 일관 표기되고, verdict는 /Subj가 올바른 자리 — 1-e판의 "/T=verdict" 결정을 폐기·대체) |
| 4. FreeText에 Popup 없음 | 반영 — 참조 패턴은 주(main) 주석 1개당 Popup 1개. Square가 코멘트 스레드 캐리어(/Contents=라벨), FreeText는 우리가 추가한 상시-표시 라벨이라는 위상 차이를 docstring에 명시(Step 1/3) |
| 5. AC/DoD/테스트 갱신 | 반영 — AC2 확장, T3c(양방향 왕복 + /T·/Subj + /CreationDate **형식 패턴만** 검증) 신설, 항목당 오브젝트 수 2→3 반영해 T3~T5 기대값 갱신, Code Writing Guide에 타임스탬프 리터럴 assert 금지 명시 |
| 6. 페이지 무결성 무영향 | 반영 — Popup은 아무것도 그리지 않는 빈 오브젝트로 /Annots에만 추가되므로 기존 T2가 그대로 커버. R10에 한 줄 명시 |

## 0-B. 1-e Findings Disposition (유지 — 변경 없음)

| ID | 처리 요지 |
|---|---|
| H1 | 설계 변경으로 해결: FreeText 자체 /AP(벡터 칩+4x 한글 글리프 이미지) — pdfium 렌더 실측(F12). CID 임베딩 기각(비대칭 리스크·~300줄 파싱·라이선스), NeedAppearances는 AcroForm 전용 확정(F10) |
| H2 | R5 정정(데이터셋 /Annots 0건, F14) + 합성 사전-주석 테스트 T2b |
| H3 | 케이스 46/62 CropBox 오프셋 실측 리터럴(F13) → T1 리터럴 + 케이스 46 E2E |
| H4 | T7(정적 회귀 pytest, SKILL.md 43행 포함) + T8(수동 git-status 위임) 신설, D5/D6→T7·D8→T8 매핑 |
| M1 | 자체 /AP로 구조 해소 — 라벨 크기는 실제 폰트 메트릭 측정(WYSIWYG), 잔여는 R2 |
| M2 | dedupe 키에 verdict+label 포함 + 반례 테스트 |
| M3 | 실측(F11)으로 미수정: PdfReader 평탄화가 상속 /Rotate를 리프에 병합 — 회귀 fixture만 추가 |
| M4 | R7에 annotation-locator.md stale 문구 기록 |
| L1~L5 | 전부 반영(상수 재캘리브레이션 명시, `:g` 통일, FreeText kwargs 불신뢰 경고, 성능 disposition+선택 스모크, SKILL.md 정확 경로) |

## 실측 확인 사실 (F1~F15 유지 + 신규 F16~F17 — 재확인 불필요)

- **F1.** `PdfWriter(clone_from=...)`+`add_annotation` 후 전 페이지 /Contents 바이트 원본 완전 동일(실 케이스 24 확인).
- **F2.** 주석 개별 제거·재저장 후에도 콘텐츠 무손상, 나머지 주석 잔존.
- **F3.** 현 pypdfium2 `render()`에 `draw_annots` 인자 없음 — 주석은 기본 렌더.
- **F4.** pdfium: /AP 없는 Square는 자체 외형 생성·렌더, /AP 없는 FreeText는 픽셀 0.
- **F5.** pypdf 6.6.2 FreeText: /DA에 Tf 누락(+kwargs 상호 오염) → /DA 수동 재정의 필수.
- **F6.** 한글 /Contents 왕복 무손상(육안 확인).
- **F7.** 회전 실태: 케이스 24 전 페이지 R=90(pdfium이 적용 렌더); PU2601233 R=0/A=90; PU2601565-01 R=90/A=270(T=0)·R=90/A=0(T=90) 혼재 → T=(R+A)%360 필수.
- **F8.** `.cache`에 annotations.json 0건 → E2E는 fixture.
- **F9.** 테스트 위치: `skills\cert-review\tests\test_annotate_pdf.py`.
- **F10.** `set_need_appearances_writer`=AcroForm 폼 필드 전용 — FreeText 무효.
- **F11.** PdfReader 평탄화가 상속 속성(/Rotate 등)을 리프에 병합(원시 바이트+소스+동작 3중 확인). `writer._root_object["/Pages"]` 변조로 상속 fixture 생성 가능.
- **F12.** FreeText 자체 /AP(Form XObject: 벡터 칩 + `flate_encode` 이미지 XObject) → pdfium이 한글 라벨 완전 렌더(글리프 다크 픽셀 1339, 칩 배경색 정확). `StreamObject.flate_encode()`는 키 보존+/Filter 자동.
- **F13.** CropBox≠MediaBox 실측: 케이스 46 p1 crop=(3.96001, 2.88, 599.76, 845.28) 등, 케이스 62 crop=(0.72, 0.53999, ...) — 전 페이지 R=0.
- **F14.** 데이터셋 `*comment*` 파일 /Annots 0건(파일명은 스캔 속 필기 의미).
- **F15.** 상속-회전 fixture 트릭 검증 완료.
- **F16. (신규)** `pypdf.annotations.Popup` 존재, 시그니처 `Popup(*, rect, parent: DictionaryObject|None = None, open: bool = False)` — **kwarg명 `parent`**. 내부에서 `parent.indirect_reference`로 /Parent를 설정하므로 **부모를 먼저 `add_annotation`으로 등록**해야 함(미등록이면 경고 후 /Parent 미설정). `add_annotation(page_number, annotation)`은 전달 객체를 그대로 등록·반환(`ret is 입력 == True`)하고 `.indirect_reference`(IndirectObject)를 부여하며, **등록 후의 키 변조도 출력에 반영됨**(왕복 확인).
- **F17. (신규)** Popup을 `add_annotation`하면 pypdf가 /Parent를 읽어 **부모 Square의 `/Popup` 역방향 링크를 자동 설정**함을 실측. 저장·재독 후 `sq[/Popup].get_object() is popup && popup[/Parent].get_object() is sq` == True, /Open=False, /Contents 없음(빈 스레드 — 참조 문서와 동일 상태), /T·/Subj·/NM 왕복 보존. (자동 설정은 문서화되지 않은 동작이므로 방어적 명시 설정을 병행 — Step 4.)

---

## 1. Requirements Summary

- Phase C 렌더러를 "페이지 래스터화+번인"에서 **네이티브 PDF 주석 오브젝트 생성**으로 완전 교체.
  - 박스 = `/Square`(무채움, verdict 색 테두리, 자체 /AP 없음 — F4) + **Acrobat 네이티브 패턴과 동일한 빈 `/Popup` 동반 주석(양방향 링크)** — 참조 `docs\PU2601564.pdf`의 실제 사내 검토자 패턴 준수.
  - 라벨 = `/FreeText` + 자체 /AP(벡터 칩+4x 한글 글리프 이미지) → 전 주요 뷰어 상시 표시(F12). FreeText에는 Popup 없음.
  - 스티키노트 단독·Stamp 절충·병행 옵션 없음.
- 전 페이지 완전 copy-through(clone_from), /Annots에만 append. 주석은 개별 삭제/이동/수정 가능.
- PASS 제외, 색상 단일 소스, ≤50자 truncation, dual-gate, stem 라우팅, oob 가드, summary 스키마 유지.
- 좌표: 정렬 공간 fractional bbox → 사용자 공간 /Rect, T=(R+A)%360 4케이스 + CropBox 오프셋 + 상속 /Rotate.
- 코멘트 메타: `/T="cert-review"`, `/Subj=verdict`, `/NM` 결정적 고유 ID, `/M`·`/CreationDate`(실행 시각, D:YYYYMMDDHHMMSS).
- CLI `--dpi` 완전 제거, `skills\cert-review-annotate\SKILL.md` 동기 갱신, 테스트 재작성(T7 정적 회귀 포함).
- 편집 대상은 `D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection\plugin\ReportReviewer\` 하위만. 마켓플레이스 클론·캐시 수정 금지. 신규 의존성 금지(pypdf+Pillow+malgun.ttf).

## 2. Acceptance Criteria

| # | 항목 | Before | After |
|---|---|---|---|
| AC1 | 원본 레이어 | 래스터 대체 | 전 페이지 /Contents 바이트 완전 동일, MediaBox/CropBox/Rotate 불변, 기존 /Annots 위 append |
| AC2 | 박스 | Pillow 픽셀 | `/Square`: /IC 부재, /C=verdict RGB(0~1), /BS {/W 2, /S /S}, /F 4, /Contents=라벨, **/T="cert-review", /Subj=verdict, /NM="cert-review-p{페이지:02d}-{순번:02d}", /M·/CreationDate="D:YYYYMMDDHHMMSS" 형식, /Popup=동반 Popup 간접 참조** |
| AC2b | **Popup(신규)** | 없음 | `/Popup`: /Open=False, /Contents 없음(빈 스레드), /Parent=해당 Square 간접 참조(**양방향 왕복 성립**), /Rect=Square 오른쪽 180×120pt(페이지 경계 클램프, 좌표 리터럴 검증 비대상 — UI 힌트) |
| AC3 | 라벨 | Pillow 픽셀 | `/FreeText`: /Contents 한글 원문(≤50자), /DA="/Helv 10 Tf 0 g", /F 4, **/T="cert-review", /Subj=verdict, /NM=...-label**, 자체 /AP /N=Form XObject(T≠0 시 /Matrix), **Popup 없음** |
| AC4 | 위치 정확도 | 픽셀 드로잉 | T=0/90/180/270 리터럴 + 케이스 46 CropBox 리터럴 (152.91, 424.08, 301.86, 634.68)±0.01 |
| AC5 | 삭제 가능성 | 불가 | 개별 제거 후 콘텐츠 무손상(자동) |
| AC6 | 게이트·라우팅 | 동작 | 동일 + 같은 bbox·다른 verdict 보존 |
| AC7 | CLI | --dpi 있음 | --dpi 제거(argparse 명시 에러) |
| AC8 | 의존성 | +pypdfium2+폰트 | pypdf+Pillow(라벨 AP 전용)+malgun.ttf(CERT_REVIEW_FONT), pypdfium2 import 0건, 신규 패키지 0 |
| AC9 | summary | 7키 | 동일 키·의미. **boxes_drawn 1건 = Square+Popup+FreeText 3오브젝트 묶음** |
| AC10 | 문서 | burn-in 서술 | SKILL.md가 네이티브 주석+자체 AP+**Popup 동반** 반영, "burn-in"·"--dpi" 0건 |

## 3. Implementation Steps

수정 파일(전부 `...\testbed\1. Standard Inspection\plugin\ReportReviewer\` 하위): `skills\cert-review\scripts\annotate_pdf.py`(전면 재작성), `skills\cert-review\scripts\cli.py`(375~434·886~895행), `skills\cert-review\tests\test_annotate_pdf.py`(재작성), `skills\cert-review-annotate\SKILL.md`, `requirements.txt`(코멘트만).

### Step 1. annotate_pdf.py 제거·유지·상수

**제거**: `io`·`pypdfium2` import, `_render_page_pil`, `_draw_annotations`, `render_annotated_pdf`, `_LINE_W_PER_DPI`, `_FONT_PX_PER_DPI`. **유지(무변경)**: `_hex_to_rgb`, `_verdict_rgb`, `_truncate`, `_label_for`, `_rects_overlap`, `_place_label`, `LABEL_MAX`, `_VERDICT_FILL`, `_ANNOTATABLE`, `Annotation`, `load_annotations`, 기존 공용 import(단, `bbox_to_pixels`·`rotate_upright` import 제거). **유지(용도 변경)**: `DEFAULT_FONT`(CERT_REVIEW_FONT env), `_load_font`(hard-fail 관례, 크기=`int(round(LABEL_FONT_PT*AP_OVERSAMPLE))`), PIL import(라벨 AP 글리프 전용).

**신규 import**: `zlib`, `time`(타임스탬프), `from pypdf.annotations import FreeText, Popup, Rectangle`, `from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject, StreamObject, TextStringObject`.

**신규 상수** (L1: pt 재캘리브레이션 — 구 200dpi 등가 병기):
```python
BORDER_W_PT = 2; LABEL_FONT_PT = 10.0; LABEL_GAP_PT = 4.0; LABEL_BOX_PAD = 2.0
AP_OVERSAMPLE = 4.0; _CHIP_BORDER_W = 0.75; _LABEL_GRAY = (0.313725,)*3
ANNOT_AUTHOR = "cert-review"          # /T — 도구 상수(사람 이름 아님)
POPUP_W_PT, POPUP_H_PT = 180.0, 120.0  # Acrobat 관례적 UI 힌트 크기
```

docstring 전면 재작성 — 기존 항목(네이티브 주석·copy-through·좌표 규약·C1·자체 AP 근거·수정 시 AP 재생성 유의)에 추가: **주석 위상 — Square가 주(main) 주석이며 Acrobat 네이티브와 동일하게 빈 /Popup 동반 스레드를 갖는다(참조: 사내 실제 검토 사례 docs/PU2601564.pdf 패턴); FreeText는 상시-표시 라벨 오버레이라 Popup을 갖지 않는다. /M·/CreationDate는 Acrobat 코멘트 메타를 위해 실행 시각을 읽는다(이 모듈의 유일한 wall-clock — cli.py 타임스탬프 관례와 동일한 예외).**

### Step 2. 좌표 변환 (1-e판 그대로 — 무변경)

`_aligned_to_user_frac(u,v,t)` 4-branch(0:(u,v) / 90:(v,1−u) / 180:(1−u,1−v) / 270:(1−v,u)), `aligned_bbox_to_user_rect(bbox,mx0,my0,wp,hp,t)`(두 모서리 변환+min/max 정규화), `_aligned_page_size_pt`. 기하 소스는 `page.cropbox`, `R=int(page.get("/Rotate") or 0)%360`(상속은 F11로 자동), `A=rotations.get(p,0)`, `T=(R+A)%360`. 테스트 리터럴(400×300 bbox(0.25,0.25,0.5,0.5)): T=0 (100,150,200,225) / 90 (100,75,200,150) / 180 (200,75,300,150) / 270 (200,150,300,225); 케이스 46 오프셋 리터럴 (152.91,424.08,301.86,634.68)±0.01.

### Step 3. 주석 빌더 (Popup 추가 반영)

`_rgb01`, `_verdict_hex6`, `_measure_label`, `_render_label_image`, `_image_xobject`, `_AP_MATRIX`{90:[0,1,-1,0,0,0], 180:[-1,0,0,-1,0,0], 270:[0,-1,1,0,0,0]}, `_label_ap`은 1-e판 그대로.

```python
def _pdf_now() -> str:
    return time.strftime("D:%Y%m%d%H%M%S")   # 오프셋 생략은 스펙 허용; 테스트는 형식만 검증

def _build_square(rect_pt, verdict, label, nm, stamp) -> Rectangle:
    sq = Rectangle(rect=rect_pt, interior_color=None)
    # 수동 키: /C=_rgb01(_verdict_rgb(verdict)), /BS {/W 2, /S /S}, /F 4, /Contents=label,
    #          /T=ANNOT_AUTHOR, /Subj=verdict, /NM=nm, /M=stamp, /CreationDate=stamp
    return sq

def _popup_rect(sq_rect, mx0, my0, wp, hp) -> tuple:
    # Square 오른쪽: x0 = sq_rect[2]+LABEL_GAP_PT, y1 = sq_rect[3]; 크기 POPUP_W_PT x POPUP_H_PT.
    # cropbox 경계 클램프: x0 = min(x0, mx0+wp-POPUP_W_PT); x0 = max(x0, mx0); y 동일 요령.
    # UI 힌트 좌표(내용상 무의미) — 리터럴 테스트 비대상, 경계 클램프만 보장.

def _build_popup(square: Rectangle, rect_pt, nm, stamp) -> Popup:
    pop = Popup(rect=rect_pt, parent=square, open=False)   # F16: kwarg명 'parent'!
    # 수동 키: /NM=nm+"-popup", /M=stamp. /Contents 없음(빈 스레드 = 참조와 동일). /Open=False는 생성자.
    return pop

def _build_label_annot(writer, rect_pt, verdict, label, font, t, nm, stamp) -> FreeText:
    # 1-e판 그대로(자체 /AP, /DA 수동) + /T=ANNOT_AUTHOR, /Subj=verdict, /NM=nm+"-label", /M=stamp.
    # Popup은 만들지 않는다(주석 위상 — docstring 참조).
```
`/NM` 규칙: `f"cert-review-p{page:02d}-{seq:02d}"`(페이지 내 부착 순번) — 결정적·문서 내 고유, 테스트 리터럴 검증 가능.

### Step 4. `write_annotated_pdf` — 항목당 부착 시퀀스 (F16/F17 실측 순서)

시그니처·골격은 1-e판 그대로(`(pdf_path, anns_by_page, out_pdf, rotations=None, font_path=DEFAULT_FONT) -> (out_path, boxes_drawn, page_count, oob_count)`; clone_from; oob 가드; dedupe 키=(rect 반올림, verdict, label); 정렬공간 라벨 배치 후 동일 역변환). **항목당 부착 순서만 다음으로 확정**:
```python
stamp = _pdf_now()                       # 함수 진입 시 1회
...
nm = f"cert-review-p{p:02d}-{seq:02d}"
sq = _build_square(rect, ann.verdict, ann.label, nm, stamp)
writer.add_annotation(p - 1, sq)         # F16: sq 자체가 등록되고 .indirect_reference 부여
pop = _build_popup(sq, _popup_rect(rect, mx0, my0, Wp, Hp), nm, stamp)
writer.add_annotation(p - 1, pop)        # F17: pypdf가 sq[/Popup] 역방향 링크 자동 설정
sq[NameObject("/Popup")] = pop.indirect_reference  # 자동 설정은 미문서 동작 — 방어적 명시(동일값 멱등)
# 이어서 FreeText(자체 /AP) — 1-e판 그대로. z-order: Square→Popup→FreeText(라벨 최상위).
drawn += 1                               # 3오브젝트 묶음 = 1 카운트(AC9)
```
등록 후 키 변조가 출력에 반영됨은 F16에서 왕복 확인됨. PASS·dedupe skip 시 세 오브젝트 모두 생성 안 함.

### Step 5. `annotate_case` — 1-e판 그대로 (dpi 제거, font_path 존치, 호출부 교체, summary 무변경)

### Step 6. cli.py — `--dpi` 완전 제거 (1-e판 그대로; help 문구 "native, individually editable PDF annotations")

### Step 7. `skills\cert-review-annotate\SKILL.md`

1-e판 갱신 목록(3행 description, **43행 "burn-in matches" → "annotations match"**, 44행 Method, Phase C --dpi 제거+불릿, 134행 C1, 137행 Korean integrity, 148행 flow) 유지 + **44행 Method에 "each Square carries an Acrobat-native empty /Popup companion (bidirectional /Popup–/Parent link), matching the in-house reviewer's Acrobat annotation pattern (ref: docs/PU2601564.pdf)" 추가**.

### Step 8. requirements.txt 코멘트 갱신 (1-e판 그대로)

### Step 9. 테스트 재작성 — 섹션 6

## 4. Code Writing Guide

1-e판 전체 유지(utf-8·`:g` 포맷·/DA 수동(**L3: FreeText kwargs 불신뢰**)·AP는 add 전 완성·`draw_annots` 금지·신규 패키지 금지·클론/캐시 수정 금지·번인 코드 삭제·단계별 즉시 실행 검증·scratchpad) + 추가:
- **Popup kwarg명은 `parent`**(`parent_annotation` 아님 — TypeError, F16). 부모 Square를 **먼저 add_annotation**해 `.indirect_reference`를 확보한 뒤 Popup을 만들 것(미등록 부모면 pypdf가 경고만 내고 /Parent를 빠뜨림).
- **타임스탬프(/M·/CreationDate)는 정확 리터럴 assert 금지** — `^D:\d{14}` 형식 패턴만 검증(테스트 결정론성). `_pdf_now()` 호출은 write_annotated_pdf 진입 시 1회로 제한(항목 간 동일 stamp — 결정적 비교 가능).

## 5. Definition of Done

- [ ] D1. `PYTHONIOENCODING=utf-8 python -m pytest tests/test_annotate_pdf.py -v` 전 통과.
- [ ] D2. 실데이터 E2E(PU2601233 = R=0/A=90, 케이스 46 = CropBox 오프셋)에서 전 페이지 콘텐츠 바이트 원본 일치 [T2·T6-E2E].
- [ ] D3. 주석 객체 검증 통과: Square(/Rect 리터럴·/C·/BS·/Contents·/T="cert-review"·/Subj=verdict·/NM 리터럴·/M·/CreationDate 형식·**/Popup 존재**), **Popup(/Open=False·/Contents 없음·/Parent→Square 양방향 왕복)**, FreeText(/Contents 한글·/DA Tf·/AP /N Form·T≠0 /Matrix·Popup 없음), PASS 주석 0개 [T1, T3, T3c].
- [ ] D4. 주석 개별 삭제 후 콘텐츠 무손상 [T5].
- [ ] D5. 번인 잔재 제거(annotate_pdf.py 금지 심볼 0건, cli annotate --dpi 0건) [T7].
- [ ] D6. `skills\cert-review-annotate\SKILL.md` "burn-in"·"--dpi" 0건 + Step 7 반영 [T7].
- [ ] D7. 한글 무결성: /Contents 재독 육안 일치 + pdfium 렌더 라벨 글리프 픽셀 존재(자동) [T6 + Verification 4].
- [ ] D8. `git status` 변경 범위 = 계획 5파일+테스트 [T8 수동].

## 6. Adversarial Test Environment

파일: `plugin\ReportReviewer\skills\cert-review\tests\test_annotate_pdf.py`. 공용 헬퍼(`_make_pdf`(실 콘텐츠 스트림·rotate·rotate_on_pages_node·cropbox), `_content_bytes`, `_annots`)와 유지 테스트 12종은 1-e판 그대로.

- **T1. 좌표 정확도** [→D3]: 1-e판 그대로(4-branch 리터럴·순방향 항등·45도 ValueError·케이스 46 오프셋 리터럴·R/A 조합 3종·상속 /Rotate fixture).
- **T2. 페이지 무결성** [→D2]: 1-e판 그대로 — **Popup 추가 후에도 기대값 불변**(Popup은 /Annots 엔트리일 뿐 아무것도 그리지 않음 — 요청 6 명시 커버). T2b(사전 주석 보존) 그대로.
- **T3. 주석 객체 검증** [→D3]: `test_square_and_freetext_fields` — 주의/N/A/FAIL 각 1건 → **페이지 /Annots에 (Square+Popup+FreeText)×3 = 9 엔트리**; Square 필드(1-e판 + /T=="cert-review"·/Subj==verdict·/NM==리터럴·/Popup 존재); FreeText(1-e판 + /T·/Subj·/NM·**Popup 부재**); PASS 직접 주입 시 0개. `test_label_ap_matrix_on_rotated_page` 그대로.
  - **T3c(신규). `test_square_popup_bidirectional_link`**: 저장·재독 후 각 Square에 대해 `sq[/Popup].get_object()`가 /Subtype==/Popup이고 그 `/Parent`.get_object()의 /NM이 해당 Square /NM과 일치(왕복); Popup /Open==False·/Contents 부재; **`/CreationDate`·`/M`은 `re.fullmatch(r"D:\d{14}", ...)` 형식만 검증(정확 타임스탬프 assert 금지)**; Square와 Popup의 stamp 동일값 확인.
- **T4. 경계값** [→D3, AC6]: 1-e판 그대로 — 단 기대 오브젝트 수를 3오브젝트 묶음 기준으로 갱신(`test_duplicate_bbox_dedupes`: 묶음 1개=엔트리 3개; `test_same_bbox_different_verdict_kept`: 묶음 2개=엔트리 6개).
- **T5. 삭제 가능성** [→D4]: FreeText 1개 제거·재저장 → 콘텐츠 무손상 + **Square·Popup 잔존**(F2 회귀).
- **T6. 렌더링 프록시** [→D7]: 1-e판 그대로(Square 테두리색 픽셀, FreeText 라벨 칩·글리프 픽셀, T=90 회전 AP 1건; Acrobat 육안은 위임). Popup은 시각 요소가 없어 렌더 assert 비대상(명시 주석).
- **T7. 정적 회귀** [→D5, D6]: 1-e판 그대로(annotate_pdf.py 금지 심볼, cmd_annotate·argparse annotate 블록 한정 --dpi 0건, SKILL.md stale 문구 0건).
- **T8. 수동 확인** [→D8]: 커밋 전 git status 대조(명시적 위임, pytest 비대상).
- **T6-E2E**(pytest 외): PU2601233·케이스 46 fixture → CLI 실행 → 콘텐츠 바이트·/Annots(Popup 링크 포함)·한글 read-back 검증 스크립트.

## 7. Risks and Mitigations

- **R1. 뷰어 의존(축소됨)**: 자체 /AP로 라벨 전 뷰어 상시 표시(F12). 잔여: (a) 글리프 4x 래스터 — 극단 확대 픽셀레이션, (b) 뷰어에서 라벨 텍스트 수정 시 /AP 재생성, (c) 실사용 뷰어 최종 육안 → Verification 5 위임.
- **R2. 수정-후 외형**: /DA(Helv 10 Tf) 명시로 재생성 안전. 수용.
- **R3. 회전 좌표 변환**: 운영 실재 3조합 리터럴 고정(T1), min/max 정규화, /AP /Matrix 필수(T3).
- **R4. CropBox 오프셋**: 실측 리터럴 테스트(T1) + 케이스 46 E2E.
- **R5. 기존 주석 보유 원본**: 데이터셋에 실재하지 않음(F14 — 정정됨). 견고성 요구로서 T2b 합성 fixture 검증.
- **R6. stale 배포본**: 옛 SKILL.md의 --dpi 호출은 argparse 명시 에러. 클론/캐시 동기화는 범위 밖 후속.
- **R7. 스코프 밖 문서 stale**: `agents/annotation-locator.md`의 "burn-in" 문구 — 후속 정리 대상 기록.
- **R8. 표시 방향**: A≠0 페이지는 원본대로 옆으로 보임; 라벨 AP는 /Matrix로 콘텐츠 기준 수평(구 burn-in 관례 동일). 수용·docstring 명기.
- **R9. 폰트 의존 존속**: burn-in과 동일 의존(malgun/CERT_REVIEW_FONT), 부재 시 hard-fail 관례 유지.
- **R10. (신규, 요청 6) Popup 무영향 명시**: Popup은 시각 요소가 없는 빈 오브젝트(/Contents 없음, 참조 문서와 동일 상태)로 /Annots에만 추가되므로 페이지 무결성(전 페이지 콘텐츠 바이트 동일)에 영향 없음 — 별도 리스크가 아니며 기존 T2가 자동 검증으로 그대로 커버(F17 왕복 실측 완료).

## 8. Verification Steps

작업 디렉토리: `...\plugin\ReportReviewer\skills\cert-review`
1. `PYTHONIOENCODING=utf-8 python -m pytest tests/test_annotate_pdf.py -v` 전 통과 → `python -m pytest tests -v` 전체 회귀.
2. 정적 확인은 T7이 대행(D5/D6).
3. **실데이터 E2E**: `.cache\PU2601233\PU2601233_annotations.json`·`.cache\46\46_annotations.json` fixture → `python -m scripts.cli annotate --case ...` → 검증 스크립트로 (a) 전 페이지 콘텐츠 바이트 일치, (b) /Annots 필드+**Square↔Popup 양방향 링크**, (c) 삭제 무손상. 가능하면 PU2601565-01 반복.
4. **한글 read-back**: /Contents 재독 육안 + pdfium 렌더 글리프 픽셀 자동 확인(라벨 크롭 PNG 병행).
5. **위임 검증**: 실사용 뷰어(권장 Acrobat, 가능하면 Chrome)에서 (a) 한글 라벨 상시 표시, (b) 주석 개별 선택·이동·삭제, **(c) Square 클릭/Comments 패널에서 Acrobat 네이티브 사각형 주석과 동일하게 팝업 스레드가 열리는지**(참조 PU2601564.pdf와 나란히 비교) 육안 확인 요청. 라벨 텍스트 수정 시 외형 재생성 안내.
6. 커밋 전 `git status` 대조(T8/D8) — 커밋·배포는 revision-tracker 후속 위임.
7. (선택) 케이스 72(143p) 타이밍·크기 스모크.

— 이상. 이 최종판이 이전 계획을 완전히 대체한다. 스모크 산출물(`native_annot_smoke.py`, `smoke_freetext_ap.pdf`, `smoke_ap_label.png`, `smoke_inherited_rotate.pdf`, `smoke_popup.pdf`)은 scratchpad에 보존됨.
