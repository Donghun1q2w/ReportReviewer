# Review Criteria (도메인 규칙 참조)

본 문서는 **Claude 보조 판정 시점에만** 참조하는 도메인 규칙 정리본이다. 모든 수치는 `plugin/cert-review-skill/data/*.csv`의 출처 4종 메타데이터를 통해 ref_code/MPS에서 인용된 것이며, 본 문서에 적은 수치는 가독성을 위한 사본일 뿐 **런타임 판정에는 CSV만 사용**한다.

## 0. 출처 강제 원칙 (C2/C8)

| 단계 | 규칙 |
|---|---|
| CSV row import | 4종 메타(source_file/anchor/snippet/sha256) 없으면 거부 |
| Python 결정적 판정 | CSV에서만 수치 인용. 코드에 하드코딩된 수치 사용 금지 |
| Claude 보조 판정 | annotations.json / emails.json / mps 텍스트에서 evidence를 인용하지 않으면 finding 작성 금지 |
| 출력 직전 검증 | source_validator가 evidence 없는 finding을 dropped_findings.json으로 격리 |

## 1. Grade 라우팅 (data/grade_routing.csv)

성적서 grade 문자열 → 검토 기준이 되는 ASME spec + ref_code 파일 매핑.

| 성적서 표기 | ASME spec | ref_code 폴더 | 비고 |
|---|---|---|---|
| `A106 B`, `SA106 Gr.B`, `SA-106 B` | SA-106 Gr.B | ASTM_A106_A106M_15 또는 _19a_RED | MPS 명시 시 그 연도 우선 |
| `A106 C`, `SA-106 C` | SA-106 Gr.C | (동일) | Mn max 1.65% (Footnote B) |
| `P11`, `A335 P11`, `F11` | SA-335 P11 / SA-182 F11 | ASTM_A335_A335M_19a, ASTM_A182_A182M_16a | |
| `P22`, `A335 P22`, `F22` | SA-335 P22 / SA-182 F22 | (동일) | |
| `P91`, `A335 P91`, `F91`, `WP91` | SA-335 P91 / SA-182 F91 / SA-234 WP91 | (동일) + MPS Restricted 적용 | |
| `P92`, `F92`, `WP92` | SA-335 P92 / SA-182 F92 / SA-234 WP92 | (동일) | Trace elements MPS |
| `A105`, `SA-105` | SA-105 | ASTM_A105_A105M_14 | |
| `A193 B7` | SA-193 B7 | ASTM_A193_A193M_14 (rawdata) | 볼트 |
| `A194 2H`, `A194 7` | SA-194 2H/7 | ASTM_A194_A194M_14a (rawdata) | 너트 |
| `A672 B70` | SA-672 B70 | ASTM_A672_A672M_14 | Welded pipe |
| `A182 F304` | SA-182 F304 | ASTM_A182_A182M_16a | Stainless |
| `SCM435` | JIS G4105 SCM435 | (코드 없음 — MPS만) | Bolt material |

## 2. MPS Override 규칙 (data/mps_overrides.csv)

MPS가 Code보다 엄격한 항목 (MPS 우선):

| Grade | 항목 | Code 기준 | MPS 기준 | 출처 |
|---|---|---|---|---|
| P91 | C max | 0.12 | 0.12 (동일) | SA-335 Table 1 |
| P91 | Mn max | 0.60 | 0.50 | MPS Table 1 Restricted |
| P91 | S max | 0.010 | 0.005 | MPS Table 1 Restricted |
| P91 | Ni max | 0.40 | 0.20 | MPS Table 1 Restricted |
| P91 | TS min | 585 MPa | 630 MPa (91 ksi) | MPS Table 2 |
| P91 | Normalizing | — | 1040–1080 °C | MPS Heat Treatment |
| P91 | Tempering | ≥730 °C | 750–780 °C | MPS Heat Treatment |
| P92 | TS min | 620 MPa | 620 MPa (동일) | Code |
| P92 | Pb max | — | 0.001 (1 ppm) | MPS Trace Elements |
| P92 | Sb max | 0.003 | 0.003 (동일) | Code |
| P92 | Normalizing | — | 1050–1080 °C | MPS Heat Treatment |
| P92 | Tempering | ≥730 °C | 760–780 °C | MPS Heat Treatment |
| P91·P92 | δ-ferrite | — | ≤5% (P91), ≤2.5% (P92) | MPS Microstructure |
| P91·P92 | N/Al ratio | — | ≥ 4 | MPS Chemistry |

