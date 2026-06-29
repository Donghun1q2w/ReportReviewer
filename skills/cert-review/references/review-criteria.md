# Review Criteria (domain rule reference)

This document is a consolidated set of domain rules referenced **only at the moment of Claude compliance judgment**. All numeric values are cited from ref_code/MPS via the source metadata (3 types) in the plugin's `data/*.csv`; the numbers written in this document are merely copies for readability, and **only the CSV is used for runtime judgment**.

> **Output notation convention**: Do not use the section sign (§) in any output text — report wording, findings, notes, doc_checks, etc. All output text — findings, notes, doc_checks, issue_summary — is authored in Korean (reviewer vocabulary). When referencing a criterion clause in this document, use the "기준 N" format, e.g. `기준 3.1`, `기준 11.2`.

## 0. Source Enforcement Principle (C2/C8)

| Stage | Rule |
|---|---|
| CSV row import | Reject if the 3 metadata types (source_file/anchor/snippet) are missing |
| Python deterministic judgment | Cite numbers only from CSV. Hardcoded numbers in code are prohibited |
| Claude auxiliary judgment | Do not write a finding without citing evidence from the cert body / MPS text |
| Pre-output validation | source_validator quarantines findings without evidence into dropped_findings.json |

## 1. Grade Routing (data/grade_routing.csv)

Maps the cert grade string → the ASME spec and ref_code file that serve as the review basis.

| Cert notation | ASME spec | ref_code folder | Note |
|---|---|---|---|
| `A106 B`, `SA106 Gr.B`, `SA-106 B` | SA-106 Gr.B | ASTM_A106_A106M_15 or _19a_RED | If MPS specifies, that edition year takes priority |
| `A106 C`, `SA-106 C` | SA-106 Gr.C | (same) | Mn max 1.65% (Footnote B) |
| `P11`, `A335 P11`, `F11` | SA-335 P11 / SA-182 F11 | ASTM_A335_A335M_19a, ASTM_A182_A182M_16a | |
| `P22`, `A335 P22`, `F22` | SA-335 P22 / SA-182 F22 | (same) | |
| `P91`, `A335 P91`, `F91`, `WP91` | SA-335 P91 / SA-182 F91 / SA-234 WP91 | (same) + MPS Restricted applied | |
| `P92`, `F92`, `WP92` | SA-335 P92 / SA-182 F92 / SA-234 WP92 | (same) | Trace elements MPS |
| `A105`, `SA-105` | SA-105 | ASTM_A105_A105M_14 | |
| `A193 B7` | SA-193 B7 | ASTM_A193_A193M_14 (MPS only if ref_code absent) | Bolt |
| `A194 2H`, `A194 7` | SA-194 2H/7 | ASTM_A194_A194M_14a (MPS only if ref_code absent) | Nut |
| `A672 B70` | SA-672 B70 | ASTM_A672_A672M_14 | Welded pipe |
| `A182 F304` | SA-182 F304 | ASTM_A182_A182M_16a | Stainless |
| `SCM435` | JIS G4105 SCM435 | (no code — MPS only) | Bolt material |

## 2. MPS Override Rules (data/mps_overrides.csv)

Items where MPS is stricter than Code (MPS takes priority):

| Grade | Item | Code basis | MPS basis | Source |
|---|---|---|---|---|
| P91 | C max | 0.12 | 0.12 (same) | SA-335 Table 1 |
| P91 | Mn max | 0.60 | 0.50 | MPS Table 1 Restricted |
| P91 | S max | 0.010 | 0.005 | MPS Table 1 Restricted |
| P91 | Ni max | 0.40 | 0.20 | MPS Table 1 Restricted |
| P91 | TS min | 585 MPa | 630 MPa (91 ksi) | MPS Table 2 |
| P91 | Normalizing | — | 1040–1080 °C | MPS Heat Treatment |
| P91 | Tempering | ≥730 °C | 750–780 °C | MPS Heat Treatment |
| P92 | TS min | 620 MPa | 620 MPa (same) | Code |
| P92 | Pb max | — | 0.001 (1 ppm) | MPS Trace Elements |
| P92 | Sb max | 0.003 | 0.003 (same) | Code |
| P92 | Normalizing | — | 1050–1080 °C | MPS Heat Treatment |
| P92 | Tempering | ≥730 °C | 760–780 °C | MPS Heat Treatment |
| P91·P92 | δ-ferrite | — | ≤5% (P91), ≤2.5% (P92) | MPS Microstructure |
| P91·P92 | N/Al ratio | — | ≥ 4 | MPS Chemistry |

