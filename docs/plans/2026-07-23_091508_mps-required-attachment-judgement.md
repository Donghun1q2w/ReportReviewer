# MPS 요구사항 대비 동봉 문서 첨부 자동판정(기준 20) — 구현 계획

- **작성**: 2026-07-23 09:15 (전담 플래닝 에이전트, Fable 5, dh-dev Step 1-c)
- **상태**: Pending Review (사용자 검토 대기 — dh-dev Step 2)
- **대상**: `plugin/ReportReviewer` (단일 소스, `git@github.com:Donghun1q2w/ReportReviewer.git`, main). 스킬 디렉토리 = `skills/cert-review/` (이하 SKILL_DIR). 모든 경로는 저장소 루트 기준.
- **선행 작업**: Phase 1.6 doc-classify (커밋 8d38090/4433fd1, v1.4.0, `docs/plans/2026-07-22_170520_mtc-doc-classification-phase16.md`) — 그 계획 1.5절 "향후 과제"로 분리했던 **"MPS/규격 요구 대비 동봉 문서 첨부 여부 자동판정"**이 이번 범위다.

> **조사 재검증 결과 요약 (이 계획이 직접 확인)**
> - `scripts/doctype.py:153-183` `excluded_documents_for_case`의 현재 필드는 `stem, doc_type, doc_type_ko, pages, page_range, note`뿐 — heat/품목 식별자 없음 (인용 정확).
> - `scripts/merge_reviews.py:293-306` — `excluded_documents`는 결정적 주입, findings 미오염 (인용 정확).
> - `agents/mps-extractor.md` — PMI 100%·MT/PT 트리거는 **`nde_microstructure` 블록(81행)**, EN 10204·체크리스트(X marks)는 **`document_requirements` 블록(82-83행)**. 두 블록 분리 확인. digest 항목 형태는 `{requirement|item, value, text, source}` (`.cache/10/10_mps_digest.json` 실측).
> - `agents/nde-reviewer.md` — 본문 인쇄 PMI 값 판정 기능 실존 (`.cache/4/4_review_nde.json`: `"item":"PMI","cert":"100%PMI Acceptable","verdict":"PASS"` 9건). PMI 요구 출처는 `data/nde_rules.csv`(P11/P22/P91/P92만 `PMI | 100% 수행` 행 보유) + digest `nde_microstructure`.
> - `references/review-criteria.md` — 기준 17.1 "별도 문서" 규칙(330행), 기준 19.3 "OUT OF SCOPE … deferred to future work"(416-418행) 인용 정확. 단순 신설 시 자기모순 — 개정 필수.
> - **실물 페어링 확정 (이번 조사의 신규 성과)**: 이전 세션에서 실패했던 MPS 페어링을 찾았다. MTC와 MPS가 **같은 프로젝트 폴더 체계**에 실존한다:
>   - MTC: `D:\001_Work\2026\033_성적서 검토\Cert_Auto_examine\MTC\P260017-01_MHI_Tallgrass\PU2601565-01\PU2601565-1-MTC.pdf` (23p, 9.4MB)
>   - MPS: `D:\001_Work\2026\033_성적서 검토\Cert_Auto_examine\MPS\04. MHPS\P260017-01_MHI_Tallgrass\2. MPS\MPS-SH-MTA-A234WPB&C.PDF` (2p) + `MPS-SH-MTA-A234WP22.PDF` (2p) — 서명·직인 스캔본, 프로젝트명 "TALLGRASS ILS WY POWER GENERATION, USA" 일치 육안 확인.
>   - MTC 육안 검증: p.1 완제품 성적서(LS룽산, A234-WPB-S, Heat 14328912, PO PU2601565-003/004/017/018), **p.22 자분탐상 보고서(NDE_REPORT — 90° 회전, 炉号 Heat No. 열 보유: WF24088280Z·14328912·25C05594·25D201950·22D105372·23215117·24088676Z 등)**, **p.23 PMI 보고서(PMI_REPORT — Heat 열 없음, P/O NO. 열만: PU2601565-039, A234-WP22 CL.1-S)**.
>   - MPS 육안 검증: 두 MPS 모두 Special Requirements item 14 "**100% MT/PT is required on end preparation (end bevel surface) for butt weld**" 요구, item 5 "Dimensional checks", item 6/7/8 문서요건 표(X marks). **PMI 요구는 두 MPS 모두 없음** — 즉 p.23 PMI 보고서는 "요구 없는 자발 첨부"로, **과잉판정(요구 없는데 미첨부/첨부 finding 발행) 방지**를 실물로 검증하는 최적 소재.

---

## 1. Requirements Summary

### 1.1 문제

Phase 1.6이 동봉 문서를 분류·제외까지는 하지만, **"MPS가 요구하는 별도 시험보고서(PMI/NDE/치수 등)가 실제로 첨부되었는가"는 판정하지 못한다.** 현재 기준 17.1은 "별도 문서 존재를 확인할 수 없으면 finding 생략"이므로, 요구 문서가 통째로 누락돼도 무증상 통과한다. 반대로 nde-reviewer가 본문 인쇄값 부재를 근거로 미기재 finding을 낼 때, 실제로는 별도 첨부 보고서가 존재하는 경우 오탐이 된다.

### 1.2 사용자 확정 스코프 (변경 불가)

1. **매칭 정밀도 = 품목(heat) 단위.** `excluded_documents[]` 스키마를 확장해 각 동봉 문서가 어느 heat_no/품목에 대한 것인지 판독·기록한다. 판독 주체는 **doc-classifier**. 케이스 단위 존재여부만 보는 얕은 매칭은 기각(다품목 오판정 위험).
2. **실물 1건 harness 반입 + 실동 E2E 검증 포함.** 합성 fixture만으로 종결 금지.

### 1.3 핵심 설계 결정 (이 계획이 확정 — executor 재량 없음)

**결정 1 — 스키마 확장: sidecar `documents[]`에 related 식별자, excluded_documents[]에 relay.**

`<stem>_doctype.json` `schema_version`을 `"1.1"`로 올리고 run 단위 `documents[]` 항목에 다음 optional 필드를 추가한다 (pages 맵은 불변 — 제외 권위 유지, 1.0 sidecar 하위호환):

