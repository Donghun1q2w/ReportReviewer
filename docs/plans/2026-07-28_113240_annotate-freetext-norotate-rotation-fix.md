# annotate_pdf.py FreeText 라벨 NoRotate 전환 (회전 페이지 라벨 세로 뒤집힘 근본 수정) — 구현 계획

- **작성**: 2026-07-28 11:32 (전담 플래닝 에이전트, Opus, dh-dev Step 1-d — 적대 검증 1회 반영판)
- **상태**: Completed (커밋 `9e3cd1f`, pytest 39→67(annotate)/280→308(전체), D1~D18 중 D16만 사용자 수동 확인 대기 — Adobe Acrobat에서 스모크 PDF 3개(`/Rotate=90/180/270`) 리사이즈 확인 필요)
- **대상**: `plugin/ReportReviewer` (단일 소스, `git@github.com:Donghun1q2w/ReportReviewer.git`, main, HEAD `3eb08dc`). 대상 파일 3개: `skills/cert-review/scripts/annotate_pdf.py`, `skills/cert-review/tests/test_annotate_pdf.py`, `skills/cert-review-annotate/SKILL.md`.
- **동인**: `testbed/1. Standard Inspection/ref/2026-246#-7.21_annotated(1).pdf` 실측 — `/Rotate=90` 성적서 1페이지의 FreeText 검토 라벨을 사용자가 Adobe Acrobat에서 리사이즈하면 Acrobat이 커스텀 `/AP`(회전 보정 `/Matrix`)를 버리고 자체 리치텍스트로 재생성하며, 그 결과 라벨이 세로로 뒤집혀 보이고 이후 리사이즈해도 되돌아가지 않음(두 참고 PDF를 pypdf 파싱 + pypdfium2 렌더로 직접 대조해 확정). 해결: FreeText에 `/F` NoRotate 비트(16)를 세우고, 라벨 `/Rect`를 회전-독립적 앵커(칩 좌상단 1개 코너만 변환) 방식으로 재계산해 Acrobat 재생성 후에도 항상 가로 한 줄 레이아웃이 나오도록 함. Square/Popup은 이 버그가 없어 무변경.
- **적대 검증**: contrarian/gap_hunter 2레인 완료(계획 핵심 좌표 수학·스코프 경계는 두 레인 모두 독립 재계산으로 정확함을 확인) — 발견 10건(HIGH 4·MEDIUM 3·LOW 3) 전건 반영판. 미해소 HIGH 0건. 처분표는 아래.

## 검증 발견 처분표

| ID | 레인 | 심각도 | 처분 | 반영 위치 (요지) |
|---|---|---|---|---|
| F1 | gap_hunter | HIGH | 반영 | Step 8(e) 파라미터에 실측상 최악 편차 조합 `R0-A180-T180` 추가(총 7조합), Step 8(d)에 `a=180` 리터럴 `(200,150,300,225)` 추가. AC10/D8 갱신 |
| F2 | contrarian | HIGH | 반영 | Step 8(f)를 `(rotate, rotations)` 2인자로 확장해 실제 운영 케이스(PU2601233/PU2601565, `a≠0`)를 pdfium 픽셀 렌더로 검증(6조합). `_chip_geometry` 대체 금지 명시 |
| F3 | gap_hunter | HIGH | 반영 | 신규 테스트 (m) `test_multiple_labels_on_rotated_page_do_not_overlap` 추가 — 회전 걸린 페이지에 라벨 3개, 겹침 회피 fallback 실제로 태움. AC21/D17 신설 |
| F4 | gap_hunter | HIGH | 반영 | V7을 회전 4종 각각 별도 단일 페이지 PDF로 명시, V8을 `/Rotate=90/180/270` 3개 경로 모두 제시하도록 갱신(1-c가 셋 다 지정). D16/AC20/R1 동기화 |
| F5 | contrarian | MEDIUM | 반영 | SKILL.md 테스트 (h)에 "리사이즈/resize" 사실 자체를 검사하는 어설션 추가(기존엔 "NoRotate" 단어만 검사) |
| F6 | gap_hunter | MEDIUM | 반영 | 프로덕션 진입점 `annotate_case` 테스트에 FreeText NoRotate 어설션(신규 (n)) 추가. AC22/D18 신설 |
| F7 | gap_hunter | MEDIUM | 반영 | 패딩 경계값 테스트 (i)를 회전 4종 parametrize로 확장 — D6의 "모든 회전×패딩" 주장이 실제로 참이 되도록 |
| LOW-1~3 | 양쪽 | LOW | 반영(실측치로 정정) | 줄 번호 인용 3곳 재확인(1곳은 원본이 이미 정확했음), `_place_label` docstring 일반화 1문장, Section 1.4에 554~559줄 예외 명시, 부록 A 테스트 라벨 (c)/(d) 헤딩 분리, 완료 보고 산출물 규격 추가 |

**재설계 없음 확인**: 두 레인 모두 핵심 알고리즘(`label_rect_for_norotate`/`_aligned_bbox_to_display_box`, `r` vs `a` 구분)의 리터럴 수치를 독립적으로 손으로 재계산해 정확함을 확인했고, Square/Popup 무변경 범위(`_build_square`/`_popup_rect`/`_build_popup`/568~581줄)가 성립 가능함을 코드 추적으로 확인했다. 이번 개정은 **테스트 커버리지 보강**(7건)과 문서·검증 절차 보강(3건)에 국한되며, Step 3/Step 7의 핵심 코드 블록은 원본과 동일하다.

---

## 1. Requirements Summary

### 1.1 해결할 문제

`/Rotate=90/180/270`인 페이지에 붙인 FreeText 검토 라벨을 사용자가 Adobe Acrobat에서 **리사이즈**하면, Acrobat이 우리가 심어둔 `/AP`를 버리고 자체 리치텍스트 레이아웃으로 재생성한다. 현재 라벨의 raw `/Rect`는 회전 때문에 폭↔높이가 뒤바뀐 **좁고 긴 세로 사각형**(예: 폭 35.9pt)이므로, Acrobat이 그 좁은 폭에 맞춰 줄바꿈해 글자를 세로로 쌓고, 여기에 페이지 `/Rotate` 표시 변환이 겹쳐 **라벨이 세로로 뒤집혀 보인다**. 한 번 재생성되면 되돌아가지 않는다.

### 1.2 근본 원인 (실측 확정 — 재조사 금지)

`_label_ap()`가 회전 페이지에서 라벨을 가로로 보이게 하려고 `/AP`에 회전 보정 `/Matrix`(`_AP_MATRIX`)를 심는 트릭에 의존한다. 이 트릭은 **뷰어가 우리 `/AP`를 그대로 쓸 때만** 성립하며, Acrobat의 AP 재생성(편집뿐 아니라 **리사이즈**로도 발동)을 견디지 못한다. Square 주석은 방향성 콘텐츠가 없어 `/Matrix` 트릭 자체가 없고, 실측상 Acrobat이 Square의 AP를 재생성하지도 않으므로 **문제는 FreeText에만 국한**된다.

### 1.3 해결 방향 (사용자 승인 완료)

완화(라벨 폭 넓히기)가 아니라 근본 수정:

1. FreeText `/F`에 **NoRotate 비트(16)** 를 세운다 (`4 | 16 = 20`).
2. `/AP` `/N` Form XObject에서 **`/Matrix`를 모든 T에 대해 완전히 제거**한다. `/BBox`는 지금과 동일한 자연스러운 `(0, 0, chip_w, chip_h)`.
3. `/Rect`를 **회전-독립적 앵커 방식**으로 계산한다: 칩의 좌상단 한 점만 좌표 변환하고, 거기서 자연스러운(회전 안 된) `chip_w` x `chip_h`만큼 오른쪽+아래로 펼친다. 결과적으로 `/Rect`는 **항상 가로로 넓은 자연스러운 모양**이 되어, Acrobat이 재생성해도 한 줄 가로 레이아웃이 나오고 NoRotate가 그것을 뷰어 기준 수평으로 고정한다.

### 1.4 범위 밖 (scope creep 금지 — 반드시 준수)

- Square / Popup 주석은 **일절 수정 금지**: `_build_square`, `_popup_rect`, `_build_popup`, 그리고 `write_annotated_pdf` 안의 Square/Popup 생성 블록(현행 568~581줄)은 diff 0줄이어야 한다.
- **다만 554~559줄은 정당한 수정 대상이다.** 이 구간은 Square/Popup/FreeText가 **공유**하는 페이지 단위 값(`r`, `a`, `t`, 그리고 `wa,ha` → `ws,hs`)을 계산하는 곳으로, Step 7-2가 여기서 `a`를 `% 360` 정규화하고 `wa,ha`를 `ws,hs`로 대체한다. 이는 위의 "Square/Popup 일절 수정 금지"(=AC18/D11이 지정하는 568~581줄 및 세 함수 본문) 규칙 **위반이 아니다**. Square 경로가 소비하는 값(`t`)의 정의는 바뀌지 않는다.
- 리뷰 로직, `<case>_annotations.json` 계약, 색상 매핑, PASS 제외 규칙, 네이티브 주석 아키텍처(Square+Popup+FreeText) 자체는 변경하지 않는다.
- testbed `ref/` 폴더의 기존 발급 PDF 2개를 포함해 **이미 발급된 annotated PDF는 재생성하지 않는다**. 리포지토리에 PDF를 커밋하지 않는다.
- 과거 기각된 "CID 폰트 임베딩(벡터 글리프)" 방식은 **재제안 금지**.
- `docs/plan_history.md`, `docs/revision_history.md`는 실행 에이전트가 직접 수정하지 않는다(오케스트레이터 담당).

### 1.5 계획 수립 중 추가로 실측 확정한 사실 (실행 에이전트는 그대로 신뢰할 것)

계획 단계에서 pypdfium2로 6개 `(R, A)` 조합을 렌더링해 픽셀 단위로 측정했다(`scratchpad/spike_norotate_A_nonzero.py`). 결과:

| R (page `/Rotate`) | A (align-inputs 적용 회전) | T=(R+A)%360 | t-앵커 `/Rect` | r-앵커 `/Rect` | 렌더 결과 |
|---|---|---|---|---|---|
| 90 | 0 | 90 | (82, 61, 142, 75) | (82, 61, 142, 75) | **완전 동일** |
| 180 | 0 | 180 | (300, 43, 360, 57) | (300, 43, 360, 57) | **완전 동일** |
| 270 | 0 | 270 | (318, 211, 378, 225) | (318, 211, 378, 225) | **완전 동일** |
| 0 | 90 | 90 | (82, 61, 142, 75) | (100, 154, 160, 168) | t-앵커는 칩이 박스 **아래쪽으로 186px 이탈** |
| 90 | 270 | 0 | (100, 229, 160, 243) | (82, 136, 142, 150) | t-앵커는 칩이 **페이지 오른쪽 끝(598/600px)에서 잘림** |
| 0 | 180 | 180 | (300, 43, 360, 57) | (200, 154, 260, 168) | t-앵커는 칩이 **대각선 반대편으로 300px 이탈 — 실측상 가장 나쁜 편차** |

핵심 결론 2가지:

- **A = 0일 때 t-앵커와 r-앵커는 수치적으로 완전히 동일하다.** 즉 사용자가 이미 검증한 T=90/180/270 수치(`matrix_bbox == norotate_bbox` 픽셀 일치)는 r-앵커에서도 한 글자도 바뀌지 않는다.
- **A ≠ 0일 때는 t-앵커가 라벨을 엉뚱한 곳에 놓는다.** NoRotate는 페이지 자신의 `/Rotate`(=R)에 대해서만 작동하므로, 라벨은 항상 "표시 공간(display space, raw를 R만큼 회전한 공간)" 기준으로 수평하게 그려진다. 따라서 라벨 배치도 표시 공간에서 계산해야 한다. `A ≠ 0`은 실제 운영 케이스다(테스트 id `R0-A90-T90-PU2601233`, `R90-A270-T0-PU2601565`).

→ 따라서 본 계획은 앵커 변환 회전각으로 `t` 대신 **페이지 자신의 `/Rotate`인 `r`** 을 쓰고, `_place_label`도 aligned 공간 대신 **표시 공간**에서 돌린다. `A = 0`이면 두 공간이 같으므로 사용자 검증 수치가 그대로 보존된다.

