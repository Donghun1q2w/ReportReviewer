# OCR 에이전트 모델 A/B — Sonnet 5 vs Opus 4.8 (실측 후 우수 모델 교체)

- **Date**: 2026-07-01
- **Status**: Completed (2026-07-01) — 결과: **Opus 4.8 유지** (Sonnet 5 화학 배율 해석 실패). 상세: [ocr-model-ab-2026-07-01-results](../ocr-model-ab-2026-07-01-results.md)
- **Target agent**: `plugin/ReportReviewer/agents/ocr-extractor.md` (현재 `model: claude-opus-4-8`)
- **요청**: plug 내부 OCR agent에 대해 sonnet 5 와 opus 4.8 성능을 실측 비교하고, 성능이 좋은 모델로 교체.

---

## 1. 배경 · 선행 근거 (반드시 반영)

- OCR 에이전트(`ocr-extractor`)의 **유일한 책임은 전사(transcription)** 이다 — PNG 타일을 Claude Vision으로 읽어 `<stem>_extracted.json`을 생성. 판정/비교/보고서는 하위 5개 reviewer의 몫. 따라서 **OCR 에이전트의 "성능" = 전사 정확도(특히 숫자·식별자)** 이다.
- **선행 실측 근거 (auto-memory)**: 과거 전 에이전트를 opus 4.8로 고정하며 *"sonnet/haiku 실측 탈락"*, *"병목은 opus 숫자 검증이 본질"* 로 기록됨. 즉 이전 세대 sonnet은 이미 한 번 탈락한 이력이 있음. 본 작업은 **신형 Sonnet 5**로의 재검증이므로 정당하나, 이 선행 근거 때문에 **숫자 셀 정확도를 결정 기준의 최우선**으로 둔다.
- 모델 교체 메커니즘: SKILL.md L67 — `CLAUDE_CODE_SUBAGENT_MODEL` 환경변수가 frontmatter `model`을 오버라이드. 벤치마크 시에는 Agent/Workflow `model` 파라미터(`opus`=Opus 4.8, `sonnet`=Sonnet 5)로 **동일 지침을 두 모델에 태워** 모델만 격리 비교한다.
- 46개 전 케이스에 opus 4.8 베이스라인 캐시(extracted.json + tiles)가 이미 존재 → **PDF 재렌더링 없이 즉시 A/B 가능**. 선행 통제실험 전례(`.cache/4_smoke_opus300`, `4_tiling_run`, `4_digest_run`, `4_verified_baseline`)와 동일하게 **모델 접미사 캐시 파티션**으로 격리한다.

---

## 2. 벤치마크 설계 (모델 격리 · 전사 정확도 중심)

### 원칙
동일한 캐시 타일(`.cache/<case>/tiles/`)을 입력으로, **byte-identical한 ocr-extractor 지침**을 opus·sonnet 두 모델에 각각 태운다. 출력은 서로 다른 파일에 저장하여 베이스라인을 덮어쓰지 않는다:
- opus → `.cache/<case>/<stem>_extracted__opus.json`
- sonnet → `.cache/<case>/<stem>_extracted__sonnet.json`

### Phase A — 전사 A/B (fan-out)
케이스 × 모델 각 조합에 대해 ocr-extractor 지침 + delegation context(case id, skill dir 절대경로, mode=full, 모델 접미사 출력경로)를 태워 전사 실행. 각 케이스는 opus/sonnet가 **완전히 동일한 타일**을 읽는다.

### Phase B — 판정(adjudication) 및 채점
케이스별로 `__opus.json` vs `__sonnet.json`를 **결정적 필드**에서 diff:
- header 식별자: cert_no, grade, heat_no, size_od_wt, quantity
- chemistry: element별 value (소수 정밀도 — **최우선 채점 대상**)
- mechanical: TS/YS/EL/RA/hardness/impact
- heat_treatment: 단계별 temp/time
- nde: 수행여부·notch·결과

**불일치(disagreement) 셀마다** 판정 에이전트가 실제 PNG 타일을 열어(육안 GT) 어느 값이 맞는지 재정한다(둘 다 오독 가능). 이로써 모델별 *숫자 셀 정확도*, *식별자 정확도*, *전체 셀 일치율*을 산출.

### Phase C — 엔드투엔드 recall/precision 확인 (선택 · 사용자 스코프)
숫자 결정적 케이스 소수(2건)에 대해 각 모델 전사물을 **opus 고정 5 reviewer**에 태워 → merge-reviews → `evaluate` → recall/precision을 GT(comments.md)와 비교. "전사 차이가 실제 finding을 움직이는가"를 확인 (OCR 품질을 최종 지표에 투영).

### 시간·비용 측정
정확도가 결정 기준이나, 부차 지표로 모델별 상대 wall-clock(단계 로그 기준 집계)과 토큰량을 기록. (Sonnet은 구조적으로 빠름 — 관건은 "숫자 OCR에서 opus를 대체할 만큼 정확한가".)

---

## 3. 대상 케이스 (권장: 난이도 스펙트럼 + 숫자 결정 P9x 가중)