## 3. 화학성분 판정 규칙

### 3.1 기본 룰
- Heat Analysis와 Product Analysis 모두 규격 범위 내
- **A106/SA-106 C/Mn 각주 (Footnote A/B) — Mn 판정 시 필수 적용**:
  Table 1 각주에 따라 C가 규정 max보다 낮으면 그 감소분만큼 Mn max가 상향된다.
  ```
  조정 Mn max = min( base_Mn_max + floor((C_max - C실측)/0.01) × 0.06 , cap )
     C_max : Gr.A 0.25 / Gr.B 0.30 / Gr.C 0.35
     cap   : Gr.A 1.35% / Gr.B·C 1.65%
     base_Mn_max : Table 1 Mn max (예: Gr.B/C 1.06)
  ```
  **Mn은 base max가 아니라 위 조정 max로 판정한다.** 예: SA-106-B, C=0.17 → 조정 max = 1.06 + 13×0.06 = 1.84 → cap 1.65 → **Mn 1.21%는 PASS**(오탐 금지). C가 max에 근접하면 상향폭이 작아 정상적으로 FAIL 가능.
- A106 5원소 합계: Cr + Cu + Mo + Ni + V ≤ 1.0%
- P91/P92: Ni + Mn ≤ 1.0%

### 3.2 컬럼 정합성 검증
스캔 OCR은 컬럼 밀림 가능. Claude는 추출 후 다음을 확인:
1. 각 원소값이 해당 컬럼 Max/Min 범위와 물리적으로 부합?
2. 성적서에 Cev가 있으면 역산 일치?  `Cev = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15`
3. P91 Cr이 ~9% 수준, P22 Cr이 ~2% 수준 등 grade별 통상 범위와 일치?

불일치 시 OCR을 재시도하지 말고 **원본 PNG를 다시 vision으로 읽어 명시적 보정**한다.

## 4. 기계적 성질 판정

| 항목 | 우선순위 | 비고 |
|---|---|---|
| TS min | MPS > Code | P91: MPS 630MPa > Code 585MPa |
| YS min | MPS > Code | 동일 |
| EL min | Code Table 2 | 시편 종류(Round/Strip, L/T) 별 |
| Hardness | MPS 범위 | P91/P92: 200–248 HBW (MPS) |

## 5. 열처리 판정

- 모든 단계(N → T → 냉각)가 각각 범위 내일 때만 종합 PASS
- 이탈량 ≤ 10°C → WARNING, > 10°C → FAIL
- 유지시간: MPS Table 2 두께별 최소시간 + Tempering 1hr/25mm

## 6. NDE 및 특별요구사항

| 항목 | 규칙 |
|---|---|
| UT Notch | MILL → GE Notch (≤5% wall, 0.3mm 중 큰값), STOCK → Code Notch (≤12.5% wall, 0.1mm) |
| δ-ferrite | P91 ≤5%, P92 ≤2.5%, AMS-2315 또는 ASTM E562 측정 + 대표 사진 첨부 |
| Code Case | P91: B31 Case 215-1, P92: CC 2179-11 + B31 Case 183-5 (또는 MPS 명시 case) |
| MT/PT | Butt welding end / Bevel ends 가공 시 필수 (MPS 명시) |
| PMI | 100% 수행 |
| No Welding | MPS 금지 시 "NO WELDING REPAIR" 문구 확인 |

