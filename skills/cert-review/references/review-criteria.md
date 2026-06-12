# Review Criteria (도메인 규칙 참조)

본 문서는 **Claude compliance 판정 시점에만** 참조하는 도메인 규칙 정리본이다. 모든 수치는 플러그인의 `data/*.csv`의 출처 메타데이터(3종)를 통해 ref_code/MPS에서 인용된 것이며, 본 문서에 적은 수치는 가독성을 위한 사본일 뿐 **런타임 판정에는 CSV만 사용**한다.

> **출력 표기 규약**: 보고서 문구·findings·notes·doc_checks 등 모든 출력 문구에 절 기호(섹션 부호)를 사용하지 말 것. 본 문서의 기준 조항을 참조할 때는 `기준 3.1`, `기준 11.2`처럼 "기준 N" 형식으로 표기한다.

## 0. 출처 강제 원칙 (C2/C8)

| 단계 | 규칙 |
|---|---|
| CSV row import | 메타 3종(source_file/anchor/snippet) 없으면 거부 |
| Python 결정적 판정 | CSV에서만 수치 인용. 코드에 하드코딩된 수치 사용 금지 |
| Claude 보조 판정 | cert body / MPS 텍스트에서 evidence를 인용하지 않으면 finding 작성 금지 |
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
| `A193 B7` | SA-193 B7 | ASTM_A193_A193M_14 (ref_code 부재 시 MPS만) | 볼트 |
| `A194 2H`, `A194 7` | SA-194 2H/7 | ASTM_A194_A194M_14a (ref_code 부재 시 MPS만) | 너트 |
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

## 7. Finding 카테고리 정의 (도메인 의미 기반)

각 카테고리는 검토 대상 도메인 속성으로 정의한다. 검출 방식과 필수 evidence channel을 함께 명시한다.

| Category | 도메인 의미 | 검출 방식 | 필수 evidence channel |
|---|---|---|---|
| Chemistry | 화학성분 값·범위·누락 | CSV 룩업 비교 | body + mps/ref_code |
| Mechanical | 인장·항복·연신·경도·충격 | CSV 룩업 비교 | body + mps/ref_code |
| HeatTreatment | 열처리 온도·시간·방법 | CSV 룩업 비교 | body + mps/ref_code |
| NDE | UT/MT/PT/RT/Hydro 수행·조건 | 비교 + 본문 판독 | body 또는 mps |
| Microstructure | δ-ferrite·grain size·대표 사진 | 수치 비교 + 본문 판독 | body 또는 mps |
| Identification | 식별·적합성 속성 불일치 (PO/Heat/Spec/치수·수량 등) | 본문 ↔ MPS 대조 | mps 또는 body |
| DocumentError | 성적서 내부 오류·누락 | 본문 판독 | body 또는 mps |
| Other | 위 카테고리에 명확히 속하지 않는 이슈 | 본문 판독 | body |

## 8. Severity 결정 룰

| 조건 | severity |
|---|---|
| MPS/Code 명시 한계 초과 (수치) | Reject |
| 요구 시험·기재 누락 | ActionRequired |
| "??? please explain" 등 의문 표기 | Question |
| 단순 표기 오류, 사인 누락 | Minor |

값이 경계치 ±10% 이내이고 한계를 넘지 않으면 WARNING은 카테고리가 아니라 비고로만 기록.

## 9. SEVERITY CALIBRATION (도메인 심각도 기준)

본 섹션은 severity 값(Reject / ActionRequired / Question / Minor)의 도메인 적용 기준을 정의한다. 아래 규칙은 측정값 위반·서류 누락·확인 요청·경미 오타 등 검토 상황별로 일관된 심각도를 부여하기 위한 것이다.

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

## 10. Claude 보조 Finding 생성 가이드

CSV·도메인 룰 비교로 잡히지 않는 **본문/MPS 대조 기반 이슈**(식별 불일치, 서류 누락, 사진 누락 등)를 Claude가 직접 읽고 finding으로 생성하는 단계다.

### 10.1 입력 채널

Claude는 다음 채널을 읽어 finding 후보를 식별한다:

| 채널 키 | 소스 경로 | 내용 |
|---|---|---|
| `body` | `extracted.json` → `page_extraction[page]` (channels.body) | 성적서 페이지 본문 (Claude Vision OCR 결과) |
| `mps` | MPS 스캔 OCR 본문 | 발주 spec·요구사항 (식별·적합성 대조용) |