> **개정판 주석 (F1)**: 위 표에서 **가장 편차가 큰 `(R=0, A=180)` 조합이 초판 테스트 스위트에서 빠져 있었다.** 개정판은 이 조합을 테스트 (e)의 파라미터와 테스트 (d)의 리터럴 양쪽에 명시적으로 추가한다. 이 파라미터를 다시 제거하지 말 것(부록 B-11).

부수 실측(리스크 근거용):
- `pypdf.generic.RectangleObject`는 좌표를 **정규화하지 않는다**(`RectangleObject((160,225,100,211))` → `[160,225,100,211]` 그대로). 따라서 `(llx, lly, urx, ury)` 순서를 생성 시점에 올바르게 만들어야 한다.
- NoRotate 플래그를 **무시하는 뷰어**를 가정해 `/F=4`로 새 `/Rect`를 렌더링해보면, 칩은 26x118px(세로)로 페이지와 함께 회전되지만 **여전히 한 줄**이다. 즉 최악의 경우에도 "본문과 같이 옆으로 누움"이지 "글자가 세로로 쌓임"이 아니다 — graceful degradation 확인.
- `pypdf.annotations.Popup.__init__`는 `/F`를 설정하지 않는다(소스 확인). 따라서 Popup의 NoRotate 비트 검사는 `int(pop.get("/F", 0)) & 16 == 0` 형태여야 한다.

### 1.6 개정판에서 추가로 실측 확정한 사실 (테스트 설계 근거)

개정 단계에서 리포지토리를 **읽기 전용으로** 로드해 실제 함수(`_render_label_image`, `_chip_size_pt`, `_place_label`, `_aligned_to_user_frac`, `_aligned_page_size_pt`, `_rects_overlap`)로 새 테스트를 시뮬레이션했다. 실행 에이전트는 아래 값을 그대로 신뢰해도 된다.

- 상수 실측: `LABEL_GAP_PT = 4.0`, `LABEL_BOX_PAD = 2.0`, `LABEL_FONT_PT = 10.0`, `DEFAULT_FONT = C:\Windows\Fonts\malgun.ttf`(존재 확인).
- 칩 크기 실측(`_chip_size_pt`, 패딩 제외): `"FAIL: 가"` → (34.75, 9.5), `"주의: 나"` → (37.75, 9.5), `"N/A: 다"` → (34.0, 9.5), `"FAIL: 배치"` → (44.75, 9.5), `"주의: 한글 라벨 렌더 확인"` → (116.25, 9.5), `"가"*49 + "…"` → (497.5, 9.5). **칩 높이는 폰트 크기에만 의존해 항상 9.5pt**이므로, 라벨 문자열을 바꿔도 세로 마진 계산은 흔들리지 않는다.
- `_aligned_bbox_to_display_box((0.25,0.25,0.5,0.5), 400, 300, 180)` = **(200, 150, 300, 225)** — 테스트 (d)에 추가할 리터럴. (a=180은 페이지 폭·높이를 바꾸지 않으므로 `ws,hs`도 (400,300).)
- 테스트 (e)의 **7조합 전부**를 실제 함수로 시뮬레이션한 결과: 모든 조합에서 `chip_w > chip_h`, `overlap == False`, `gap == 2.00pt`(허용치 `LABEL_GAP_PT + 2*LABEL_BOX_PAD = 8.0`). 신규 `R0-A180-T180`도 통과(box=(200,150,300,225), 복원 chip=(198,134.5,246.75,148), `/Rect`=(198,152,246.75,165.5)).
- 테스트 (m)의 3주석 배치를 시뮬레이션한 결과: 라벨1은 above, 라벨2는 above 충돌 → **below**, 라벨3은 **right** 또는 다른 슬롯으로 밀려나 `placed` 겹침 회피 분기가 실제로 실행된다. chip-chip 겹침 0건, 자기 Square 겹침 0건. 자기 박스와의 세로 마진은 `LABEL_GAP_PT − LABEL_BOX_PAD = 2.0pt`로 **구조적으로 결정**되며 라벨 길이에 무관하다.
- **`_place_label`은 "다른 라벨"과 "페이지 경계"만 회피하고 "다른 주석의 Square"는 회피하지 않는다**(현행 함수의 기존 성질, 이번 변경과 무관). 따라서 테스트 (m)은 *자기 자신의* Square와의 비겹침만 어설션한다 — 타 Square와의 겹침을 어설션하면 리팩터링과 무관한 이유로 깨진다.

---

## 2. Acceptance Criteria

모든 항목은 "변경 전 → 변경 후" 대비로 기술한다. 테스트 페이지는 400x300pt, CropBox 없음(`mx0=my0=0, wp=400, hp=300`) 기준.

| ID | 시나리오 | 변경 전 (현행) | 변경 후 (요구) | 검증 |
|---|---|---|---|---|
| **AC1** | `/Rotate=90` 페이지의 FreeText `/AP /N` | `/Matrix = [0,1,-1,0,0,0]` 존재 | `/Matrix` **키 자체가 없음** | 테스트 (a) |
| **AC2** | `/Rotate=0/180/270` 페이지의 FreeText `/AP /N` | 0→없음, 180/270→`/Matrix` 존재 | **전부 `/Matrix` 없음** | 테스트 (a) |
| **AC3** | FreeText `/F` | `4` | **`20`** (=`4 \| 16`, Print + NoRotate) | 테스트 (a), (b) |
| **AC4** | Square `/F` | `4` | **`4` 그대로 (불변)** | 테스트 (a), 기존 `test_square_and_freetext_fields` |
| **AC5** | Popup `/F` | 미설정 | **미설정 그대로**, NoRotate 비트 없음 | 테스트 (a) |
| **AC6** | FreeText `/Rect` 모양 | 회전 시 폭↔높이 뒤바뀜 (예: 14 x 60) | **항상 `/AP /BBox`와 동일한 폭·높이** (예: 60 x 14), 그리고 `llx<urx`, `lly<ury` | 테스트 (a), (i) |
| **AC7** | `label_rect_for_norotate((0.25,0.25),(60,14),0,0,400,300,r)` | (함수 없음) | r=0→`(100,211,160,225)`, r=90→`(100,61,160,75)`, r=180→`(300,61,360,75)`, r=270→`(300,211,360,225)` | 테스트 (c) |
| **AC8** | 위 함수 + CropBox 오프셋 (케이스 46 p1: `mx0=3.96001, my0=2.88, wp=595.79999, hp=842.4, r=0`) | (함수 없음) | `(152.91, 620.68, 212.91, 634.68)` | 테스트 (c) |
| **AC9** | 위 함수에 `r=45` | (함수 없음) | `ValueError` (기존 `_aligned_to_user_frac` 동작 재사용, 새 방어코드 없음) | 테스트 (c) |
| **AC10** | 라벨과 Square의 표시 공간 인접성, `(R,A)` **7조합** `(0,0) (90,0) (180,0) (270,0) (0,90) (90,270) (0,180)` | A≠0에서 최대 300px 이탈/페이지 끝 잘림 | 칩이 박스와 **겹치지 않고**, 최근접 간격 ≤ `LABEL_GAP_PT + 2*LABEL_BOX_PAD` | 테스트 (e) |
| **AC11** | pdfium **실제 렌더 픽셀**에서 라벨 칩 형태, `(R,A) ∈ {(0,0),(90,0),(180,0),(270,0),(0,90),(90,270)}` | Matrix 경로로 가로 (A=0만 검증됨) | **가로 유지** (dark-pixel bbox의 폭 > 높이) — `a≠0` 운영 케이스 2종 포함 | 테스트 (f) |
| **AC12** | `annotate_pdf.py` 소스 내 `_AP_MATRIX` 심볼 | 존재 (345, 383, 384줄) | **0건** | 테스트 (g) + grep |
| **AC13** | `write_annotated_pdf(rotations={1: 450})` | `t=(r+450)%360` 정상 동작 | `{1: 90}`과 **동일한 `/Rect`** 산출 | 테스트 (j) |
| **AC14** | `write_annotated_pdf(rotations={1: 45})` | `ValueError` | **`ValueError` 그대로** | 테스트 (k) |
| **AC15** | `LABEL_BOX_PAD = 0.0` monkeypatch, **`/Rotate ∈ {0,90,180,270}` 전부** | (미검증) | `/Rect` 폭·높이 ≡ `/AP /BBox` 폭·높이 유지, `/F==20` | 테스트 (i) |
| **AC16** | 50자 한글 라벨 + `/Rotate=90` | (미검증) | 칩 좌상단이 표시 공간에서 `>= -LABEL_BOX_PAD`로 클램프됨, `/Rect`≡`/BBox` 유지 | 테스트 (l) |
| **AC17** | `SKILL.md` 캐비어트 | "If a user *edits* the label text..." (부정확) | **리사이즈도 트리거함을 명시**(그 사실 자체를 테스트가 고정) + `NoRotate` 단어 포함, `burn-in`/`--dpi` 문구 여전히 없음 | 테스트 (h) |
| **AC18** | Square/Popup 코드 diff | — | `_build_square`, `_popup_rect`, `_build_popup` 및 `write_annotated_pdf`의 Square/Popup 생성 블록(568~581줄) **변경 0줄**. (554~559줄 공유 계산부는 예외 — 1.4 참조) | `git diff` 육안 + 기존 T3/T3c 테스트 통과 |
| **AC19** | 전체 테스트 | 39 passed (annotate 파일) | annotate 파일 및 `tests/` 전체 **0 failed / 0 error** | Verification 1~3 |
| **AC20** | (자동 검증 불가) Acrobat 리사이즈 후 라벨 방향, **`/Rotate=90/180/270` 각각** | 세로로 뒤집힘 | **가로 유지** | 사용자 수동 확인 (Section 6.4, V8이 회전별 개별 PDF 3개 제공) |
| **AC21** | **[신규]** 같은 페이지에 주석 3개 + 회전(`R=90` 또는 `A=90`) | (미검증 — 기존 다중 주석 테스트는 `rotate=0`이라 표시공간 분기를 태우지 못함) | 라벨 칩끼리 **서로 겹치지 않고**, 각 칩이 **자기 Square와도 겹치지 않음** | 테스트 (m) |
| **AC22** | **[신규]** 프로덕션 진입점 `annotate_case`(→ CLI `annotate --case`), `applied={"1":90}` | Square `/Rect`만 검증 | FreeText도 `/F==20`, `/Matrix` 부재, `/Rect`≡`/BBox` | 테스트 (n) |

---

## 3. Implementation Steps (구현 지침)

### Step 0. 착수 전 베이스라인 확보

```powershell
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer\skills\cert-review"
python -m pytest tests/ -q          # 전체 baseline 카운트를 기록해 둘 것
python -m pytest tests/test_annotate_pdf.py -q   # 기대: 39 passed
```

그리고 `_AP_MATRIX`가 이 파일 밖에서 쓰이지 않는지 반드시 확인(계획 단계 grep 결과: 코드 참조는 `annotate_pdf.py` 345/383/384줄뿐, 나머지는 `docs/plans/*.md`의 과거 기록과 테스트뿐 — 과거 plan 문서는 **수정하지 않는다**):

```powershell
Set-Location "C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer"
git grep -n "_AP_MATRIX"
```

---

### Step 1. `annotate_pdf.py` — 모듈 docstring 갱신

**1-1. 46~48줄 인용 블록 교체** (46줄은 문맥용으로 그대로 두고, 실제 교체 대상 문장은 **47~48줄**이다 — 텍스트 그대로 찾아 바꾸므로 줄 번호가 아니라 문자열로 매칭할 것).

변경 전:
```
``PdfReader``) and ``A`` is the align-inputs applied clockwise rotation — plus
the page ``/CropBox`` origin offset. A rotated page's label appearance carries an
``/AP`` ``/Matrix`` so its glyphs stay content-horizontal (never aspect-distorted).
```

변경 후:
```
``PdfReader``) and ``A`` is the align-inputs applied clockwise rotation — plus
the page ``/CropBox`` origin offset. The FreeText label is the one exception: it
is *anchored*, not mapped. It carries the NoRotate flag (``/F`` bit 5), which pins
the UPPER-LEFT corner of its ``/Rect`` to a fixed page location and then draws the
chip unrotated from there, so the label is placed by transforming that single
corner out of the *display* space (the page turned by its own ``/Rotate``) — the
space the reader actually sees. Its ``/Rect`` is therefore always the chip's
natural, never-swapped width x height.
```

