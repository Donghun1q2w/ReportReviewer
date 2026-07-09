# 2026-07-09 — 페이지 회전 정렬(Phase 1.5) 기능 추가

**Summary**: OCR 이전 단계에 페이지별 회전 감지(page-aligner 에이전트)·교정(align-inputs CLI)을 편입 — 스캔이 페이지별로 회전 혼재된 성적서도 타일링·OCR·crop·annotate가 정렬 좌표계에서 일관 동작.

**Plan**: [2026-07-09_085623_page-orientation-alignment](../plans/2026-07-09_085623_page-orientation-alignment.md) (Rev.1 승인: MPS 제외 + 모델 순차 벤치마크)

## Rationale

PU2601233-2-MTC.pdf(73p) 실측: 메타데이터 /Rotate는 전부 0인데 스캔 내용이 51페이지 90° 회전·22페이지 정방향으로 혼재. 회전 페이지에서 2×2 타일 의미론(r0=헤더)과 Vision 판독 정확도가 붕괴하고, crop/annotate의 fractional bbox 좌표계도 불일치.

## Changed Files

| 파일 | 상태 | 설명 |
|---|---|---|
| `skills/cert-review/scripts/orient_sheets.py` | added | 컨택트시트 생성(3×4 썸네일+정방향 라벨, cert 전용), stem별 시트 재생성 시 잔존물 정리 |
| `skills/cert-review/scripts/align_inputs.py` | added | 회전 적용 CLI 엔진 — 페이지별 2단계 커밋(temp→기록→원자적 교체, 크래시-세이프 멱등), stem 커버리지 게이트, crop/annotate용 `applied_rotations` 조회 |
| `agents/page-aligner.md` | added | 문서 정렬 에이전트(Phase 1.5, claude-opus-4-8 — 블라인드 A/B로 선정), 시계방향 회전각 판정 규칙·uncertain 보수 폴백 |
| `skills/cert-review/scripts/cli.py` | modified | `orient-sheets`/`align-inputs` 서브커맨드, align 게이트 계약(exit 0 필수) |
| `skills/cert-review/scripts/prep_inputs.py` | modified | 재렌더 전 정렬기록 삭제+구 페이지 아티팩트 purge(축소 PDF 유령 페이지 방지), sidecar `rotations: null` 스탬프(정렬 대기 마커) |
| `skills/cert-review/scripts/extraction_check.py` | modified | 캐시 게이트에 `alignment_pending`(rotations null → stale) 추가 — `--force`/`--dpi` 재렌더 홀 봉인, 구버전 sidecar(키 부재)는 기존 의미 유지 |
| `skills/cert-review/scripts/tile_inputs.py` | modified | `_stems_in_png_dir` glob→정규식 (100p+ 3자리 페이지 인식) |
| `skills/cert-review/scripts/crop.py` | modified | 렌더 후 적용 회전 재현 → bbox를 정렬 좌표계에서 해석(하위호환) |
| `skills/cert-review/scripts/annotate_pdf.py` | modified | `render_annotated_pdf(rotations=)` + annotate_case가 alignment 기록 소비, 회전 원본의 주석 면은 정방향 래스터로 산출 |
| `skills/cert-review/SKILL.md` | modified | 에이전트 7→8종, Phase 1.5 시퀀스(orient→delegate→align)·게이트·캐시 표·흐름도·시간예산 ⑥ |
| `agents/ocr-extractor.md` | modified | 사전 정렬 전제 + 회전 타일 발견 시 전사 금지·보고 1줄 |
| `README.md` · `.claude-plugin/marketplace.json` | modified | 특징·CLI·구조·에이전트 표 갱신, v1.2.0→**1.3.0**, 테스트 수 145 정정 |
| `docs/orient-model-selection-2026-07-09.md` | added | 모델 벤치마크 결과 문서 |
| `tests/test_align_inputs.py`(15) · `test_orient_sheets.py`(8) | added | 마커픽셀 방향·멱등·크래시 복구·커버리지 게이트 / 시트 배치·100p+·재생성 정리 |
| `tests/test_prep_cache.py`(+5) · `test_crop.py`(+2) · `test_annotate_pdf.py`(+2) · `test_tile_inputs.py`(+1) · `test_extraction_check.py`(+2) | modified | 정렬기록 수명주기·좌표계·캐시 3상태·축소 purge 회귀 |

## Details

### 적대적 리뷰(53 에이전트, 5차원×3스켑틱) 확정 결함 6종 → 전부 수정
1. **align 중단 시 이중회전(major)** → 페이지별 2단계 커밋 + 원자적 기록(os.replace) + 페이지별 예외 격리(failed_pages)
2. **`--force` 재렌더 후 fresh 오판(major)** → sidecar rotations 3상태(부재=구버전 OK/null=정렬 대기→stale/dict=완료)
3. **정렬 커버리지 계약 부재(major)** → png stem 대조 `uncovered_stems` + CLI exit 1 게이트
4. **100p+ 페이지 인식 불가(major)** → 정규식 인벤토리 (extraction_check와 동일 기준)
5. **재렌더 잔존물(minor)** → 렌더 전 기록 삭제 + 유령 페이지/타일/시트 purge
6. **README 수치 불일치(minor)** → 145 기준 정정

### 검증
- `pytest tests/` **145 passed** (기존 111 + 신규 34, 회귀 0), C1 가드 통과, py_compile 전 모듈 OK.
- **E2E (PU2601233, 73p)**: prep→orient-sheets(7시트)→page-aligner(opus)→align-inputs(51p 회전, exit 0)→tile-inputs(292타일). 재실행 멱등(0 rotated/51 already-applied). read-back 육안: 회전됐던 p01·20·50·51 정방향 복원, 정방향 p30·60 보존, r0 타일 헤더 의미론 복원, 모지바케 0.
- **모델 벤치마크(블라인드, GT=오케스트레이터 픽셀 실측 73p)**: opus 4.8 **95.89%**(오분류 3건 전부 uncertain 플래그 보수 무회전) / sonnet 30.14%(방향 반전 270° 12건 포함) / haiku 30.14%(전 페이지 0°) → **opus 채택**. 상세: [orient-model-selection-2026-07-09](../orient-model-selection-2026-07-09.md).

### 배포 동기화 (후속)
- 코드(scripts/*.py)는 배포본 통째복사 가능. `agents/page-aligner.md`·SKILL.md는 배포본 KO 에디션 별도 반영 필요(통째복사 금지).