## 7. Finding 카테고리 매핑 (GT 스키마 호환)

| Category | 검출 방식 (Python deterministic vs LLM) | 필수 evidence channel |
|---|---|---|
| Chemistry | Python (CSV 룩업) | body + mps/ref_code |
| Mechanical | Python | body + mps/ref_code |
| HeatTreatment | Python | body + mps/ref_code |
| NDE | Python + LLM | body + (annotations/emails) |
| Microstructure | Python (수치) + LLM (사진 누락) | body 또는 annotations |
| Identification | LLM | annotations 또는 emails 또는 mps |
| DocumentError | LLM | annotations 또는 emails 또는 body |
| Other | LLM | annotations 또는 emails (필수) |

## 8. Severity 결정 룰

| 조건 | severity |
|---|---|
| MPS/Code 명시 한계 초과 (수치) | Reject |
| 요구 시험·기재 누락 | ActionRequired |
| "??? please explain" 등 의문 표기 | Question |
| 단순 표기 오류, 사인 누락 | Minor |

값이 경계치 ±10% 이내이고 한계를 넘지 않으면 WARNING은 카테고리가 아니라 비고로만 기록.

## 9. SEVERITY CALIBRATION (GT_Answer enum 정렬 기준)

본 섹션은 GT_Answer enum 값의 실제 적용 기준을 명확히 정의한다. GT 데이터를 직접 읽지 않아도 아래 규칙을 따르면 enum 값이 일치해야 한다.

### 9.1 Reject

다음 중 하나 이상에 해당하면 **Reject**:

- **수치 위반**: 측정값이 MPS 또는 Code의 hard limit(min/max)을 위반.
  - 예: Pb 측정값 0.004% > MPS 한계 0.001%; YS 측정값이 min 미만; Cr 범위 이탈; 경도(Hardness) max 초과.
- **필수 시험 미수행**: 해당 자재 유형·납품 조건에서 의무인 시험이 **전혀 수행되지 않음**.
  - 예: STOCK 납품 조건의 NDE(UT/MT/PT) 미수행.
- **자재/제품 유형 불일치**: 성적서상 material grade 또는 product type이 PO/MPS 지정과 불일치.

### 9.2 ActionRequired

다음 중 하나 이상에 해당하면 **ActionRequired** (수치 위반 없이 서류·기재 보완이 필요한 경우):

- 시험 기록 누락: MT/PT 결과가 보고서에 미기재 (수행 여부 불명).
- 대표 사진 누락: Delta ferrite 측정 요구 시 대표 미세조직 사진 미첨부.
- 화학성분 값 미기재: N, Al 등 MPS 요구 원소가 성적서에 입력되지 않음.
- Code Case 문구 미기재: MPS/Code에서 요구하는 Code Case 번호 또는 적합 선언 누락.
- 수량·규격·Spec 오기재로 재발행 필요: 오류 자체는 수치 위반이 아니나 문서 재발행 없이는 납품 불가.
- Product Analysis 건수 부족: 요구 Heat 수 대비 실제 PA 기록 건수 미달.

### 9.3 Question

- 검토자가 "??? please explain", "please confirm" 등 **명시적 의문 또는 확인 요청**을 기재한 경우.
- 값이 이상해 보이나 한계를 초과하는지 불명확하여 **추가 설명 없이는 판정 불가**한 경우.
- 반드시 결함이 아닐 수 있으며, 제조사 회신으로 해소 가능.

### 9.4 Minor

- Spec impact 없는 **순수 오타** (단위 표기법, 소수점 자릿수 표기 등).
- 서명·날인 누락 등 **절차적 누락**이지만 검토 판정에 영향 없음.
- 검토자 메모성 코멘트로 Action 불요.

### 9.5 복합 판정 우선순위