```json
{
  "schema_version": "1.1",
  "stem": "...", "pages": {...}, "uncertain_pages": [...],
  "documents": [
    {"doc_type": "PMI_REPORT", "pages": [23], "issuer": "...", "evidence": "...",
     "related_heat_nos": ["23215117"],
     "related_po_items": ["PU2601565-039"],
     "related_source": "p.23 PMI 표 P/O NO. 열",
     "related_confidence": "high"}
  ]
}
```

- **판독 규칙 (doc-classifier)**: EXCLUDED 라벨 run마다 해당 페이지의 full render(`.cache/<case>/png/<stem>_pNN.png`)를 `Read`하여 표의 **Heat No.(炉号)/P/O NO./MPR NO. 열을 verbatim 전사**한다. run 길이 ≤4p는 전 페이지, >4p는 첫·끝 페이지 우선 후 표가 이어지면 전부. 실물 레이아웃 확인 결과(위 조사): NDE 보고서는 Heat 열 직접 보유, PMI 보고서는 P/O NO.만 보유, 외관치수 보고서는 둘 다 보유 — **두 필드를 모두 스키마에 둔 이유**. 해당 열이 없으면 빈 리스트. 추측·보완 금지.
- `related_confidence`: 식별자 열을 선명히 판독했으면 `"high"`, 부분 판독·번짐이면 `"low"`. 필드 부재(1.0 sidecar) 시 소비 측이 `"low"`로 간주.
- `excluded_documents_for_case`(doctype.py)가 run↔`documents[]`를 **doc_type 동일 + 페이지 교집합 최대** 규칙으로 결정적으로 join하여, merge_reviews가 주입하는 `excluded_documents[]` 레코드에 `related_heat_nos`, `related_po_items`, `related_confidence`를 추가한다(미매칭 → `[]`/`[]`/`"low"`).

**결정 2 — 배치: "판단은 에이전트, 결정은 코드" 재사용, 판정 소유는 2개 reviewer 분담.**

| 역할 | 담당 | 산출 |
|---|---|---|
| 식별자 판독 (판단) | `doc-classifier` (Phase 1.6) | sidecar `documents[]` related 필드 |
| heat 대조·coverage 산출 (결정) | 신규 `scripts/attachments.py` + CLI `attachments` (Phase 4 step 1, `limits` 직후) | `.cache/<case>/<case>_attachments.json` |
| 요구↔첨부 판정 (판단) | `nde-reviewer` (PMI_REPORT·NDE_REPORT·MICROSTRUCTURE_REPORT), `format-reviewer` (APPEARANCE_DIMENSION_REPORT·PHYSICAL_CHEMICAL_TEST_REPORT·HEAT_TREATMENT_CHART·MTC_RAW_MATERIAL — document_requirements 체크리스트 유형) | 기존 partial review 내 row/finding |
| 리포트 표기 (결정) | `merge_reviews`(relay)·`compliance_report`(관련 Heat 컬럼) | review.json·xlsx |

heat 문자열 대조는 순수 결정적(공백 제거+대문자화 정규화 후 완전일치)이므로 코드가 수행한다. PO 품목→heat 역해석(본문 Detailed List 대조)은 판단이 필요하므로 reviewer 몫으로 남긴다(attachments pack이 `related_po_items`를 그대로 전달).

**결정 3 — nde-reviewer 본문 인쇄값 판정과의 충돌 방지: 단일 소유 + 고정 우선순위 ladder.**

같은 heat h·요구 R(예: PMI 100%)에 대해 nde-reviewer 내부에서 아래 순서로 **한 번만** 판정한다 (도메인당 소유 에이전트가 1개이므로 에이전트 간 충돌은 구조적으로 불가능; 소유 경계는 SKILL.md Domain-boundary 표와 기준 20.1에 명문화):

| 상태 | 본문 인쇄값 | 첨부 (해당 doc_type) | 처리 (nde[] row / finding) |
|---|---|---|---|
| **A** | 있음 (판정 가능) | 무관 | **기존 로직 그대로** (PASS/FAIL). 첨부는 row note에 참고 기재만 허용. 첨부판정 스킵 — "PMI 미첨부" finding 절대 금지 |
| **B** | 없음 (`/`·미기재) | 케이스 전체에 해당 유형 0건 | 요구 근거 인용 가능(17.1) + `sidecar_present: true`(check-doctype 통과) + h가 검토 대상 material일 때만: **ActionRequired** "『R』 결과 본문 미기재 및 별도 보고서 미첨부". sidecar 부재(레거시 캐시) 시 기존대로 생략 |
| **C** | 없음 | 있음 + `heat_coverage`에 h 포함 (`related_confidence: high`) | row **PASS**, cert에 "본문 미기재 — 별도 <유형> 보고서 첨부 확인 (p.N)". finding 없음. **첨부 보고서의 값 자체는 기준 19.2에 따라 비교하지 않음을 note에 명기** |
| **D** | 없음 | 있음 + h 미포함(식별자 불일치·판독 불가·confidence low) | row **주의** + **Question** finding "첨부 <유형> 보고서의 대상 heat/품목 확인 불가" (`related_po_items` 있으면 본문 Detailed List로 1회 대조 시도 후 해소되면 C로 승격). 자동 FAIL 금지 |

format-reviewer도 자기 소유 유형에 동일 ladder를 적용한다("본문 인쇄값" 자리는 "본문 내 해당 항목 증빙" — 예: 외관·치수 검사 결과가 본문 Visual & Dim 열에 인쇄된 경우 = 상태 A).

**결정 4 — 기준 17.1/19.3 개정** (정확한 문구는 3절 Step 8의 before/after).

**결정 5 — 오탐 방지 게이트 (Phase 1.6 보수 원칙 계승)**:
1. **미첨부 ActionRequired 3중 전제**: 요구 근거 인용(MPS 문서번호+항번 또는 CSV `nde_rules` 행, 17.1) + 해당 케이스 doctype sidecar 완비(`sidecar_present: true`) + 대상 heat가 materials 검토 대상.
2. 첨부 존재하되 coverage 불명 → **Question까지만** (상태 D).
3. `related_confidence: "low"`인 coverage는 상태 C의 PASS 근거로 쓰지 않음 → 상태 D 취급.
4. **첨부 부재만으로 Reject 금지** (수치 위반이 아닌 문서 보완 사안 — 기준 9.2 정합).
5. **요구가 없는 첨부는 finding 금지** (정보성 — excluded_documents로만 보고, 기준 17.7). 실물 E2E의 PMI 보고서가 바로 이 경로를 검증한다.

### 1.4 범위 밖 (명시)

