# annotate 직전 페이지별 업라이트 정규화 전처리 추가 (Acrobat 핸들 UI 불일치 구조적 제거) — v1.8.0

- **Date**: 2026-07-29 09:00:28
- **Author**: dh-dev 워크플로우 (계획: Fable 5/max effort, 실행: Opus/max effort)

## Rationale / Plan

**Plan**: [2026-07-28_162707_annotate-upright-normalization](../plans/2026-07-28_162707_annotate-upright-normalization.md)

커밋 `9e3cd1f`(NoRotate 앵커, 2026-07-28)로 회전 페이지(`/Rotate≠0`)의 FreeText 검토 라벨이 Acrobat 리사이즈 후에도 항상 가로를 유지하도록 근본 수정했으나, 사용자가 실제 Acrobat에서 확인한 결과 Acrobat 자체의 선택/리사이즈 핸들 오버레이 UI가 NoRotate를 무시하고 페이지 회전 추종 좌표로 그려져 핸들 박스가 실제 라벨과 점대칭 위치에 나타나는 잔존 한계가 발견되어 "Known Acrobat limitation"으로 문서화·종결(커밋 `45bc2ee`)했다.

사용자가 "성적서를 페이지별로 분리 후 회전정렬 후 재결합하고 나서 코멘트 입력 방식으로 진행해도 같은 이슈가 발생할지" 조사를 요청. 조사 결과: `label_rect_for_norotate(..., r)`이 호출하는 `_aligned_to_user_frac(u, v, r)`은 `r == 0`일 때 항등변환이므로, 페이지의 실제 `/Rotate`가 0이면 NoRotate 앵커 계산과 Acrobat 핸들 UI가 따르는 "페이지 회전 추종" 변환이 둘 다 무회전으로 수렴해 애초에 두 경로가 갈라질 지점이 소멸한다는 구조적 결론을 도출. 단, 이를 위해서는 verbatim 보존 원칙(`clone_from` — 페이지 콘텐츠 불변)을 일부 페이지에 한해 완화해야 하는 트레이드오프가 있음을 사용자에게 보고하고 승인받아 진행.

dh-dev 전 절차(1-a 분석 → 1-b 인터뷰 4개 설계 결정 확정 → 1-c 재진술 → 1-d 계획 수립[Fable 5] → 1-e 적대적 검증[contrarian+gap_hunter 병렬, HIGH 3건 발견 → 단일 재수정 사이클로 전건 반영] → Step 2 사용자 승인 → Step 3 실행[Opus])을 거쳐 구현.

## Changed Files

| File | Status | Description |
|------|--------|-------------|
| `skills/cert-review/scripts/upright_pdf.py` | Added | 페이지별 업라이트 정규화 전처리 모듈(무손실 matrix bake-in) |
| `skills/cert-review/tests/test_upright_pdf.py` | Added | 신규 유닛 테스트 19개(U1~U15, 일부 parametrize) |
| `skills/cert-review/scripts/annotate_pdf.py` | Modified | `annotate_case`만 수정(2단 폴백 통합) + import 2개 + 모듈 독스트링 1문단. `write_annotated_pdf` 이하 좌표변환/빌더 함수는 diff 0줄 |
| `skills/cert-review/tests/test_annotate_pdf.py` | Modified | 기존 1건 의도적 갱신 + 신규 A1~A9 추가(67→78 passed) |
| `skills/cert-review-annotate/SKILL.md` | Modified | Method 행·좌표 관례·Known Acrobat limitation 블록 갱신(헤지 문구 반영) |
| `.claude-plugin/marketplace.json` | Modified | 버전 1.7.0 → 1.8.0 |
| `README.md` | Modified | 변경이력 1행 추가 |
| `docs/plans/2026-07-28_162707_annotate-upright-normalization.md` | Added | dh-dev 계획 문서(Rev.1, findings 반영표 포함) |
| `docs/plan_history.md` | Modified | 계획 인덱스 행 추가 |
| `skills/cert-review/scripts/cli.py` | Modified | 커밋 전 code-reviewer 검토(HIGH 1건) 반영 — `annotate` 서브커맨드가 tier-2 skip(stem 전체 실패) 발생 시 `[OK]`+exit 0 대신 `[WARN]`+exit 1 반환 |

## Details