동일 항목에 복수 severity가 적용 가능하면 **더 높은 severity 하나만** 사용한다 (Reject > ActionRequired > Question > Minor). 동일 검토자 이슈를 두 개 finding으로 분리하지 말 것.

## 10. PHASE 5 — LLM Finding 생성 가이드

Phase 5는 Python deterministic 판정(Phase 3)에서 감지되지 않은 **comment 기반 이슈**를 Claude가 직접 읽고 finding을 생성하는 단계다.

### 10.1 입력 채널

Claude는 다음 세 채널을 읽어 finding 후보를 식별한다:

| 채널 키 | 소스 경로 | 내용 |
|---|---|---|
| `annotations` | `extracted.json` → `channels.annotations.items[]` | 성적서 PDF 주석 (검토자 메모, 스탬프 텍스트 등) |
| `emails` | `extracted.json` → `channels.emails.items[]` | 검토자 이메일 본문 스레드 |
| `body` | `extracted.json` → `page_extraction[page]` | 성적서 페이지 본문 (cert page context) |

### 10.2 Grade 귀속 규칙

annotation이 특정 페이지와 연결되어 있으면 **그 페이지의 `page_extraction[page].header.grade`** 값을 해당 finding의 `material_grade`로 사용한다. 페이지 연결 정보가 없는 경우(이메일 등)에는 이메일 본문에 명시된 grade 또는 해당 case의 대표 grade를 사용한다.

### 10.3 Finding 생성 대상 카테고리

Phase 5에서 생성하는 finding의 카테고리는 다음으로 제한한다:

- `Identification` — 자재 식별 불일치 (PO 번호, Heat 번호, 자재 grade 불일치 등)
- `DocumentError` — 서류 오류·누락 (Code Case 미기재, 재발행 필요 등)
- `Microstructure` — 미세조직 관련 이슈 (delta ferrite 사진 누락, 값 미기재 등)
- `NDE` — comment에서 파악된 NDE 이슈 (MT/PT 미수행 언급 등)
- `Chemistry` — comment에서 파악된 화학성분 이슈 (N/Al 미기재 언급 등)
- `Other` — 위 카테고리에 해당하지 않는 기타 검토자 이슈

> Python deterministic 판정(Phase 3)이 이미 수치 위반으로 잡은 항목과 **중복되는 finding은 생성하지 않는다** (deduplicate).

### 10.4 llm_findings.json 경량 스키마

출력 파일명: `<case_id>_llm_findings.json`

```json
{
  "case_id": "...",
  "findings": [
    {
      "finding_id": "(선택) 문자열, 예: F-LLM-001",
      "category": "Identification|DocumentError|Microstructure|NDE|Chemistry|Other",
      "severity": "Reject|ActionRequired|Question|Minor",
      "material_grade": "성적서 페이지에서 귀속된 grade 문자열",
      "heat_no": "해당 Heat 번호 (알 수 없으면 null)",
      "cert_pdf": "성적서 파일명 (확장자 포함)",
      "page_ref": "페이지 번호 또는 범위 (예: 2 또는 2-3, 모를 경우 null)",
      "issue_summary": "검토자 스타일의 한국어 요약 (1–2문장)",
      "details": "상세 설명 (영어 또는 한국어)",
      "required_action": "제조사·공급사에 요구할 조치 내용",
      "evidence": [
        {
          "channel": "annotations|emails|body",
          "cert_stem": "(선택) 해당 성적서 파일의 stem (확장자 제외)",
          "snippet": "<채널 원문에서 그대로 복사한 텍스트 — extracted.json 안에 literal로 존재해야 함>"
        }
      ]
    }
  ]
}
```

### 10.5 snippet 검증 규칙 (C2/C8 준수)