### 10.2 Grade 귀속 규칙

finding이 특정 페이지와 연결되어 있으면 **그 페이지의 `page_extraction[page].header.grade`** 값을 해당 finding의 `material_grade`로 사용한다. 페이지 연결 정보가 없는 경우에는 해당 case의 대표 grade를 사용한다.

### 10.3 Finding 생성 대상 카테고리

본 단계에서 생성하는 finding의 카테고리는 다음으로 제한한다:

- `Identification` — 자재 식별 불일치 (PO 번호, Heat 번호, 자재 grade·spec 불일치 등)
- `DocumentError` — 서류 오류·누락 (Code Case 미기재, 재발행 필요 등)
- `Microstructure` — 미세조직 관련 이슈 (delta ferrite 사진 누락, 값 미기재 등)
- `NDE` — 본문에서 파악된 NDE 이슈 (MT/PT 미수행 등)
- `Chemistry` — 본문에서 파악된 화학성분 이슈 (N/Al 미기재 등)
- `Other` — 위 카테고리에 해당하지 않는 기타 이슈

> 수치 비교(CSV 룩업)가 이미 잡은 항목과 **중복되는 finding은 생성하지 않는다** (deduplicate).

### 10.4 finding 경량 스키마

각 보조 finding은 compliance `review.json`에 다음 형태로 기록한다:

```json
{
  "case_id": "...",
  "findings": [
    {
      "finding_id": "(선택) 문자열, 예: F-001",
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
          "channel": "body|mps",
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

## 11. CATEGORY CALIBRATION (라벨 경계)

category 라벨은 아래 도메인 경계를 따른다. 이슈를 정확히 찾았더라도 라벨이 일관되지 않으면 보고서 분류가 흔들리므로 아래 규칙을 엄격히 적용한다.

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
- 단순 **판년도(edition) 차이**만 있는 경우(같은 표준 계열, 예: A106-2019 vs A106-2022)는 기준 13/Code Edition 규칙에 따라 **주의**로 처리(에러 아님). 표준 계열 자체가 다른 경우만 본 규칙(FAIL) 적용.
- **적용 범위 한정**: 본 판정은 발주 품목의 **제품 spec 라인**(Material Code / Material standard / fitting standard)에만 적용한다. 제품 spec 라인이 발주와 일치하면 **raw material(모관·소재) 라인**의 ASTM 표기는 finding으로 만들지 않는다 (SA-234/A234는 A335 계열 원소재를 명시 허용 — 실질 동등). 또한 MPS 적용문서·일반요건에 ASTM 시리즈가 명시돼 있으면(예: 'ASTM A105M-2021' 발주) 접두 차이를 지적하지 않으며, MPS가 명시적으로 ASME SA만 요구할 때만 본 규칙을 적용한다.

> 본 판정은 compliance 검토 경로(Claude 보조)에서 cert.header.spec ↔ MPS 발주 spec 비교로 수행한다. CSV 룩업만으로는 발주 spec을 구조화 입력으로 갖지 않으므로 본문/MPS 대조가 필요하다.

## 12. PAGE 귀속 규칙 (page_ref 정합)

- `page_ref`은 finding 근거가 위치한 **성적서 본문 페이지 번호**(cert cleanup PDF 기준, `channels.body.pages`)를 사용한다.
- 렌더링된 PNG 파일 stem의 `_pNN` 인덱스와 본문 논리 페이지가 어긋날 수 있으므로, 본문에 실제로 표기된 페이지 번호를 우선한다.

## 13. 완전성 원칙 (Recall 우선)

- **모든 distinct 위반·불일치를 finding으로 만든다**: 본문 수치 위반, MPS 대조 불일치, 누락 항목을 빠짐없이 포착한다.
- subtle 항목을 "노이즈"로 버리지 말 것:
  - 값이 이상해 보여 확인이 필요한 항목(예: 경도 22 HRB) → **Question/해당 category**
  - 모호한 표기(XXS vs S/160) → **Question/Identification**
  - 산술·표기 오기(Impact 평균) → **Minor/DocumentError**
  - remark란 Item No./수량 불일치 → **Minor/Identification** (spec 영향 없으면 Minor)
- false positive 억제: 본문/MPS 근거가 없는 추정성 finding은 만들지 않는다. 모든 finding은 evidence snippet이 실재해야 한다.
- **포괄적 확인 메모 제외**: "성적서 확인 요청", "전반 확인 바람" 같이 **구체적 이슈를 특정하지 않는 전체 성적서 단위의 일반 확인 멘트**는 별도 finding으로 만들지 않는다 (precision을 떨어뜨리는 noise). 단, **특정 값/항목에 대한 확인 요청**(예: "경도 22 HRB로 낮음 — 확인 바람", "이 Heat의 N/Al 확인")은 Question finding으로 생성한다. 구분 기준: 확인 대상이 **구체적 측정값·항목·페이지**로 특정되면 finding, 성적서 전체에 대한 막연한 멘트면 제외.

## 14. 자체 인쇄 기준 자기정합 (성적서 내 Standard 행 대조)

성적서가 스스로 인쇄한 기준값 행(Standard value / Spec min·max / 標準值 등)이 있으면, **모든 결과값(成品值/Result) 행을 그 인쇄 기준과 행·열 단위로 1:1 대조**한다.

- 결과값이 자체 표기 기준을 벗어나면 — 외부 Code/CSV 기준으로는 합격이더라도 — `기준 미달`(Mechanical/Chemistry FAIL) 또는 `기준값 오기`(DocumentError) 중 하나가 반드시 성립하므로 finding으로 보고하고 재발행·해명을 요구한다.
- 성적서 표기 기준이 Code보다 엄격할 때 **더 느슨한 Code 값으로 묵시 대체 판정하는 것을 금지**한다.
- 연신율(EL) 판정 시 성적서의 시편 형상(round vs strip, 폭·G.L., L/T 방향)을 확인한다. CSV의 EL min이 어느 시편 기준인지 명시되지 않았으면 시편 불일치 가능성을 주의로 표기한다.
- 역방향(성적서 인쇄 기준이 Code보다 **느슨**한 경우, 예: CL.3 자재에 CL.1 한계 인쇄)도 `DocumentError — 인쇄 기준 오기`로 보고한다 (실측이 엄격한 쪽 기준을 충족하는지도 병기).

## 15. spec 표기 검증 (존재하지 않는 규격 번호)

- Phase 2가 verbatim 전사한 모든 규격 번호(제품·원소재·시험규격)를 보유 카탈로그(`grade_routing.csv`, `code_edition_map.csv`, ref_code 폴더명)와 대조한다.
- **카탈로그·실존 표준 목록에 없는 규격 번호는 가장 유사한 유효 규격으로 치환하지 말고** `DocumentError/Identification — 존재하지 않거나 확인 불가한 규격 표기(재발행 요청 대상)`로 보고한다. 추정 규격은 note에만 기재하고 판정은 원문 표기 기준으로 한다.
- 단순 표기 형식 차이(ASME 정식 표기에 하이픈 유무, 'SA193-B7' 등)는 본 규칙의 대상이 아니다 — 실존 규격의 표기 변형은 지적하지 않는다.

## 16. Class 제한 및 (Grade, Class, Heat) 커버리지

- Phase 2 인벤토리의 모든 (Grade, Class, Heat) 고유 조합이 materials[]에 매핑되어 각각 검토되어야 한다. **Grade가 같아도 Class가 다르면 별개 품목**이다 (대표 페이지 샘플링은 동일 조합 그룹 내부에서만 허용).
- MPS의 **Class 제한 문구**(`CL.1만 허용`, `CL.2 or 3 is not allowed`)와 **수기·적색 개정 노트**는 체크리스트 항목으로 승격한다: 측정값이 범위 내여도 (a) 품목의 Class 표기 자체, (b) 성적서에 인쇄된 수검기준(standard value) 범위가 MPS 제한과 다르면 부적합으로 보고한다.
- Class가 있는 grade(SA-182 F22, SA-234 WP11/WP22 등)는 cert의 Class 표기(CL.1/2/3)를 먼저 추출하고 **해당 Class의 기준값 행만** 사용한다. CSV에 Class 병합 행만 있으면 ref_code 원문 Table을 직접 재확인 후 판정한다.

## 17. Finding 발행 게이트 (precision 방어선)

모든 finding은 아래 게이트를 통과해야 `findings[]`에 들어간다. 게이트에 걸리는 항목은 버리는 것이 아니라 `doc_checks`/`notes`(정보성) 또는 `code_edition_note`(검토 한계 메타)로 분리 기록한다.

### 17.1 요구 근거 게이트
- Reject/ActionRequired finding은 **현재 케이스 MPS의 문서번호+항번** 또는 **code 조항('shall' 수준)**을 인용할 수 있을 때만 발행한다. 인용 불가 → 발행 금지.
- action 문구가 "확인 요청/권장/보완 검토"로 끝나고 위반 수치·조항이 없는 항목은 findings에 넣지 않는다.
- **타 케이스/타 MPS 계열 조항 전이 금지**: 다른 구매자·다른 MPS의 유사 조항(δ-ferrite 사진, butt weld 100% MT/PT, PMI 등)을 grade가 같다는 이유로 현재 케이스에 적용하지 않는다.
- **수신 문서 구분**: "CMTR과 함께 제출하는 별도 문서(item list/packing list)에 기재" 요구를 "CMTR 본문 기재 누락"으로 보고하지 않는다. 별도 문서의 존부를 확인할 수 없으면 finding을 생략한다.
- MPS 문서요건표를 근거로 들 때는 해당 행이 **(X)로 마크**되었는지 crop 판독으로 확인한다. 빈 괄호 `( )` 항목은 요구사항이 아니다. 보고요구 컬럼과 witness/hold 컬럼을 혼동하지 않는다.

### 17.2 적용성 게이트
- 조건부 요구는 대상 품목의 적용성을 먼저 판정한다: 제품 형상 한정(`butt weld end bevel` 한정 MT/PT → SW/threaded/blind 품목 미적용), 치수·등급 조건(A105 열처리: over NPS4 **and** above Class 300), `If Any` 단서, 비금속 자재에 금속 NDE 등. 미적용이면 '미기재' finding 대신 N/A로 기록한다.
- spec 적합 선언이 내포하는 속성(예: A672 = 종방향 시임 용접, seamless = 용접부 없음)에 대해 "명시 없음/확인 불가" finding을 만들지 않는다.
- 조항의 부등호 방향·적용 제품형태를 원문 그대로 보존한다 (elbow 조항을 reducer/tee에 적용 금지).

### 17.3 기준값 출처 게이트
- FAIL에 사용하는 한계값은 **grade+Class+Type+시편방향이 정확히 일치하는 행**만 사용한다.
- 둘 이상의 출처(ASTM 원문 OCR vs ASME SEC II OCR vs data CSV vs 성적서 인쇄 기준란)가 **충돌하면 FAIL을 발행하지 않고** 충돌 사실을 주의/검증노트로 출력한다. 인접 행과 동일 값이 반복되는 표(행 시프트 시그널)는 원문 페이지를 재확인한다.
- 성적서 인쇄 기준란과 적용 기준이 **3개 이상 속성에서 동시에** 어긋나면 제조사 오기보다 스킬 측 기준 선택 오류(Class 오인·OCR 행 시프트)를 먼저 의심하고 재검증한다.
- CSV 행 사용 전 provenance anchor의 grade 토큰이 대상 grade와 일치하는지 확인한다. 불일치 행은 사용 금지하고 데이터 버그로 보고한다.
- MPS 표의 해당 셀이 `Note N`/`to be reported`/`---`/공란이면 수치 한계가 아니므로 위반 판정 금지. 성적서의 측정값(<0.001 등)을 한계값으로 역사용하지 않는다.

### 17.4 부재 주장 게이트 ('미기재' finding 전 필수 확인)
- 전 페이지의 **Remark/각주/헤더 Material 라인까지 판독한 뒤에만** 'X 미기재'를 발행한다 (PMI·ferrite·Code Case·열처리 세부는 Remark 기재 관행).
- 해당 셀을 crop/zoom 재판독해 픽셀 수준 공란을 확인한다. 숫자·기호가 하나라도 보이면 공란 finding을 폐기한다.
- 결과란의 `/`·`-`는 N/A(미적용) 관행 표기다 — 해당 시험이 MPS에서 명시 요구된 경우에만 '미수행/미기재'로 발행한다.
- 성적서가 별도 Report No.를 명시 인용하면(예: 'Ferrite Contents Report No. ...') '미기재 FAIL' 대신 '참조 리포트 확인 필요' 주의로 강등한다.
- Product Analysis(P행) 공란은 제품규격 의무 또는 MPS의 명시 요구('shall')가 있을 때만 finding으로 한다. 'purchaser may' 조항뿐이면 양식 잔재로 간주한다 (A105/A182 계열은 heat analysis만 의무).

### 17.5 OCR 재검증 게이트
- 위반 성립이 OCR 숫자 **한 자리**에 달려 있으면 ≥3x zoom으로 재판독하고, '적합' 판독이 동등하게 가능하면 위반을 발행하지 않는다.
- 식별자 불일치(Heat No 등)의 한 글자 차이(H/N, 0/O, 1/I, 5/6)는 양쪽 위치를 재판독한 후 동일하면 발행 금지. 실제 상이가 확정될 때만 보고.
- 기호·약어는 같은 문서의 범례/각주를 먼저 해석한다 (`•L=Longitudinal`을 304L로 추정 금지).
- '값 불명확, 재확인 필요' 류 자기불확실 항목은 findings 금지 — zoom 재판독으로 확정하거나 extraction 주의 노트로 분리한다.

### 17.6 병합 원칙
- 동일 이슈(같은 속성·같은 근본원인)는 페이지/Heat가 달라도 **finding 1건**으로 통합하고 위치를 `p.3~p.8 (Heat A/B/C)` 식으로 나열한다. 페이지당/Heat당 분리 생성 금지 (기준 10.6의 'Heat별 분리'보다 본 규칙이 우선한다 — 단일 이슈가 복수 Heat에 걸치면 1건에 heat 목록 병기).
- 단일 이슈의 하위 측면(수치/방법/사진)과 파생 관찰(원인 규명, 적용조건 확인불가)은 별도 finding으로 쪼개지 않고 주 finding의 note/action에 병합한다.
- 예외(기준 16/NDE 적용성 분리): 요건 **트리거 식별**(예: butt welding end 보유 제품)과 **요건 위반**(MT/PT 미수행)은 서로 다른 판정이므로 각각 1건씩 둔다.

### 17.7 정보성 분리
- 위반이 아닌 관찰은 findings에 넣지 않는다: 값 적합 + 양식/위치 메모, PASS·경계 근접("마진 0") 확인, 보수적 양식 인쇄값, 동등 spec 접두 혼재(원소재 라인), 요구 근거 없는 항목의 공란(Charpy 빈 칸 등), 채번 순서 추정.
- **열처리 기록 공란 예외**: 성적서가 열처리 수행을 표기(N/T 온도 기재 등)했으나 **유지시간(holding time)이 표시되지 않은** 경우, MPS/Code가 해당 자재의 열처리 기록 보고를 요구하면(열처리 의무 자재의 CMTR 열처리 기재 요건 포함) 이는 정보성이 아니라 `HeatTreatment — 유지시간 미기재`(ActionRequired) finding으로 발행한다. 요구 근거가 전혀 없는 경우에만 정보성으로 분리한다.
- 검토 한계 메타(MPS 미제공, ref_code 미수록, 배치 범위)는 `code_edition_note`로만 기록한다.
- **Reject는 명문 한계의 수치 초과/미달이 확정된 경우에만** 사용한다. 표기·양식·문서관리성 관찰은 최대 '주의'(Question/Minor)로 제한한다.
- 단위 상이 항목은 환산 판정 우선: 환산값이 범위 내면 MPS에 명시적 단위 조항이 있을 때만 Minor 1건, 없으면 doc_checks 메모.

## 18. 검토자 표준 어휘 (issue_summary 표기 규약)

`issue_summary`는 실제 검토자의 관용구로 작성한다 — 보고서 일관성과 후속 검색성을 위한 표기 규약이다.

| 상황 | 표준 어휘 |
|---|---|
| 측정값이 max 초과 | "**기준값 초과**" (예: "P 0.050% — 인쇄 spec max 0.035% 기준값 초과") |
| 측정값이 min 미달 | "**기준 미달**" (예: "TS 400MPa — 성적서 표기 최소 415MPa 기준 미달") |
| 항목·문서 없음 | "**누락**" / "**미기재**" |
| 값 존재하나 다름 | "**불일치**" |
| 요구 시험 미실시 | "**미수행**" |
| 표기 오류 | "**오기**" |
| 동일 번호 재사용 | "**중복**" |
| 판정 불가 | "**확인 불가**" |

- 요약 문장에 **핵심 속성명(원소 기호·시험 항목)과 측정값·기준값 수치를 포함**한다 (예: "Cr 8.49% — SA-234 WP91 기준 8.0~9.5% 내 적합" 식의 PASS 문장은 findings에 쓰지 않음).
- 제품 특성·단부 형상·치수 표기를 언급할 때는 성적서/도면 원문 표기를 그대로 보존해 요약에 사용한다 (임의 번역·의역으로 원문 키워드를 소실시키지 않는다).
