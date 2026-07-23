---
name: cert-review
description: Inspection Certificate (MTC/성적서) review for piping materials. Compares scanned PDF certificates against MPS (구매시방서) and ASTM/ASME reference codes, emits a 6-sheet (+1 conditional mill-cert sheet) Korean Excel report, and evaluates against ground-truth. Use for MTC review, 성적서 검토, 자재 성적서, material test report verification.
---

# cert-review — Claude Orchestration Procedure

This document is the MTC (material test certificate) compliance review execution procedure that **the Claude Code CLI agent (orchestrator = main loop) follows directly**. It uses only the **folders and files of 3 categories (① reference code documents ② certificates under review ③ MPS)** as input,
and clearly separates the deterministic Python modules (`scripts/`) from the subagent delegation steps.

The orchestrator is responsible for deterministic CLI execution, gate decisions, parallel delegation scheduling, and aggregation of outputs, while transcription (Vision OCR) and
per-domain compliance judgment are delegated to the plugin subagents (`agents/`). **Because subagents cannot spawn nested
subagents, all parallelization and gating is performed directly by this skill.**

---

## Constraints (invariants)

| ID | Content |
|---|---|
| **C1** | No Python OCR libraries allowed — none of `pytesseract`, `easyocr`, `paddleocr`, `pymupdf`, `fitz`, `pdfplumber`, `openai` (vision), `anthropic` (vision), `google.cloud.vision`, etc. `pypdf` text extraction and `pypdfium2` rendering are permitted. OCR is performed only via Claude Vision (reading PNGs with the `Read` tool). |
| **C2** | Every finding's `evidence` item requires source metadata (`source_file` / `anchor` / `snippet`). `source_validator` quarantines items that are missing it. |
| **C3** | If the ref_code year differs from the year specified in the MPS, state it in the remarks. |
| **C7** | The execution environment is Windows PowerShell + Python. All commands run from the plugin (skill) directory, prefixed with `PYTHONIOENCODING=utf-8`, in the form `python -m scripts.cli ...`. |
| **C8** | A CSV reference-value row without all three source-metadata fields is rejected at the loading stage (`validate-refs` exit 0 required). |

---

## Input whitelist (only 3 categories)

> **The operational (review) stage reads only the folders and files of the 3 categories below. Anything else is blocked by the input guard.**

| Input category | Purpose |
|---|---|
| ① Reference code documents | OCR of code source text such as ASTM/ASME (read-only, source of reference values) |
| ② Certificates under review (MTC/Inspection Cert) | Certificate PDFs/images (PNG rendering → Vision OCR) |
| ③ MPS (purchase specification) | MPS documents (identification and conformance comparison) |

Each category's **actual source folder/file names vary by deployment environment**, and are specified in code via env (`CERT_REVIEW_REF_CODE_DIR` / `CERT_REVIEW_CERT_DIR` / `CERT_REVIEW_MPS_DIR`) (when unset, the test-harness layout is the default). The review logic recognizes inputs by these 3 categories, not by folder name.

`scripts/__init__.py` audits file opens via `sys.addaudithook` when the package loads. During operation,
opening `rawdata/` (all modules) or `standard inspection GT data/` (outside the evaluation module `eval_harness`) immediately raises
`PermissionError` — the guard **blocks rawdata and GT simultaneously** to force the review path not to depend on the ground truth (GT) or
original annotations. Direct `Read` access by Claude agents (both orchestrator and subagents) is also
prohibited. Evaluation does not need direct access because `eval_harness.py` reads each case's `comments.md` internally.

> **On the case (`case_id`), the `<case>` subfolder, and the `--case` argument**: these are an organization scheme **exclusive to the plugin test harness (the testbed 46-case regression)**. The test harness separates multiple certificates into numbered folders (`<case>/`) and runs the regression by selecting one with `--case <id>`. **In the deployment (production) environment, no case_id is taken at session start**; the 3-category inputs placed in the working folder are themselves the review unit. The `--case <id>`/`<case>` in the CLI examples and Phase descriptions below are written with respect to this test-harness execution (`.cache/<case>/` is the runtime cache partition key).

---

## Subagents (`agents/`)

The review work is delegated to **10 plugin subagents**. Each writes only a partial output, and the orchestrator merges them via deterministic CLI. **The detailed procedures (transcription rules, per-domain judgment rules) belong to each agent's document — they are not duplicated in this SKILL.md.**

| Agent | model | Role | Partial output |
|---|---|---|---|
| `page-aligner` | claude-opus-4-8 | Phase 1.5 per-page **rotation detection** from contact sheets (detection only — rotation is applied by `align-inputs`) | `<stem>_orientation.json` |
| `doc-classifier` | claude-opus-4-8 | Phase 1.6 per-page document-type classification (classification only — exclusion applied by deterministic CLI/merge) | `<stem>_doctype.json` |
| `ocr-extractor` | claude-opus-4-8 | Phase 2 Vision **tile-reading** transcription only (full / fragment modes) | `<stem>_extracted.json` or `parts/<stem>__pSSS-EEE.json` |
| `mps-extractor` | claude-opus-4-8 | **Single extraction** of the MPS scan just before Phase 4 → produces the shared digest consumed by the 5 review agents | `<case>_mps_digest.json` |
| `chemistry-reviewer` | claude-opus-4-8 | Phase 4 chemical composition review | `<case>_review_chemistry.json` |
| `mechanical-reviewer` | claude-opus-4-8 | Phase 4 mechanical properties review | `<case>_review_mechanical.json` |
| `heat-treatment-reviewer` | claude-opus-4-8 | Phase 4 heat treatment review | `<case>_review_heat_treatment.json` |
| `nde-reviewer` | claude-opus-4-8 | Phase 4 NDE/special-requirements review | `<case>_review_nde.json` |
| `format-reviewer` | claude-opus-4-8 | Phase 4 document/identification/print-criteria review | `<case>_review_format.json` |
| `mill-cert-reviewer` | claude-opus-4-8 | Phase 4 원자재 MILL CERT 검증·교차비교 (기준 21·22, mill cert 존재 케이스 한정 조건부) | `<case>_review_mill_cert.json` |

