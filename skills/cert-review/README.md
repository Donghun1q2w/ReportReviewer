# cert-review

Automated review of material inspection certificates (자재 성적서/MTC) — Claude Code plugin. Single compliance path.

## Quick Start (Windows PowerShell)

```powershell
# Run from the plugin (skill) directory — where this README lives
$env:PYTHONIOENCODING="utf-8"
# (Optional) Specify dataset root. If unset, auto-detected from parent folder.
$env:CERT_REVIEW_WORKDIR="<WORK>"
python -m scripts.cli build-manifest
# After running Phase 1–4, merge partial reviewer outputs
python -m scripts.cli merge-reviews --all
python -m scripts.cli evaluate --all
```

## Performance Subcommands (for iterative loops)

```powershell
# Cache gate: extraction freshness check (fresh | legacy | stale | missing)
#   fresh/legacy = skip Phase 1·2 (reuse existing extraction), stale/missing = re-extract
python -m scripts.cli cache-status --all

# prep-inputs: write PDF sha256+dpi sidecar; skips render if unchanged (--force to override, --dpi to set resolution)
python -m scripts.cli prep-inputs --case 4 --dpi 300

# crop: re-render ambiguous cell regions at high DPI (bbox: fractional coordinates 0.0–1.0, origin top-left)
python -m scripts.cli crop --case 4 --stem <stem> --page 2 --bbox 0.10,0.42,0.55,0.50 --dpi 300

# limits: extract only relevant reference limit rows per case, with provenance (Phase 4 context diet)
python -m scripts.cli limits --case 4
```

> For multiple cases (`--all`), Phase 0 (build-manifest) and Phase 3 (validate-refs) are run once upfront, then
> the orchestrator (SKILL.md) uses **case × domain-agent 2-D scheduling** (concurrency cap 6–10) to reduce
> wall-clock time. There is no per-case wrapper sub-agent; the orchestrator performs fan-out directly.
> See the **Parallel Execution Rules** section in `SKILL.md` for details. Quality obligations (all-page mandate, verbatim transcription, evidence required) remain unchanged.

## Inputs (3 Categories Only)

The review workflow reads only folders and files in the **3 categories** listed below. The actual source folder/filename for each category is set via env vars (`CERT_REVIEW_REF_CODE_DIR` / `CERT_REVIEW_CERT_DIR` / `CERT_REVIEW_MPS_DIR`); if unset, the test-harness layout is the default.

| Input Category | Tool | Output |
|---|---|---|
| ① Reference code documents (ASTM/ASME, read-only) | CSV reference source | `data/*.csv` |
| ② 성적서 (MTC) under review | pypdfium2 + Claude Vision | `<stem>_extracted.json` (channels: body) |
| ③ MPS (구매시방서) | Claude Vision | Identification and conformance check |

Ground-truth evaluation data (reviewer `comments.md`) is accessed **only during the evaluate phase** (code guard enforced). The `rawdata/` originals are off-limits during normal operation (guard blocks access).

> **혼입 동봉 문서는 Phase 1.6에서 페이지 단위 분류·제외** — enclosed mixed-in documents (원자재 성적서·PMI·NDE·치수검사보고서 등) are classified per-page by `doc-classifier` in Phase 1.6, and every non-finished-product page is deterministically excluded from comparison (whitelist: only 완제품 성적서/미상 are reviewed). See 기준 19 in `references/review-criteria.md`.

> **Note on `<case>` / `--case`**: The `<case>` subdirectory and `--case <id>` argument in Quick Start / subcommands above are **exclusively for the plugin test harness (46-case regression)**. In a deployment environment, the 3-category inputs in the working folder are the review unit, and no case_id is requested at session start.

## Pipeline (Single Compliance Path)