- 첨부 보고서 **내부 값**의 스펙 대조 (기준 19.2 유지 — 값 비교는 계속 제외).
- PMI/NDE 이외 신규 taxonomy 라벨 추가 (13종 불변).
- 46케이스 재추출, 배포본 KO 동기화 (기존 후속 과제 그대로).
- `agents/page-aligner.md`, `scripts/align_inputs.py`, `scripts/extraction_check.py`, `scripts/eval_harness.py` — 무수정 (불변 영역).

---

## 2. Acceptance Criteria

Before 베이스라인 (이번 조사에서 직접 검증한 현재 동작):

- `excluded_documents[]` 레코드에 related 필드 없음 (`doctype.py:171-181`).
- 기준 17.1: 별도 문서 존재 확인 불가 시 finding 생략 → **요구 문서 통누락이 무증상 통과** / 기준 19.3: 첨부판정 명시적 범위 외.
- `.cache/10/10_review.json` (sidecar 없는 레거시)의 merge 재실행은 deep-equal (Phase16 AC-2로 입증된 상태).

| ID | 기준 (이진 판정) |
|---|---|
| **AC-1** | `python -m pytest` 전체 통과 (기존 184 + 신규 전부, 실패·에러 0). |
| **AC-2 (하위호환)** | sidecar 없는 case 10에서 `merge-reviews --case 10` 재실행 → 기존 `10_review.json` 대비 `materials[]`/`findings[]` deep-equal, `excluded_documents: []` 유지. `attachments --case 10` → exit 0 + `sidecar_present: false` + `attachments: []`. |
| **AC-3 (스키마 확장)** | 합성 sidecar(1.1, documents[] related 필드 포함)로 `merge-reviews` 실행 시 review.json `excluded_documents[]` 각 레코드에 `related_heat_nos`/`related_po_items`/`related_confidence`가 기록되고, 1.0 sidecar(documents[] 무)면 `[]`/`[]`/`"low"` 폴백. |
| **AC-4 (결정적 대조)** | `attachments --case`가 `<case>_attachments.json`을 산출: `heat_coverage`는 정규화(공백 제거+대문자) 완전일치만 인정, 인벤토리에 없는 related heat는 `unmatched_heat_nos`로 분리(자동 FAIL 유발 금지), 동일 유형 복수 첨부는 coverage 합집합. |
| **AC-5 (실물 E2E — 분류·판독)** | PU2601565-01 반입 후 전체 파이프라인 실행: `<stem>_doctype.json`이 23페이지 전부 라벨, p.22가 `NDE_REPORT`·p.23이 `PMI_REPORT`로 분류되고 각 run의 `documents[]`에 related 식별자 기록 — p.22는 `related_heat_nos`에 실물 인쇄 heat들(14328912, 23215117 등) 포함, p.23은 `related_po_items`에 `PU2601565-039` 계열 포함·`related_heat_nos`는 `[]`. |
| **AC-6 (실물 E2E — 판정)** | 동일 케이스 review.json에서: (a) MPS에 PMI 요구가 없으므로 **PMI 첨부/미첨부 관련 finding 0건**(과잉판정 방지 — 이 실물 케이스의 핵심 검증), (b) MT/PT는 본문 인쇄값 존재 heat에서 상태 A로 기존 판정만 발행(첨부 중복 finding 0건), (c) `excluded_documents[]` 2건(NDE_REPORT·PMI_REPORT)에 related 필드 기록, (d) xlsx "검토 제외 문서" 블록에 관련 Heat/품목 컬럼 렌더 + 한글 read-back 무결. |
| **AC-7 (ladder 경계 3상태)** | 시뮬레이션 케이스(실물 캐시 사본 + 조작 attachments pack, 6.3절 AT-2)에서 nde-reviewer가 상태 B→ActionRequired, 상태 C→PASS(finding 0), 상태 D→Question(주의)을 각각 산출하고, 상태 A 케이스(case 4 실측 review 유지 — 본문 PMI PASS 9건)에서 첨부 관련 finding이 추가되지 않는다. |
| **AC-8 (불변 영역 무회귀)** | `git diff --stat`에 `agents/page-aligner.md`, `scripts/align_inputs.py`, `scripts/extraction_check.py`, `scripts/eval_harness.py` 미포함. `check-doctype` 게이트는 1.0/1.1 sidecar 모두 기존과 동일 판정(documents[] 비검증 유지). |
| **AC-9 (문서 동기화)** | review-criteria.md(17.1 개정·19.3 개정·기준 20 신설), doc-classifier.md, nde-reviewer.md, format-reviewer.md, SKILL.md(Phase 4 step 1·위임 컨텍스트·레이아웃·흐름도·시간예산·Domain-boundary), README.md, marketplace.json(1.5.0) 갱신 완료. 어느 파일에도 "§" 문자 없음. |
| **AC-10 (데이터 위생)** | 커밋 diff에 고객 PDF/PNG/JSON 산출물 없음. 실물 케이스는 harness 데이터셋 루트(저장소 밖)에만 복사, `git status` 클린 재확인. |

---

## 3. Implementation Steps

구현 순서 = 아래 Step 순서. 1개 feature 커밋 권장: `feat(cert-review): MPS 요구 대비 동봉문서 첨부 자동판정(기준 20) — v1.5.0`.

### Step 1 — `agents/doc-classifier.md` 개정 (related 식별자 판독)

- frontmatter `description`에 "records per-run related heat/PO identifiers for requirement-vs-attachment judgement (기준 20)" 1구 추가. `model: claude-opus-4-8` 불변.
- **Procedure 절에 신규 step 6.5** (기존 step 6 보수 원칙 다음):

> **[Related-identifier reading — EXCLUDED runs only]** For every run labelled with an EXCLUDED type, `Read` the full-page render(s) `.cache/<case>/png/<stem>_pNN.png` of that run (all pages when the run is ≤4 pages; first + last page when longer, then the rest only if the identifier table continues) and transcribe **verbatim** the identifier columns printed in the document's table: Heat No. (炉号) values into `related_heat_nos`, P/O NO. / MPR NO. / Item No. values into `related_po_items`. Record where they were read in `related_source` (e.g. "p.23 PMI 표 P/O NO. 열"). Set `related_confidence: "high"` only when the column was clearly legible; `"low"` otherwise. **If the document prints no such column, leave the list empty — never infer identifiers from neighbouring finished-product pages.** Rotated enclosed reports are already upright at this phase (post-alignment), so the columns are readable.