- **Model**: all agents use claude-opus-4-8 — prioritizing multi-item MTC identification and numeric-reading accuracy. OCR (transcription) and review (judgment) are separated by role, not by model (300 DPI required).
- **Tile reading**: `ocr-extractor` reads **2×2 overlapping tiles** per page (`.cache/<case>/tiles/`) instead of the full-page PNG. When the model reads a PNG, it downsamples to ~1568px on the long edge, so a full page (~3500px) smears small digits; but a 2×2 tile is ~1957px on the long edge, ~1.8× sharper even after downsampling, so it is read **without crop**.
- **Note**: if the `CLAUDE_CODE_SUBAGENT_MODEL` environment variable is set, it overrides the model in the frontmatter — to apply the intended model, **run with this environment variable unset**.
- **Chemistry-consistency responsibility boundary**: `ocr-extractor` performs only the first-pass physical-range screening (whether element values fit the grade's usual range); the Cev back-calculation and the confirming crop re-read are the responsibility of `chemistry-reviewer`.
- **MPS digest sharing**: the MPS PDF is a scan, so having each reviewer Vision-OCR it separately is redundant and slow. When `mps-extractor` performs a **single extraction** of the MPS and stores it in `<case>_mps_digest.json` as per-domain blocks (`chemistry`/`mechanical`/`heat_treatment`/`nde_microstructure`/`document_requirements`, each item with a source-text source + verbatim quote), the 5 review agents read only their own domain block and **do not open the original MPS PDF/PNG** (falling back only when the digest has no requirement for that grade). Numeric reference values still take priority from `<case>_limits.json` (CSV-derived), and only the MPS special-requirement text is quoted from the digest.

---

## Directory Layout

> The three top-level input folder names under `<WORK>/` below are the **test-harness default layout** — at deployment they are specified via env (`CERT_REVIEW_*_DIR`), and the review logic recognizes inputs by the 3 categories, not by folder name. Everything under `.cache/<case>/` is the **runtime cache partition** (case key).

```
<WORK>/  (= dataset root, anchor for input relative paths)
├── ref_code/                                       ← ASTM/ASME code OCR (read-only)
├── standard inspection Cert cleanup data/<case>/   ← certificate PDF (body OCR target)
├── standard inspection MPS cleanup data/<case>/    ← MPS PDF
├── standard inspection GT data/<case>/comments.md  ← evaluation only (eval_harness access only)
├── output/                                         ← report outputs and evaluation results
└── ... plugin/ReportReviewer/                      ← plugin root
    ├── agents/                                     ← plugin subagents (includes frontmatter model)
    │   ├── page-aligner.md                         ← Phase 1.5 rotation detection (claude-opus-4-8)
    │   ├── doc-classifier.md                       ← Phase 1.6 per-page document-type classification (claude-opus-4-8)
    │   ├── ocr-extractor.md                        ← Phase 2 Vision transcription (opus 4.8)
    │   ├── chemistry-reviewer.md                   ← Phase 4 chemistry (claude-opus-4-8)
    │   ├── mechanical-reviewer.md                  ← Phase 4 mechanical (claude-opus-4-8)
    │   ├── heat-treatment-reviewer.md              ← Phase 4 heat treatment (claude-opus-4-8)
    │   ├── nde-reviewer.md                         ← Phase 4 NDE (claude-opus-4-8)
    │   └── format-reviewer.md                      ← Phase 4 document/identification (claude-opus-4-8)
    └── skills/cert-review/                         ← this skill directory (CLI execution base)
        ├── SKILL.md  ·  manifest.json (produced by build-manifest)
        ├── .cache/<case>/                          ← per-case intermediate outputs
        │   ├── png/                                ← prep-inputs rendered PNG (upright after align-inputs)
        │   ├── orient/                             ← orient-sheets contact sheets + sheets_index.json (page-aligner input)
        │   ├── <stem>_orientation.json             ← page-aligner output (per-page clockwise rotation 0/90/180/270)
        │   ├── <stem>_alignment.json               ← align-inputs applied-rotation record (idempotency + crop/annotate space)
        │   ├── classify/                           ← classify-sheets UPRIGHT contact sheets + sheets_index.json (doc-classifier input)
        │   ├── <stem>_doctype.json                 ← doc-classifier output (per-page document-type labels; deterministic exclusion authority)
        │   ├── tiles/                              ← tile-inputs 2×2 overlapping tiles (4 tiles per page, <stem>_pNN_rRcC.png)
        │   ├── mps_png/                            ← prep-mps rendered MPS PNG
        │   ├── mps_tiles/                          ← prep-mps MPS 2×2 overlapping tiles (for mps-extractor reading)
        │   ├── <stem>_prep.json                    ← sidecar (PDF sha256+dpi+applied rotations, for the cache gate)
        │   ├── parts/<stem>__pSSS-EEE.json         ← fragment-mode segment extraction (merge-parts input)
        │   ├── crops/                              ← crop CLI high-DPI region PNG (re-read of ambiguous cells)
        │   ├── <stem>_extracted.json               ← Vision OCR output (channels: body)
        │   ├── <case>_mps_digest.json              ← mps-extractor output (per-domain MPS special requirements + source-text quotes, shared by the 5 review agents)
        │   ├── <case>_limits.json                  ← limits CLI output (relevant reference values + provenance)
        │   ├── <case>_attachments.json             ← attachments CLI output (기준 20 enclosed-report presence per heat)
        │   ├── <case>_mill_cert.json               ← mill-cert CLI output (기준 21/22 교차비교 팩)
        │   ├── <case>_review_<domain>.json         ← review agent partial output (chemistry|mechanical|heat_treatment|nde|format|mill_cert)
        │   └── <case>_review.json                  ← merge-reviews merged result (Phase 5/6 input)
        ├── .cache/cache_status.json                ← cache-status output (fresh/legacy/stale/missing)
        ├── data/*.csv                              ← 7 reference-value CSVs (see the "Domain-rule reference locations" table below)
        ├── references/                             ← extraction-schema.json · review-criteria.md
        └── scripts/                                ← deterministic Python modules (cli·prep_inputs·source_validator·compare_engine·compliance_report·eval_harness)
```

> **Path notation**: the plugin (skill) directory is the current directory where this document resides (the parent of `scripts/cli.py`).
> The subagents (`agents/*.md`) live under the **plugin root** above it. The CLI runs from the skill directory.
> The dataset root (`<WORK>`) is specified by the `CERT_REVIEW_WORKDIR` environment variable, or when unset it is auto-discovered by walking
> up from the CWD/plugin location to find a directory containing a `standard inspection Cert cleanup data` folder.

---

## PowerShell usage example

```powershell
$env:PYTHONIOENCODING = "utf-8"
$env:CERT_REVIEW_WORKDIR = "<WORK>"   # (optional) auto-detected if unset
Set-Location "<plugin (skill) directory: where this SKILL.md lives>"

python -m scripts.cli build-manifest                    # Phase 0: cert/MPS index
python -m scripts.cli cache-status --case 4 | --all     # cache gate (fresh|legacy|stale|missing)
python -m scripts.cli prep-inputs --case 4 [--dpi 300] [--force]   # Phase 1: PNG render + sidecar
python -m scripts.cli orient-sheets --case 4            # Phase 1.5: labelled contact sheets (page-aligner input)
python -m scripts.cli align-inputs --case 4             # Phase 1.5: apply detected rotations to page PNGs (idempotent)
python -m scripts.cli tile-inputs --case 4 | --all      # Phase 1: page PNG → 2×2 overlapping tiles (4 per page)
python -m scripts.cli classify-sheets --case 4          # Phase 1.6: upright contact sheets (doc-classifier input)
python -m scripts.cli check-doctype --case 4            # Phase 1.6: doctype gate (exit 0 required)
python -m scripts.cli prep-mps --case 4 [--dpi 300]     # Phase 1: MPS PDF → mps_png + mps_tiles (mps-extractor input)
python -m scripts.cli merge-parts --case 4              # merge fragment (>6p) segments
python -m scripts.cli check-extraction --case 4 | --all # Phase 2.5: completeness gate
python -m scripts.cli crop --case 4 --stem <stem> --page 2 --bbox 0.10,0.42,0.55,0.50 --dpi 300  # re-read ambiguous cell
python -m scripts.cli validate-refs                     # Phase 3: CSV provenance validation
python -m scripts.cli limits --case 4                   # Phase 4: relevant reference-value rows + provenance
python -m scripts.cli attachments --case 4             # Phase 4: 기준 20 enclosed-report attachment index (sidecar 부재 시에도 exit 0)
python -m scripts.cli mill-cert --case 4                # Phase 4: 기준 21/22 교차비교 팩 (런 0건도 exit 0)
python -m scripts.cli merge-reviews --case 4            # merge the review agents' partial outputs (최대 6부분 — mill_cert는 선택적)
python -m scripts.cli evaluate --case 4 | --all         # Phase 6: evaluation against comments.md
```

---

## Time budget (tiered by case complexity)

Do not sacrifice accuracy for time — opus's precise crop reading of numeric cells is performed as much as the case complexity demands. Time is an outcome, not a ceiling. The target wall-clock is applied in tiers by case complexity:

- **Simple** (1–3 pages, 1–2 items): target **≤30 min**.
- **Standard** (4–6 pages, several items): target **≤60 min**.
- **Complex** (>6 pages, or 7+ items, or multiple grades): **60–90 min allowed**. With simultaneous multi-case fan-out, it may grow further due to opus concurrent-call throttling.

Structural devices that keep time proportional to complexity: ① identification is finalized in a single ocr-extractor pass (no reviewer re-verification) ② reviewer crops focus on judgment-critical cells (no indiscriminate full-coverage crop) ③ parallelization of large certs (≤4p segments) (below) ④ **tiling (tile-inputs)** — when ocr-extractor reads 2×2 overlapping tiles, OCR becomes **~2.6× faster and crops drop to nearly 0** relative to the full page (small digits that smeared under downsampling are read without crop) ⑤ **MPS digest sharing (mps-extractor)** — extracting the MPS scan only once and sharing it as a per-domain digest removes the 5 review agents' redundant MPS OCR, shortening the review wall **~3×** (per-reviewer separate Vision-OCR ~95 min → digest consumption ~32 min, with no recall regression) ⑥ **pre-OCR page alignment (orient-sheets + page-aligner + align-inputs)** — rotated scan pages are straightened before tiling, so the tile semantics (r0=header) and digit legibility hold on rotated inputs too; detection costs ~1 sheet Read per 12 pages plus one delegation per case. ⑦ **Phase 1.6 document-type classification (classify-sheets + doc-classifier + check-doctype)** — one added delegation per case adds roughly **+2–4 min (simple) / +3–5 min (standard) / +10–15 min (complex 73p)**, but this is largely **offset by the minimal-entry OCR of excluded pages** (excluded pages skip table transcription), so the net is ≈ **0±5 min** for mixed complex files; the tier targets (≤30 / ≤60 / 60–90 min) are **unchanged**. In multi-case runs, the intra-case 5-agent parallelism overlaps with inter-case parallelism, so keep the total concurrent-agent cap of 6–10. ⑧ **기준 20 attachment judgement** — doc-classifier's related-identifier reading of EXCLUDED runs adds **+1–3 min only on cases that actually have enclosed documents**, and the reviewer-side attachment ladder is absorbed within the existing Phase 4 delegation (net ≈ **+0–3 min**); the deterministic `attachments` CLI is sub-second. Tier targets are **unchanged**. ⑨ **기준 21/22 MILL CERT 검증** — mill cert 전사 예외는 동봉 mill cert 보유 케이스에서만 페이지당 기존 OCR 동일 비용(+통상 1~2p), `mill-cert-reviewer` 1위임 추가(조건부 — `applicable: true` 케이스 한정, 결정적 `mill-cert` CLI는 sub-second) — 티어 목표 불변.

---

## Parallel-execution rules (2-dimensional orchestration: case × agent)

> **[MANDATORY] This loop (the orchestrator) directly schedules the agent delegations for all cases.**
> The case-wrapper subagent is abolished — because subagents cannot spawn nested subagents, both the case fan-out and
> the agent fan-out are performed directly by this loop.

Parallelization is only a speed rule and does not replace any quality obligation. The token budget, procedure, and evidence obligations are unchanged.

| Rule | Content |
|---|---|
| **Phase 0·3 pre-execution** | `build-manifest` and `validate-refs` each run **once** invariantly before fan-out. If `validate-refs` is not exit 0, do not start the fan-out |
| **Total concurrent agents** | Combined cap of **6–10** (sum of classification, OCR, MPS extraction, and review agents) |
| **Phase 1.6 classification** | `doc-classifier` runs **once per case** (after align-inputs, gated by `check-doctype` exit 0 before OCR). It counts toward the 6–10 concurrent-agent cap like any other delegation |
| **Case pipeline overlap** | Per case, OCR (Phase 1·2), MPS extraction (`mps-extractor`, parallel to cert OCR), the completeness gate (2.5), and review (Phase 4) proceed, and **the 5 review agents are deployed starting from cases that have completed OCR, passed 2.5, and produced `<id>_mps_digest.json`**. Overlap of the OCR stage and the review stage across cases is allowed (while one case is in OCR, another may be in review) |
| **Phase 5·6 batch** | The report (Phase 5) and evaluation (Phase 6) are performed in a batch **after all cases' merge-reviews complete**, by this loop or `evaluate --all` |

A single-case run follows the Phase 0→6 sequential flow below as-is (the same procedure without fan-out).

---

## Phase 0: build-manifest

**Purpose**: scan the two cert/MPS cleanup directories to generate the case index (`manifest.json`) (`build-manifest`). **Run only once before fan-out** (a shared single file — to prevent concurrent-write conflicts).

- Scan the certificate and MPS input directories (when env is unset, the test-harness defaults `standard inspection Cert cleanup data/` and `standard inspection MPS cleanup data/`).
- `rawdata/` and `standard inspection GT data/` are **not scanned** (input guard).
- Output: the plugin directory `manifest.json` (schema_version: "2.0").
- Success criterion: exit 0, prints `case_count`.

---

## Phase 1·2·2.5: input preparation + OCR transcription (orchestrator sequence)

Perform the sequence below per case. **The orchestrator runs the deterministic CLI directly and delegates only the Vision transcription to `ocr-extractor`.**

### 1) Cache gate (orchestrator-run)

> **[MANDATORY] Before input preparation, run `cache-status --case <id>` first.**
>
> | Status | Meaning | Handling |
> |---|---|---|
> | `fresh` | PDF sha256+dpi match, extraction complete | **Skip Phase 1·1.5·2** and use the existing `<stem>_extracted.json` as-is |
> | `legacy` | Extraction is complete but the sidecar is an old version (auto-backfilled) | **Treated the same** as `fresh` — skip Phase 1·1.5·2 |
> | `stale` | PDF sha256 mismatch (the source changed), dpi mismatch, or **alignment pending** (the PNGs were re-rendered after the last alignment — e.g. `--force`/`--dpi` rerun; sidecar `rotations: null`) | **Perform** Phase 1·1.5·2 (re-render — which resets the rotation records — + re-align + re-delegate). Alignment-pending only: prep-inputs will report all certs cached — proceed from Phase 1.5 (orient-sheets) onward |
> | `missing` | No extraction output | **Perform** Phase 1·1.5·2 |
>
> - If the PDF changes, it no longer matches the sidecar sha256, automatically becomes `stale`, and re-extraction is forced — a stale extraction is never implicitly reused.
> - **The Phase 2.5 check-extraction gate always runs regardless of a cache hit (fresh/legacy).** A cache skip does not exempt the completeness check.
> - On a re-run with unchanged inputs (repeated evaluate, or re-running only Phase 4 after a criteria revision), all cases become `fresh`/`legacy` and OCR Reads drop to zero.

### 2) prep-inputs (orchestrator runs directly, deterministic) — `prep-inputs --case <id>`

- Render the cert PDF with `pypdfium2` to produce `.cache/<case>/png/<stem>_p01.png`, `_p02.png`, … (DPI 300, change via `--dpi`).
- **Note**: an existing DPI 200 cache is treated as `stale` due to dpi mismatch and is re-rendered + re-extracted on the next run.
- Also writes the extraction skeleton JSON (`<stem>_extracted.json`) and the sidecar (`<stem>_prep.json`, sha256+dpi).
- A re-render (stale/--force) also deletes the stem's `<stem>_orientation.json`/`<stem>_alignment.json` so Phase 1.5 re-detects rotation on the fresh (unaligned) render.
- **After running, check the case's PNG count** to determine the next-stage mode (full / fragment).

### 2.2) orient-sheets (orchestrator runs directly, deterministic) — `orient-sheets --case <id>`

- Run immediately after prep-inputs. Compose the rendered cert pages into labelled **contact sheets** (3×4 thumbnails per sheet, upright `pNN` label bars) under `.cache/<case>/orient/` plus `orient/sheets_index.json`.
- Why: scanned certs arrive with per-page rotation mixed inside one PDF (metadata `/Rotate`=0, scan content sideways — 0°/90° mixed is common). Sheets compress orientation detection to ~1 Read per 12 pages instead of 1 per page.

### 2.3) page-aligner delegation (Phase 1.5, MANDATORY before tiling/OCR)

- **Delegate `page-aligner`** to read the contact sheets and write per-stem `.cache/<case>/<stem>_orientation.json` (clockwise 0/90/180/270 per page; uncertain pages fall back to the full-page PNG, then to 0 + `uncertain_pages`).
- **Delegation context spec** (must be included): case id · the skill directory **absolute path** · output obligation (`<stem>_orientation.json`, every page recorded) · compliance instructions (**C1, the 3-category input whitelist, judge page content not the upright labels**).
- The detection detail procedure (reading rules, angle semantics, self-check) is held by `agents/page-aligner.md` — **do not duplicate it in SKILL.md**.

### 2.4) align-inputs (orchestrator runs directly, deterministic) — `align-inputs --case <id>`

- Apply the detected rotations to the page PNGs in place (Pillow lossless transpose, per-page two-phase commit — crash-safe, never double-rotates). The sidecar's `rotations` map flips from `null` (render pending alignment) to the applied map, which is what the cache gate checks.
- **[GATE] exit 0 required.** Exit 1 means an uncovered stem (a rendered cert with no `<stem>_orientation.json` — re-delegate `page-aligner` for it) or failed pages (fix the reported PNGs) — **do not proceed to tile-inputs/OCR until exit 0.**
- `crop` and `annotate` re-render from the source PDF, so they consult the same applied map to reproduce the aligned image space — fractional bboxes are **always aligned-space**.
- If page-aligner reported every page as 0 (already upright), this is a no-op — still run it (cheap) so the alignment record exists and the sidecar marker clears.

### 2.5) tile-inputs (orchestrator runs directly, deterministic) — `tile-inputs --case <id>`

- Run immediately after align-inputs (tiles must be cut from **upright** pages — the `r0`=header semantics assume it). Split each page PNG in `.cache/<case>/png/` into **2×2 overlapping tiles** per page (`.cache/<case>/tiles/<stem>_pNN_rRcC.png`, `r0`=top·`r1`=bottom, `c0`=left·`c1`=right, 6% overlap).
- Why: when the model reads a PNG it downsamples to ~1568px on the long edge, so a full page (~3500px) smears small digits. A 2×2 tile is ~1957px on the long edge, ~1.8× sharper even after downsampling, so ocr-extractor reads it **without crop**.
- The next-stage mode (full / fragment) branch is **still based on PNG count** and is independent of tiling.

### 2.6) classify-sheets (orchestrator runs directly, deterministic) — `classify-sheets --case <id>`

- Run **after align-inputs** (so the sheets carry **upright** pixels). Compose the aligned page PNGs (`.cache/<case>/png/`) into UPRIGHT contact sheets under `.cache/<case>/classify/` plus `classify/sheets_index.json` (the doc-classifier input).
- **The Phase 1.5 `orient/` sheets must NOT be reused here** — they are composed from **pre-alignment** pixels, so rotated letterheads/title-blocks are unreadable and document-type discrimination fails. classify-sheets re-composes fresh upright sheets specifically for document-type reading.

### 2.7) doc-classifier delegation (Phase 1.6, MANDATORY before OCR)

- **Delegate `doc-classifier`** to read the upright classify sheets (`.cache/<case>/classify/`) — and, at MTC-style run boundaries, the header tiles (`.cache/<case>/tiles/<stem>_pNN_r0c0.png`) — and write per-stem `.cache/<case>/<stem>_doctype.json` labelling **every page**.
- **Delegation context spec** (must be included): case id · the skill directory **absolute path** · output obligation (**every page labelled; values ∈ the 13 taxonomy codes**) · compliance instructions (**C1 read-only PNG opening, the 2-label INCLUDED whitelist (`MTC_FINISHED`/`UNKNOWN`) + conservative `UNKNOWN`, the document-run continuity rule — a finished-product MTC's internal PMI/NDE/dimension sections are NOT separate documents — and judge page content, not the `pNN` label bar**) · **related-identifier reading for EXCLUDED runs** (verbatim Heat/PO columns from the enclosed document's own table, into `documents[].related_heat_nos`/`related_po_items` — details in agents/doc-classifier.md; this is the sole 기준 20 attachment-matching input).
- The classification detail procedure (taxonomy cues, sheet-reading rules, finished-vs-raw discrimination, self-check) is held by `agents/doc-classifier.md` — **do not duplicate it in SKILL.md**.

### 2.8) check-doctype (orchestrator runs directly, deterministic gate) — `check-doctype --case <id>`

- **[GATE] exit 0 required.** This gate verifies every rendered stem has a valid `<stem>_doctype.json`. Exit 1 causes and handling:
  - a rendered stem with **no `<stem>_doctype.json`** → re-delegate `doc-classifier` for it;
  - **page coverage gaps/extras or invalid labels** (a label outside the 13 codes) → fix / re-delegate;
  - **an entire stem classified non-finished** (no `MTC_FINISHED`/`UNKNOWN` page) → abnormal; request human confirmation and stop.
- A **WARNING** (exclusion ratio > 60% on a stem of ≥4 pages) stays **exit 0**, but the orchestrator should re-check 2–3 boundary pages full-page before proceeding.
- **Do not delegate `ocr-extractor` until exit 0** (same gate pattern as align-inputs).

### 2.9) prep-mps (orchestrator runs directly, deterministic) — `prep-mps --case <id>`

- Run immediately after tile-inputs. Render the MPS PDF in `standard inspection MPS cleanup data/<case>/` with `pypdfium2` into PNGs in `.cache/<case>/mps_png/`, then generate 2×2 overlapping tiles per page into `.cache/<case>/mps_tiles/` (the same principle as cert tiling — sharpening scan characters that smear under downsampling).
- This output is the input for the next stage's `mps-extractor` delegation. Because it is independent of the cert OCR path (prep-inputs/tile-inputs), it can proceed in parallel with the cert OCR delegation.

### 3) ocr-extractor / mps-extractor parallel delegation (mode branches by PNG count, tile reading)

> Cert transcription (`ocr-extractor`) and MPS extraction (`mps-extractor`) are **independent, so delegate them in parallel in a single message**. `mps-extractor` reads `mps_tiles/` once and produces `<case>_mps_digest.json` as per-domain blocks (`chemistry`/`mechanical`/`heat_treatment`/`nde_microstructure`/`document_requirements`, each item with a source-text source + verbatim quote). The 5 Phase 4 review agents share-consume this digest (reviewers do not re-OCR the original MPS).

- **PNG ≤ 6 → full mode**: **a single `ocr-extractor` delegation**. The agent transcribes all pages of the case and completes `<stem>_extracted.json` directly.
- **PNG > 6 → fragment mode**: split the pages into **segments (≤4p)** and **delegate `ocr-extractor` in parallel** (multiple delegations in one message). Each delegation saves a `parts/<stem>__pSSS-EEE.json` fragment. **After all segments complete**, the orchestrator merges with `merge-parts --case <id>` (preserving the skeleton top-level, with deterministic priority and issue reporting on page duplication).

**Delegation context spec** (must be included in each `ocr-extractor` delegation):
- case id
- the skill directory **absolute path**
- the mode (full / fragment) and, for fragment, the assigned page segment
- compliance instructions: **C1–C8, the 3-category input whitelist, tile reading (4 tiles per page, crop omitted as a rule), verbatim transcription, all-pages obligation**
- **Phase 1.6 document-type consumption**: read `.cache/<case>/<stem>_doctype.json` (absent → treat every page as `MTC_FINISHED` = current behaviour); for EXCLUDED-type pages emit only the **minimal entry** (`header: {}`, `doc_type`, the 제외 remark) instead of transcribing tables; **stamp `doc_type`** on `MTC_FINISHED`/`UNKNOWN` entries; build the `(Grade, Class, Heat)` inventory from **included pages only**; raise **"분류 재확인 요청"** on a suspected misclassification (details in `agents/ocr-extractor.md`)

> The transcription detail procedure (tile-batch Read, per-page entry, spec verbatim, (Grade,Class,Heat) inventory, first-pass chemistry screening, etc.) is held by `agents/ocr-extractor.md` — **do not duplicate it in SKILL.md**.

**mps-extractor delegation context spec** (must be included in the `mps-extractor` delegation):
- case id
- the skill directory **absolute path**
- output obligation: `.cache/<case>/<case>_mps_digest.json` (per-domain blocks + per-item source-text source + verbatim quote)
- compliance instructions: **C1–C8, the 3-category input whitelist, MPS tile reading, verbatim quoting, all-pages obligation**

> The MPS extraction detail procedure (per-domain block classification, requirement-mark reading, verbatim quoting rules, etc.) is held by `agents/mps-extractor.md` — **do not duplicate it in SKILL.md**.

### 4) check-extraction gate (orchestrator-run, always) — `check-extraction --case <id>`

- For each cert PDF, `page_extraction` must cover all rendered pages and `channels.body.pages` must match for **exit 0**.
- On empty extraction or missing pages, exit 1 — **re-delegate only the missing page segment to `ocr-extractor`** (fragment mode) and gate again.
- **Do not start Phase 4 review until this gate passes.**

---

## Phase 3: validate-refs

**Purpose**: verify that every row in `data/*.csv` complies with C2/C8 (all three source-metadata fields present) (`validate-refs`). **Run only once before fan-out** (a precondition gate common to all cases).

- `source_validator` checks each CSV row for the existence of `source_file` and the inclusion of `snippet`.
- **If not exit 0, do not proceed to subsequent stages.**
- The 7 CSVs validated: `chemistry_limits` · `mechanical_limits` · `heat_treatment` · `nde_rules` · `grade_routing` · `mps_overrides` · `code_edition_map`.

---

## Phase 4: compliance review (orchestrator sequence)

**Purpose**: compare the Phase 2 extracted values against the ref_code/CSV reference values and MPS limits to generate findings. Per-domain judgment is delegated in parallel to the 5 review agents, and the orchestrator merges them deterministically.

### 1) limits lookup + attachment index (orchestrator-run, once) — `limits --case <id>` then `attachments --case <id>`

- Based on the case extraction inventory (grade·class), select only the relevant CSV rows and produce `.cache/<case>/<case>_limits.json` as JSON including the 3 provenance fields (`source_file`/`anchor`/`snippet`). **The values are still CSV-derived, and snippet/anchor are preserved so C2/C8 are satisfied.**
- If a grade routing failure is stated in the output JSON's `unrouted`, then **only for that grade** finalize the manual routing information from the CSV source and `review-criteria.md`, and **attach that resolution information to the delegation context**. (A successfully routed grade needs no extra work.)
- Then run `attachments --case <id>` to produce `.cache/<case>/<case>_attachments.json` — the 기준 20 attachment index (enclosed PMI/NDE/dimension report presence per finished-product heat, from the doctype sidecars' related identifiers). **Always run it — a case with no doctype sidecar still exits 0 (`sidecar_present: false`)**, and reviewers then simply skip attachment judgement.
- Then run `mill-cert --case <id>` to produce `.cache/<case>/<case>_mill_cert.json` — the 기준 21/22 cross-comparison pack (MTC_RAW_MATERIAL run subgrouping, linkage, forging predicate, tensile/chemistry identity states). **Always run it — a case with no mill cert run still exits 0 (`applicable: false`)**; `applicable` is the mill-cert-reviewer delegation condition below.

### 2) Parallel delegation of the 5 review agents (concurrently in one message)

After `limits` completes (and after that case's `mps-extractor` has produced `<case>_mps_digest.json`), **delegate the 5 agents below in parallel in a single message**.

**+ 조건부 6번째: `applicable: true`인 케이스는 `mill-cert-reviewer`를 5 리뷰어와 같은 단일 메시지에 병렬 위임 (케이스당 최대 6 동시 — 총 동시 캡 6–10 내, C-M4).** 위임 컨텍스트: case id · SKILL_DIR 절대경로 · 출력 의무(`<case>_review_mill_cert.json`) · 준수사항(C1–C8, 3범주 화이트리스트, 기준 20 첨부판정 발행 금지, 재-OCR 금지). `applicable: false`인 케이스는 위임을 생략한다.

The context to include in each delegation:
- case id
- the skill directory **absolute path**
- its own domain's partial-output obligation: `.cache/<case>/<case>_review_<domain>.json`
- (if applicable) unrouted-grade resolution information
- **read MPS special requirements from its own domain block in `<case>_mps_digest.json` and do not open the original MPS PDF/PNG** (fall back only when the digest has no requirement for that grade).
- **Excluded-page rule (기준 19)**: pages whose `doc_type` is an EXCLUDED type must not have their data compared, their grades/heats registered into `materials[]`, or be cited as evidence — the exclusion memo is emitted deterministically by `merge-reviews` (`excluded_documents`), so reviewers raise no findings about them.
- **기준 20 attachment judgement**: nde/format reviewers read `<case>_attachments.json` and apply the 기준 20 ladder for their own doc types (ownership table in review-criteria.md 기준 20.1); body-printed values always take precedence (상태 A), and other reviewers ignore the file. Absent or `sidecar_present: false` → skip attachment judgement entirely.

The review agents do not re-verify the identification fields finalized by ocr-extractor (the header's grade/heat_no/cert_no/size/qty) (see the time-budget section).

**Routing table by 기준 number** (only which agent owns which 기준 — the judgment procedure belongs to each agent's document):

| Agent | Assigned 기준 |
|---|---|
| `chemistry-reviewer` | 기준 3.1 (A106 C/Mn footnote), MPS override, Cev back-calculation |
| `mechanical-reviewer` | TS/YS/EL/RA/hardness ranges |
| `heat-treatment-reviewer` | per-step temperature·time, the ±10°C rule |
| `nde-reviewer` | 기준 NDE rules (MILL/STOCK notch), separate NDE-applicability reporting, δ-ferrite·Code Case·PMI |
| `format-reviewer` | 기준 11.2 (identification spec family), 기준 14 (self-consistency of the cert's own print criteria), 기준 15 (spec-notation verification), 기준 16 (Class restriction·inventory coverage) |
| `mill-cert-reviewer` | 기준 21 (MILL CERT 검증·연결성), 기준 22 (22.1 화학 주의 / 22.2 단조 인장 전사 FAIL) |

> The per-domain judgment details (the Cev back-calculation formula, the ±10°C branch, the 기준 11.2/14/15/16 application procedure, the finding gate (기준 17) and standard vocabulary (기준 18)) belong to each agent's document and `references/review-criteria.md` — **do not duplicate in SKILL.md**.

**Domain-boundary table (preventing duplicate issuance)**:

| Item | Owning domain |
|---|---|
| N / Al numeric judgment | chemistry |
| δ-ferrite · Code Case · PMI | nde |
| print-criteria notation-error label (document defect) | format |
| judgment of the measured value itself (against the print criteria) | chemistry / mechanical (the numeric-owning domain) |
| dimensions / quantity / Heat No | format |
| 동봉 보고서 첨부판정 — PMI/NDE/Microstructure 유형 (기준 20) | nde |
| 동봉 보고서 첨부판정 — 치수/이화학/열처리차트/원자재 유형 (기준 20) | format |
| MILL CERT 자체 유효성·연결성·MTC 교차비교 (기준 21·22) | mill_cert |
| 원자재 성적서 첨부 여부 판정 (기준 20) | format (불변) |

### 3) merge-reviews (orchestrator-run, after all complete) — `merge-reviews --case <id>`

If a review agent reports a grade correction (differing from the inventory), the orchestrator's rule is to re-run that case's `limits --case` to re-supply the corrected grade's reference-value rows (including MPS override) and re-delegate the affected domains (an agent's manual augmentation from the CSV source is a secondary path).

- **Deterministically merge** 최대 6개 부분 파일 (`<case>_review_chemistry.json` … `_format.json` + 선택적 `<case>_review_mill_cert.json` — 부재 시 경고 없음) into a single `<case>_review.json`: global finding renumbering, worst-value aggregation of the verdict. **The downstream Phase 5/6 contract is unchanged.**

### Source-citation rule (C2)

> **If there is no evidence, do not write the finding.** Place at least one item in each finding's `evidence` array, and the `snippet` must exist literally in the channel source text (body/MPS) (`source_validator` quarantines a missing snippet). **Cite numeric criteria only from the CSV — do not use code-hardcoded numbers.**

---

## Phase 5: compliance_report (6-sheet (+1 conditional mill-cert sheet) Korean Excel)

**Purpose**: output the findings in `review.json` as a 6시트(+조건부 1시트: 원자재 MILL CERT 검토) Korean Excel report.

- `compliance_report.build_compliance_report` reads `review.json` and generates the report.
- Output: `output/reports/<case_id>/<case_id>_MTC_Review.xlsx`
- **6-sheet (+1 conditional mill-cert sheet) structure**:

  | # | Sheet name | Content |
  |---|---|---|
  | 1 | 종합 요약 | per-case PASS/FAIL, finding aggregation, review timestamp |
  | 2 | 화학성분 | per-element Heat/Product values vs reference, verdict |
  | 3 | 기계적 성질 | TS/YS/EL/RA/hardness vs reference, verdict |
  | 4 | 열처리 | per-step temperature·time vs reference, verdict |
  | 5 | NDE / 특별요구 | whether UT/MT/PT/PMI were performed, notch spec, δ-ferrite |
  | 6.5 | 원자재 MILL CERT 검토 | (조건부) 기준 21·22 연결성·자체검증·교차비교 행 — `mill_cert` 행이 있을 때만 생성 |
  | 6 | Finding 목록 | finding_id, category, severity, issue_summary, evidence summary |

- **Verdict / severity vocabulary (canonical)**: every cell verdict (overall + per-row, all domains) must be exactly one of **`PASS | 주의 | FAIL | N/A`**; finding severity must be one of **`Reject | ActionRequired | Question | Minor | Info`**. `compliance_report` deterministically **canonicalises** any non-standard label (e.g. `합격`→PASS, `REVIEW`/`ActionRequired`→주의, `INFO`/`정보성`/`확인 불가`→N/A) and **always applies a colour** (PASS=green, FAIL=red, 주의=yellow, N/A=grey). Agents should still emit the canonical tokens directly — do not invent variants.
- **Output language**: the 6-sheet (+1 conditional mill-cert sheet) report and all finding text (`issue_summary`/`content`/`notes`/`doc_checks`) are authored in Korean (reviewer vocabulary), unchanged from current behavior. The sheet names above (종합 요약, 화학성분, 기계적 성질, 열처리, NDE / 특별요구, (조건부) 원자재 MILL CERT 검토, Finding 목록) are emitted verbatim in Korean.
- Do not use the section sign in report text. Cite criteria clauses in the `기준 3.1` format.
- File encoding: `openpyxl` default (UTF-8). Uses Korean font fallback.

---

## Phase 6: evaluate (evaluation against comments.md)

**Purpose**: compare the compliance `review.json` predictions against each case's actual reviewer findings (`comments.md`) to decide
PASS/FAIL (`evaluate --case <id>` / `--all`).

- `scripts/eval_harness.py` is the **only module** that reads `standard inspection GT data/<case>/comments.md`. No path other than this command opens the GT directory directly (input guard).
- The GT is `comments.md`, the reviewer's actual findings **clustered by page × topic**, and it is matched against the predicted findings to compute recall/precision/case_pass.
- Output: `output/eval/<case_id>_eval.json` or `output/eval/all_eval.json`, plus a summary markdown report.

---

## Overall execution flow summary

```
[Multi] Phase 0·3 once before fan-out → this loop schedules the case × agent 2 dimensions
        (concurrency 6–10, deploy review starting from cases that completed OCR and passed 2.5)   [Single] sequential below (same without fan-out)

Phase 0   build-manifest    → manifest.json                                    ※ once before fan-out
Phase 3   validate-refs     → exit 0 required                                  ※ once before fan-out
──── below is per-case (orchestrator sequence) ────
[GATE]    cache-status      → fresh/legacy = skip Phase 1·1.5·2 / stale/missing = perform
Phase 1   prep-inputs       → png/*.png + <stem>_prep.json (run directly) → mode decided by PNG count
Phase 1.5 orient-sheets     → orient/*__sheetNN.png + sheets_index.json (run directly)
          [delegate page-aligner/opus] read sheets → <stem>_orientation.json (per-page 0/90/180/270)
          align-inputs      → rotate png/*.png upright + <stem>_alignment.json (run directly, idempotent)
Phase 1   tile-inputs       → tiles/*_pNN_rRcC.png (2×2 overlapping tiles per page, run directly)
Phase 1.6 classify-sheets   → classify/*__sheetNN.png + sheets_index.json (upright sheets, run directly)
          [delegate doc-classifier/opus] read upright sheets → <stem>_doctype.json (per-page document-type label)
          check-doctype     → exit 0 required (gate; re-delegate on gap/invalid label/all-excluded stem)
          prep-mps          → mps_png/*.png + mps_tiles/*.png (MPS render+tile, run directly)
Phase 2   [delegate ocr-extractor/opus]  ≤6p full once → <stem>_extracted.json   ┐ parallel
                                       >6p fragment parallel(≤4p) → parts/*.json → merge-parts │
          [delegate mps-extractor/opus]  read mps_tiles once → <id>_mps_digest.json           ┘
                            (tile reading·C1·verbatim·all-pages obligation, details in agents/ocr-extractor.md·mps-extractor.md)
Phase 2.5 check-extraction  → exit 0 required (always runs; on failure re-delegate only the missing segment)
──── starting from cases that completed OCR, passed 2.5, and produced mps_digest ────
Phase 4   limits → <id>_limits.json  → attachments → <id>_attachments.json (기준 20, sidecar 부재도 exit 0)
            → mill-cert → <id>_mill_cert.json (기준 21/22, 런 0건도 exit 0)
            → [delegate 5 reviewers (+ conditional mill-cert-reviewer)/claude-opus-4-8 in one message, parallel]
            chemistry·mechanical·heat_treatment·nde·format (+mill_cert if applicable) → <id>_review_<domain>.json
            (MPS special requirements consumed from <id>_mps_digest.json's own domain block — original MPS not opened;
             nde/format apply the 기준 20 ladder for their own doc types from <id>_attachments.json)
          merge-reviews → <id>_review.json (renumber·worst-value verdict, downstream contract unchanged)
──── batched after all cases' merge-reviews ────
Phase 5   compliance_report → output/reports/<id>/<id>_MTC_Review.xlsx (6 sheets + conditional mill-cert sheet)
Phase 6   evaluate --case <id> | --all → output/eval/*  (recall/precision/case_pass)
```

> **Model note**: all agents use claude-opus-4-8 (same for OCR and review), applied via each agent's frontmatter model.
> If `CLAUDE_CODE_SUBAGENT_MODEL` is set it overrides this, so **run with it unset**.

---

## Domain-rule reference locations

Numeric judgment criteria must be cited from the locations below. The values written in this document are copies for readability;
**runtime judgment uses only the CSV** (C2/C8).

| Judgment item | CSV file | Remarks |
|---|---|---|
| Chemical composition range | `data/chemistry_limits.csv` | Heat/Product distinction, MPS override separate |
| MPS-priority items | `data/mps_overrides.csv` | listed only when MPS > Code |
| Mechanical properties | `data/mechanical_limits.csv` | TS/YS/EL/RA/hardness |
| Heat-treatment conditions | `data/heat_treatment.csv` | per-step temperature·time, the ±10°C rule |
| NDE rules | `data/nde_rules.csv` | MILL/STOCK notch distinction |
| Grade → Spec | `data/grade_routing.csv` | grade string → ASME spec mapping |
| ref_code year | `data/code_edition_map.csv` | remark on year mismatch (C3) |

For Claude's judgment, refer to each review agent's document (`agents/*-reviewer.md`) and
`references/review-criteria.md` for the detailed domain rules (complex chemistry rules, NDE special requirements, finding category definitions,
severity decision rules, etc.).