### `scripts/upright_pdf.py` (Added)

- `page_upright_turns(reader, rotations)` — 페이지별 `t=(r+a)%360` 정규화 필요 맵 계산. 클램프(r∉{0,90,180,270}→0)를 a와 결합하기 **전에** 적용.
- `write_upright_pdf(src, dst, turns)` — `pypdf.PageObject.transfer_rotation_to_content()`로 회전 matrix를 content stream에 무손실 전사, `/Rotate=0`으로 리셋(90/270은 MediaBox/CropBox 폭·높이 스왑). 암호화 소스는 `ValueError`.
- `ensure_upright_pdf(pdf_path, case_cache, rotations)` — 캐시 게이트 래퍼. `.cache/<case>/upright/<stem>_upright.pdf` + 사이드카(schema_version+pypdf_version+source_sha256+rotations 4중 키). 정규화 불필요 전환 시 스테일 캐시 자동 제거. 메타데이터 마커로 이중 회전 차단.
- 예외 계약: 암호화는 **metadata 접근 전** `ValueError`("encrypted" 포함) — `pypdf.errors.FileNotDecryptedError`가 `OSError`/`ValueError`의 서브클래스가 아님을 실측 확인(오케스트레이터가 pypdf 6.6.2로 직접 재검증)하고 반영. 손상 PDF는 `PyPdfError` 계열 자연 전파.
- import는 `pypdf`+stdlib+`scripts.align_inputs`/`scripts.source_validator`만 직접 사용(PIL/pypdfium2 직접 import 없음 — 단 `align_inputs` 경유 전이적 PIL 로드는 알려진 사실로 독스트링에 명기).

### `scripts/annotate_pdf.py` (Modified — `annotate_case`만)

- 그룹 루프에 2단 폴백 추가: **1단** — `ensure_upright_pdf` 호출 실패 시(`OSError`/`ValueError`/`PyPdfError`) note 남기고 원본 PDF+기존 NoRotate 경로로 폴백. **2단** — legacy 경로조차 판독 불가능한(실제 암호화·손상) PDF는 해당 stem만 `skipped=True`로 스킵하고 형제 stem·케이스 반환은 정상 진행(변경 전에는 케이스 전체가 크래시했음 — 순수 개선).
- 정규화 사용 시 `write_annotated_pdf`에 `rotations={}`를 전달해 이중 회전 방지.
- summary `outputs[*]`에 `upright`/`skipped` 키 추가(기존 키는 유지 — additive-only).

### `tests/test_annotate_pdf.py` (Modified)

- `test_annotate_case_consumes_alignment_record` → `test_annotate_case_normalizes_alignment_rotation`으로 갱신(MediaBox 스왑, Square 좌표, `/Rotate=0` 등 신규 기대값). 나머지 66개는 무수정 통과.
- A1~A9 신규: 정렬 회전 정규화, 메타데이터 회전 정규화, 신·구 경로 시각 동등성(±2px), flat 스킵, 폴백(시뮬레이션+실제 암호화/손상 PDF 무목킹 E2E), 멀티-stem 격리, unresolved-stem 무영향.

### `skills/cert-review-annotate/SKILL.md` (Modified)

- "Annotation scope & style" Method 행, Phase C 좌표 관례 불릿, "Known Acrobat limitation" 블록을 업라이트 정규화 도입에 맞춰 갱신. 한계 서술은 "정규화 이전 산출물 또는 폴백 경로에 한정"으로 조건부 헤지(정규화 자체가 실패해 폴백을 타면 한계가 여전히 적용될 수 있음을 명시 — 계획 자신의 fail-open 설계와 모순되지 않도록).
- 금지어("burn-in", "--dpi") 미포함·필수어("norotate", "resize") 유지 확인(`test_skillmd_no_stale_wording` 통과).

## Verification