- `snippet`은 **채널 원문(`extracted.json` 내부 텍스트)에서 공백 정규화 후 literal 일치**해야 한다.
- source_validator가 `snippet`이 해당 채널 텍스트에 존재하지 않으면 해당 finding을 `dropped_findings.json`으로 격리한다.
- snippet을 요약하거나 재작성하지 말 것. 검토자가 쓴 원문 그대로 복사한다.

### 10.6 Finding 분리·병합 원칙

- **단일 이슈 = 단일 finding**: 같은 검토자 코멘트("delta ferrite 미기재 + 대표 사진 누락")에서 파생된 이슈는 finding 하나로 합친다. 억지로 분리하지 않는다.
- **복수 Heat에 걸친 동일 이슈**: Heat별로 별도 finding을 생성하되, `heat_no`를 각각 명시한다.
- **Python deterministic finding과 중복**: `issue_summary`나 `category`+`heat_no` 조합이 기존 numeric finding과 동일하면 LLM finding을 생성하지 않는다.

## 11. CATEGORY CALIBRATION (enum 라벨 정렬)

검토자가 부여하는 category는 아래 경계를 따른다. 이슈를 정확히 찾았더라도 라벨이 틀리면 GT와 매칭되지 않으므로 아래 규칙을 엄격히 적용한다.

| category | 적용 대상 (이 패턴이면 반드시 이 라벨) |
|---|---|
| `Identification` | **식별·적합성 속성의 불일치/모호**: Heat No., Cert No., Spec/Code 명칭, Grade, Marking, **수량(Quantity)**, **사이즈(Size)·두께 스케줄(XXS/S160 등)**, **치수(Dimension) 실측 허용범위 초과**, 제품 유형(Welded vs SMLS) 불일치. → PO/MPR/도면과 성적서 기재가 다르거나 모호하면 **Identification** |
| `DocumentError` | **성적서 자체의 내부 오류·누락**: 산술 오기(Impact 평균 30 vs 실제 29), 기준값 오기(Mn max 1.35 vs 1.65), Code Case 문구 누락, 적용 표준 라벨 오기(A182 vs SA182), 발행일 오류, 채워야 할 칸 미기입 |
| `Chemistry` | 화학 성분 값/누락 (N/Al 미기재, Pb 초과, CEF 산정 불가 등) |
| `Mechanical` | TS/YS/EL/RA/경도/충격 값·누락 |
| `HeatTreatment` | 열처리 온도/시간/방법/누락 |
| `NDE` | UT/MT/PT/RT/Hydro 미수행·조건 불만족 |
| `Microstructure` | delta ferrite, grain size, 대표 사진 등 |
| `Other` | **위 어느 것에도 명확히 속하지 않을 때만**. ID·문서·시험 속성 이슈라면 절대 Other로 두지 말 것 |

> 자주 틀리는 경계: **치수/수량/사이즈/Heat No 불일치 → `Identification`** (DocumentError나 Other 아님). **성적서 내부 계산·표기 오류 → `DocumentError`**.

### 11.1 누락 vs 불일치 우선순위 (중요)

값/필드의 상태에 따라 category가 갈린다:

- **누락·미기입·미접수 → `DocumentError`** (그 속성이 치수·식별 속성이라도 우선). 성적서에 마땅히 있어야 할 항목/문서가 **없는** 경우는 내부 누락이다.
  - 예: "Branch 부 두께 **누락**" → DocumentError (Identification 아님). "Item No.45 성적서 **미접수**/누락" → DocumentError. "Code Case 문구 누락" → DocumentError.
- **값이 존재하나 PO/MPR/도면과 불일치·모호 → `Identification`** (해당 속성이 식별 속성일 때).
  - 예: "XXS vs S/160 혼용 표기"(모호) → Identification. "Heat No. 불일치"(값 있으나 다름) → Identification. "치수 실측값이 허용범위 초과"(값 존재, 이탈) → Identification.
- 즉 **존재-but-틀림 = Identification**, **아예-없음 = DocumentError**.

