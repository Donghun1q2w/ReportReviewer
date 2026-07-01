# OCR 에이전트 모델 A/B 결과 — Sonnet 5 vs Opus 4.8

- **Date**: 2026-07-01
- **Plan**: [2026-07-01_ocr-model-ab-sonnet5-vs-opus48](plans/2026-07-01_ocr-model-ab-sonnet5-vs-opus48.md)
- **대상**: `agents/ocr-extractor.md` (Phase 2 Claude Vision 전사 전담)
- **결론**: **Opus 4.8 유지. Sonnet 5로 교체하지 않음.** (이미 설정된 opus 4.8이 우수 모델로 재확인됨)

---

## 1. 방법 (모델 격리 A/B)

- 8개 cert stem(케이스 10·73·26·52·36×2·4×2, 총 22페이지·88 타일)에 대해 **동일한 캐시 타일**에 **byte-identical한 `ocr-extractor.md` 지침**을 opus 4.8 / sonnet 5에 각각 태워(모델만 차등) 전사.
- 출력은 `__opus.json` / `__sonnet.json` 접미사로 분리 저장(베이스라인 비파괴). `.cache/`는 gitignore.
- 결정적 필드(header 식별자·chemistry element값·mechanical 수치·HT temp/time·NDE)를 페이지 정렬 후 diff → 불일치 셀을 **실제 PNG 재독으로 육안 판정**.
- 실행: 워크플로 fan-out(16 에이전트), 세션 effort 동일(xhigh) 양쪽 적용.

## 2. 정량 결과

| 지표 | 값 |
|---|---|
| 전체 셀 일치율(양쪽 존재) | **791/874 = 90.5%** |
| 값 불일치 | 83 (nde 56 · header 13 · **chemistry 11** · mech 3) |
| presence-only | opus측 75 / sonnet측 33 |
| 출력 토큰 | opus **255,254** / sonnet **249,136** (≈동일, 2.4% 차) |

- **presence-only의 대부분은 실제 누락이 아니라 키 명명 아티팩트** — 예: opus `ht.NORMALIZING (915±15°C).temp_C=915` vs sonnet `ht.NORMALIZING.temp_C=915`는 **동일 데이터**를 다르게 키잉한 것(HT 온도/시간 값은 양쪽 일치). NDE 테스트명 철자(`VISUAL_DIMENSIONAL` vs `VISUAL_DIMENSIONS`)도 동일. **sonnet이 데이터를 체계적으로 누락하지 않음.**
- **값 불일치의 대부분은 cosmetic** — NDE 결과 표현 상세도(`100%UT ASTM E213; 100% Acceptable` vs `100% Acceptable`), cert_no 하이픈 간격(`DL - 26 - 045 - 1` vs `DL-26-045-1`), vendor 끝 마침표. 양쪽 다 올바르게 판독, 포맷만 다름. 일부 header에서는 오히려 sonnet이 더 완전(`F91(Type1)`, spec 접미사 포함).

## 3. 판정: 진짜 수치 불일치(PNG 육안 재독)

| 분쟁 | Cert 실제(PNG 확인) | 판정 |
|---|---|---|
| **c4(SA106C) chemistry 11셀** | cert에 `×100`/`×1000` 배율 헤더 존재. 실제 C=0.2, Mn=1.16, Cr=0.24, Mo=0.0041 (A106C 물리 타당) | **opus 정답 / sonnet 오답** — sonnet은 배율 미적용 원시 정수 저장(C=**20**, Mn=**116**, Cr=**24**) → 물리적으로 불가능(탄소 20%, Mn 116%>100%). 두 모델 모두 Cev=0.445를 계산했으나 sonnet만 원소 필드에 원시값을 저장한 **내부 불일치** |
| c26 p2 hardness 144/141 | cert에 `141 , 144` 두 값 인쇄 | **TIE** (둘 다 cert 값; 대표값 선택 차이) |
| c36 s1 p3 hardness 231/232 | cert에 `231 231 232` 세 값 인쇄 | **TIE** (둘 다 정독; opus=최빈값 231) |
| c36 s2 p3 hardness 231/226 | (다중 판독값 패턴, 저위험) | 실질 TIE |

- opus는 P22/P11/P91/P92/SA106C **전 stem에서 배율(×100/×1000)을 일관되게 정확 적용**. sonnet은 7 stem에서는 정상이었으나 **가장 복잡한 다중배율 표(c4 SA106C sub-cert)에서 실패**.

## 4. 결정 근거

성적서 검토는 **화학성분 정확도가 최우선인 안전-critical 도메인**이다. Sonnet 5는 대부분 opus와 대등(90.5% 일치, HT/NDE/식별 사실상 동일, 토큰량 유사)하나, **8 stem 중 1개에서 화학 배율 해석 실패로 11개 원소를 100×/1000× 오류**를 냈다. 이는:

- 하위 chemistry-reviewer에 물리적으로 불가능한 값(C=20%, Mn=116%)을 넘겨 **다수의 오탐 finding**을 유발하거나, `_correct_chemical_scale` **안전망에 의존**하게 만든다(안전망은 backstop이지 primary 경로가 아니며 모든 케이스를 잡는다는 보장이 없다).
- 계획의 tie-breaker 규칙("정확도 퇴보가 있으면 속도 이점은 무효")에 해당 — 게다가 토큰량 이점도 사실상 없음.
- 선행 실측 근거("병목은 opus 숫자 검증이 본질", "sonnet 실측 탈락")를 **Sonnet 5 재검증으로 재확인**.

→ **ocr-extractor 모델은 opus 4.8 유지.** frontmatter/SKILL 변경 없음.

## 5. 재현 산출물

- 전사 산출물: `.cache/<case>/<stem>_extracted__{opus,sonnet}.json` (gitignore, 벤치마크 참조용)
- diff 원자료: `scratchpad/ocr_ab_diff.json`, 채점 스크립트 `scratchpad/diff_extractions.py`
- 판정 근거 PNG: c4 p1 `tiles/..._p01_r0c0.png`(×100/×1000 헤더), c26 p2 / c36 s1 p3 `tiles/..._r1c1.png`(hardness 다중값)

## 6. 후속(선택)

- Sonnet 5를 **reviewer(비-OCR) 역할**에는 별도 검증 여지 있음(판정 로직은 숫자 배율 해석 부담이 낮음). 단 본 A/B 범위 밖.
- 화학 배율 오류를 근본 차단하려면 추출 스키마/에이전트에 "원시값 저장 금지, 반드시 실제 wt%로 정규화" 자기검증 1줄을 강화하는 방안(모델 무관 개선) 고려 가능.