## 3. Chemistry Judgment Rules

### 3.1 Basic Rules
- Both Heat Analysis and Product Analysis within the spec range
- **A106/SA-106 C/Mn footnote (Footnote A/B) — mandatory when judging Mn**:
  Per the Table 1 footnote, if C is below the specified max, Mn max is raised by that reduction amount.
  ```
  adjusted Mn max = min( base_Mn_max + floor((C_max - C_measured)/0.01) × 0.06 , cap )
     C_max : Gr.A 0.25 / Gr.B 0.30 / Gr.C 0.35
     cap   : Gr.A 1.35% / Gr.B·C 1.65%
     base_Mn_max : Table 1 Mn max (e.g. Gr.B/C 1.06)
  ```
  **Judge Mn against the adjusted max above, not the base max.** e.g. SA-106-B, C=0.17 → adjusted max = 1.06 + 13×0.06 = 1.84 → cap 1.65 → **Mn 1.21% is PASS** (no false positive). When C is near the max, the upward allowance is small, so a FAIL is normally possible.
- A106 five-element sum: Cr + Cu + Mo + Ni + V ≤ 1.0%
- P91/P92: Ni + Mn ≤ 1.0%

### 3.2 Column Consistency Verification
Scan OCR may shift columns. After extraction, Claude verifies:
1. Does each element value physically fit the Max/Min range of its column?
2. If the cert has Cev, does back-calculation match?  `Cev = C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15`
3. Does it match the usual per-grade range, e.g. P91 Cr ~9%, P22 Cr ~2%?

If inconsistent, do not retry OCR; **re-read the original PNG with vision and apply an explicit correction**.

## 4. Mechanical Property Judgment

| Item | Priority | Note |
|---|---|---|
| TS min | MPS > Code | P91: MPS 630MPa > Code 585MPa |
| YS min | MPS > Code | same |
| EL min | Code Table 2 | By specimen type (Round/Strip, L/T) |
| Hardness | MPS range | P91/P92: 200–248 HBW (MPS) |

## 5. Heat Treatment Judgment

- Overall PASS only when every stage (N → T → cooling) is each within range
- Deviation ≤ 10°C → WARNING, > 10°C → FAIL
- Holding time: MPS Table 2 minimum time by thickness + Tempering 1hr/25mm

## 6. NDE and Special Requirements

| Item | Rule |
|---|---|
| UT Notch | MILL → GE Notch (greater of ≤5% wall and 0.3mm), STOCK → Code Notch (≤12.5% wall, 0.1mm) |
| δ-ferrite | P91 ≤5%, P92 ≤2.5%, AMS-2315 or ASTM E562 measurement + representative photo attached |
| Code Case | P91: B31 Case 215-1, P92: CC 2179-11 + B31 Case 183-5 (or MPS-specified case) |
| MT/PT | Mandatory when machining Butt welding end / Bevel ends (MPS-specified) |
| PMI | Performed 100% |
| No Welding | When prohibited by MPS, confirm the "NO WELDING REPAIR" wording |

## 7. Finding Category Definitions (domain-meaning based)

Each category is defined by the domain attribute under review. The detection method and required evidence channel are specified together.

