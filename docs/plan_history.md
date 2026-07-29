# Plan History

| Date | Plan | Status |
| --- | --- | --- |
| 2026-07-28 | [annotate 직전 페이지별 업라이트 정규화 전처리 (Acrobat 핸들 UI 불일치 구조적 제거)](plans/2026-07-28_162707_annotate-upright-normalization.md) | Completed (v1.8.0, 커밋 5d23ece+push 완료, pytest 308→338, DoD 25건 중 24건 자동 검증 통과·DoD-19는 사용자 실물 Acrobat 확인 완료("정상 생성"). 커밋 전 code-reviewer HIGH 1건(tier-2 폴백이 전량 실패도 OK로 보고) 발견·즉시 반영) |
| 2026-07-28 | [annotate_pdf.py FreeText 라벨 NoRotate 전환 (회전 페이지 라벨 세로 뒤집힘 근본 수정)](plans/2026-07-28_113240_annotate-freetext-norotate-rotation-fix.md) | Completed (커밋 9e3cd1f, pytest 280→308, D1~D18 중 D16(Acrobat 실제 리사이즈)만 사용자 수동 확인 대기, 나머지 17개 자동 검증 통과) |
| 2026-07-23 | [동봉 원자재 성적서(MILL CERT) 검증 도메인·에이전트 추가(기준 21/22)](plans/2026-07-23_183734_mill-cert-review-domain.md) | Completed (v1.7.0, 커밋 008b357, pytest 280/280, DoD-a 10/10 + E2E 5/5 — PU2601564 단조 인장 전사복제 FAIL 재현) |
| 2026-07-23 | [MPS 요구사항 대비 동봉 문서 첨부 자동판정(기준 20)](plans/2026-07-23_091508_mps-required-attachment-judgement.md) | Completed (v1.5.0, DoD 10/10, pytest 208/208, 실물 E2E PU2601565-01 AC-5·6 통과·ladder A/B/C/D 검증) |
| 2026-07-22 | [혼입 문서 페이지 분류(Phase 1.6 doc-classify) 및 비교 제외 — 1단계](plans/2026-07-22_170520_mtc-doc-classification-phase16.md) | Completed (DoD 10/10, pytest 184/184 독립 재검증, 커밋 8d38090+4433fd1, push 완료) |
| 2026-07-09 | [페이지 회전 정렬(문서 정렬 에이전트) — OCR 이전 페이지별 방향 교정](plans/2026-07-09_085623_page-orientation-alignment.md) | Completed (v1.3.0, pytest 145/145, opus 채택 95.89%) |
| 2026-07-01 | [OCR 모델 A/B — Sonnet 5 vs Opus 4.8](plans/2026-07-01_ocr-model-ab-sonnet5-vs-opus48.md) | Completed (Opus 4.8 유지) |
| 2026-06-29 | [판정 문구 일원화 및 색상 미적용 해결](plans/2026-06-29_verdict-unify-color-fix.md) | Completed |