- **Output 스키마 예시를 1.1로 갱신** (1.3절 결정 1의 JSON 그대로). `pages` 맵·13라벨 규칙 불변 명기. "documents[] is advisory for exclusion, but its related fields are the **only** source for 기준 20 attachment matching — omitting them degrades attachment judgement to 확인 불가 (Question), never to auto-FAIL" 1문 추가.
- Self-check에 "every EXCLUDED run has a documents[] entry (with related fields, possibly empty lists)" 추가. Completion report에 run별 related 식별자 개수 보고 추가.

### Step 2 — `scripts/doctype.py` 확장 (결정적 join)

`excluded_documents_for_case`(153행) 개정 — diff 스케치:

```python
def _advisory_documents(doctype: dict) -> list[dict]:
    docs = doctype.get("documents")
    return [d for d in docs if isinstance(d, dict)] if isinstance(docs, list) else []

def _match_run_meta(pages: list[int], doc_type: str, advisory: list[dict]) -> dict:
    """Pick the advisory documents[] entry with same doc_type and maximal
    page overlap (0 overlap -> no match). Conservative fallbacks."""
    best, best_overlap = None, 0
    page_set = set(pages)
    for d in advisory:
        if str(d.get("doc_type")) != doc_type:
            continue
        try:
            overlap = len(page_set & {int(p) for p in (d.get("pages") or [])})
        except (TypeError, ValueError):
            continue
        if overlap > best_overlap:
            best, best_overlap = d, overlap
    def _strs(v): return [str(x) for x in v] if isinstance(v, list) else []
    conf = str(best.get("related_confidence")) if best else ""
    return {
        "related_heat_nos": _strs(best.get("related_heat_nos")) if best else [],
        "related_po_items": _strs(best.get("related_po_items")) if best else [],
        "related_confidence": conf if conf in ("high", "low") else "low",
    }
```

`excluded_documents_for_case` 루프에서 `load_doctype` 결과를 유지해 두고(`excluded_pages_map` 재호출 구조를 `doctype = load_doctype(...)` + `_page_labels` 직접 사용으로 소폭 재구성), run별 dict 조립부(171-181행)에 `**_match_run_meta(pages, doc_type, _advisory_documents(doctype))` 병합. 모듈 docstring의 필드 목록·`__all__` 갱신. **`pages` 맵이 제외 권위라는 원칙은 불변** — advisory는 related 메타만 공급함을 주석 1줄로 명기.

### Step 3 — `scripts/attachments.py` (신규) + CLI `attachments`

```python
"""attachments.py — 기준 20 deterministic attachment index (Phase 4 input).

Joins the Phase 1.6 doctype sidecars (excluded enclosed-document runs with
related heat/PO identifiers) against the finished-product heat inventory from
*_extracted.json INCLUDED pages, and writes <case>_attachments.json consumed by
nde-reviewer / format-reviewer for requirement-vs-attachment judgement.
Matching is exact string equality after normalisation (whitespace stripped,
upper-cased) — no fuzzy matching; unmatched related heats are reported, never
auto-failed. Absent sidecars -> sidecar_present false (legacy behaviour:
reviewers skip attachment judgement). C1: JSON only. C7: utf-8.
"""
_HEAT_NORM_RE = re.compile(r"\s+")

def _norm_heat(v: str | None) -> str:
    return _HEAT_NORM_RE.sub("", str(v or "")).upper()

def collect_finished_heats(case_cache: Path) -> list[str]:
    # *_extracted.json 순회, excluded_pages_map으로 제외 페이지 스킵(refpack
    # collect_inventory:88-118과 동일 관용구), header.heat_no verbatim 수집
    # (order-stable de-dup, 빈 값 제외).

def build_attachments_pack(case_id: str, cache_root: Path) -> dict:
    # excluded_documents_for_case() 결과(=related 필드 포함)를 기반으로:
    #   attachments[]: 각 레코드 + matched_heat_nos / unmatched_heat_nos
    #     (정규화 대조, matched는 inventory의 verbatim 표기로 기록)
    #   heat_coverage: {doc_type: {inventory verbatim heat: [page_range, ...]}}
    #     — related_confidence "high"인 run만 coverage에 산입 (결정 5-3)
    #   finished_heats: verbatim 목록
    #   sidecar_present: case_cache에 *_doctype.json 존재 여부
    # 산출: .cache/<case>/<case>_attachments.json (schema_version "1.0",
    #   ensure_ascii=False, indent=2 — merge_reviews와 동일 관용구)
    # extracted 부재 시 FileNotFoundError (refpack:209와 동일 안내 문구)
```

`scripts/cli.py`: `cmd_attachments` — `cmd_limits`(605-627행) 출력·exit 관용구를 따름 (`[OK] attachments --case N: M enclosed run(s), sidecar_present=..., coverage: PMI_REPORT 1 heat, ...`). 파서 등록은 `limits` 블록(832-834행) 다음:

```python
p = sub.add_parser("attachments", help="기준 20: enclosed-document attachment index (requirement-vs-attachment input)")
p.add_argument("--case", required=True)
p.set_defaults(func=cmd_attachments)
```

에러 처리: sidecar 부재는 **에러 아님** (exit 0, `sidecar_present: false`, `attachments: []`) — 레거시 캐시 하위호환. extracted 부재만 exit 1.

### Step 4 — `scripts/merge_reviews.py` (docstring만)

코드 변경 불필요 — `excluded_documents_for_case` 결과를 그대로 주입하므로(296행) related 필드는 자동 반영된다. 모듈 docstring(20-28행)의 `excluded_documents[]` 필드 목록에 `related_heat_nos, related_po_items, related_confidence`를 추가.

### Step 5 — `scripts/compliance_report.py` "검토 제외 문서" 블록 확장

기존 제외 블록 렌더 루프(Phase16 Step 10으로 삽입된 부분)에서 컬럼 6 추가:

```python
rel = ", ".join(d.get("related_heat_nos") or []) or ", ".join(d.get("related_po_items") or [])
ws.cell(row=r, column=6).value = f"관련 Heat/품목: {rel}" if rel else "관련 Heat/품목: 확인 불가"
```

구버전 review.json(필드 부재)은 `or []` 폴백으로 "확인 불가" 렌더 — 기존 열 1~5 불변.

### Step 6 — `agents/nde-reviewer.md` 개정