**1-2. 57~59줄 Note 교체** (이 캐비어트가 부정확함이 실측으로 밝혀진 부분).

변경 전:
```
Note: if a viewer user *edits* a FreeText label's text, that viewer regenerates
its ``/AP`` from ``/DA`` (viewer fonts; pdfium-family viewers then stop showing
it) — moving/deleting is unaffected.
```

변경 후:
```
Note: Adobe Acrobat throws a ``/FreeText``'s supplied ``/AP`` away and re-lays the
label out with its own fonts not only when the text is *edited* but also when the
annotation is merely **resized** (measured on a real ``/Rotate=90`` cert). The
label therefore never relies on an ``/AP`` ``/Matrix``: whatever a viewer
regenerates is laid out inside a naturally wide ``/Rect`` (one line, no vertical
stacking) and NoRotate keeps it viewer-horizontal. Moving/deleting is unaffected.
```

---

### Step 2. `annotate_pdf.py` — `/F` 플래그 상수 추가

106줄 `POPUP_W_PT, POPUP_H_PT = 180.0, 120.0  # Acrobat-conventional UI-hint size` **바로 다음 줄**에 추가:

```python
# FreeText /F flags (PDF 32000-1 Table 165): 4 = Print, 16 = NoRotate. NoRotate
# pins the label's upper-left /Rect corner to the page but leaves its appearance
# unrotated, so the chip stays viewer-horizontal on a /Rotate-ed page even after
# Acrobat discards our /AP and regenerates its own. Square/Popup keep plain Print
# (they have no directional content, so page rotation is exactly what they want).
FREETEXT_FLAGS = 4 | 16
```

`_build_square`의 `NumberObject(4)`(416줄)는 **절대 건드리지 않는다** (AC18).

---

### Step 3. `annotate_pdf.py` — 좌표 헬퍼 2개 추가

`_aligned_page_size_pt`(294~298줄) **바로 다음**, 그리고 `# ---- Label appearance stream ----` 구분선(**301~303줄** — 실측 확인함) **앞**에 삽입한다.

```python
def _aligned_bbox_to_display_box(
    bbox: tuple[float, float, float, float], ws: float, hs: float, a: int
) -> tuple[float, float, float, float]:
    """Aligned fractional bbox -> display-space box in pt (top-left origin, y-down).

    ``a`` is the align-inputs applied rotation, i.e. the turn that takes the
    *display* (what a viewer actually shows) to the *aligned* space the reviewers
    annotated in; undoing it puts the cell back where the reader sees it. The
    label is placed here, not in aligned space, because a NoRotate annotation is
    always drawn display-horizontal — "above / below / right of the box" has to
    mean what the reader sees. When ``a == 0`` the two spaces coincide and this is
    a plain scale, so the unrotated and page-rotation-only cases are unchanged.

    Both corners are transformed and min/max-normalised — legitimate for a *box*,
    unlike the NoRotate anchor below, which must keep one specific corner.
    """
    pts = [
        _aligned_to_user_frac(bbox[0], bbox[1], a),
        _aligned_to_user_frac(bbox[2], bbox[3], a),
    ]
    xs = sorted(p[0] for p in pts)
    ys = sorted(p[1] for p in pts)
    return (xs[0] * ws, ys[0] * hs, xs[1] * ws, ys[1] * hs)


def label_rect_for_norotate(
    chip_topleft_frac: tuple[float, float],
    chip_size_pt: tuple[float, float],
    mx0: float,
    my0: float,
    wp: float,
    hp: float,
    r: int,
) -> tuple[float, float, float, float]:
    """Display-space chip top-left -> user-space /Rect for a NoRotate label.

    A NoRotate annotation keeps the UPPER-LEFT corner of its /Rect glued to a
    fixed page location and then draws its never-rotated width x height down and
    to the right of it, so exactly one corner is transformed and the /Rect keeps
    the chip's natural shape (which is also what makes an Acrobat-regenerated
    appearance lay the label out on one line).

    Deliberately NOT ``aligned_bbox_to_user_rect``: normalising two corners with
    min/max picks a *different* corner as the geometric minimum on 90/270, so the
    label would unfold from the wrong end of the box.

    ``r`` is the page's own ``/Rotate`` — the turn the viewer applies — not the
    review-space ``T``; NoRotate resists page rotation, nothing else. Raises via
    ``_aligned_to_user_frac`` on any r outside {0, 90, 180, 270}.
    """
    ax, ay = _aligned_to_user_frac(chip_topleft_frac[0], chip_topleft_frac[1], r)
    chip_w, chip_h = chip_size_pt
    llx = mx0 + ax * wp
    ury = my0 + hp - ay * hp          # PDF is y-up; ay is a top-down fraction
    return (llx, ury - chip_h, llx + chip_w, ury)
```

주의사항 (실행 에이전트가 지켜야 할 함정):

- `label_rect_for_norotate`가 돌려주는 튜플은 **항상** `llx < urx`, `lly < ury`다(`chip_w`, `chip_h` > 0). `pypdf.generic.RectangleObject`는 정규화를 하지 않으므로(실측) 이 순서를 절대 바꾸지 말 것. `min`/`max` 정규화를 추가하지 말 것 — 90/270에서 잘못된 코너가 앵커가 된다.
- 반환된 `/Rect`가 CropBox 밖으로 나갈 수 있는데 **정상이다**. NoRotate 주석에서 `/Rect`의 비앵커 코너는 실제 그려지는 위치와 무관하다. **CropBox 클램프를 넣지 말 것.**
- `__all__`(697~702줄)은 **수정하지 않는다**. `aligned_bbox_to_user_rect`도 public 이름이지만 `__all__`에 없다 — 동일 관례를 따른다. 테스트는 `A.label_rect_for_norotate`로 접근한다.

---

### Step 4. `annotate_pdf.py` — `_AP_MATRIX` 제거

342~349줄(주석 3줄 + dict 5줄)을 **통째로 삭제**한다.

```python
# Counter-clockwise T rotation that returns aligned-space text to user space.
# (T=0 omits /Matrix.) The viewer maps the transformed /BBox onto /Rect, so no
# translation term is needed — without this, 90/270 aspect-distorts the glyphs.
_AP_MATRIX = {
    90: [0, 1, -1, 0, 0, 0],
    180: [-1, 0, 0, -1, 0, 0],
    270: [0, -1, 1, 0, 0, 0],
}
```

---

### Step 5. `annotate_pdf.py` — `_label_ap` 시그니처에서 `t` 제거

**인터페이스 변경**: `_label_ap(writer, img, verdict_rgb255, t)` → `_label_ap(writer, img, verdict_rgb255)`.
(사용하지 않는 매개변수를 남기지 않는다 — karpathy 가이드라인.)

352~357줄 시그니처:
```python
def _label_ap(
    writer: PdfWriter,
    img: Image.Image,
    verdict_rgb255: tuple[int, int, int],
):
```

358~362줄 docstring에 한 문단 추가:
```python
    """Build the FreeText /AP /N Form XObject (vector chip + glyph image); return ref.

    ``img`` is the pre-rendered label raster from ``_render_label_image`` — the
    same object whose size drove the /Rect placement, so /BBox ≡ chip geometry.

    No ``/Matrix``, ever: the label's /Rect is already the chip's natural,
    unrotated shape and the annotation carries NoRotate, so the identity mapping
    of /BBox onto /Rect is exactly right on every page rotation. A rotation
    /Matrix here would also be silently dropped the moment Acrobat regenerates
    the appearance (see the module docstring).
    """
```

383~384줄 삭제:
```python
    if t in _AP_MATRIX:
        form[NameObject("/Matrix")] = ArrayObject([FloatObject(v) for v in _AP_MATRIX[t]])
```

---

### Step 6. `annotate_pdf.py` — `_build_label_annot` 수정

**인터페이스 변경**: `_build_label_annot(writer, rect_pt, verdict, label, img, t, nm, stamp)` → `_build_label_annot(writer, rect_pt, verdict, label, img, nm, stamp)` (`t` 제거).

- 464~473줄 시그니처에서 `t: int,` 줄 삭제.
- docstring(474~480줄) 끝에 한 줄 추가:
  ```
    /F carries NoRotate on top of Print (FREETEXT_FLAGS) so the chip stays
    viewer-horizontal on a rotated page; ``rect_pt`` is therefore the chip's
    natural width x height anchored at its upper-left corner, never a rotated box.
  ```
- 489줄: `ft[NameObject("/F")] = NumberObject(4)` → `ft[NameObject("/F")] = NumberObject(FREETEXT_FLAGS)`
- 495줄: `ap[NameObject("/N")] = _label_ap(writer, img, rgb, t)` → `ap[NameObject("/N")] = _label_ap(writer, img, rgb)`

---

### Step 7. `annotate_pdf.py` — `write_annotated_pdf` 라벨 배치 로직 교체

**7-1. docstring(522~532줄)에 한 문장 추가** — 마지막 문장 ``Returns ``(out_path, boxes_drawn, page_count, oob_count)``.`` 바로 앞에:

```
    The Square's /Rect is mapped from the aligned (review) space via ``T``; the
    FreeText label is instead anchored in the *display* space (the page turned by
    its own ``/Rotate``) because it carries NoRotate and is therefore always drawn
    viewer-horizontal. The two coincide whenever the applied rotation is 0.
```

**7-2. 557~559줄 교체.**

변경 전:
```python
        a = rotations.get(p, 0) if rotations else 0
        t = (r + a) % 360
        wa, ha = _aligned_page_size_pt(wp, hp, t)
```

변경 후:
```python
        a = (rotations.get(p, 0) if rotations else 0) % 360
        t = (r + a) % 360
        ws, hs = _aligned_page_size_pt(wp, hp, r)  # display space (what a viewer shows)
```

- `% 360` 정규화 이유: 기존에는 `a`가 `(r + a) % 360` 안에서만 쓰여 `a=450` 같은 값도 통했다. 이제 `a`가 `_aligned_bbox_to_display_box`에 직접 전달되므로, 정규화하지 않으면 예전에 통하던 입력이 새로 `ValueError`가 되는 회귀가 생긴다. 파이썬 `%`는 음수도 올바르게 감싼다(`-90 % 360 == 270`).
- `wa, ha`는 라벨 경로에서만 쓰였으므로(586/587/595줄) 완전히 대체된다. Square 경로(568줄)는 `t`만 쓰므로 그대로.
- `a=45` 같은 진짜 잘못된 값은 **568줄 Square 경로의 `aligned_bbox_to_user_rect(..., t)` 가 먼저 `ValueError`를 던진다**(t가 유효하지 않게 되므로). 즉 **새 방어 코드가 필요 없다** — 기존 예외 동작을 그대로 재사용한다.

**7-3. 583~597줄 교체.**

변경 전:
```python
            # Label: render once; img.size drives placement AND the /AP /BBox.
            img = _render_label_image(ann.label, font, rgb)
            tw_pt, th_pt = _chip_size_pt(img)
            box_al = (ann.bbox[0] * wa, ann.bbox[1] * ha, ann.bbox[2] * wa, ann.bbox[3] * ha)
            lx, ly = _place_label(box_al, tw_pt, th_pt, wa, ha, placed, pad=LABEL_GAP_PT)
            chip = (
                lx - LABEL_BOX_PAD,
                ly - LABEL_BOX_PAD,
                lx + tw_pt + LABEL_BOX_PAD,
                ly + th_pt + LABEL_BOX_PAD,
            )
            placed.append(chip)
            chip_frac = (chip[0] / wa, chip[1] / ha, chip[2] / wa, chip[3] / ha)
            label_rect = aligned_bbox_to_user_rect(chip_frac, mx0, my0, wp, hp, t)
            ft = _build_label_annot(writer, label_rect, ann.verdict, ann.label, img, t, nm, stamp)
```