| Category | Domain meaning | Detection method | Required evidence channel |
|---|---|---|---|
| Chemistry | Chemistry value·range·omission | CSV lookup comparison | body + mps/ref_code |
| Mechanical | Tensile·yield·elongation·hardness·impact | CSV lookup comparison | body + mps/ref_code |
| HeatTreatment | Heat treatment temperature·time·method | CSV lookup comparison | body + mps/ref_code |
| NDE | UT/MT/PT/RT/Hydro performance·conditions | comparison + body reading | body or mps |
| Microstructure | δ-ferrite·grain size·representative photo | numeric comparison + body reading | body or mps |
| Identification | Identification·conformance attribute mismatch (PO/Heat/Spec/dimension·quantity, etc.) | body ↔ MPS cross-check | mps or body |
| DocumentError | Internal cert error·omission | body reading | body or mps |
| Other | Issue that clearly does not belong to the above categories | body reading | body |

## 8. Severity Decision Rules

| Condition | severity |
|---|---|
| Exceeds an MPS/Code stated limit (numeric) | Reject |
| Required test/entry omission | ActionRequired |
| Questioning marks such as "??? please explain" | Question |
| Simple notation error, missing signature | Minor |

If a value is within ±10% of the boundary and does not exceed the limit, record WARNING only as a note, not as a category.

## 9. SEVERITY CALIBRATION (domain severity basis)

This section defines the domain application basis for the severity values (Reject / ActionRequired / Question / Minor). The rules below are intended to assign consistent severity across review situations such as measured-value violations, document omissions, confirmation requests, and minor typos.

### 9.1 Reject

**Reject** if one or more of the following applies:

- **Numeric violation**: a measured value violates an MPS or Code hard limit (min/max).
  - e.g. Pb measured 0.004% > MPS limit 0.001%; YS measured below min; Cr out of range; Hardness exceeds max.
- **Required test not performed**: a test mandatory for the material type / delivery condition is **not performed at all**.
  - e.g. NDE (UT/MT/PT) not performed for a STOCK delivery condition.
- **Material/product type mismatch**: the cert's material grade or product type does not match the PO/MPS designation.

### 9.2 ActionRequired

**ActionRequired** if one or more of the following applies (document/entry supplementation needed without a numeric violation):

- Test record omission: MT/PT result not stated in the report (performance unknown).
- Representative photo omission: representative microstructure photo not attached when Delta ferrite measurement is required.
- Chemistry value not stated: an MPS-required element such as N or Al is not entered in the cert.
- Code Case wording not stated: the Code Case number or conformance declaration required by MPS/Code is missing.
- Re-issue needed due to misentered quantity/dimension/Spec: the error itself is not a numeric violation, but delivery is impossible without re-issuing the document.
- Insufficient Product Analysis count: the actual number of PA records falls short of the required number of Heats.

### 9.3 Question

- The reviewer has written an **explicit question or confirmation request** such as "??? please explain" or "please confirm".
- A value looks abnormal but it is unclear whether it exceeds the limit, so **no judgment is possible without further explanation**.
- It may not necessarily be a defect and can be resolved by a manufacturer reply.

### 9.4 Minor

- A **pure typo** with no spec impact (unit notation, decimal-place notation, etc.).
- A **procedural omission** such as a missing signature/seal, but with no effect on the review judgment.
- A reviewer memo-type comment requiring no Action.

### 9.5 Composite Judgment Priority

If multiple severities could apply to the same item, use **only the single higher severity** (Reject > ActionRequired > Question > Minor). Do not split the same reviewer issue into two findings.

## 10. Claude Auxiliary Finding Generation Guide

This is the stage where Claude directly reads and generates findings for **body/MPS cross-check based issues** (identification mismatch, document omission, photo omission, etc.) that CSV/domain-rule comparison does not catch.

### 10.1 Input Channels

Claude reads the following channels to identify finding candidates:

