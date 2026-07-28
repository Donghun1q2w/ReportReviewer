# 2026-07-28 — annotate_pdf.py FreeText 라벨 NoRotate 전환 (회전 페이지 라벨 세로 뒤집힘 근본 수정)

**Summary**: 회전된 페이지(`/Rotate=90/180/270`)에 붙는 FreeText 검토 라벨 주석이 Adobe Acrobat에서 리사이즈될 때 세로로 뒤집혀 보이던 버그를 근본 수정. 기존 `/AP` `/Matrix` 회전 보정 트릭(Acrobat이 리사이즈 시 AP를 자체 재생성하면서 함께 소실됨)을 제거하고, FreeText `/F`에 NoRotate 비트(`/F=20`)를 세운 뒤 `/Rect`를 회전-독립적 앵커(칩 좌상단 한 점만 좌표 변환, 자연스러운 폭×높이로 펼침) 방식으로 재계산하도록 교체. Square/Popup 주석은 이 버그가 없어(byte-identical 확인) 무변경.

**Plan**: [2026-07-28_113240_annotate-freetext-norotate-rotation-fix](../plans/2026-07-28_113240_annotate-freetext-norotate-rotation-fix.md) (dh-dev 승인 완료, 적대 검증 2레인(contrarian/gap_hunter) 발견 10건 전건 반영)

## Rationale

실측 동인: `testbed/1. Standard Inspection/ref/2026-246#-7.21_annotated(1).pdf` — `/Rotate=90` 성적서 1페이지의 FreeText 검토 라벨을 사용자가 Adobe Acrobat에서 리사이즈하자 라벨 텍스트가 세로로 뒤집혔고 이후 다시 리사이즈해도 되돌아가지 않았다. 두 참고 PDF를 pypdf 파싱 + pypdfium2 렌더로 직접 대조해 원인을 확정: Acrobat이 FreeText 주석을 "리치텍스트가 살아있는" 객체로 취급해, 사용자가 리사이즈만 해도(텍스트 편집이 아니어도) 우리가 심어둔 `/AP`(회전 보정 `/Matrix` 포함)를 버리고 자체 폰트로 재생성한다. 회전 페이지에서는 라벨의 raw `/Rect`가 필연적으로 폭↔높이가 뒤바뀐 좁고 긴 형태이므로, Acrobat의 재생성 로직이 이를 좁은 텍스트 칸으로 오인해 줄바꿈하고, 페이지 회전 표시 변환이 겹쳐 세로 글자로 보인다.

계획 단계에서 pypdfium2 실측으로 PDF `/F` NoRotate 플래그(bit 5, 값 16)의 정확한 좌표 의미론을 역공학: NoRotate 주석은 raw `/Rect`의 upper-left 코너(`llx, ury`)만 페이지 회전 변환을 따라가고, 그 지점부터는 회전되지 않은 자연스러운 폭·높이로 펼쳐진다. 이 성질을 이용해 라벨의 `/Rect`를 항상 자연스러운(가로로 넓은) 형태로 유지하면, Acrobat이 AP를 재생성해도 한 줄 가로 레이아웃이 나오고 NoRotate가 뷰어 기준 수평으로 고정한다 — `/Matrix`와 달리 `/F`는 주석 딕셔너리 자체의 키라 AP 재생성과 무관하게 살아남는다.

적대 검증(contrarian/gap_hunter) 과정에서 초판 계획의 중요한 결함 2건이 추가로 발견되어 반영됨: (1) 실측상 가장 편차가 큰 회전 조합(`R=0, A=180`, 300px 이탈)이 테스트에서 누락, (2) 이 재설계를 촉발한 실제 운영 케이스(PU2601233/PU2601565, `a≠0`)가 픽셀 렌더로 한 번도 검증되지 않음 — 둘 다 개정판에 반영.

## Changed Files (3 files, +436/-56)

### 수정