변경 후:
```python
            # Label: render once; img.size drives placement AND the /AP /BBox.
            img = _render_label_image(ann.label, font, rgb)
            tw_pt, th_pt = _chip_size_pt(img)
            # Placed in DISPLAY space: a NoRotate label is drawn viewer-horizontal,
            # so above/below/right must mean what the reader sees. Identical to the
            # aligned space (and to the pre-NoRotate placement) whenever a == 0.
            box_disp = _aligned_bbox_to_display_box(ann.bbox, ws, hs, a)
            lx, ly = _place_label(box_disp, tw_pt, th_pt, ws, hs, placed, pad=LABEL_GAP_PT)
            chip = (
                lx - LABEL_BOX_PAD,
                ly - LABEL_BOX_PAD,
                lx + tw_pt + LABEL_BOX_PAD,
                ly + th_pt + LABEL_BOX_PAD,
            )
            placed.append(chip)
            # Only the chip's top-left is transformed (the NoRotate anchor); its
            # size is the /AP /BBox size, so /Rect and /BBox can never diverge.
            label_rect = label_rect_for_norotate(
                (chip[0] / ws, chip[1] / hs),
                (chip[2] - chip[0], chip[3] - chip[1]),
                mx0, my0, wp, hp, r,
            )
            ft = _build_label_annot(writer, label_rect, ann.verdict, ann.label, img, nm, stamp)
```

**불변식(반드시 유지)**: `chip[2]-chip[0] == tw_pt + 2*LABEL_BOX_PAD == _label_ap`의 `/BBox` 폭 `w`, `chip[3]-chip[1] == th_pt + 2*LABEL_BOX_PAD == /BBox` 높이 `h`. 이 대응이 깨지면 뷰어가 `/BBox`를 `/Rect`에 맞춰 **스케일**해 글리프가 왜곡된다. `chip`에서 직접 크기를 뽑아 전달하는 위 코드가 이 불변식을 구조적으로 보장한다. `tw_pt`/`th_pt`에 `2*LABEL_BOX_PAD`를 다시 더하는 식으로 중복 계산하지 말 것.

**7-4. `_place_label` docstring 일반화 (LOW-4, 한 줄 수정).**

`_place_label` 함수 **본문 로직은 한 줄도 고치지 않되**, 177~178줄 docstring의 마지막 문장이 리팩터링 후 부정확해진다(이제 호출자가 표시 공간 좌표를 넘긴다). 좌표계-무관하게 일반화한다.

변경 전:
```
    Tries above / below / right of the box, then stacks downward; always clamps
    inside the page. The box itself is never moved (only the label). Works in the
    aligned space (points now, pixels in the burn-in era) — pure geometry.
```

변경 후:
```
    Tries above / below / right of the box, then stacks downward; always clamps
    inside the page. The box itself is never moved (only the label). Pure geometry
    in whatever single space the caller passes (display space for the NoRotate
    label; points now, pixels in the burn-in era) — box, chip and page extent must
    simply all be in that same space.
```

**엣지 케이스 처리 방침:**

| 상황 | 처리 |
|---|---|
| CropBox ≠ MediaBox (케이스 46/62류) | 이미 `mx0/my0/wp/hp`가 CropBox 기준. `label_rect_for_norotate`가 동일 오프셋을 쓰므로 추가 작업 없음. AC8이 리터럴로 고정. |
| `_place_label` 페이지 경계 클램프 | 클램프는 `tw`/`th`(패딩 제외) 기준이라 칩이 최대 `LABEL_BOX_PAD`(2pt)만큼 페이지 밖으로 나갈 수 있다 — 현행과 동일. `chip[0]/ws`가 살짝 음수가 되어도 `_aligned_to_user_frac`은 순수 산술이라 문제없다. **부호 반전은 일어나지 않는다**: 앵커 변환은 좌상단 한 점의 아핀 변환이고, 확장 방향은 언제나 표시 공간 오른쪽+아래로 고정이다. |
| 라벨이 페이지보다 넓음 | `_place_label`이 `max(0, min(cx, page_w - tw))`로 `x=0` 클램프. 칩이 오른쪽으로 넘쳐 렌더 시 잘림 — 현행과 동일, 변경 없음. |
| `LABEL_BOX_PAD = 0` | `chip == (lx, ly, lx+tw, ly+th)`, `/BBox == (0,0,tw,th)`. 불변식 그대로 성립. |
| `r`이 `VALID_ROTATIONS` 밖 | 555~556줄이 이미 `r = 0`으로 클램프. 새 코드 불필요. |
| `t`가 유효하지 않음 (`a=45` 등) | 568줄 Square 경로가 먼저 `ValueError`. 새 코드 불필요. |
| 같은 페이지 다중 주석 | `placed` 리스트가 페이지당 한 번 계산된 `ws, hs, a`를 공유한다. 모든 라벨이 **같은 표시 공간**에서 계산되므로 겹침 회피가 그대로 성립 — 새 코드 불필요, 회귀 가드는 테스트 (m). |
| PASS 등 필터링 | 565~567줄 그대로. 변경 없음. |
| dedupe 키 | 569~572줄 그대로(Square rect 기준). 변경 없음. |

---

### Step 8. `test_annotate_pdf.py` — 테스트 갱신/추가

**8-0. 공용 헬퍼 추가.** `_freetext`(124~125줄) 다음에:

```python
# raw fractional -> display fractional; the exact inverse of
# A._aligned_to_user_frac (pinned by test_aligned_to_user_frac_all_rotations).
_FWD_FRAC = {
    0: lambda a, b: (a, b),
    90: lambda a, b: (1 - b, a),
    180: lambda a, b: (1 - a, 1 - b),
    270: lambda a, b: (b, 1 - a),
}


def _chip_geometry(ft) -> tuple[list[float], float, float]:
    """FreeText annot -> (/Rect as floats, chip width, chip height from /AP /BBox)."""
    rc = [float(v) for v in ft["/Rect"]]
    bx = [float(v) for v in ft["/AP"]["/N"].get_object()["/BBox"]]
    return rc, bx[2] - bx[0], bx[3] - bx[1]


def _display_chip(ft, rotate: int, wp: float = 400.0, hp: float = 300.0):
    """FreeText -> (chip box as the reader sees it, display page w, display page h).

    Forward-maps the NoRotate anchor (llx, ury) out of user space with _FWD_FRAC
    and unfolds the /AP /BBox size down-and-right from it — i.e. exactly what a
    NoRotate-implementing viewer does, so every assertion built on it is about
    what is actually seen rather than about raw coordinates.
    """
    rc, chip_w, chip_h = _chip_geometry(ft)
    ws, hs = A._aligned_page_size_pt(wp, hp, rotate)
    u, v = _FWD_FRAC[rotate](rc[0] / wp, (hp - rc[3]) / hp)
    return (u * ws, v * hs, u * ws + chip_w, v * hs + chip_h), ws, hs
```

> `_display_chip`은 초판에서 테스트 (e)/(l)에 인라인으로 있던 3줄을 **기계적으로 추출**한 것이다(수식 동일, 검증된 좌표 수학 변경 없음). 신규 테스트 (m)이 같은 변환을 세 번째로 쓰기 때문에 헬퍼로 뺀다.

기존 `test_aligned_to_user_frac_all_rotations`(234~250줄) 안의 로컬 `fwd` dict(242~247줄)는 `_FWD_FRAC`을 쓰도록 정리한다(중복 제거).

`_dark_pixel_count`(632~637줄) 다음에:

```python
def _dark_pixel_bbox(img, step=1):
    """Bounding box of the label chip: its grey border (80,80,80) and black glyphs
    are the only sub-250 sum pixels — the verdict fills (sum >= 646) and the test
    page's pure-blue stroke (sum 255) never qualify."""
    px = img.load()
    w, h = img.size
    xs, ys = [], []
    for y in range(0, h, step):
        for x in range(0, w, step):
            if sum(px[x, y][:3]) < 250:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None
```

---

**(a) 391~406줄 `test_label_ap_matrix_on_rotated_page`를 통째로 교체** (이름도 변경 — 더 이상 Matrix를 다루지 않음):

```python
@requires_font
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_label_ap_never_carries_matrix_and_sets_norotate(tmp_path: Path, rotate):
    """The /AP /Matrix trick is gone; NoRotate + a naturally shaped /Rect replace it.

    Acrobat throws a FreeText's /AP away on a mere resize, so the label must not
    depend on one: /F bit 5 (NoRotate) keeps it viewer-horizontal and /Rect keeps
    the chip's unrotated width x height on every page rotation.
    """
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 회전")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate)
    annots = _annots(PdfReader(str(out)).pages[0])
    ft = _freetext(annots)

    assert "/Matrix" not in ft["/AP"]["/N"].get_object()
    assert int(ft["/F"]) == 20                       # 4 Print | 16 NoRotate
    assert int(_square(annots)["/F"]) == 4           # Square untouched
    assert int(_by_subtype(annots, "/Popup")[0].get("/F", 0)) & 16 == 0

    rc, chip_w, chip_h = _chip_geometry(ft)
    assert rc[2] - rc[0] == pytest.approx(chip_w, abs=1e-6)
    assert rc[3] - rc[1] == pytest.approx(chip_h, abs=1e-6)
    assert rc[2] > rc[0] and rc[3] > rc[1]           # RectangleObject does not normalise
```

**(b) 374줄 수정** (`test_square_and_freetext_fields`):
```python
        assert int(ft["/F"]) == 4 | 16   # Print + NoRotate (label stays viewer-horizontal)
```

**(c) 순수 기하 테스트 추가** — `test_aligned_bbox_to_user_rect_literals`(253~271줄) 다음, `@requires_font` 블록 앞에 (폰트 불필요, 항상 실행):

```python
def test_label_rect_for_norotate_literals():
    """The NoRotate anchor: one corner transformed, natural size unfolded from it."""
    chip, size = (0.25, 0.25), (60.0, 14.0)
    f = A.label_rect_for_norotate
    assert list(f(chip, size, 0, 0, 400, 300, 0)) == pytest.approx([100, 211, 160, 225], abs=0.01)
    assert list(f(chip, size, 0, 0, 400, 300, 90)) == pytest.approx([100, 61, 160, 75], abs=0.01)
    assert list(f(chip, size, 0, 0, 400, 300, 180)) == pytest.approx([300, 61, 360, 75], abs=0.01)
    assert list(f(chip, size, 0, 0, 400, 300, 270)) == pytest.approx([300, 211, 360, 225], abs=0.01)
    # case 46 p1 CropBox offset (F13), r=0
    got = f(chip, size, 3.96001, 2.88, 599.76 - 3.96001, 845.28 - 2.88, 0)
    assert list(got) == pytest.approx([152.91, 620.68, 212.91, 634.68], abs=0.01)
    # the /Rect is always a valid, natural-shaped rectangle on every rotation
    for r in (0, 90, 180, 270):
        x0, y0, x1, y1 = f(chip, size, 0, 0, 400, 300, r)
        assert x1 - x0 == pytest.approx(60.0) and y1 - y0 == pytest.approx(14.0)
    with pytest.raises(ValueError):        # reuses _aligned_to_user_frac's guard
        f(chip, size, 0, 0, 400, 300, 45)
```

**(d) [헤딩 분리 — 부록 A 번호 정합] 두 번째 순수 기하 테스트** — (c) 바로 다음:

```python
def test_aligned_bbox_to_display_box_undoes_applied_rotation():
    """All four applied rotations, including the 180 that misplaces a chip by 300px."""
    bbox = (0.25, 0.25, 0.5, 0.5)
    g = A._aligned_bbox_to_display_box
    assert list(g(bbox, 400, 300, 0)) == pytest.approx([100, 75, 200, 150], abs=0.01)
    assert list(g(bbox, 400, 300, 90)) == pytest.approx([100, 150, 200, 225], abs=0.01)
    assert list(g(bbox, 400, 300, 180)) == pytest.approx([200, 150, 300, 225], abs=0.01)
    assert list(g(bbox, 300, 400, 270)) == pytest.approx([150, 100, 225, 200], abs=0.01)
```

> `a=180`은 페이지 폭·높이를 바꾸지 않으므로 `ws,hs`가 `(400,300)`인 것이 맞다(90/270만 swap). 리터럴 `[200, 150, 300, 225]`는 실제 모듈 함수로 실측 확인함.

**(e) 표시 공간 인접성 회귀 테스트 추가** — (a) 다음에. **7조합**:

```python
@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(0, None, id="R0-A0-T0"),
        pytest.param(90, None, id="R90-A0-T90"),
        pytest.param(180, None, id="R180-A0-T180"),
        pytest.param(270, None, id="R270-A0-T270"),
        pytest.param(0, {1: 90}, id="R0-A90-T90-PU2601233"),
        pytest.param(90, {1: 270}, id="R90-A270-T0-PU2601565"),
        pytest.param(0, {1: 180}, id="R0-A180-T180"),   # worst measured drift: 300px
    ],
)
def test_label_anchor_lands_beside_the_square_in_display_space(tmp_path, rotate, rotations):
    """The label must sit next to its box *as the viewer sees it*, for every (R, A).

    Anchoring with T instead of the page's own /Rotate silently misplaces the chip
    by up to a third of the page whenever the applied rotation is non-zero; the
    (0, 180) case is the measured worst one and must never leave this list.
    """
    bbox = (0.25, 0.25, 0.5, 0.5)
    ann = A.Annotation("c", 1, bbox, "FAIL", "FAIL: 배치")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate, rotations=rotations)
    ft = _freetext(_annots(PdfReader(str(out)).pages[0]))
    chip, ws, hs = _display_chip(ft, rotate)
    assert chip[2] - chip[0] > chip[3] - chip[1], "label chip must stay wider than tall"

    box = A._aligned_bbox_to_display_box(bbox, ws, hs, (rotations or {}).get(1, 0))
    assert not A._rects_overlap(chip, box), f"label overlaps its box: {chip} vs {box}"
    gap_x = max(box[0] - chip[2], chip[0] - box[2], 0.0)
    gap_y = max(box[1] - chip[3], chip[1] - box[3], 0.0)
    assert max(gap_x, gap_y) <= A.LABEL_GAP_PT + 2 * A.LABEL_BOX_PAD + 0.01
```

> 실측: 7조합 모두 `gap == 2.00pt`(허용치 8.0), 겹침 없음, `chip_w > chip_h`.

**(f) 648~659줄 `test_freetext_label_renders_in_pdfium` 주석 수정 + 회전·적용회전 전수 렌더 테스트 추가.**

기존 테스트에서 655줄의 낡은 주석 `# rotated page: the /AP /Matrix path still renders glyphs (Popup is invisible)`를
`# rotated page: NoRotate + the natural /Rect still render glyphs (Popup is invisible)`로 교체하고, 그 아래에 새 테스트를 추가:

```python
@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(0, None, id="R0-A0"),
        pytest.param(90, None, id="R90-A0"),
        pytest.param(180, None, id="R180-A0"),
        pytest.param(270, None, id="R270-A0"),
        pytest.param(0, {1: 90}, id="R0-A90-T90-PU2601233"),
        pytest.param(90, {1: 270}, id="R90-A270-T0-PU2601565"),
    ],
)
def test_label_renders_horizontal_on_every_page_rotation(tmp_path: Path, rotate, rotations):
    """pdfium (which implements NoRotate) must draw the chip wider than tall.

    This is the only *pixel* evidence in the suite, so the two real applied-rotation
    cases belong here too — reading /AP /BBox instead would prove nothing about how
    the annotation is actually composited onto a rotated page.
    """
    ann = A.Annotation("c", 1, (0.2, 0.2, 0.8, 0.5), "주의", "주의: 한글 라벨 렌더 확인")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate, rotations=rotations)
    img = _render_first_page(out)
    assert _has_color(img, _WARN_RGB), "label chip background not rendered"
    bb = _dark_pixel_bbox(img)
    assert bb is not None, "no dark chip/glyph pixels — Korean label not rendered"
    assert (bb[2] - bb[0]) > (bb[3] - bb[1]), (
        f"chip is taller than wide at /Rotate={rotate}, applied={rotations}"
        " — it rotated with the page"
    )
```

> **금지**: 이 테스트를 `_chip_geometry`(= `/AP /BBox` 치수 읽기)로 대체하지 말 것. `/BBox`는 정의상 항상 가로이므로 아무것도 증명하지 못한다. 반드시 `_render_first_page` → `_dark_pixel_bbox` 경로(실제 pdfium 렌더 픽셀)여야 한다.
> 라벨 `"주의: 한글 라벨 렌더 확인"`의 칩은 116.25 x 9.5pt(실측)로 두 신규 조합 모두 표시 페이지 안에 온전히 들어온다(계산 확인).

**(g) 정적 회귀 가드 추가** — `test_no_burnin_symbols`(672~677줄) 다음:

```python
def test_no_ap_matrix_symbol():
    """The /AP rotation-matrix trick must be gone (Acrobat drops it on resize)."""
    src = Path(A.__file__).read_text(encoding="utf-8")
    assert "_AP_MATRIX" not in src
```

**(h) `test_skillmd_no_stale_wording`(691~696줄)에 2줄 추가:**
```python
    assert "norotate" in text, "SKILL.md must document the NoRotate label flag"
    # the *reason* the caveat was rewritten: resizing (not just editing) triggers
    # Acrobat's AP regeneration. Pin the fact, not merely the flag name.
    assert "리사이즈" in text or "resize" in text, (
        "SKILL.md must state that a mere resize also regenerates the appearance"
    )
```
(`text`는 `.lower()` 처리된 문자열이므로 `"resize"`는 소문자로, 한글은 대소문자 영향 없음.)

**(i)(j)(k)(l) 적대적 테스트 추가** — T4 경계값 섹션(`test_oob_page_counted_not_attached` 뒤, 489줄 근처)에:

```python
@requires_font
@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
def test_zero_chip_padding_keeps_rect_and_bbox_in_sync(tmp_path: Path, monkeypatch, rotate):
    """Boundary: no chip padding at all — /Rect must still equal the /AP /BBox.

    Parametrised over every rotation so DoD D6's "all rotations x both paddings"
    claim is literally what runs, not an extrapolation from a single rotate=90.
    """
    monkeypatch.setattr(A, "LABEL_BOX_PAD", 0.0)
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "FAIL: 패딩0")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=rotate)
    ft = _freetext(_annots(PdfReader(str(out)).pages[0]))
    rc, chip_w, chip_h = _chip_geometry(ft)
    assert rc[2] - rc[0] == pytest.approx(chip_w, abs=1e-6)
    assert rc[3] - rc[1] == pytest.approx(chip_h, abs=1e-6)
    assert int(ft["/F"]) == 20


@requires_font
def test_applied_rotation_normalised_modulo_360(tmp_path: Path):
    """450 deg must behave exactly like 90 deg (it did before NoRotate too)."""
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "F")
    _, o1 = _attach(tmp_path, {1: [ann]}, rotate=0, rotations={1: 90})
    d2 = tmp_path / "d2"
    d2.mkdir()
    _, o2 = _attach(d2, {1: [ann]}, rotate=0, rotations={1: 450})
    r1 = [float(v) for v in _freetext(_annots(PdfReader(str(o1)).pages[0]))["/Rect"]]
    r2 = [float(v) for v in _freetext(_annots(PdfReader(str(o2)).pages[0]))["/Rect"]]
    assert r1 == pytest.approx(r2, abs=0.01)


@requires_font
def test_invalid_applied_rotation_still_raises(tmp_path: Path):
    """Bad input keeps the pre-existing failure mode — no new defensive code."""
    ann = A.Annotation("c", 1, (0.25, 0.25, 0.5, 0.5), "FAIL", "F")
    with pytest.raises(ValueError):
        _attach(tmp_path, {1: [ann]}, rotate=0, rotations={1: 45})


@requires_font
def test_max_length_label_on_rotated_page_stays_clamped(tmp_path: Path):
    """A 50-char label is wider than the display page: _place_label's clamp must
    still bite in display space, and /Rect must stay in sync with the /AP /BBox."""
    ann = A.Annotation("c", 1, (0.85, 0.85, 0.98, 0.95), "FAIL", "가" * 49 + "…")
    _, out = _attach(tmp_path, {1: [ann]}, rotate=90)
    ft = _freetext(_annots(PdfReader(str(out)).pages[0]))
    rc, chip_w, chip_h = _chip_geometry(ft)
    assert rc[2] - rc[0] == pytest.approx(chip_w, abs=1e-6)
    assert rc[3] - rc[1] == pytest.approx(chip_h, abs=1e-6)
    chip, ws, hs = _display_chip(ft, 90)
    assert chip[0] >= -A.LABEL_BOX_PAD - 0.01                     # clamped to the left edge
    assert -A.LABEL_BOX_PAD - 0.01 <= chip[1] <= hs + A.LABEL_BOX_PAD + 0.01
```

**(m) [신규] 회전 페이지 다중 라벨 회귀 테스트** — (l) 다음, T4 섹션 안:

```python
@requires_font
@pytest.mark.parametrize(
    ("rotate", "rotations"),
    [
        pytest.param(90, None, id="R90-A0-three-labels"),
        pytest.param(0, {1: 90}, id="R0-A90-three-labels"),
    ],
)
def test_multiple_labels_on_rotated_page_do_not_overlap(tmp_path: Path, rotate, rotations):
    """Three labels on one *rotated* page: the shared display space must hold.

    write_annotated_pdf computes ws/hs/a once per page and every label on that page
    reuses them through the same `placed` list. The pre-NoRotate multi-annotation
    test runs at rotate=0, where display space == aligned space, so it never
    exercises this. The boxes are deliberately close enough that the first chip's
    preferred slot is taken, forcing _place_label's above -> below -> right fallback.

    Only each chip's own Square is asserted clear: _place_label avoids other
    *labels* and the page edge, never other annotations' boxes — a pre-existing
    property of the untouched function, not something this change may claim.
    """
    anns = [
        A.Annotation("c", 1, (0.10, 0.50, 0.30, 0.65), "FAIL", "FAIL: 가"),
        A.Annotation("c", 1, (0.14, 0.50, 0.34, 0.65), "주의", "주의: 나"),
        A.Annotation("c", 1, (0.18, 0.50, 0.38, 0.65), "N/A", "N/A: 다"),
    ]
    (_, drawn, _, _), out = _attach(tmp_path, {1: anns}, rotate=rotate, rotations=rotations)
    assert drawn == 3
    annots = _annots(PdfReader(str(out)).pages[0])
    squares = _by_subtype(annots, "/Square")
    freetexts = _by_subtype(annots, "/FreeText")
    assert len(squares) == 3 and len(freetexts) == 3

    a = (rotations or {}).get(1, 0)
    chips = []
    for ann, sq, ft in zip(anns, squares, freetexts):
        assert str(ft["/NM"]) == f"{sq['/NM']}-label"   # pairing is explicit, not positional
        chip, ws, hs = _display_chip(ft, rotate)
        assert chip[2] - chip[0] > chip[3] - chip[1], "every chip stays wider than tall"
        own_box = A._aligned_bbox_to_display_box(ann.bbox, ws, hs, a)
        assert not A._rects_overlap(chip, own_box), f"label sits on its own box: {chip}"
        chips.append(chip)

    for i in range(len(chips)):
        for j in range(i + 1, len(chips)):
            assert not A._rects_overlap(chips[i], chips[j]), (
                f"labels {i} and {j} overlap in display space: {chips[i]} vs {chips[j]}"
            )
```

> 실측: 두 파라미터 모두 라벨1=above, 라벨2=below(above 충돌), 라벨3=right 또는 다른 슬롯으로 실제 fallback이 발생하며, chip-chip 겹침 0건 / 자기 Square 겹침 0건, 자기 박스와의 마진 2.0pt(= `LABEL_GAP_PT − LABEL_BOX_PAD`, 라벨 길이 무관하게 구조적으로 결정).

**(n) [신규 어설션] 프로덕션 진입점 커버리지** — 기존 `test_annotate_case_consumes_alignment_record`(553~577줄)의 마지막 Square 어설션(577줄) **다음에** 추가(테스트 이름·기존 어설션은 그대로 유지):

```python
    # The real entry point must produce NoRotate labels too — this case runs with
    # applied={"1": 90} on an unrotated page, i.e. exactly the a != 0 path.
    ft = _freetext(_annots(page))
    assert int(ft["/F"]) == 20                      # 4 Print | 16 NoRotate
    assert "/Matrix" not in ft["/AP"]["/N"].get_object()
    rc, chip_w, chip_h = _chip_geometry(ft)
    assert rc[2] - rc[0] == pytest.approx(chip_w, abs=1e-6)
    assert rc[3] - rc[1] == pytest.approx(chip_h, abs=1e-6)
```

---

### Step 9. `cert-review-annotate/SKILL.md` 갱신

**9-1. 129~131줄 캐비어트 bullet 교체** (실측 확인한 줄 범위 — 3줄짜리 bullet 전체).

변경 전:
```
- The Korean label is always visible in every major viewer (self-generated appearance
  stream). If a user *edits* the label text in a viewer, that viewer regenerates the
  appearance with its own fonts — moving/deleting is unaffected.
```