| Channel key | Source path | Content |
|---|---|---|
| `body` | `extracted.json` → `page_extraction[page]` (channels.body) | Cert page body (Claude Vision OCR result) |
| `mps` | MPS scan OCR body | Order spec·requirements (for identification·conformance cross-check) |

### 10.2 Grade Attribution Rule

If a finding is linked to a specific page, use **that page's `page_extraction[page].header.grade`** value as the finding's `material_grade`. If there is no page-link information, use the case's representative grade.

### 10.3 Finding Generation Target Categories

The categories of findings generated in this stage are limited to:

- `Identification` — material identification mismatch (PO number, Heat number, material grade·spec mismatch, etc.)
- `DocumentError` — document error·omission (Code Case not stated, re-issue needed, etc.)
- `Microstructure` — microstructure-related issue (delta ferrite photo omission, value not stated, etc.)
- `NDE` — NDE issue identified in the body (MT/PT not performed, etc.)
- `Chemistry` — chemistry issue identified in the body (N/Al not stated, etc.)
- `Other` — other issue not falling under the above categories

> **Do not generate a finding that duplicates** an item already caught by numeric comparison (CSV lookup) (deduplicate).

### 10.4 Lightweight Finding Schema

Each auxiliary finding is recorded in the compliance `review.json` in the following form:

```json
{
  "case_id": "...",
  "findings": [
    {
      "finding_id": "(optional) string, e.g. F-001",
      "category": "Identification|DocumentError|Microstructure|NDE|Chemistry|Other",
      "severity": "Reject|ActionRequired|Question|Minor",
      "material_grade": "grade string attributed from the cert page",
      "heat_no": "the Heat number (null if unknown)",
      "cert_pdf": "cert file name (including extension)",
      "page_ref": "page number or range (e.g. 2 or 2-3, null if unknown)",
      "issue_summary": "Korean reviewer-style summary (1–2 sentences)",
      "details": "detailed description (English or Korean)",
      "required_action": "the corrective action to request from the manufacturer/supplier",
      "evidence": [
        {
          "channel": "body|mps",
          "cert_stem": "(optional) the stem of the cert file (excluding extension)",
          "snippet": "<text copied verbatim from the channel source — must exist as a literal in extracted.json>"
        }
      ]
    }
  ]
}
```

### 10.5 snippet Validation Rules (C2/C8 compliance)

- `snippet` must be a **literal match against the channel source (text inside `extracted.json`) after whitespace normalization**.
- If source_validator finds that `snippet` does not exist in the channel text, it quarantines the finding into `dropped_findings.json`.
- Do not summarize or rewrite the snippet. Copy the reviewer's original text verbatim.

### 10.6 Finding Splitting·Merging Principle

- **Single issue = single finding**: issues derived from the same reviewer comment ("delta ferrite 미기재 + 대표 사진 누락") are merged into one finding. Do not force a split.
- **Same issue across multiple Heats**: create a separate finding per Heat, but state each `heat_no`.
- **Duplicate of a Python deterministic finding**: if `issue_summary` or the `category`+`heat_no` combination is identical to an existing numeric finding, do not generate the LLM finding.

## 11. CATEGORY CALIBRATION (label boundaries)

Category labels follow the domain boundaries below. Even if an issue is found correctly, inconsistent labeling destabilizes report classification, so apply the rules below strictly.