| 케이스 | 페이지 | grade | 선정 이유 |
|---|---|---|---|
| 10 | 1p | WP91-S | 단순 P91 fitting (베이스라인) |
| 73 | 1p | F92 | 단순 F92 단조품 |
| 26 | 2p | A105 + F91 | 혼합 grade, 표준 난이도 |
| 52 | 3p | SA193-B7 | 수치 mechanical 이슈 이력(TS 412) |
| 36 | 6p | **P92** | 제한화학(Cr 8.73 등 소형 숫자) — **숫자 OCR 결정적** |
| 4 | 9p | **P91/P92/P11/P22 다중** | 최난도 복합 케이스(기존 실험 스캐폴드 보유) |

- 합계 ≈ 22페이지 × 2모델 = 44 전사. P9x 제한화학 비중을 높여 "opus 숫자 검증 병목" 가설을 정면으로 검증.
- **스코프는 사용자 결정 사항** — 케이스 수(빠른 3건 ~ 권장 6건 ~ 광범위)와 Phase C 포함 여부에 따라 비용이 크게 달라짐.

---

## 4. 결정 규칙 (decision rule)

- **교체(Sonnet 5 채택)**: 숫자 셀 정확도 및 식별자 정확도에서 sonnet 5 ≥ opus 4.8 (결정적 셀에서 유의미한 퇴보 없음) **AND** (Phase C 수행 시) recall/precision 비퇴보. → `ocr-extractor` frontmatter `model`을 `claude-sonnet-5`로 교체.
- **유지(Opus 4.8 유지)**: sonnet 5가 숫자 셀에서 퇴보(예: 소수점·자릿수 오독으로 화학/기계 값 오류) → opus 유지 + 신형 sonnet 재검증 근거를 문서화(선행 근거 갱신).
- 동률에 가까우면 속도/비용 이점을 tie-breaker로 고려하되, **정확도 퇴보가 있으면 속도 이점은 무효**(성적서 검토는 정확도 우선 도메인).

---

## 5. 구현 단계 (승인 후 Step 3)

1. **사전 게이트**: 대상 케이스의 tiles 존재 확인(없으면 `prep-inputs`+`tile-inputs` 결정적 재생성 — 모델 무관).
2. **Phase A 워크플로**: 케이스×모델 fan-out으로 전사 → 모델 접미사 JSON 저장. ocr-extractor.md 본문을 프롬프트로 그대로 사용(모델만 차등).
3. **Phase B 채점 스크립트 + 판정 에이전트**: 결정적 필드 diff(결정적 Python) → 불일치 셀만 PNG 재독 판정 에이전트로 재정 → 모델별 정확도 집계.
4. **Phase C(선택)**: 2건 엔드투엔드 eval.
5. **결과 리포트**: `docs/`에 A/B 결과표(모델별 정확도·불일치 목록·시간/토큰) 산출.

## 6. 교체 절차 (Step 4 · sonnet 채택 시 동기화 지점)

- `plugin/ReportReviewer/agents/ocr-extractor.md` frontmatter `model` 교체.
- `skills/cert-review/SKILL.md` — 서브에이전트 표(L57)의 `ocr-extractor` 모델 표기 및 "all agents use claude-opus-4-8" 문구를 정합하게 수정(OCR만 분리).
- **배포본 동기화(메모리 분기 규칙 준수)**: 코드가 아닌 agents/SKILL은 EN(플러그인)/KO(배포본) 통째복사 금지 — 배포본 `.claude/skills`의 해당 에디션은 model 라인만 개별 반영.
- `docs/revision_history.md` 항목 추가, `docs/plan_history.md` Completed 갱신, 커밋 제안.

---

## 7. Acceptance Criteria

- [ ] Phase A: 대상 전 케이스에서 opus/sonnet 전사 JSON이 동일 타일 기준으로 생성됨(페이지 수 일치).
- [ ] Phase B: 결정적 필드 diff + 불일치 셀 PNG 재독 판정 완료, 모델별 숫자/식별자 정확도 수치화.
- [ ] 결정 규칙에 따른 **명확한 승자 판정** + 근거 표.
- [ ] (교체 시) frontmatter/SKILL/배포본 동기화 + 회귀 무결(`pytest`) 확인 + Korean 무결성 read-back.
- [ ] 결과·결정이 `docs/`에 기록되고 auto-memory 선행 근거가 갱신됨.

---

## 8. 리스크 · 완화

| 리스크 | 완화 |
|---|---|
| 육안 GT 판정도 오독 가능 | 판정은 고DPI 원본 PNG(타일 아닌 원본)로 재독, 애매하면 `crop` CLI 고DPI 확대 |
| 케이스 편향(소수 표본) | 난이도 스펙트럼 + P9x 숫자결정 가중으로 대표성 확보; 필요 시 케이스 확장 |
| Phase A 비용(복합 케이스 60~90분/건) | 스코프 사용자 승인; 캐시 재사용으로 렌더링 비용 0 |
| sonnet/opus 지침 동일성 훼손 | ocr-extractor.md 본문을 두 모델에 byte-identical로 주입, 출력경로만 차등 |