변경 후:
```
- The Korean label is always visible in every major viewer (self-generated appearance
  stream). Adobe Acrobat regenerates that appearance with its own fonts not only when
  the label text is *edited* but also when the annotation is merely **resized**(리사이즈). The
  label is built to survive that: its `/Rect` is always the chip's natural (never
  width/height-swapped) shape, so a regenerated appearance still lays out on one line,
  and the `/FreeText` carries the **NoRotate** flag (`/F` bit 5) so it stays horizontal
  for the reader even on a `/Rotate`-ed page. Moving/deleting is unaffected.
```

> 테스트 (h)는 `"리사이즈" in text or "resize" in text`를 검사하므로 영문 `resized`만으로도 통과한다. 위처럼 한글 병기를 넣으면 한국어 독자에게도 사실이 드러나 이중으로 안전하다 — 둘 중 하나는 반드시 남길 것.

**9-2. 44줄 Method 표 셀** — `...so the label shows in every major viewer.` 다음에 삽입:
```
The label carries the `NoRotate` flag and a naturally shaped `/Rect`, so it stays horizontal for the reader on `/Rotate`-ed pages even after a viewer regenerates its appearance.
```

**9-3. 125~128줄 좌표 규약 bullet** 끝(128줄 뒤)에 한 문장 추가:
```
  The Square is mapped from that aligned space; the `NoRotate` label is instead anchored
  in the display space (the page turned by its own `/Rotate`), which is the same space
  whenever the align-inputs applied rotation is 0.
```

**금지**: `burn-in`, `burn in`, `--dpi` 문구를 새로 넣지 말 것(`test_skillmd_no_stale_wording`이 실패한다).

---

## 4. Code Writing Guide (코드 작성 가이드)

- **인코딩**: 모든 파일 I/O는 `encoding='utf-8'` 명시. Python 실행 시 `PYTHONIOENCODING=utf-8` 프리픽스 필수. 한글이 포함된 테스트 문자열/주석 작성 후 반드시 파일을 다시 읽어 한글이 깨지지 않았는지 확인(mojibake 신호: `占쏙옙`, `ï»¿`, U+FFFD, 엉뚱한 `?`). SKILL.md에 새로 넣는 `리사이즈` 문구도 이 확인 대상이다.
- **docstring 톤 유지**: 이 파일은 각 함수/모듈에 "무엇"이 아니라 **"왜"** 를 적는 스타일이다(예: `_hex_to_rgb`의 "stripped by position, never by character class"). 새 함수 `label_rect_for_norotate` / `_aligned_bbox_to_display_box`도 같은 톤으로 "왜 min/max를 쓰면 안 되는가", "왜 t가 아니라 r인가"를 적는다. 단순 서술("returns a rect")로 줄이지 말 것. 신규 테스트의 docstring도 같은 규칙 — "무엇을 검사하는가"가 아니라 "이 케이스가 왜 위험한가"를 적는다.
- **사용하지 않는 매개변수를 남기지 말 것**: `_label_ap`, `_build_label_annot`의 `t`는 제거한다. 하위 호환용으로 `t=None` 같은 잔재를 남기지 않는다(둘 다 private, 외부 호출자 없음 — Step 0 grep으로 확인).
- **낡아버린 서술 제거**: `_AP_MATRIX` dict와 그 위 3줄 주석, 모듈 docstring 47~48줄, 57~59줄, `_place_label` docstring의 "Works in the aligned space", 테스트 655줄 주석 — 전부 갱신 대상이다. "설명이 코드보다 오래된" 상태를 남기지 말 것.
- **surgical diff**: Square/Popup 관련 코드는 공백 하나도 바꾸지 않는다(단, 554~559줄 공유 계산부는 Step 7-2의 명시적 대상이므로 예외 — 1.4 참조). 리팩터링 충동(예: `_build_square`의 `NumberObject(4)`를 상수로 빼기)을 억제할 것 — AC18 위반이다.
- **매직 넘버**: `4 | 16`은 `FREETEXT_FLAGS` 상수로 한 번만 정의하고 주석에 PDF 스펙 근거(Table 165)를 남긴다. 테스트에서는 의도가 드러나도록 `4 | 16` 또는 `20`을 직접 쓰되 주석을 붙인다(상수 import로 자기참조 테스트가 되지 않게).
- **부동소수 비교**: 테스트는 `pytest.approx`를 쓴다. 기존 관례대로 좌표는 `abs=0.01`, 폭/높이 항등은 `abs=1e-6`.
- **테스트 스킵 관례 유지**: 한글 폰트가 필요한 통합 테스트에는 `@requires_font`를 붙인다. 순수 기하 테스트((c), (d), (g), (h))는 폰트 없이 항상 실행되어야 한다.
- **테스트 헬퍼 중복 금지**: 표시 공간 복원 로직은 `_display_chip` 하나만 두고 (e)/(l)/(m)이 공유한다. 같은 3줄을 세 번 인라인하지 말 것.
- **새 파일 생성 금지**: 문서/리포트 `.md`를 새로 만들지 말 것. 스모크 스크립트는 리포지토리 밖 scratchpad에만 둔다.

---

## 5. Definition of Done (개발 완료조건)

전부 바이너리로 판정 가능해야 한다. D16만 자동 검증 불가로 명시 분리한다.

| ID | 조건 | 판정 방법 | 매핑된 적대적 테스트 |
|---|---|---|---|
| **D1** | `tests/test_annotate_pdf.py` 전체 통과 (0 failed, 0 error), 통과 개수는 baseline 39 이상 | Verification V2 | 전체 |
| **D2** | `tests/` 전체 통과 (0 failed, 0 error), baseline 대비 신규 실패 0건 | Verification V3 | 전체 |
| **D3** | `annotate_pdf.py`에 `_AP_MATRIX` 심볼 0건 | Verification V4 grep | (g) |
| **D4** | `/Rotate ∈ {0,90,180,270}` 전부에서 FreeText `/AP /N`에 `/Matrix` 없음 | 테스트 (a) | (a) |
| **D5** | FreeText `/F == 20`; Square `/F == 4`; Popup NoRotate 비트 0 | 테스트 (a), (b) | (a), (b) |
| **D6** | 모든 회전(`0/90/180/270`) 및 `LABEL_BOX_PAD ∈ {2.0, 0.0}`에서 FreeText `/Rect` 폭·높이 ≡ `/AP /BBox` 폭·높이, 그리고 `llx<urx ∧ lly<ury` | 테스트 (a)(회전 전수 x 패딩 2.0), (i)(회전 전수 x 패딩 0.0), (l) | (a), (i), (l) |
| **D7** | `label_rect_for_norotate` 리터럴 5종 + CropBox 오프셋 일치, `r=45` → `ValueError`; `_aligned_bbox_to_display_box` 리터럴 4종(`a=0/90/180/270`) 일치 | 테스트 (c), (d) | (c), (d) |
| **D8** | `(R,A)` **7조합**(`(0,180)` 포함) 전부에서 라벨이 Square와 겹치지 않고 간격 ≤ `LABEL_GAP_PT + 2*LABEL_BOX_PAD` | 테스트 (e) | (e) |
| **D9** | pdfium **실제 렌더 픽셀**에서 `(R,A)` 6조합(A=0 4종 + `a≠0` 운영 2종) 전부 칩의 dark-pixel bbox 폭 > 높이 | 테스트 (f) | (f) |
| **D10** | `rotations={1:450}` ≡ `{1:90}`; `rotations={1:45}` → `ValueError` | 테스트 (j), (k) | (j), (k) |
| **D11** | Square/Popup 코드 diff 0줄 — `_build_square`, `_popup_rect`, `_build_popup`, `write_annotated_pdf`의 sq/pop 생성 블록(568~581줄). 554~559줄 공유 계산부는 대상 아님 | Verification V5 (`git diff`) | 기존 `test_square_and_freetext_fields`, `test_square_popup_bidirectional_link`, `test_delete_annotation_preserves_content` |
| **D12** | `SKILL.md`에 **리사이즈 트리거 사실이 텍스트로 존재**(`리사이즈` 또는 `resize`) + `NoRotate` 단어 포함, `burn-in`/`burn in`/`--dpi` 여전히 0건 | 테스트 (h) | (h) |
| **D13** | 모듈/함수 docstring에 `/AP /Matrix`로 방향을 맞춘다는 서술이 남아 있지 않음 (47~48줄, 57~59줄, `_label_ap`, `_build_label_annot`, `write_annotated_pdf`, `_place_label` docstring) | V4 grep + 육안 | (g)로 심볼 수준 커버, 서술은 육안 |
| **D14** | 회전 스모크 PDF 4종을 직접 렌더한 PNG에서 **한글이 가로로, 깨짐 없이** 보임 (Korean-integrity 규칙) | Verification V7 (PNG를 실제로 Read해 육안 확인) | V7 자체 |
| **D15** | 리포지토리에 PDF/PNG/스크립트 등 산출물이 추가되지 않음 (`git status`가 3개 소스 파일 수정만 표시) | Verification V5 | — |
| **D16** | **[자동 검증 불가 — 사용자 수동 확인]** 사용자가 Adobe Acrobat에서 라벨을 리사이즈한 뒤에도 텍스트가 가로로 유지됨. **`/Rotate=90` 필수, `/Rotate=180`·`270`도 가능하면 확인** | 사용자 육안 확인. V8이 회전별 **개별 단일 페이지 PDF 3개** 경로를 제시 | **해당 없음 — 이 항목 자체가 검증 방법이다. 로컬 자동 테스트로는 Acrobat의 AP 재생성 엔진을 재현할 수 없으므로 별도 자동 테스트를 만들지 말 것.** |
| **D17** | **[신규]** 회전 걸린 페이지(`R=90` 및 `A=90`)에 주석 3개 부착 시 라벨끼리 겹침 0건, 각 라벨이 자기 Square와 겹침 0건 | 테스트 (m) | (m) |
| **D18** | **[신규]** `annotate_case`(프로덕션 진입점, `applied={"1":90}`) 경유 산출물의 FreeText가 `/F==20`, `/Matrix` 부재, `/Rect`≡`/BBox` | 테스트 (n) | (n) |

---

## 6. Adversarial Test Environment (적대적 테스트 환경)

### 6.1 경계값

| 케이스 | 입력 | 기대 | 테스트 |
|---|---|---|---|
| 패딩 0 x 회전 전수 | `LABEL_BOX_PAD = 0.0` (monkeypatch), `/Rotate ∈ {0,90,180,270}` | `/Rect` ≡ `/BBox`, `/F=20` 유지 | (i) |
| 최대 길이 라벨 | 50 코드포인트 한글(`"가"*49 + "…"`, 실측 칩 폭 497.5pt), 박스가 페이지 우하단(0.85~0.98), `/Rotate=90` — 라벨 폭이 표시 페이지 폭(300pt)보다 큼 | `_place_label` 클램프가 표시 공간에서 작동해 칩 좌상단이 `>= -LABEL_BOX_PAD`; `/Rect` ≡ `/BBox` | (l) |
| 전면 bbox | `bbox=(0,0,1,1)` + CropBox | Square `/Rect == (0,0,400,300)` 불변 | 기존 `test_full_page_bbox` |
| CropBox ≠ MediaBox | 케이스 46 p1 오프셋 | 앵커 리터럴 `(152.91, 620.68, 212.91, 634.68)` | (c) |
| 회전 전수 | `/Rotate ∈ {0,90,180,270}` | `/Matrix` 부재 + `/F=20` + `/Rect`≡`/BBox` | (a) |
| `(R,A)` 조합 전수 | `(0,0) (90,0) (180,0) (270,0) (0,90) (90,270) (0,180)` | 표시 공간 인접성 | (e) |
| `(R,A)` 픽셀 렌더 | 위 중 6조합(`(0,180)` 제외 — (e)가 좌표로 이미 고정) | dark-pixel bbox 폭 > 높이 | (f) |
| 다중 주석 x 회전 | 주석 3개, `(R=90,A=0)` 및 `(R=0,A=90)`, 슬롯 충돌하도록 근접 배치 | 라벨 간 겹침 0, 자기 Square와 겹침 0 | (m) |
| 프로덕션 진입점 | `annotate_case`, `applied={"1":90}` | Square `/Rect` 리터럴 유지 + FreeText NoRotate 3종 | (n) |