| category | Applies to (this pattern must take this label) |
|---|---|
| `Identification` | **Mismatch/ambiguity of identification·conformance attributes**: Heat No., Cert No., Spec/Code name, Grade, Marking, **Quantity**, **Size·thickness schedule (XXS/S160, etc.)**, **Dimension measured value exceeding tolerance**, product type (Welded vs SMLS) mismatch. → If the cert entry differs from or is ambiguous against the PO/MPR/drawing, **Identification** |
| `DocumentError` | **Internal error·omission within the cert itself**: arithmetic misentry (Impact average 30 vs actual 29), reference-value misentry (Mn max 1.35 vs 1.65), Code Case wording omission, applied-standard label misentry (A182 vs SA182), issue-date error, a blank that should be filled left empty |
| `Chemistry` | Chemistry value/omission (N/Al not stated, Pb exceedance, CEF cannot be computed, etc.) |
| `Mechanical` | TS/YS/EL/RA/hardness/impact value·omission |
| `HeatTreatment` | Heat treatment temperature/time/method/omission |
| `NDE` | UT/MT/PT/RT/Hydro not performed·conditions not satisfied |
| `Microstructure` | delta ferrite, grain size, representative photo, etc. |
| `Other` | **Only when it clearly belongs to none of the above**. Never leave an ID·document·test attribute issue as Other |

> Commonly mistaken boundaries: **dimension/quantity/size/Heat No mismatch → `Identification`** (not DocumentError or Other). **Internal cert calculation·notation error → `DocumentError`**.

### 11.1 Omission vs Mismatch Priority (important)

The category splits depending on the state of the value/field:

- **Omission·not-entered·not-received → `DocumentError`** (takes priority even if the attribute is a dimension·identification attribute). When an item/document that should rightfully be in the cert is **absent**, it is an internal omission.
  - e.g. "Branch portion thickness **omitted**" → DocumentError (not Identification). "Item No.45 cert **not received**/omitted" → DocumentError. "Code Case wording omitted" → DocumentError.
- **Value exists but mismatches/ambiguous against PO/MPR/drawing → `Identification`** (when the attribute is an identification attribute).
  - e.g. "Mixed notation XXS vs S/160" (ambiguous) → Identification. "Heat No. mismatch" (value present but different) → Identification. "Dimension measured value exceeds tolerance" (value present, deviating) → Identification.
- In short, **exists-but-wrong = Identification**, **entirely-absent = DocumentError**.

### 11.2 Material Spec Standard Mismatch (ASME SA vs ASTM A) — judged as an error

If the **standard family·prefix differs** between the MPS/PO order spec and the cert-stated spec, judge it as an **`Identification` error (FAIL) even if the material is effectively identical**. Because the material identification on the order and the cert is formally inconsistent, it is subject to correction (cert re-issue).

- e.g. MPS order **ASME SA-106** (general requirement SA-530) ↔ cert states **ASTM A-106** → **FAIL / Identification**. (ASME `SA-` prefix vs ASTM `A-` prefix)
- e.g. order SA-182 ↔ cert A182, order SA-234 ↔ cert A234, and the like.
- Since the chemical·mechanical reference values are effectively identical for ASME SA-xxx ≈ ASTM A-xxx, the **reference-value comparison may pass**, but record it as a separate **FAIL in the notation/identification review (notation·format sheet)**.
- When there is only a simple **edition difference** (same standard family, e.g. A106-2019 vs A106-2022), handle it as 주의 per the 기준 13/Code Edition rule (not an error). Apply this rule (FAIL) only when the standard family itself differs.
- **Scope limitation**: this judgment applies only to the order item's **product spec line** (Material Code / Material standard / fitting standard). If the product spec line matches the order, do not raise a finding for the ASTM notation on the **raw material (mother tube·base material) line** (SA-234/A234 explicitly permits A335-family base material — substantively equivalent). Also, if an ASTM series is stated in the MPS applicable document·general requirements (e.g. an 'ASTM A105M-2021' order), do not flag the prefix difference; apply this rule only when MPS explicitly requires ASME SA only.

> This judgment is performed on the compliance review path (Claude auxiliary) by comparing cert.header.spec ↔ MPS order spec. Since CSV lookup alone does not hold the order spec as structured input, a body/MPS cross-check is needed.

## 12. PAGE Attribution Rule (page_ref consistency)

- `page_ref` uses the **cert body page number** where the finding basis is located (per the cert cleanup PDF, `channels.body.pages`).
- Since the `_pNN` index in the rendered PNG file stem may diverge from the logical body page, prioritize the page number actually printed in the body.