```
build-manifest → prep-inputs (PNG body) → align-inputs (Phase 1.5)
 → classify-sheets → [doc-classifier/claude-opus-4-8] per-page doctype labels → check-doctype gate (Phase 1.6)
 → [ocr-extractor/claude-opus-4-8] Vision OCR
 → check-extraction gate → limits lookup
 → [chemistry/mechanical/heat-treatment/nde/format-reviewer parallel delegation]
 → merge-reviews (deterministic merge of partial outputs → review.json)
 → compliance_report (6시트 한글 xlsx) → evaluate (comments.md baseline)
```

> **Output language**: The compliance report is a **6-sheet Korean Excel (6시트 한글 xlsx)**. All finding text, issue_summary, and content fields are written in Korean using standard reviewer vocabulary — this is unchanged from current behavior.

### Review Agents and Partial Outputs

The orchestrator dispatches all 5 domain review agents **in parallel in a single message** during Phase 4; the Phase 1.6 `doc-classifier` runs **once per case earlier** (before OCR, classification only). Each agent writes its partial output to `.cache/<case>/`:

| Agent | model | Partial Output File |
|---|---|---|
| `doc-classifier` (Phase 1.6, pre-OCR) | claude-opus-4-8 | `<stem>_doctype.json` |
| `chemistry-reviewer` | claude-opus-4-8 | `<case>_review_chemistry.json` |
| `mechanical-reviewer` | claude-opus-4-8 | `<case>_review_mechanical.json` |
| `heat-treatment-reviewer` | claude-opus-4-8 | `<case>_review_heat_treatment.json` |
| `nde-reviewer` | claude-opus-4-8 | `<case>_review_nde.json` |
| `format-reviewer` | claude-opus-4-8 | `<case>_review_format.json` (section key: `doc_checks`) |

After all agents complete, the `merge-reviews` CLI deterministically merges the 5 files into a single `<case>_review.json` (global finding renumbering, worst-case verdict). OCR is handled exclusively by `ocr-extractor` (claude-opus-4-8). All agents use claude-opus-4-8 (accuracy first); OCR (transcription) and review (judgment) are separated by role, not model — with tiered time budgets by complexity (simple ≤30 min / standard ≤60 min / complex 60–90 min, accuracy paramount).

> **Model routing note**: If the `CLAUDE_CODE_SUBAGENT_MODEL` environment variable is set, it overrides the model specified in agent frontmatter. To apply routing as intended, **run with this env var unset**.

## Hard Constraints

- **C1**: OCR uses Claude Vision exclusively. Importing Python OCR libraries is prohibited (enforced by regression tests).
- **C2**: Every judgment row and finding must carry source metadata (`source_file`/`anchor`/`snippet`). Missing metadata causes the entry to be discarded from output.
- **C3**: Year mismatches in ref_code must be noted in remarks.
- **C7**: All commands operate via PowerShell + python.
- **C8**: CSV rows without all 3 provenance metadata fields are rejected at load time (`validate-refs` must exit 0).

## Directory Layout

```
skills/cert-review/        # plugin (skill) root — CLI execution base
├── SKILL.md               # Claude orchestration (Phase 0–6, orchestrator-only)
├── manifest.json          # auto-generated case index
├── data/                  # reference CSVs (3 provenance metadata fields required)
├── scripts/               # Python deterministic modules
│   ├── cli.py             # subcommand entry point
│   ├── merge_reviews.py   # deterministic merge of 5-agent partial outputs
│   └── ...                # prep/validate/eval + domain helpers
├── references/            # domain rules + JSON schemas
└── tests/                 # pytest regression (184 tests, including 18 in test_merge_reviews.py, test_doctype.py for Phase 1.6)
```

Sub-agent files (`agents/*.md`) reside under the **plugin root** (one level above this directory). The CLI is run from the skill directory.

## Evaluation Criteria (match definition)

A reviewer finding (`comments.md`, page × topic cluster) counts as "reproduced" when **content + material_grade + page + severity-tier** all match.
- severity-tier: major{Reject,ActionRequired} / minor{Question,Minor}
- category · exact-severity are **diagnostic indicators** (reviewer judgment may vary for the same issue)
- recall is per-case full-recall, precision is global, dropped = 0