### 6.2 잘못된 입력

| 케이스 | 입력 | 기대 |
|---|---|---|
| 무효 회전각 | `rotations={1: 45}` | `ValueError` (기존과 동일, 새 방어코드 없음) — 테스트 (k) |
| 360 초과 회전각 | `rotations={1: 450}` | `{1: 90}`과 동일 결과 — 테스트 (j) |
| 무효 페이지 `/Rotate` | 예: `/Rotate=45` | 555~556줄이 `r=0`으로 클램프 — 기존 동작 유지, 별도 테스트 불필요 |
| PASS 직접 주입 | `verdict="PASS"` | 주석 0개 — 기존 `test_pass_injected_directly_yields_no_annotations` |
| 페이지 범위 밖 | `page=99` | `oob_count`에 계상, 미부착 — 기존 `test_oob_page_counted_not_attached` |
| 불량 bbox / bool page | `load_annotations` dual gate | 기존 `test_load_annotations_dual_gate` |

### 6.3 회귀 방지

| 위험 | 가드 |
|---|---|
| `T=0`(무회전) 페이지 동작이 바뀜 — 이제 T=0에도 NoRotate가 켜짐 | 테스트 (a)의 `rotate=0` 파라미터, (e)의 `R0-A0-T0`, (f)의 `R0-A0`. `/Rotate=0`에서 NoRotate는 no-op이므로 시각적으로 동일해야 한다. 또한 기존 `test_rect_matches_metadata_rotation`, `test_annotate_case_consumes_alignment_record`의 Square 리터럴이 그대로 통과해야 한다. |
| **`A≠0` 운영 케이스가 픽셀로 검증되지 않음** | 테스트 (f)의 `R0-A90-T90-PU2601233`, `R90-A270-T0-PU2601565` 파라미터 (초판에서 누락되었던 구멍) |
| **최악 편차 조합 `(0,180)`이 어디에서도 검증되지 않음** | 테스트 (e)의 `R0-A180-T180`, 테스트 (d)의 `a=180` 리터럴 (초판에서 누락되었던 구멍) |
| **다중 주석이 표시 공간 분기를 태우지 못함** | 테스트 (m) (초판에서 누락되었던 구멍) |
| **프로덕션 진입점이 NoRotate로 검증되지 않음** | 테스트 (n) (초판에서 누락되었던 구멍) |
| Square/Popup을 실수로 건드림 | 기존 `test_square_and_freetext_fields`(`/IC` 없음, `/C` 3요소, `/BS`, `/F==4`, `/AP` 없음, `/Popup` 있음), `test_square_popup_bidirectional_link`(양방향 링크, `/Open=False`, `/Contents` 없음, 공유 stamp), `test_delete_annotation_preserves_content` + V5 diff 검사 |
| 페이지 콘텐츠 바이트 변조 | 기존 `test_all_pages_content_bytes_identical`, `test_preexisting_annots_preserved` |
| 글리프 왜곡(`/BBox`≠`/Rect` 스케일링) | 테스트 (a), (i), (l), (n)의 폭·높이 항등 검사 |
| 라벨 겹침 회피 로직 파손 | 기존 `test_place_label_avoids_overlap`, `test_place_label_clamps_into_page` (함수 자체는 미수정) + 신규 (m) |
| 금지 import 재유입 | 기존 `test_no_forbidden_imports`, `test_no_burnin_symbols` |
| 문서-코드 불일치 재발 | 테스트 (g) `_AP_MATRIX` 부재, 테스트 (h) SKILL.md `NoRotate` 언급 **및 리사이즈 사실 존재** |

### 6.4 정적 검증으로 원천적으로 확인 불가능한 항목 (사용자 수동 확인 필요)

> **이 항목은 자동 테스트를 만들지 말 것.** 로컬에는 Acrobat의 리치텍스트 AP 재생성 엔진이 없고, pypdf/pdfium은 우리가 쓴 AP를 그대로 존중하므로 "Acrobat이 AP를 버린 뒤의 결과"를 재현할 방법이 없다.

- **A1. Acrobat 리사이즈 후 방향**: 사용자가 라벨을 Adobe Acrobat에서 리사이즈한 뒤 텍스트가 **가로**로 유지되는지 (D16 = 목표의 성공 기준 (2)). 1-c 확정 목표가 `/Rotate=90/180/270`을 모두 대상으로 지정했으므로, **V8은 세 회전 각각의 단일 페이지 PDF를 제공**하고 사용자에게 최소 `/Rotate=90`, 가능하면 셋 다 확인을 요청한다.
- **A2. Acrobat의 "보기 회전(Rotate View)"과 NoRotate 상호작용**: 사용자가 뷰를 회전했을 때 라벨이 어떻게 보이는지. PDF 스펙은 NoRotate를 페이지 `/Rotate` 기준으로 정의하지만 뷰어별 해석 차이 가능성이 있음.
- **A3. 타 뷰어 확인(선택)**: Chrome PDF viewer / macOS Preview / Edge. 자동 fallback 동작은 실측으로 "본문과 같이 옆으로 누움, 한 줄 유지"임이 확인되었으므로(Section 1.5) 최악의 경우도 이전 대비 퇴보가 아니다.

실행 에이전트는 V8에서 A1을 수행할 수 있는 스모크 PDF들을 scratchpad에 만들어 사용자에게 **회전별 경로를 모두** 제시하고, 여기까지가 자동 검증의 한계임을 보고에 명시한다.

---

## 7. Risks and Mitigations

**R1. Acrobat이 NoRotate를 스펙대로 구현하지 않을 잔여 위험** (중간 / 영향 큼)
- 근거: pdfium은 스펙대로 구현함을 실측 확인(6개 조합 + 테스트 (f)가 CI에서 6조합 재확인). Acrobat은 로컬에서 검증 불가.
- 왜 이 방식이 Acrobat의 AP 재생성 이후에도 살아남는가 (논리적 근거):
  1. `/F`는 **주석 딕셔너리 자체**의 키다. Acrobat이 재생성하는 것은 `/AP` 스트림이며, `/F`·`/Rect`·`/Contents`·`/DA` 등 다른 키는 보존된다. 즉 NoRotate는 AP 재생성과 **독립적으로 살아남는다**. (반면 `/Matrix`는 `/AP` **안에** 있어서 재생성 시 함께 사라진다 — 이것이 현행 버그의 정확한 메커니즘.)
  2. 설령 어떤 뷰어가 NoRotate를 **완전히 무시**해도, 새 `/Rect`가 가로로 넓기 때문에 재생성된 리치텍스트는 **한 줄**로 배치된다. 실패 모드가 "글자가 세로로 쌓임(판독 불가)" → "본문과 같이 옆으로 누움(기존에 이미 수용된 상태)"으로 **완화**된다. 실측으로 확인(26x118px, 한 줄).
- 완화: 최종 확인은 사용자 몫(D16/A1). **V8에서 `/Rotate=90/180/270` 세 회전의 스모크 PDF를 각각 별도 파일로 제공해, 초판에서 90만 제공되어 180/270에 확인 경로가 아예 없던 구멍을 막는다.**

**R2. `A ≠ 0` 페이지의 라벨 방향·배치가 의도적으로 바뀐다** (확실 / 영향 중간)
- 변경 전: 라벨이 `/AP /Matrix`로 **본문 콘텐츠 기준 수평**(화면에서는 옆으로 누움).
- 변경 후: 라벨이 **뷰어 기준 수평**, 그리고 배치 기준도 표시 공간으로 이동.
- 왜 수용 가능한가: (1) 사용자의 확정 목표가 "항상 가로"다. (2) `A ≠ 0` + `R = 0`인 경우 Acrobat은 어차피 raw 수평으로 재생성하므로, 기존의 콘텐츠 정렬은 리사이즈 한 번에 사라지는 불안정한 상태였다. 새 방식은 우리가 그리는 모습과 Acrobat이 재생성하는 모습을 **일치**시켜 WYSIWYG 안정성을 얻는다. (3) 배치 기준을 표시 공간으로 옮기지 않으면 라벨이 최대 300px 이탈하거나 페이지 끝에서 잘린다(실측).
- 완화: 모듈 docstring / `write_annotated_pdf` docstring / SKILL.md에 명시. 테스트 (e)가 **7개 조합**을, (f)가 픽셀로 6개 조합을, (n)이 프로덕션 진입점을 고정.

**R3. 이미 발급된 annotated PDF와의 시각적 불일치** (확실 / 영향 낮음)
- 기존 산출물은 여전히 Matrix 방식이며 재생성하지 않는다(사용자 확정 범위).
- 완화: 재생성은 별도 요청 시 진행. 이번 커밋에 PDF를 포함하지 않는다(D15). testbed `ref/`의 2개 파일은 회귀 참고용으로만 두고 커밋하지 않는다.

**R4. private 함수 시그니처 변경(`_label_ap`, `_build_label_annot`의 `t` 제거)** (낮음)
- 근거: 두 함수 모두 모듈 private이고 호출부는 각각 1곳. 테스트도 직접 호출하지 않음(테스트 import 목록 확인 완료).
- 완화: Step 0의 `git grep`으로 재확인.

**R5. `_place_label` 입력 공간 변경으로 인한 회귀** (낮음)
- `_place_label` 함수 **본문은 한 줄도 고치지 않는다**(docstring 한 문장만 일반화 — Step 7-4). 바뀌는 것은 호출자가 넘기는 좌표계뿐이다.
- `a == 0`이면 `_aligned_bbox_to_display_box(bbox, ws, hs, 0)`은 `box_al`과 **수치적으로 동일**하고 `(ws, hs) == (wa, ha)`이므로, 기존 A=0 경로는 입력까지 완전히 같다(실측 표에서 3개 조합 rect 완전 일치로 확인).
- 다중 주석이 페이지당 한 번 계산된 `ws, hs, a`를 공유하는 구조는 코드 추적으로 안전함이 확인되었으나, 이번 리팩터링이 정확히 건드리는 지점이므로 테스트 (m)이 회귀 가드를 세운다.

**R6. `RectangleObject`가 좌표를 정규화하지 않음** (낮음, 실측 확인)
- 잘못된 순서로 `/Rect`를 만들면 조용히 그대로 기록된다.
- 완화: `label_rect_for_norotate`가 구조적으로 올바른 순서를 보장하고, 테스트 (a)가 `rc[2] > rc[0] and rc[3] > rc[1]`을 검사한다.

**R7. `a` 정규화(`% 360`) 누락 시 기존 입력이 새로 예외를 던짐** (낮음)
- 완화: Step 7-2에서 `% 360` 적용, 테스트 (j)가 고정.

**R8. dark-pixel 기반 렌더 테스트의 취약성** (낮음)
- 칩 회색 테두리 `(80,80,80)` sum=240 < 250, 글리프는 검정, verdict 채움은 sum ≥ 646(주의 `#FFEB9C` = 646), 테스트 페이지 파랑 스트로크는 sum=255 — 모두 임계값 250과 충분히 떨어져 있음을 계산으로 확인. 안티앨리어싱은 흰색 쪽으로만 밝아진다.
- 완화: 라벨 문자열을 충분히 길게 유지해 폭:높이 비를 확보(`"주의: 한글 라벨 렌더 확인"` 실측 116.25 x 9.5pt ≈ 12:1). **라벨을 짧게 바꾸지 말 것.** (f)의 신규 두 조합도 이 라벨이 표시 페이지 안에 온전히 들어옴을 계산으로 확인했다.

**R9. 테스트 (m)의 배치 어설션이 라벨 길이 변경에 취약해질 위험** (낮음)
- 자기 박스와의 세로 마진 2.0pt는 `LABEL_GAP_PT − LABEL_BOX_PAD`로 **구조적으로 결정**되며, 칩 높이(9.5pt, 폰트 크기에만 의존)와 무관하다.
- 완화: (m)의 bbox·라벨 문자열을 바꾸지 말 것(부록 B-12). 타 Square와의 겹침은 어설션하지 않는다 — `_place_label`의 기존 성질이라 리팩터링과 무관하게 깨질 수 있다.

---

## 8. Verification Steps

모든 명령은 아래 디렉터리에서 실행한다.

```powershell
$env:PYTHONIOENCODING = "utf-8"
Set-Location "C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer\skills\cert-review"
```

