# 2026-07-23 — chemistry_limits.csv SA-105 provenance 잠정 예외처리

**Summary**: `limits`/`validate-refs` CLI를 블로킹하던 SA-105 7개 행(C/Mn/Si/P/S/Cr/Mo)의 provenance 오류에 대해, CSV 값은 그대로 유지하고 provenance 검증만 명시적·추적 가능한 잠정 예외(`KNOWN_PROVENANCE_GAPS`)로 처리 — 매 로드마다 `[WARN]`으로 노출, 다른 576개 행의 검증 엄격도는 무변경.

## Rationale

**조사 결과**(같은 세션 직전 턴): `ref_code/output_sec2_pta_1of2/ASME_SEC_II_PTA_1of2_2023/SA-105_SA-105M.md`의 221~224페이지 원문 OCR 자체가 환각(hallucination) 상태 — 문법이 깨진 의미불명 문장, "SA-106/SA-106M"·"SA-102/SA-106M"(존재하지 않는 조합) 오표기 러닝헤더가 SA-105 페이지 구간에 새어 들어와 있음(진짜 SA-106은 225페이지부터). 이 손상은 raw OCR(`raw_pages/pages_0221-0225.md`) 단계부터 존재하며, 5개 독립 위치(testbed/Cert_Auto_examine/hermes-loop/sample_docs/work)에서 바이트 단위로 동일 — 이번 세션 작업과 무관한 선재 이슈. `validate-refs` 전수 검증(583행) 결과 실패는 이 7행이 전부이며, CSV의 SA-105 수치(C 0.35max, Mn 0.60–1.05, Si 0.10–0.35, P 0.035max, S 0.040max, Cr 0.30max, Mo 0.12max)는 잘 알려진 실제 ASTM A105/A105M Table 1 기준과 일치 — CSV 자체는 정확할 가능성이 매우 높고, 근거로 삼아야 할 원문 텍스트 쪽이 깨진 것으로 판단.

**사용자 지시**: "CSV 값 유지하고 provenance만 잠정 예외처리." 원본 PDF가 프로젝트 내에서 발견되지 않아 즉시 재OCR은 불가능한 상태이므로, 데이터를 수정하거나 근거 없이 스니펫을 조작하지 않고(허위 provenance 생성 금지 — C2/C8 원칙), 검증 계층에 좁고 추적 가능한 예외를 추가하는 방식으로 구현.

## Changed Files

| 파일 | 상태 | 설명 |
|---|---|---|
| `skills/cert-review/scripts/source_validator.py` | modified | `KNOWN_PROVENANCE_GAPS` 신설 — (csv 파일명, grade, element, analysis) 키의 명시적 allowlist. `ValidationResult`에 `waived`/`waiver_reason` 필드 추가. `_check`/`validate_csv_row`/`validate_csv_file`가 `csv_name`을 받아 스니펫 미발견 시 이 목록만 조회(다른 실패 사유엔 미적용) |
| `skills/cert-review/scripts/refdata_loader.py` | modified | `load_csv`가 waived 행을 정상 로드하되 매 호출마다 `[WARN]`을 stderr에 출력(결코 무음 처리 안 함). strict 예외는 waived 아닌 실패가 하나라도 있으면 그대로 발생 |
| `skills/cert-review/scripts/cli.py` | modified | `cmd_validate_refs`가 `csv_name`을 전달하고 waived 건수·사유를 `[WARN]`으로 출력, 파일별/전체 요약에 "N waived" 표기 |
| `skills/cert-review/tests/test_source_validator.py` | modified | waiver 매칭(성공)·미매칭(element 불일치)·csv_name 미스코프(성공 안 함)·gap 목록 자체 검증 4건 추가 |
| `skills/cert-review/tests/test_refdata_loader.py` | added | `load_csv`의 strict 예외 유지, waived 행 로드+경고 출력, waived와 비waived 실패 혼재 시 여전히 raise, 무관 CSV는 경고 없음 4건 |

## Details

### 설계
- **키는 (csv 파일명, grade, element, analysis)** — 라인 번호가 아니라 내용 기반 키라 CSV 행 순서가 바뀌어도 안전. `chemistry_limits.csv`의 SA-105 7개 원소(C/Mn/Si/P/S/Cr/Mo)만 정확히 리스트됨 — V는 이미 통과하므로 목록에 없음, Ni 등 다른 원소는 여전히 엄격 검증.
- **불투명 예외 금지**: `load_csv` 호출마다 `[WARN]`을 출력하고, `validate-refs`도 파일별 "(N waived)" 표기 + 사유 전문을 출력 — 예외가 눈에 띄지 않게 통과하는 경로는 없음.
- **범위 최소화**: 스니펫-미발견 실패 지점에서만 조회. 필드 누락·source_file 부재 실패는 이 예외로 구제되지 않음(진짜 손상된 인용은 여전히 차단).
- **CSV 데이터 무변경**: `data/chemistry_limits.csv`는 한 바이트도 건드리지 않음 — 사용자 지시대로 값 유지.

### 검증
- `pytest` **217 passed**(기존 209 + 신규 8).
- `validate-refs` 실행: `[OK] chemistry_limits.csv: 361 rows, 361 valid, 0 failed (7 waived)` + 각 행 사유 전문 출력, 전체 `[OK] 7 CSVs validated, 583 total rows, 0 failures, 7 waived`.
- `limits --case 10`, `limits --case 4` 둘 다 이전엔 `MissingProvenanceError`로 크래시했으나 이제 정상 완료(52/17/... 행 로드), `[WARN]` 7건이 실행마다 눈에 보이게 출력됨을 직접 확인.
- `git status` — `data/*.csv` 무변경 확인, 5개 파일만 스테이징 대상.

### 향후 과제
- SA-105_SA-105M.md 221~224페이지 원본 PDF 확보 후 재OCR — 완료되면 `KNOWN_PROVENANCE_GAPS`의 해당 7개 항목 제거(주석에 명시됨).
- 이번 조사 중 발견된 부수 신호(SA-249/SA-320/SA-372/SA-376 등 러닝헤더 불일치)는 현재 어느 CSV에서도 인용되지 않아 조치 불필요하나, 향후 새 grade 추가 시 같은 패턴 재확인 권장.