## 13. Completeness Principle (Recall first)

- **Make a finding for every distinct violation·mismatch**: capture body numeric violations, MPS cross-check mismatches, and omitted items without exception.
- Do not discard subtle items as "noise":
  - An item that looks abnormal and needs confirmation (e.g. 경도 22 HRB) → **Question/the relevant category**
  - Ambiguous notation (XXS vs S/160) → **Question/Identification**
  - Arithmetic·notation misentry (Impact average) → **Minor/DocumentError**
  - Item No./quantity mismatch in the remark field → **Minor/Identification** (Minor if no spec impact)
- Suppress false positives: do not make speculative findings without body/MPS basis. Every finding must have an actually existing evidence snippet.
- **Exclude blanket confirmation memos**: a **general confirmation comment at the whole-cert level that does not pinpoint a specific issue**, such as "성적서 확인 요청" or "전반 확인 바람", is not made into a separate finding (it is noise that lowers precision). However, a **confirmation request about a specific value/item** (e.g. "경도 22 HRB로 낮음 — 확인 바람", "이 Heat의 N/Al 확인") is generated as a Question finding. Distinguishing criterion: if the confirmation target is pinpointed to a **specific measured value·item·page**, it is a finding; if it is a vague comment about the whole cert, exclude it.

## 14. Self-Printed Reference Self-Consistency (cross-check of the Standard row within the cert)

If the cert has a self-printed reference-value row (Standard value / Spec min·max / 標準值, etc.), **cross-check every result-value (成品值/Result) row 1:1 against that printed reference, row by row and column by column**.