### 11.2 자재 spec 표준 불일치 (ASME SA vs ASTM A) — 에러로 판정

MPS/PO 발주 spec과 성적서 기재 spec의 **표준 계열·접두어가 다르면 사실상 동일 자재여도 `Identification` 에러(FAIL)**로 판정한다. 발주서와 성적서의 자재 식별이 형식상 불일치하므로 시정(성적서 재발행) 대상이다.

- 예: MPS 발주 **ASME SA-106** (일반요건 SA-530) ↔ 성적서 **ASTM A-106** 기재 → **FAIL / Identification**. (ASME `SA-` 접두 vs ASTM `A-` 접두)
- 예: 발주 SA-182 ↔ 성적서 A182, 발주 SA-234 ↔ 성적서 A234 등 동형.
- 화학·기계 기준값은 ASME SA-xxx ≈ ASTM A-xxx로 사실상 동일하므로 **기준값 비교는 통과**할 수 있으나, **표기/식별 검토(표기·형식 시트)에서 별도 FAIL** 항목으로 기록한다.
- 단순 **판년도(edition) 차이**만 있는 경우(같은 표준 계열, 예: A106-2019 vs A106-2022)는 §13/Code Edition 규칙에 따라 **주의**로 처리(에러 아님). 표준 계열 자체가 다른 경우만 본 규칙(FAIL) 적용.

> 결정적 엔진(compare_engine)은 MPS 발주 spec을 구조화 입력으로 갖지 않으므로 본 판정은 Phase 5(LLM)·compliance 검토 경로에서 cert.header.spec ↔ MPS 발주 spec 비교로 수행한다.

## 12. PAGE 귀속 규칙 (page_ref 정합)

- `page_ref`은 **주석(annotation)의 원본 페이지 번호**(`channels.annotations.items[].page`)를 사용한다. 이 번호는 rawdata 원본 PDF 기준이며 GT의 page 번호와 같은 체계다.
- 렌더링된 cleanup PNG의 인덱스(부분 페이지 추출로 재번호된 값)를 page_ref로 쓰지 말 것. cleanup 본문은 원본의 일부 페이지만 담아 페이지가 어긋난다.
- 이메일 유래 finding은 page_ref를 null로 두거나, 이메일이 특정 페이지를 지목하면 그 번호를 쓴다.

## 13. 완전성 원칙 (Recall 우선)

- **모든 distinct 검토자 표시를 finding으로 만든다**: 텍스트 주석, 마킹+이메일 언급, zip 폴더명(이슈별 분류), 이메일 본문 각 지적 사항을 빠짐없이 포착한다.
- subtle 항목을 "노이즈"로 버리지 말 것:
  - 값이 이상해 보여 확인 요청한 항목(예: 경도 22 HRB) → **Question/해당 category**
  - 모호한 표기(XXS vs S/160) → **Question/Identification**
  - 산술·표기 오기(Impact 평균) → **Minor/DocumentError**
  - remark란 Item No./수량 불일치 → **Minor/Identification** (spec 영향 없으면 Minor)
- false positive 억제: 근거(annotation/email/zip 폴더명)가 없는 추정성 finding은 만들지 않는다. 모든 finding은 evidence snippet이 실재해야 한다.
- **포괄적 확인 메모 제외**: "성적서 확인 요청", "전반 확인 바람" 같이 **구체적 이슈를 특정하지 않는 전체 성적서 단위의 일반 확인 멘트**는 별도 finding으로 만들지 않는다 (precision을 떨어뜨리는 noise). 단, **특정 값/항목에 대한 확인 요청**(예: "경도 22 HRB로 낮음 — 확인 바람", "이 Heat의 N/Al 확인")은 Question finding으로 생성한다. 구분 기준: 확인 대상이 **구체적 측정값·항목·페이지**로 특정되면 finding, 성적서 전체에 대한 막연한 멘트면 제외.