**V1. 착수 전 baseline** (Step 0에서 이미 수행)
```powershell
python -m pytest tests/ -q                        # 전체 카운트 기록
python -m pytest tests/test_annotate_pdf.py -q    # 기대: 39 passed
```

**V2. annotate 테스트**
```powershell
python -m pytest tests/test_annotate_pdf.py -q
```
→ 0 failed / 0 error. 실패 시 `-x -vv`로 좁혀 원인 수정 후 재실행. **실패를 남긴 채 완료 보고 금지.**

신규/확장 파라미터가 실제로 수집됐는지 id로 확인한다(오타로 조용히 빠지는 것을 방지):
```powershell
python -m pytest tests/test_annotate_pdf.py -q --collect-only -k "R0-A180 or PU2601233 or PU2601565 or three-labels"
```
→ 최소 5건(= (e) `R0-A180-T180`, (e)/(f)의 PU2601233·PU2601565, (m) 2건)이 수집되어야 한다.

**V3. 전체 스위트**
```powershell
python -m pytest tests/ -q
```
→ baseline 대비 신규 실패 0건.

**V4. 정적 grep**
```powershell
Set-Location "C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer"
git grep -n "_AP_MATRIX" -- skills/          # 기대: 0 hits (docs/plans/*.md 과거 기록은 제외)
git grep -n "NoRotate" -- skills/            # annotate_pdf.py + tests + SKILL.md 에 존재
git grep -n "AP.*Matrix" -- skills/cert-review/scripts/annotate_pdf.py
git grep -n "aligned space" -- skills/cert-review/scripts/annotate_pdf.py   # _place_label docstring 잔재 확인
```
마지막 두 명령의 결과에 "방향을 맞추기 위해 Matrix를 쓴다" 또는 "`_place_label`은 aligned 공간에서 동작한다"는 취지의 서술이 남아 있으면 안 된다(부정문 설명은 허용).

**V5. diff 검사 (Square/Popup 불변 + 산출물 미포함)**
```powershell
git status --short
git diff --stat
git diff -U3 -- skills/cert-review/scripts/annotate_pdf.py
```
- `git status`는 정확히 3개 파일 수정만 표시해야 한다: `skills/cert-review/scripts/annotate_pdf.py`, `skills/cert-review/tests/test_annotate_pdf.py`, `skills/cert-review-annotate/SKILL.md`. PDF/PNG/스크립트 등 신규 파일이 있으면 안 된다(D15).
- diff를 육안으로 훑어 `_build_square`, `_popup_rect`, `_build_popup` 및 `write_annotated_pdf`의 `sq = _build_square(...)` ~ `sq[NameObject("/Popup")] = pop.indirect_reference` 블록(568~581줄)에 변경 라인이 **하나도 없음**을 확인(D11). 554~559줄에 변경이 있는 것은 정상이다(Step 7-2).

**V6. 기존 스파이크 재현** (기준값이 그대로인지 확인)
```powershell
Set-Location "C:\Users\donghun.lee\.claude\plugins\marketplaces\ReportReviewer\skills\cert-review"
python "C:\tmp\claude\D--001-Work-2026-033--------Certification-Examine-testbed-1--Standard-Inspection\9d6a5fcc-e325-40b6-b7f0-13fba8471311\scratchpad\spike_norotate_A_nonzero.py"
```
기대: `a=0` 3행에서 `rectA == rectB`, 모든 행에서 `horizontal=True`, `overlaps_square=False`.
주의: `scratchpad\spike_norotate4_all_t.py`는 `_AP_MATRIX`를 import하므로 **이번 변경 후 ImportError로 실패한다 — 정상이다**. 이 스크립트를 고치거나 삭제하지 말 것(과거 증거 보존). 실행할 필요도 없다.

**V7. 신규 스모크 렌더 + 한글 무결성 육안 확인 (필수, D14)**

scratchpad에 새 스크립트를 작성해 실행한다(리포지토리 안에 만들지 말 것). 내용:

1. `write_annotated_pdf`로 `/Rotate ∈ {0, 90, 180, 270}` 4종에 한글 라벨(`"주의: 열처리 온도 미기재"` 등) 주석을 부착한다. **각 회전은 반드시 별도의 단일 페이지 PDF 파일로 만든다** — 파일명 예: `smoke_norotate_R0.pdf`, `smoke_norotate_R90.pdf`, `smoke_norotate_R180.pdf`, `smoke_norotate_R270.pdf`. (한 PDF에 4페이지로 묶지 말 것: V8에서 사용자가 Acrobat으로 회전별 확인을 할 때 어느 페이지가 어느 회전인지 헷갈리고, 회전 하나만 열어보기도 어렵다.)
2. 각 출력 PDF를 `pypdfium2`로 `scale=3.0, draw_annots=True` 렌더해 PNG로 저장한다(파일명도 회전별로 구분).
3. 각 PNG에 대해 dark-pixel bbox의 폭/높이를 출력한다.
4. 각 출력 PDF의 FreeText `/Contents`, `/F`, `/Rect`, `/AP /N /BBox`, `/Matrix` 유무를 pypdf로 읽어 출력한다.

그다음 **반드시 4개 PNG를 Read 도구로 직접 열어 육안 확인**한다:
- 한글이 **가로**로 읽히는가
- 한글이 **깨지지 않았는가** (U+FFFD, `占쏙옙`, `ï»¿`, 엉뚱한 `?` 없음)
- 라벨 칩이 검토 박스 옆에 붙어 있는가

그리고 콘솔에 출력된 `/Contents` 한글 문자열도 육안 확인한다. 깨짐이 발견되면 **성공 보고 금지** — 인코딩 원인(읽기 인코딩, `PYTHONIOENCODING`, BOM, 터미널 코드페이지)을 진단·수정 후 이 단계부터 재검증한다.

**V8. 사용자 수동 확인용 산출물 준비 (D16 / A1)**

V7에서 만든 스모크 PDF 중 **`/Rotate=90`, `/Rotate=180`, `/Rotate=270` 세 파일의 scratchpad 절대 경로를 모두** 사용자에게 제시하고, 다음을 요청한다:

1. Adobe Acrobat에서 열기 (**최소 `/Rotate=90` 하나, 가능하면 셋 다**)
2. 라벨 주석을 클릭해 핸들로 **리사이즈**
3. 텍스트가 **가로로 유지**되는지 확인 (변경 전에는 세로로 뒤집혔음)

1-c 확정 목표가 `/Rotate=90/180/270`을 모두 대상으로 지정했으므로 세 파일을 모두 제시해야 한다 — 90만 제시하면 180/270에 대한 확인 경로가 자동/수동 어느 쪽에도 존재하지 않게 된다.

보고 시 "여기까지가 자동 검증 한계이며, Acrobat의 AP 재생성 동작은 로컬에서 재현 불가"임을 명시한다. 실제 성적서로 확인하고 싶다는 요청이 오면 `python -m scripts.cli annotate --case <id>`로 신규 케이스를 생성해 확인하도록 안내한다(기존 `ref/` 파일은 재생성하지 않음).

**완료 보고 형식 (필수)**

완료 보고에는 아래를 반드시 포함해 revision-tracker가 그대로 활용할 수 있게 한다:
- **부록 A의 변경 요약 표** 또는 `git diff --stat` 결과 (둘 중 하나 이상)
- V2/V3의 실제 pytest 요약 라인(baseline 39 → 최종 통과 수)
- V7에서 육안 확인한 PNG 파일 경로와 "한글 가로·깨짐 없음" 확인 문구
- V8에서 사용자에게 제시한 3개 PDF 경로

---

### 부록 A. 변경 요약 (한눈에)

| 파일 | 변경 |
|---|---|
| `annotate_pdf.py` | 모듈 docstring 2곳 갱신(46~48줄 블록 / 57~59줄) / `FREETEXT_FLAGS = 4 \| 16` 추가 / `_aligned_bbox_to_display_box`, `label_rect_for_norotate` 신규 / `_AP_MATRIX` 삭제 / `_label_ap`·`_build_label_annot`에서 `t` 제거 + `/F` 변경 / `write_annotated_pdf` 라벨 배치 블록 표시 공간 전환 + `a % 360` / `_place_label` docstring 1문장 일반화(본문 무변경) |
| `test_annotate_pdf.py` | 헬퍼 4개 추가(`_FWD_FRAC`, `_chip_geometry`, `_dark_pixel_bbox`, `_display_chip`) / 테스트 1개 대체 (a) / 기존 3곳 수정 (b), (f 주석), (n) / (h) 2줄 추가 / **신규 10개** (c),(d),(e),(f),(g),(i),(j),(k),(l),(m) |
| `cert-review-annotate/SKILL.md` | 캐비어트 bullet 교체(129~131줄, 리사이즈 사실 명시) / Method 표 셀 보강(44줄) / 좌표 규약 bullet 보강(125~128줄) |

신규/수정 테스트 대응표:

| 라벨 | 함수명 | 성격 |
|---|---|---|
| (a) | `test_label_ap_never_carries_matrix_and_sets_norotate` | 대체 (회전 4종 parametrize) |
| (b) | `test_square_and_freetext_fields` 374줄 | 수정 1줄 |
| (c) | `test_label_rect_for_norotate_literals` | 신규 (순수 기하) |
| (d) | `test_aligned_bbox_to_display_box_undoes_applied_rotation` | 신규 (순수 기하, `a=180` 포함) |
| (e) | `test_label_anchor_lands_beside_the_square_in_display_space` | 신규 (7조합) |
| (f) | `test_label_renders_horizontal_on_every_page_rotation` | 신규 (픽셀 렌더 6조합) + 기존 655줄 주석 수정 |
| (g) | `test_no_ap_matrix_symbol` | 신규 (정적) |
| (h) | `test_skillmd_no_stale_wording` | 수정 2줄 추가 |
| (i) | `test_zero_chip_padding_keeps_rect_and_bbox_in_sync` | 신규 (회전 4종 parametrize) |
| (j) | `test_applied_rotation_normalised_modulo_360` | 신규 |
| (k) | `test_invalid_applied_rotation_still_raises` | 신규 |
| (l) | `test_max_length_label_on_rotated_page_stays_clamped` | 신규 |
| (m) | `test_multiple_labels_on_rotated_page_do_not_overlap` | 신규 (2조합 x 주석 3개) |
| (n) | `test_annotate_case_consumes_alignment_record` | 수정 (FreeText 어설션 5줄 추가) |

### 부록 B. 실행 에이전트가 절대 하지 말아야 할 것

1. Square / Popup 코드 수정 (`_build_square`, `_popup_rect`, `_build_popup` 및 568~581줄 호출 블록)
2. `label_rect_for_norotate`에 `min`/`max` 정규화 추가 — 90/270에서 앵커 코너가 뒤바뀐다
3. `label_rect_for_norotate` 결과를 CropBox로 클램프 — NoRotate에서 비앵커 코너는 무의미하다
4. 앵커 변환에 `t`를 사용 — `A≠0`에서 최대 300px 이탈 (실측)
5. CID 폰트 임베딩 / 벡터 글리프 방식 재제안 (과거 기각)
6. `docs/plan_history.md`, `docs/revision_history.md`, `docs/plans/*.md` 수정
7. testbed `ref/`의 기존 PDF 재생성 또는 리포지토리 커밋
8. `scratchpad/spike_norotate4_all_t.py` 수정·삭제
9. `_label_ap` / `_build_label_annot`에 쓰지 않는 `t` 매개변수 잔존
10. 테스트 실패를 남긴 채 완료 보고, 또는 사용자에게 "돌려보세요"라고 자체 검증 가능한 항목을 위임
11. **테스트 (e)의 `R0-A180-T180` 파라미터, 테스트 (d)의 `a=180` 리터럴, 테스트 (f)의 `PU2601233`/`PU2601565` 파라미터 삭제** — 전부 리뷰에서 발견된 커버리지 구멍을 막는 항목이다
12. **테스트 (m)의 bbox 좌표·라벨 문자열 변경** — 겹침 회피 분기를 태우도록 실측으로 조정된 값이다
13. **테스트 (f)를 `_chip_geometry`(`/AP /BBox` 치수) 기반으로 대체** — `/BBox`는 항상 가로라 아무것도 증명하지 못한다. 반드시 pdfium 렌더 픽셀(`_dark_pixel_bbox`)이어야 한다
14. **V7에서 4개 회전을 한 PDF에 여러 페이지로 묶기** — V8의 사용자 확인 동선이 무너진다