- `pytest tests/` 308 → **338 passed** (0 failed/0 error). 오케스트레이터가 독립 재실행으로 재확인.
- `git diff`로 `write_annotated_pdf` 및 좌표변환 6종·Square/Popup/FreeText 빌더 함수 **diff 0줄** 확인(AST 비교 + 오케스트레이터 직접 diff 검토).
- 실PDF E2E 3종(스크래치 `--out`, 기존 발급물 무영향): r-only(`PU2601565-1-MTC.pdf`, 23p 전부 `/Rotate=90`), a-only(`PU2601233-2-MTC.pdf`, 73p), 결합 r+a(`2026-246#-7.21.pdf` 기반 재구성 — 아래 "알려진 제약" 참조). 3종 모두 정규화 후 출력 전 페이지 `/Rotate==0` 확인.
- `output/reports/**/*_annotated.pdf` 기존 발급물 mtime/크기 불변 확인.
- 한국어 무결성: 수정 파일 7개 UTF-8 재독, mojibake 0건. 산출 PDF의 FreeText 라벨 문자열 재독 + 렌더 글리프 존재 확인.
- 사용자가 실물 Acrobat에서 3개 산출 PDF 직접 확인 — "annotation 목적에 맞게 정상 생성" 확인.

## 커밋 전 code-reviewer 검토

`oh-my-claudecode:code-reviewer`로 신규/변경 코드 검토(정확성/SOLID/스타일/성능). 이미 dh-dev 1-e 적대 검증을 거친 사실은 재검토 대상에서 제외하고 새 관점에 집중.

- **HIGH 1건(실증 재현·즉시 반영)**: `annotate_case`의 tier-2 폴백(`_FALLBACK_EXC`)이 `write_annotated_pdf` 내부의 의도적 hard-fail(폰트 누락, 출력 파일이 Acrobat에 열려 있어 쓰기 실패 등)까지 삼켜, 케이스 전체가 0개 주석으로 끝나도 CLI가 `[OK]`+exit 0을 반환하는 회귀를 리뷰어가 직접 재현. `cli.py:cmd_annotate`에 `skipped` 집계 로직을 추가해 `[WARN]`+exit 1로 표면화하도록 수정(위 표 참조) — 재수정 후 pytest 338개 재확인, 회귀 없음.
- **MEDIUM 4건(후속 커밋으로 분리, 리뷰어 권고 동일)**: 스킵된 stem의 `out_path`가 stale 산출물을 가리킴 / `n_pdfs` 카운트가 스킵 항목 포함 / 원본 PDF 이중 파싱(단일-parse 규약 위반) / 회전 클램프 로직이 `annotate_pdf.py`·`upright_pdf.py`에 축자 중복(주석으로만 강제).
- **LOW 6건**: `.tmp` 잔류 가능성, 부분 실패 시 로그 정보 손실, 변수명(`up_scar`), 문서-코드 문구 불일치, `pg.rotation` 이중 대입, 스크래치 파일 미정리(아래 참조).
- **Open Question(미채점)**: 주석 대상이 아닌 회전 페이지까지 전량 정규화하는 현재 설계가 의도된 트레이드오프인지(성능 영향 미실측) — 향후 대량 페이지 케이스에서 체감 시 재검토.

## 알려진 제약 (커밋 후에도 유효)

- **V4.3(결합 회전) 재현 파일의 출처가 재구성본**: 계획이 지목한 원본 소스(`2026-246#-7.21.pdf`, 케이스 PU2601233-03)가 실제로는 프로젝트에 존재하지 않아, `ref/` 폴더의 이미 주석 붙은 파일에서 `/Annots`를 제거해 역산 재구성했다(annotate가 순수 additive라는 아키텍처 보장에 근거해 타당한 방법). 이 파일의 1페이지는 실제 정렬 기록이 아닌 **합성 정렬값**(a=90)을 인위적으로 결합해 t=180 경로를 테스트한 것이라, 실제 프로덕션 데이터를 반영하지 않는다 — 코드 로직 자체(수학적 정합성)는 별도로 S1~S7 스파이크와 U1~U15 유닛 테스트로 독립 검증되어 있어 이 제약이 정합성 결론에 영향을 주지 않는다.
- 배포 캐시(`~/.claude/plugins/marketplaces` 클론) 동기화, `.cache/<case>/*`를 순회하는 타 유틸(`mill_cert.py`/`refpack.py`)의 `upright/` 서브디렉토리 영향 여부는 범위 밖 후속 확인 대상.
- 이번 커밋에는 이전 스파이크 단계에서 남은 untracked 정크 파일(`crop_norm.pdf` 등 10개, `skills/cert-review/` 최상위)이 스테이징되지 않음 — 필요 시 별도 정리.