- **Inputs 표**(51-59행)에 행 추가: `.cache/<case>/<case>_attachments.json` — "기준 20 attachment index (enclosed PMI/NDE/Microstructure report presence per heat). Absent or `sidecar_present: false` → skip attachment judgement entirely (legacy behaviour)."
- **Review Scope 뒤에 신규 절 "Requirement-vs-Attachment (기준 20 — own doc types: PMI_REPORT · NDE_REPORT · MICROSTRUCTURE_REPORT)"**: 결정 3의 A/B/C/D 표를 그대로 수록하고 다음을 명기:
  - 상태 A 우선 — 본문(헤더·표·remarks)에 해당 항목 값이 인쇄돼 있으면 기존 판정만 수행, 첨부판정 스킵 (중복·상충 finding 구조적 차단).
  - 상태 B의 3중 전제(결정 5-1)와 severity 상한 ActionRequired.
  - 상태 C에서 "첨부 보고서의 값은 기준 19.2에 따라 비교하지 않는다"를 note에 명기할 것. 기준 17.4의 "Report No. 인용 시 주의 격하" 규칙과의 관계: 본문이 Report No.를 인용하고 그 유형의 첨부가 coverage 일치하면 상태 C(PASS)로 상향, 첨부가 없으면 기존대로 '참조 리포트 확인 필요' 주의 유지.
  - 상태 D의 PO-품목 해소 시도(본문 Detailed List 1회 대조) 후 잔여 불확실은 Question까지만.
- **기준 19 제외 규칙 인용부(61행)** 뒤에 1문: "Exception (기준 20): the **presence** of an enclosed report and its printed identifier columns may be used for attachment judgement via `<case>_attachments.json` — the report's measurement **values** remain excluded from comparison."

### Step 7 — `agents/format-reviewer.md` 개정

- **Input/Output Contract**(44-54행)에 `<case>_attachments.json` 입력 추가 (문구는 Step 6과 동일 취지).
- **Document Requirements Cross-Check 절**(111-115행)에 신규 단락: 기준 20 소유 유형은 `APPEARANCE_DIMENSION_REPORT`·`PHYSICAL_CHEMICAL_TEST_REPORT`·`HEAT_TREATMENT_CHART`·`MTC_RAW_MATERIAL` — digest `document_requirements`의 X-마크 항목 또는 'shall' 특별요구(예: "Dimensional checks shall be done …")가 별도 보고서 제출을 함의할 때만 A/B/C/D ladder 적용. **PMI/NDE/Microstructure 유형은 nde-reviewer 소유 — 이 에이전트는 해당 유형에 대해 어떤 finding도 내지 않는다** (중복 발행 금지). 상태 A의 "본문 증빙" 예: 본문 Visual & Dim. Inspection 열의 합격 기재.
- 기준 19 인용부(52행) 뒤에 Step 6과 동일한 기준 20 예외 1문.

### Step 8 — `references/review-criteria.md` 개정 (17.1 · 19.3 · 기준 20 신설)

**(a) 기준 17.1 넷째 불릿 (330행) — before**:

> - **Distinguish received documents**: do not report a requirement to "state it in a separate document (item list/packing list) submitted together with the CMTR" as "CMTR body entry omission". If the existence of the separate document cannot be confirmed, omit the finding.

**after**:

> - **Distinguish received documents**: do not report a requirement to "state it in a separate document (item list/packing list) submitted together with the CMTR" as "CMTR body entry omission". Enclosed-document presence is decidable under 기준 20 when the case passed the Phase 1.6 doctype gate (`<case>_attachments.json`, `sidecar_present: true`): judge attachment presence/absence per the 기준 20 ladder. Omit the finding **only** when attachment status cannot be established (doctype sidecar absent — legacy cache), and downgrade to 확인 불가 (Question) when coverage is uncertain — never auto-FAIL on uncertainty.

**(b) 기준 19.3 (416-418행) — before**:

> ### 19.3 Out of scope (future work)
> - **Requirement-vs-attachment auto-judgement is OUT OF SCOPE for this phase.** Whether an MPS-required test report (PMI/NDE/dimension, etc.) was *actually* attached — i.e. auto-verifying required-document completeness by matching MPS requirements against the classified enclosed documents — is deferred to future work.
> - This relates to the existing **기준 17.1 "별도 문서(동봉 문서)" rule**: … Phase 1.6 only classifies and excludes such enclosed documents; it does not yet decide whether a required enclosure is present or missing.

**after**:

> ### 19.3 Relation to 기준 20 (requirement-vs-attachment)
> - The requirement-vs-attachment auto-judgement formerly deferred here is now specified in **기준 20**. Phase 1.6 additionally records per-run related identifiers (`documents[].related_heat_nos` / `related_po_items`, verbatim from the enclosed document's own printed table) which 기준 20 consumes.
> - 기준 19.2 is **unchanged**: an excluded page's measurement values are still never compared. 기준 20 judges only the **presence and heat/item coverage** of enclosed documents.

**(c) 기준 20 신설** (기준 19 뒤):

> ## 20. MPS 요구 대비 동봉 문서 첨부 판정 (requirement-vs-attachment)
>
> ### 20.1 Scope and single ownership
> | doc_type | 요구 출처 | 판정 소유 |
> |---|---|---|
> | `PMI_REPORT` | `nde_rules.csv` PMI 행 / digest `nde_microstructure` | nde-reviewer |
> | `NDE_REPORT` | `nde_rules.csv` / digest `nde_microstructure` (MT/PT/UT/RT) | nde-reviewer |
> | `MICROSTRUCTURE_REPORT` | digest `nde_microstructure` (δ-ferrite 대표사진 등) | nde-reviewer |
> | `APPEARANCE_DIMENSION_REPORT` | digest `document_requirements`/'shall' 특별요구 (치수검사) | format-reviewer |
> | `PHYSICAL_CHEMICAL_TEST_REPORT` | digest `document_requirements` | format-reviewer |
> | `HEAT_TREATMENT_CHART` | digest `document_requirements`/열처리 기록 요구 | format-reviewer |
> | `MTC_RAW_MATERIAL` | digest `document_requirements` (원자재 성적 제출 요구) | format-reviewer |
> | 그 외 (COVER_LETTER·MPS_COPY·DRAWING·REVIEWED_ANNOTATED_COPY) | 판정 대상 아님 (정보성) | — |
> 소유 밖 유형에 대한 finding 발행 금지 (중복 방지).
> ### 20.2 Deterministic artifact — `<case>_attachments.json`
> (attachments CLI 산출 스키마·정규화 완전일치 규칙·`related_confidence: high`만 coverage 산입·`sidecar_present: false` 시 판정 전체 스킵)
> ### 20.3 Precedence ladder — 결정 3의 A/B/C/D 표 (본문 인쇄값 > 첨부 확인 > 확인 불가 > 미첨부)
> ### 20.4 Severity policy (conservative)
> 미첨부 확정 = **ActionRequired** 상한 (문서 보완 사안, 기준 9.2 정합 — 첨부 부재만으로 Reject 금지). coverage 불명 = **Question** 상한. 요구 없는 첨부 = finding 금지 (기준 17.7 정보성 — excluded_documents로만 보고).
> ### 20.5 Value-comparison prohibition
> 기준 19.2 재확인 — 첨부 보고서 내부 측정값은 판정 근거로 사용 금지 (presence/coverage만).

**(d)** 기준 19 도입부(390행)의 taxonomy 동기화 목록 문구는 불변(라벨 13종 무변경).

### Step 9 — `skills/cert-review/SKILL.md` 개정

1. **2.7 doc-classifier 위임 컨텍스트 스펙**(257-258행): compliance instructions에 "**related-identifier reading for EXCLUDED runs** (verbatim Heat/PO columns from the enclosed document's own table — details in agents/doc-classifier.md)" 추가.
2. **Phase 4 step 1**(321-325행): `limits --case <id>` 다음에 `attachments --case <id>` 추가 — "기준 20 attachment index; sidecar 부재 시에도 exit 0 (`sidecar_present: false`) — 항상 실행".
3. **5개 reviewer 위임 컨텍스트**(328-335행): 기존 기준 19 불릿 뒤에 1불릿 — "**기준 20 attachment judgement**: nde/format reviewers read `<case>_attachments.json` and apply the 기준 20 ladder for their own doc types (ownership table in review-criteria.md 기준 20.1); body-printed values always take precedence; other reviewers ignore the file."
4. **Domain-boundary 표**(350-358행)에 행 추가: `동봉 보고서 첨부판정 — PMI/NDE/Microstructure 유형 | nde`, `동봉 보고서 첨부판정 — 치수/이화학/열처리차트/원자재 유형 | format`.
5. **Directory Layout**(98-119행): `<case>_attachments.json` 행 추가.
6. **PowerShell usage example**(131-152행): `python -m scripts.cli attachments --case 4` 라인 추가.
7. **흐름도**(407-439행): Phase 4 라인을 `limits → attachments → [delegate 5 reviewers …]`로 갱신.
8. **시간예산 절**(156-164행): 장치 ⑧ 추가 — doc-classifier의 제외 run 식별자 판독 +1~3분(첨부 있는 케이스만), reviewer 첨부판정은 기존 위임 내 흡수(순증 ≈ +0~3분). 티어 목표 불변.

### Step 10 — `README.md`(스킬) · `.claude-plugin/marketplace.json`

- `skills/cert-review/README.md` 52행 블록에 1문 추가: "MPS가 요구하는 별도 시험보고서의 첨부 여부는 기준 20에 따라 heat 단위로 자동 판정(`attachments` CLI + nde/format reviewer)". 60행 파이프라인 다이어그램의 Phase 4에 `attachments` 표기. 107행 테스트 수 갱신.
- `marketplace.json`: version `1.4.0` → `1.5.0`, description에 "동봉 문서 첨부여부 heat 단위 자동판정(기준 20)" 반영.

### Step 11 — 테스트 (합성 fixture, tmp_path — 6절 T-1~T-6)

### Step 12 — 실물 E2E 반입·실행 (6.2절 — harness 데이터셋 루트, 커밋 금지)

### 엣지 케이스 총괄

| # | 케이스 | 처리 |
|---|---|---|
| E1 | 1.0 sidecar(documents[] 무)·related 필드 무 | join 폴백 `[]`/`[]`/`"low"` — 게이트·제외 동작 불변 (AC-3) |
| E2 | 원자재 Mill Cert의 heat == 완제품 heat | MTC_RAW_MATERIAL은 format 소유 + 원자재 제출 요구 있을 때만 사용. 인벤토리 오염 차단(L2)은 불변 |
| E3 | 첨부에 Heat 열 없음(PO만 — 실물 PMI 보고서) | heat_coverage 미산입, `related_po_items` 전달 → reviewer가 본문 Detailed List 대조(상태 D→C 승격 경로) |
| E4 | 동일 유형 복수 첨부 run | coverage 합집합 (AC-4) |
| E5 | related heat가 인벤토리에 없음(원자재 모재 heat 등) | `unmatched_heat_nos` 분리 — 자동 FAIL 금지 |
| E6 | 케이스에 excluded 문서 0 (순수 파일) | attachments pack `attachments: []` — 상태 B 게이트는 요구 근거 있을 때만 작동 |
| E7 | 다품목 동일 heat (item discriminator 분리 행) | coverage는 heat 단위 — 두 material 행 모두 동일 coverage 적용 (merge 키 규약 무변경) |
| E8 | `&` 포함 MPS 파일명 (`MPS-SH-MTA-A234WPB&C.PDF`) | 파일명 verbatim 유지, PowerShell 경로 인용 필수 (기존 `.cache/32 & 33/` 전례 있음) |
| E9 | 헤더 heat_no 공백 변형 ("14328912 " 등) | `_norm_heat` 정규화 후 대조, 기록은 verbatim |
| E10 | attachments CLI를 doctype 이후·OCR 이전에 잘못 실행 | extracted 부재 → exit 1 + "run prep-inputs + Phase-2 first" 안내 (refpack 관용구) |

---

## 4. Code Writing Guide

- **인코딩**: 모든 파일 I/O `encoding="utf-8"`, CLI는 `$env:PYTHONIOENCODING="utf-8"` 선행. 한국어 문자열 산출 후 read-back으로 한글 무결 확인 — 깨짐 발견 시 수정 전 완료 보고 금지. "§" 사용 금지 — "기준 N" 표기.
- **모델 고정**: 전 에이전트 `model: claude-opus-4-8`. haiku/sonnet 재비교 제안·수행 금지 (실측 탈락 확정).
- **taxonomy·스키마 단일 소스**: 라벨 13종 불변 — `scripts.doctype` 상수만 import, 문자열 재정의 금지. attachments pack 스키마는 `scripts/attachments.py` docstring이 권위 (기준 20.2는 참조 서술).
- **whitelist·보수 폴백 계승**: sidecar/필드 부재 = 기존 동작 (판정 스킵), 불확실 = Question 상한, 자동 FAIL 금지. 제외 판정 권위는 `pages` 맵 불변 — documents[]는 related 메타 전용.
- **기존 관용구 재사용**: JSON 로드 `doctype.load_doctype`/`align_inputs._load_json`, 제외 필터 `excluded_pages_map`(refpack:88-118 관용구), CLI 출력·exit `cmd_limits`, 산출 쓰기 `merge_reviews`(ensure_ascii=False, indent=2). 복붙 대신 import.
- **불변 영역 (수정 금지)**: `agents/page-aligner.md`, `scripts/align_inputs.py`, `scripts/orient_sheets.py`, `scripts/extraction_check.py`, `scripts/eval_harness.py`, `hermes-loop/`, ref_code/rawdata/GT, `Cert_Auto_examine\`(읽기 전용 — 원본 이동·개명 금지, 복사만).
- **금지 패턴**: 첨부 보고서 내부 값 비교(기준 19.2 위반), findings에 정보성 첨부 메모 주입(17.7), fuzzy heat 매칭(0/O 치환 등 — 완전일치만), 첨부 부재 단독 Reject, PMI/NDE 유형에 대한 format-reviewer 발행(소유 침범), `check-extraction`·merge 키 verbatim 등 기존 계약 변경.
- **커밋**: 고객 데이터 커밋 금지 — 실물 PDF는 harness 데이터셋 루트(저장소 밖)에만. 커밋 전 `git status` 재확인. conventional commit(한국어 요약).

---

## 5. Definition of Done

전 항목 이진 판정:

1. `python -m pytest` exit 0 (기존 184 + 신규, 실패·에러 0).
2. AC-2 성립 (case 10 deep-equal + attachments `sidecar_present: false`).
3. AC-3·AC-4 성립 (합성 단위 테스트 통과로 판정).
4. AC-5 성립 (실물 doctype·related 판독 — 대조 기록을 완료 보고에 첨부).
5. AC-6 성립 (실물 review.json·xlsx 4개 하위항목 전부).
6. AC-7 성립 (ladder 3상태 시뮬레이션 + 상태 A 무간섭).
7. AC-8 성립 (`git diff --stat` 불변 영역 미포함 + check-doctype 1.0/1.1 동일 판정).
8. AC-9 문서 동기화 파일 전부 커밋 포함, "§" 검색 0건.
9. AC-10 성립 (`git status` 클린, 고객 데이터 미추적).
10. main 커밋 + push 완료, `docs/plan_history.md` 행 추가(최신이 위).

---

## 6. Adversarial Test Environment

### 6.1 단위 테스트 (합성 fixture, tmp_path — 고객 데이터 비의존)

| ID | 파일 | 내용 | DoD 매핑 |
|---|---|---|---|
| T-1 | `tests/test_doctype.py` (확장) | `excluded_documents_for_case` related join: 1.1 sidecar 정상 join / 1.0 폴백 `[]`·`"low"` / doc_type 불일치 미매칭 / 페이지 교집합 최대 선택 / 비-list related 값 tolerant | DoD-3 |
| T-2 | `tests/test_attachments.py` (신규) | `_norm_heat`·`collect_finished_heats`(제외 페이지 스킵·verbatim de-dup)·`build_attachments_pack`: coverage 완전일치만 / unmatched 분리 / 복수 run 합집합 / confidence low 미산입 / sidecar 무 → `sidecar_present: false` / extracted 무 → FileNotFoundError | DoD-3 (AC-4) |
| T-3 | `tests/test_merge_reviews.py` (확장) | 1.1 sidecar 합성 → review.json excluded_documents에 related 필드 존재, findings 불변; sidecar 무 → 기존 스냅샷 deep-equal | DoD-2·3 |
| T-4 | `tests/test_compliance_report_excluded.py` (확장) | related 있는 review.json → "관련 Heat/품목" 셀 렌더·한글 무결; 필드 부재 → "확인 불가" 렌더·기존 열 불변 | DoD-5 |
| T-5 | `tests/test_cli_attachments.py` (신규 또는 test_attachments.py 내) | CLI exit 코드 매트릭스 (정상 0 / sidecar 무 0 / extracted 무 1) + 출력 라인 형식 | DoD-3 |
| T-6 | `tests/test_no_python_ocr.py` (기존 자동 커버) | 신규 모듈 C1 금지 import 없음 | DoD-1 |

### 6.2 실물 E2E (AT-1 — 커밋 없음, harness 데이터셋 루트만)

**자산 반입** (이 계획이 페어링 확정 — 도입부 조사 참조):

```
standard inspection Cert cleanup data/PU2601565-01/PU2601565-1-MTC.pdf   ← 복사
standard inspection MPS cleanup data/PU2601565-01/MPS-SH-MTA-A234WPB&C.PDF
standard inspection MPS cleanup data/PU2601565-01/MPS-SH-MTA-A234WP22.PDF
```

- 데이터셋 루트는 저장소 밖 — git 무접촉 (AC-10). GT 없음 → `evaluate` 불가, 판정은 산출물 직접 검증(AC-5·6). 원본은 `Cert_Auto_examine\`에서 복사만(이동 금지).
- 선정 근거: (i) MPS 페어링이 프로젝트명 수준에서 실증됨(TALLGRASS 일치), (ii) NDE_REPORT(heat 직접 열)와 PMI_REPORT(PO 열만)가 한 파일에 공존해 **두 식별 경로를 모두** 실물로 검증, (iii) MPS에 PMI 요구가 없어 **과잉판정 방지 게이트**를 실물로 검증, (iv) MT/PT 요구+본문 인쇄값 공존으로 **상태 A 우선순위**를 실물로 검증. 대체 후보(PU2601859-01: 외관치수 보고서 p.18 — Heat 열 CXE040090·YX2112-2008·NY251007AN10 실증)는 예비로 명시 — 주 후보 실패 시에만 사용.
- 절차: `build-manifest` → cache-status → prep-inputs → orient-sheets → page-aligner → align-inputs → tile-inputs → classify-sheets → **doc-classifier(related 판독 포함)** → check-doctype → prep-mps → OCR(23p fragment ≤4p×6, p.22 회전은 align이 처리) ∥ mps-extractor(2문서) → check-extraction → limits → **attachments** → 5 reviewer 병렬 → merge-reviews → compliance_report. 복합 티어(60~90분+α) 예산 적용.

### 6.3 ladder 경계 시뮬레이션 (AT-2 — 실물 캐시 사본 + 조작 pack, LLM 위임 3회)

E2E 완료 후 `.cache/PU2601565-01`을 `.cache/PU2601565-01_sim{B,C,D}`로 복사하고 `<case>_attachments.json`·`<case>_limits.json`만 조작(합성 PMI 요구 행 주입 등)하여 nde-reviewer를 각 1회 위임:

| 시나리오 | 조작 | 기대 |
|---|---|---|
| sim-B | PMI 요구 행 주입 + PMI_REPORT 항목 제거 + 본문 PMI 값 없는 heat 지정 | ActionRequired "미기재 및 미첨부" 정확 발행 |
| sim-C | PMI 요구 행 주입 + coverage에 대상 heat 포함(high) | row PASS "별도 첨부 확인", finding 0 |
| sim-D | PMI 요구 행 주입 + coverage 불일치(unmatched/low) | row 주의 + Question, FAIL 0 |

상태 A 무간섭은 case 4 실측(`4_review_nde.json` PMI PASS 9건)에 attachments pack(빈 첨부)을 추가한 사본으로 nde-reviewer 1회 재위임하여 "첨부 관련 finding 0 + 기존 PASS 유지"로 검증 (AC-7). 시뮬레이션 사본·조작 파일은 검증 후 삭제(자기 생성 스크래치).

### 6.4 하위호환·무영향 (AT-3·AT-4)

- AT-3: case 10 merge 재실행 deep-equal (AC-2) — LLM 불필요.
- AT-4: `attachments --case 10` → `sidecar_present: false` 확인 — LLM 불필요.

---

## 7. Risks and Mitigations

| # | 리스크 | 영향 | 완화 |
|---|---|---|---|
| R1 | **오탐 "미첨부" finding** — 공급사 분쟁급 무거운 주장 | 치명 | 3중 전제(요구 인용+doctype 완비+검토 대상 heat) + ActionRequired 상한 + 불확실 시 Question 격하 + 실물 AC-6(a)로 과잉판정 0건 검증 |
| R2 | doc-classifier의 heat/PO 오판독 → 잘못된 coverage로 상태 C 오PASS | 높음 | verbatim 전사·추측 금지 + `related_confidence: high`만 coverage 산입 + 정규화 완전일치(fuzzy 금지) + unmatched 분리. 오판독 잔여 위험은 상태 C의 note("값 비교 미수행") 명기로 사람 검토 여지 유지 |
| R3 | nde/format 중복·상충 finding | 중간 | 유형별 단일 소유 표(기준 20.1)+Domain-boundary 표+상태 A 우선 ladder — 구조적 차단, AC-7로 검증 |
| R4 | 레거시 캐시 비호환 | 중간 | 전 경로 폴백(sidecar 무=판정 스킵), AC-2·AT-4 입증. check-doctype 게이트 무강화(1.0/1.1 동일 판정) |
| R5 | 실물 반입 데이터 위생 | 중간 | 데이터셋 루트는 저장소 밖 + `.cache/` gitignore + AC-10 `git status` 재확인 |
| R6 | 시간예산 초과 (23p 복합 + related 판독 + 시뮬레이션 3회) | 낮음 | 복합 티어 60~90분+α 허용(실측 기록), related 판독은 제외 run 한정(+1~3분), 시뮬레이션은 단일 에이전트 위임만 |
| R7 | eval 지표 오염 (46케이스 회귀) | 낮음 | 신규 finding은 요구 근거+sidecar 완비 시에만 발생 — 기존 46케이스 캐시는 대부분 sidecar 무 → 무변화. `load_predictions` 무수정 |
| R8 | 플러그인 vs 배포본 분기 | 낮음 | plugin repo 단일 소스 커밋+푸시. 작업폴더 `.claude/skills` 사본 동기화 필요 여부를 구현 완료 시 확인·보고(통째 복사 금지 — 기존 memory 규칙) |

---

## 8. Verification Steps

SKILL_DIR에서 `$env:PYTHONIOENCODING="utf-8"` 설정 후 순서대로 (각 단계의 exit code·출력 샘플·한글 read-back을 완료 보고에 포함):

```powershell
# V1. 단위 회귀
python -m pytest -q                                      # exit 0

# V2. 하위호환 (case 10 — LLM 불필요)
Copy-Item .cache\10\10_review.json $env:TEMP\10_before.json
python -m scripts.cli merge-reviews --case 10            # materials/findings deep-equal 비교
python -m scripts.cli attachments --case 10              # exit 0 + sidecar_present: false

# V3. 실물 E2E (PU2601565-01 — 6.2절 반입 후)
python -m scripts.cli build-manifest
python -m scripts.cli prep-inputs --case PU2601565-01
# … orient-sheets → [page-aligner] → align-inputs → tile-inputs → classify-sheets
# → [doc-classifier: related 판독 포함] → check-doctype (exit 0)
# → 육안 대조: p.22=NDE_REPORT(related_heat_nos 실물 heat 포함), p.23=PMI_REPORT(related_po_items만) — AC-5 기록
python -m scripts.cli prep-mps --case PU2601565-01       # '&' 경로 인용 주의
# → [ocr-extractor fragment ×6 ∥ mps-extractor] → merge-parts → check-extraction (exit 0)
python -m scripts.cli limits --case PU2601565-01
python -m scripts.cli attachments --case PU2601565-01    # coverage/unmatched 출력 확인 (AC-4)
# → [5 reviewers] → merge-reviews → compliance_report
# → AC-6 검증: PMI finding 0건 / MT 상태 A / excluded_documents related 필드 / xlsx 관련 Heat 컬럼 + 한글 read-back

# V4. ladder 시뮬레이션 (6.3절 sim-B/C/D + 상태 A 무간섭) — 결과 기록 후 사본 삭제

# V5. 문서·위생
Get-ChildItem -Recurse -Include *.md,*.py,*.json | Select-String -Pattern "§"   # 0건
git status ; git diff --stat    # 불변 영역 미포함·고객 데이터 미추적 확인
# → 커밋 + push → docs/plan_history.md 행 추가 → 배포본 동기화 필요 여부 확인·보고
```

V3의 육안 대조(AC-5)와 V4의 시뮬레이션 판정 확인만 사람 판단이 개입하며, 그 외 전 단계는 executor가 직접 실행·검증한다.