- If a result value falls outside the self-stated reference — even if it passes against the external Code/CSV reference — either `기준 미달` (Mechanical/Chemistry FAIL) or `기준값 오기` (DocumentError) necessarily holds, so report it as a finding and require re-issue·explanation.
- When the cert-stated reference is stricter than the Code, **implicitly substituting the looser Code value for judgment is prohibited**.
- When judging elongation (EL), confirm the cert's specimen shape (round vs strip, width·G.L., L/T direction). If the CSV's EL min does not state which specimen it is based on, mark the possible specimen mismatch as 주의.
- The reverse case (where the cert's printed reference is **looser** than the Code, e.g. a CL.1 limit printed on a CL.3 material) is also reported as `DocumentError — 인쇄 기준 오기` (and note whether the measured value satisfies the stricter side as well).

## 15. Spec Notation Verification (non-existent specification numbers)

- Cross-check every specification number verbatim-transcribed by Phase 2 (product·base-material·test standard) against the held catalog (`grade_routing.csv`, `code_edition_map.csv`, ref_code folder names).
- **Do not substitute a specification number absent from the catalog·existing-standard list with the most similar valid spec**; report it as `DocumentError/Identification — 존재하지 않거나 확인 불가한 규격 표기(재발행 요청 대상)`. Record the presumed spec only in a note and base the judgment on the original notation.
- Simple notation-format differences (presence/absence of a hyphen in the formal ASME notation, 'SA193-B7', etc.) are not subject to this rule — do not flag notation variants of an existing spec.

## 16. Class Restriction and (Grade, Class, Heat) Coverage

- Every unique (Grade, Class, Heat) combination in the Phase 2 inventory must be mapped to materials[] and reviewed individually. **Even with the same Grade, a different Class is a separate item** (representative-page sampling is allowed only within the same combination group).
- Promote the MPS's **Class restriction wording** (`CL.1 only`, `CL.2 or 3 is not allowed`) and **handwritten·red-ink revision notes** to checklist items: even if the measured value is within range, report non-conformance if (a) the item's Class notation itself, or (b) the standard-value range printed on the cert differs from the MPS restriction.
- For grades that have a Class (SA-182 F22, SA-234 WP11/WP22, etc.), first extract the cert's Class notation (CL.1/2/3) and use **only the reference-value row for that Class**. If the CSV has only a Class-merged row, re-check the ref_code source Table directly before judging.

## 17. Finding Issuance Gate (precision defense line)

Every finding must pass the gates below to enter `findings[]`. An item caught by a gate is not discarded but recorded separately as `doc_checks`/`notes` (informational) or `code_edition_note` (review-limitation meta).

### 17.1 Requirement-Basis Gate
- Issue a Reject/ActionRequired finding only when you can cite **the current case MPS's document number + clause number** or a **code provision ('shall' level)**. Cannot cite → do not issue.
- Do not put an item whose action wording ends with "confirmation request/recommended/supplementary review" and has no violating value·provision into findings.
- **No transfer of clauses from other cases/other MPS families**: do not apply similar clauses from a different purchaser·different MPS (δ-ferrite photo, butt weld 100% MT/PT, PMI, etc.) to the current case merely because the grade is the same.
- **Distinguish received documents**: do not report a requirement to "state it in a separate document (item list/packing list) submitted together with the CMTR" as "CMTR body entry omission". If the existence of the separate document cannot be confirmed, omit the finding.
- When citing the MPS document-requirement table as basis, confirm by crop-reading whether the relevant row is **marked with (X)**. An empty-parenthesis `( )` item is not a requirement. Do not confuse the reporting-requirement column with the witness/hold column.

### 17.2 Applicability Gate
- For a conditional requirement, first judge the target item's applicability: product-shape limitation (`butt weld end bevel`-limited MT/PT → not applicable to SW/threaded/blind items), dimension·grade conditions (A105 heat treatment: over NPS4 **and** above Class 300), the `If Any` proviso, metallic NDE on a non-metallic material, etc. If not applicable, record it as N/A instead of a 'not stated' finding.
- Do not make a "not specified / cannot confirm" finding about an attribute implied by a spec conformance declaration (e.g. A672 = longitudinal seam weld, seamless = no weld).
- Preserve the inequality direction·applicable product form of the provision as in the original (do not apply an elbow provision to a reducer/tee).

### 17.3 Reference-Value Source Gate
- For the limit value used in a FAIL, use **only the row that exactly matches grade+Class+Type+specimen direction**.
- If two or more sources (ASTM source OCR vs ASME SEC II OCR vs data CSV vs the cert's printed reference field) **conflict, do not issue a FAIL**; output the conflict as a 주의/verification note. For a table where the same value repeats in adjacent rows (a row-shift signal), re-check the source page.
- If the cert's printed reference field and the applied reference diverge **on three or more attributes simultaneously**, suspect a skill-side reference-selection error (Class misidentification·OCR row shift) before a manufacturer misentry, and re-verify.
- Before using a CSV row, confirm that the provenance anchor's grade token matches the target grade. Prohibit using a mismatched row and report it as a data bug.
- If the relevant cell in the MPS table is `Note N`/`to be reported`/`---`/blank, it is not a numeric limit, so do not judge a violation. Do not reverse-use the cert's measured value (<0.001, etc.) as a limit value.

### 17.4 Absence-Claim Gate (mandatory check before a 'not stated' finding)
- Issue 'X not stated' only **after reading through all pages' Remark/footnotes/header Material line** (PMI·ferrite·Code Case·heat-treatment details are conventionally written in the Remark).
- Re-read the relevant cell by crop/zoom to confirm a pixel-level blank. If even one digit·symbol is visible, discard the blank finding.
- A `/`·`-` in the result field is a conventional N/A (not applicable) notation — issue 'not performed/not stated' only when that test is explicitly required by MPS.
- If the cert explicitly cites a separate Report No. (e.g. 'Ferrite Contents Report No. ...'), downgrade from a 'not-stated FAIL' to a '참조 리포트 확인 필요' (reference report check needed) 주의.
- A blank Product Analysis (P row) is made a finding only when there is a product-spec obligation or an MPS explicit requirement ('shall'). If there is only a 'purchaser may' provision, treat it as a form remnant (the A105/A182 family requires only heat analysis).

### 17.5 OCR Re-verification Gate
- If a violation hinges on **a single OCR digit**, re-read at ≥3x zoom; if a 'pass' reading is equally possible, do not issue the violation.
- For a one-character difference in an identifier mismatch (Heat No, etc.) (H/N, 0/O, 1/I, 5/6), do not issue if the two locations are identical after re-reading both. Report only when an actual difference is confirmed.
- For symbols·abbreviations, interpret the same document's legend/footnotes first (do not presume `•L=Longitudinal` to be 304L).
- Self-uncertain items of the 'value unclear, re-check needed' type are prohibited in findings — either confirm them by zoom re-reading or separate them into an extraction 주의 note.

### 17.6 Merging Principle
- Consolidate the same issue (same attribute·same root cause) into **one finding** even across different pages/Heats, and list the locations as `p.3~p.8 (Heat A/B/C)`. Do not create separate findings per page/per Heat (this rule takes precedence over the 'per-Heat split' of 기준 10.6 — if a single issue spans multiple Heats, list the heats together in one finding).
- Do not split the sub-aspects of a single issue (value/method/photo) and derived observations (root-cause identification, applicability cannot be confirmed) into separate findings; merge them into the main finding's note/action.
- Exception (기준 16/NDE applicability split): requirement **trigger identification** (e.g. a product having a butt welding end) and **requirement violation** (MT/PT not performed) are different judgments, so keep one finding each.

### 17.7 Informational Separation
- Do not put non-violation observations in findings: value-conforming + form/position memo, PASS·near-boundary ("margin 0") confirmation, conservative form printed value, equivalent spec-prefix mixing (base-material line), blanks for items with no required basis (empty Charpy cells, etc.), numbering-order presumption.
- **Heat-treatment record blank exception**: if the cert indicates heat treatment was performed (N/T temperature stated, etc.) but the **holding time is not shown**, and MPS/Code requires reporting the heat-treatment record for that material (including the CMTR heat-treatment entry requirement for heat-treatment-mandatory material), issue it not as informational but as a `HeatTreatment — 유지시간 미기재` (ActionRequired) finding. Separate it as informational only when there is no required basis at all.
- Record review-limitation meta (MPS not provided, ref_code not included, batch scope) only as `code_edition_note`.
- Use **Reject only when a numeric exceedance/shortfall of an explicit limit is confirmed**. Limit notation·form·document-management observations to at most '주의' (Question/Minor).
- For items with differing units, prioritize converted judgment: if the converted value is within range, one Minor only when MPS has an explicit unit provision, otherwise a doc_checks memo.

## 18. Reviewer Standard Vocabulary (검토자 표준 어휘 — issue_summary convention)

`issue_summary` is written in the actual reviewer's idiom — a notation convention for report consistency and downstream searchability.

| Situation | Standard vocabulary |
|---|---|
| Measured value exceeds max | "**기준값 초과**" (e.g. "P 0.050% — 인쇄 spec max 0.035% 기준값 초과") |
| Measured value below min | "**기준 미달**" (e.g. "TS 400MPa — 성적서 표기 최소 415MPa 기준 미달") |
| Item·document absent | "**누락**" / "**미기재**" |
| Value exists but differs | "**불일치**" |
| Required test not carried out | "**미수행**" |
| Notation error | "**오기**" |
| Same number reused | "**중복**" |
| Cannot judge | "**확인 불가**" |

- The summary sentence **includes the key attribute name (element symbol·test item) and the measured·reference numeric values** (a PASS sentence such as "Cr 8.49% — SA-234 WP91 기준 8.0~9.5% 내 적합" is not used in findings).
- When mentioning product characteristics·end shape·dimension notation, preserve the cert/drawing original notation as-is in the summary (do not lose the original keywords through arbitrary translation·paraphrase).
