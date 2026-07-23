# cert-review-annotate Phase C: 이미지 burn-in → 네이티브 PDF 주석 오브젝트 전환

- **Date**: 2026-07-23 16:43:33
- **Plan**: [2026-07-23_160912_cert-review-annotate-native-pdf-annotations-v2](../plans/2026-07-23_160912_cert-review-annotate-native-pdf-annotations-v2.md)

## Summary

Phase C 렌더러(`annotate_pdf.py`)를 "주석 페이지 래스터화 + 이미지 번인"에서 **네이티브 PDF 주석 오브젝트 생성**으로 완전 교체. 사용자 요구: 이미지 주석은 변경·제거 불가 → 개별 삭제/이동/수정 가능한 진짜 주석으로.

- **Square**(verdict 색 테두리, 무채움) + **Acrobat 네이티브 빈 Popup 동반**(양방향 /Popup↔/Parent 링크 — 사내 검토자의 실제 Acrobat 주석 패턴(참조 PU2601564.pdf) 준수) + **FreeText 한글 라벨(자체 /AP)**.
- **자체 /AP** = 벡터 칩 + 4x 오버샘플 한글 글리프 이미지 XObject — 2026-06-29 burn-in 확정 사유였던 "pypdf 벡터 FreeText는 pdfium/브라우저에서 한글 미표시"를 정면 해결(pdfium 렌더 실측). CID 폰트 임베딩(저수준 파싱·fsType 라이선스·Acrobat 비대칭 리스크)과 NeedAppearances(AcroForm 전용)는 기각.
- **전 페이지 완전 copy-through**: `PdfWriter(clone_from=reader)` — 전 페이지 `/Contents` 바이트 원본 완전 동일(자동 검증), MediaBox/CropBox/Rotate 불변.
- **좌표**: 정렬 이미지 공간 fractional bbox → 사용자 공간 /Rect 역변환. T=(R+A)%360 4케이스(운영 실재 3조합 리터럴 고정) + CropBox 오프셋(케이스 46/62 실측) + 상속 /Rotate(PdfReader 평탄화 실측).
- CLI `annotate`의 `--dpi` 완전 제거(래스터화 소멸 — 전달 시 argparse 명시 에러). 신규 의존성 0(pypdf+Pillow+malgun.ttf — 기존 그대로).

## Changed Files

| File | Status | Description |
|------|--------|-------------|
| `skills/cert-review/scripts/annotate_pdf.py` | Modified (전면 재작성) | 네이티브 Square+Popup+FreeText(자체 /AP), 좌표 역변환, clone_from verbatim |
| `skills/cert-review/scripts/cli.py` | Modified | `annotate` `--dpi` 제거, help/docstring 갱신 |
| `skills/cert-review/tests/test_annotate_pdf.py` | Modified (재작성) | 39개: 순수 12 + 좌표 4회전/CropBox/상속·무결성·필드/Popup 왕복·경계·삭제·pdfium 렌더·정적 회귀 |
| `skills/cert-review-annotate/SKILL.md` | Modified | Phase C·Method·Colour·C1·Korean integrity를 네이티브 주석+Popup으로 갱신 |
| `requirements.txt` | Modified | 코멘트만(의존성 증감 0) |

## Workflow / Quality

- dh-dev: 1-d 계획(Fable 5) → 1-e 적대검증(contrarian/gap_hunter) **HIGH 4건 1회 수정 전건 반영**(FreeText 뷰어충돌→자체 /AP 설계 변경, R5 전제 실측 정정, CropBox 실측 리터럴, DoD-테스트 매핑 T7/T8 신설) → Step 2 Comment(Popup 패턴) → Step 3 실행(Opus 4.8) → 오케스트레이터 독립 재검증.
- /simplify 4렌즈 10건 반영: PDF 이중 파싱 제거(`clone_from=reader`), `_verdict_hex6` 중복 제거, `VALID_ROTATIONS` 재사용, 라벨 측정 단일화(`_chip_size_pt`가 /Rect·/BBox 단일 소스), pad 기본값 통일, FreeText 죽은 kwargs 제거, `pytest.approx` 전환, `--dpi` 가드 동작 검증화 등.

## Verification

- `pytest tests/test_annotate_pdf.py` **39 passed** / 전체 스위트 **238 passed**(회귀 0) — 실행·오케스트레이터 이중 확인.
- 실데이터 E2E 3케이스: PU2601233(73p, R=0/A=90)·케이스 46(3p, CropBox 오프셋 — /Rect 실측 리터럴 ±0.01 일치)·PU2601565-01(23p, R=90+A=270 혼재) — 전 페이지 콘텐츠 바이트 원본 동일, Square↔Popup 왕복 True, FreeText 삭제 후 무손상.
- 한글 무결성: /Contents 재독(`'주의: 한글 라벨 왕복 확인'` 등) 육안 + pdfium 렌더 글리프 픽셀 자동 확인. 모지바케 0건.
- 성능: 케이스 72(143p/58MB) 1.8초, +9KB.
- **잔여 위임**: 실사용 뷰어(Acrobat 권장)에서 (a) 한글 라벨 상시 표시 (b) 개별 선택·이동·삭제 (c) Square 클릭 시 Popup 스레드(참조 PU2601564.pdf와 비교) 육안 확인 — `output/reports/{PU2601233,46,PU2601565-01,72}/*_annotated.pdf`.