| 파일 | 설명 |
|---|---|
| `skills/cert-review/scripts/annotate_pdf.py` | 모듈 docstring 2곳 갱신(NoRotate 앵커 설명 + Acrobat 리사이즈 캐비어트) · `FREETEXT_FLAGS = AnnotationFlag.PRINT \| AnnotationFlag.NO_ROTATE` 신설(pypdf 공식 enum 사용) · `_aligned_bbox_to_display_box`(표시 공간 박스 변환) · `label_rect_for_norotate`(NoRotate 앵커 Rect 계산) 신규 함수 2개 · `_AP_MATRIX` 딕셔너리 및 `/Matrix` 기록 로직 완전 삭제 · `_label_ap`/`_build_label_annot`에서 미사용 `t` 매개변수 제거 · `/F`를 `FREETEXT_FLAGS`로 교체 · `write_annotated_pdf` 라벨 배치 블록을 표시 공간(display space) 기준으로 전환(`a % 360` 정규화 포함) · `_place_label`/`_aligned_page_size_pt` docstring 좌표계-무관 일반화. Square/Popup 관련 함수(`_build_square`/`_popup_rect`/`_build_popup`/생성 블록)는 **byte-identical**(diff 0줄). |
| `skills/cert-review/tests/test_annotate_pdf.py` | 헬퍼 5개 추가(`_FWD_FRAC`, `_chip_geometry`, `_assert_rect_matches_bbox`, `_display_chip`, `_dark_pixel_bbox`) · Matrix 검증 테스트 1개를 NoRotate 검증 테스트로 전면 대체(회전 4종) · 신규 테스트 10개(순수 기하 2종, 표시 공간 인접성 7조합, pdfium 픽셀 렌더 6조합, 정적 `_AP_MATRIX` 부재 가드, 패딩 경계값 4회전, 회전각 정규화, 무효 회전 예외, 최대 길이 라벨 클램프 2조합, 다중 라벨 겹침 회귀) · 기존 3곳 어설션 보강(Square/Popup `/F` 불변, 프로덕션 진입점 `annotate_case` NoRotate 검증, SKILL.md 캐비어트 사실 검사). 39 → **67 passed**. |
| `skills/cert-review-annotate/SKILL.md` | 캐비어트 bullet 교체(리사이즈도 AP 재생성을 트리거한다는 사실 + NoRotate 플래그 언급) · Method 표 셀 및 좌표 규약 bullet 보강. |

### 검증 (독립 재확인 완료)

- `pytest tests/test_annotate_pdf.py -q`: **67 passed**(baseline 39). `pytest tests/ -q`: **308 passed**(baseline 280, 신규 실패 0건).
- `git diff -U0` 상 `_build_square`/`_popup_rect`/`_build_popup` 관련 라인 **0건** — Square/Popup 완전 무변경 확인.
- `git grep _AP_MATRIX`: 프로덕션 코드 0건(테스트의 부재-확인 리터럴 1건만).
- pypdfium2 렌더 스모크(`/Rotate ∈ {0,90,180,270}`, 각 별도 PDF): 4개 PNG 전부 Read 도구로 직접 열어 육안 확인 — 한글 라벨이 가로로, 깨짐 없이 렌더링됨. 특히 R90 전체 페이지 렌더에서 본문("TOP-LEFT of raw page /Rotate = 90")은 실제로 옆으로 누워 있는데 라벨만 똑바로 가로 유지되는 것을 확인(핵심 증거).
- 적대 검증 2레인(contrarian/gap_hunter, 계획 단계) + simplify 4레인(reuse/simplification/efficiency/altitude) + code-reviewer 정확성 검토(실행 후) — code-reviewer는 뮤테이션 테스트 10종 전부(anchor `t`↔`r` 오사용, min/max 반전, 부호 오류, 플래그 누락 등)가 실제로 실패로 잡히는 것을 확인 후 **APPROVE**, LOW 7건(테스트 품질/문서) 발견 → 6건 반영(dead assertion 제거 2곳, Popup 플래그 어설션 정정, `_aligned_page_size_pt` docstring 정정, SKILL.md wording guard 정정, `test_max_length_label_on_rotated_page_stays_clamped` a≠0 파라미터화), 2건은 이미 매뉴얼 검증되어 커버리지 gap으로만 기록(신규 테스트 케이스 추가는 보류).
- **사용자 수동 확인 필요(자동 검증 불가)**: Adobe Acrobat에서 실제 리사이즈 시 가로 유지 여부. 스모크 PDF 3개(`/Rotate=90/180/270`) 경로를 사용자에게 제시함.

### 무변경 (분리 원칙)

- `_build_square`, `_popup_rect`, `_build_popup` 및 이들의 호출 블록 — Square/Popup 주석 생성 로직 일체.
- `<case>_annotations.json` 계약, 색상 매핑, PASS 제외 규칙, 네이티브 주석 아키텍처(Square+Popup+FreeText) 자체.
- 리뷰 로직(5개 도메인 리뷰어), `review-criteria.md`, `review.json` 스키마, `merge_reviews`.
- testbed `ref/`의 기존 발급 PDF(회귀 참고용으로만 사용, 재생성/커밋 안 함).
