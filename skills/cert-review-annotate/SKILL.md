---
name: cert-review-annotate
description: Runs the full cert-review MTC (성적서) compliance review and then, as a follow-on step, attaches the review verdicts to the original cert PDF as native, individually editable PDF annotation objects (a border-only Square box with an Acrobat-native Popup companion + an always-visible Korean FreeText label with a self-generated appearance stream). Annotates only 주의/N/A/FAIL items (PASS excluded) in the report's verdict colours. Use for 성적서 주석, MTC 주석 PDF, 검토 결과 PDF 표기, annotated certificate.
---

# cert-review-annotate — Review + PDF Annotation Procedure

This skill **wraps the existing `cert-review` skill** and adds a **lower-priority
(후순위) annotation pass** that marks the review result directly on the original MTC
PDF. The core review is run unchanged; annotation is a strictly additive
post-processing step driven by a dedicated locator agent plus a deterministic
renderer.

```
Phase A  cert-review (unchanged)        → <case>_review.json + <case>_MTC_Review.xlsx
Phase B  annotation-locator (delegate)  → <case>_annotations.json   (후순위)
Phase C  annotate CLI (deterministic)   → <stem>_annotated.pdf
```

- **Separation of concerns**: cert-review owns the review (review.json + 6-sheet Excel).
  This skill consumes review.json **read-only** and never edits the review logic
  (the 5 reviewers, `review-criteria.md`, the review.json schema, `merge_reviews`).
- **Coordinate source**: a single dedicated **`annotation-locator`** agent produces all
  coordinates (not the 5 review agents), keeping localization in one place.
- **Output language**: this document is English; the attached annotation labels are
  Korean (reviewer vocabulary), matching the 6-sheet report.

> **Paths**: the deterministic CLI lives in the sibling `cert-review` skill
> (`../cert-review/scripts/cli.py`). Run all CLI commands from the **cert-review skill
> directory** (`SKILL_DIR`), prefixed with `PYTHONIOENCODING=utf-8`, as
> `python -m scripts.cli ...` (constraint C7). `<WORK>` is auto-discovered or set via
> `CERT_REVIEW_WORKDIR` exactly as in cert-review.

---

## Annotation scope & style (사용자 확정)

| Item | Rule |
|---|---|
| Targets | review rows whose verdict is **주의 / N/A / FAIL**. **PASS is excluded.** |
| Shape | **border-only rectangle (no fill)** enclosing the cited cell + a text label. |
| Text | ≤ **50 characters**, concise Korean. |
| Colour | same as the report verdict fills — 주의 `#FFEB9C` (yellow), N/A `#D9D9D9` (grey), FAIL `#FFC7CE` (red). (`#C6EFCE` green PASS is unused.) Colours are reused from `compliance_report` so the annotations match the Excel report exactly. |
| Method | **native PDF annotation objects** — every page is preserved verbatim (`clone_from` copy-through; content bytes, MediaBox/CropBox/Rotate unchanged). Each item attaches a border-only `/Square` (verdict-coloured border) plus an always-visible `/FreeText` Korean label with a self-generated appearance stream (vector chip + Hangul-glyph image), so the label shows in every major viewer. The label carries the `NoRotate` flag and a naturally shaped `/Rect`, so it stays horizontal for the reader on `/Rotate`-ed pages even after a viewer regenerates its appearance. Each Square carries an Acrobat-native empty `/Popup` companion (bidirectional `/Popup`–`/Parent` link), matching the in-house reviewer's Acrobat annotation pattern (ref: `docs/PU2601564.pdf`). Every annotation is individually deletable / movable / editable in a viewer. |

---

## Phase A — run cert-review (unchanged)

Execute the **entire cert-review procedure** as documented in
`../cert-review/SKILL.md` (Phase 0 build-manifest → … → Phase 5 compliance_report).
Do **not** duplicate or modify that procedure here — follow it as-is. On completion the
case has:

- `.cache/<case>/<case>_review.json` (the review result this skill annotates)
- `output/reports/<case>/<case>_MTC_Review.xlsx` (the 6-sheet report)
- `.cache/<case>/png/` and `.cache/<case>/tiles/` (rendered pages — reused by Phase B; no re-render)

If review.json already exists and is fresh (cert-review's cache gate is `fresh`/`legacy`),
Phase A is a no-op and you may proceed directly to Phase B.

---

## Phase B — delegate `annotation-locator` (후순위)

Delegate to the **`annotation-locator`** agent (one delegation per case). Context to
include:

- case id
- the **cert-review SKILL_DIR absolute path**
- the review.json path (`.cache/<case>/<case>_review.json`)
- the rendered page locations (`.cache/<case>/png` / `tiles`)
- the case's cert PDF stem list

The agent reads review.json + the cached page renders, locates each **주의/N/A/FAIL**
item's cell as a **fractional bbox** (Tier A — only confidently located cells; no
estimated boxes), authors a ≤50-char Korean label, and writes
`.cache/<case>/<case>_annotations.json`. PASS rows and reference-only N/A (참고/INFO with
no concrete cell) are skipped and counted.

> The localization detail (page/bbox resolution, label authoring, Tier-A rule,
> skip reasons) lives in `agents/annotation-locator.md` — do not duplicate it here.

### `<case>_annotations.json` contract (locator output → renderer input)

```json
{
  "case_id": "24",
  "schema_version": "1.0",
  "annotations": [
    { "stem": "PU2501275 MTC_cert", "page": 2, "bbox": [0.10, 0.42, 0.55, 0.50],
      "verdict": "FAIL", "label": "FAIL: P 0.024 > 0.02", "source_ref": "chemistry/P" }
  ],
  "skipped": [ { "reason": "reference_only_na", "ref": "chemistry/Cev" } ]
}
```

- `verdict` ∈ `주의 | N/A | FAIL` (renderer drops PASS/other).
- `bbox` = fractions in [0,1], top-left origin (same as `crop --bbox`); `page` = 1-based
  physical page **inside that stem's PDF** (= `crop --page`); `stem` required when the
  case has >1 cert PDF.
- The renderer applies a dual gate (valid bbox + integer page in range) and skips/counts
  malformed rows, so a missing/partial annotations file never errors.

---

## Phase C — attach the native annotations (deterministic)

From the cert-review SKILL_DIR:

```powershell
$env:PYTHONIOENCODING = "utf-8"
Set-Location "<...>/plugin/ReportReviewer/skills/cert-review"

python -m scripts.cli annotate --case 24                 # single case (multi cert PDF -> one _annotated.pdf each)
python -m scripts.cli annotate --case 24 --out "D:\deliver\24"   # override output dir
python -m scripts.cli annotate --all                     # batch (cases that have <case>_annotations.json)
```

- Output: `<WORK>/output/reports/<case>/<stem>_annotated.pdf` (co-located with the Excel
  report; one annotated PDF per cert PDF).
- Every page is preserved verbatim (content bytes identical; no rasterisation); the
  Square/Popup/FreeText objects are only appended to `/Annots`, so each annotation can
  be individually selected, moved or deleted in a PDF viewer.
- Coordinate convention: the locator's fractional bbox is in the *aligned* (upright)
  image space; the renderer maps it back to the original user-space `/Rect` via
  `T = (R + A) % 360` (page `/Rotate` + align-inputs applied rotation), anchored to the
  page `/CropBox` origin.
  The Square is mapped from that aligned space; the `NoRotate` label is instead anchored
  in the display space (the page turned by its own `/Rotate`), which is the same space
  whenever the align-inputs applied rotation is 0.
- The Korean label is always visible in every major viewer (self-generated appearance
  stream). Adobe Acrobat regenerates that appearance with its own fonts not only when
  the label text is *edited* but also when the annotation is merely **resized** (리사이즈). The
  label is built to survive that: its `/Rect` is always the chip's natural (never
  width/height-swapped) shape, so a regenerated appearance still lays out on one line,
  and the `/FreeText` carries the **NoRotate** flag (`/F` bit 5) so it stays horizontal
  for the reader even on a `/Rotate`-ed page. Moving/deleting is unaffected.
- **Known Acrobat limitation (real-viewer confirmed, 2026-07-28)**: on a `/Rotate`-ed page
  (verified at `/Rotate=180`), the label's *content* always renders correctly (NoRotate
  keeps it horizontal), but Adobe Acrobat's own selection/resize-handle overlay for the
  `/FreeText` is drawn using ordinary rotation-following coordinates, ignoring `NoRotate` —
  so the handle box appears point-mirrored (both axes) from where the label actually sits.
  Dragging that handle box to resize still leaves the text horizontal (worst case: it wraps
  to two lines), but the handle position itself is visually confusing. This is outside PDF
  authoring's control (NoRotate governs appearance rendering only; the PDF spec does not
  constrain a viewer's own editing-UI chrome) — do not attempt a further coordinate fix for
  it. Advise users not to drag-resize a label's handles in Acrobat; moving the whole
  annotation and deleting are unaffected.
- Backward-compatible: a case without `<case>_annotations.json` is a SKIP under `--all`
  (and an error for a single `--case`); a case with zero locatable items yields the
  original pages with `0 annotation(s)` logged.

---

## Constraints (inherited from cert-review)

| ID | Content |
|---|---|
| **C1** | No Python OCR libraries. Localization uses Claude Vision (`Read`) + the `crop` CLI; the annotate step uses `pypdf` (native annotation objects, copy-through re-assembly) + `Pillow` (label appearance-stream glyph raster only — the page itself is never rasterised) — none are OCR. |
| **C7** | Windows PowerShell + Python; run from the cert-review SKILL_DIR with `PYTHONIOENCODING=utf-8`. |
| Input whitelist | cert PDFs (already rendered in `.cache`), the cache, and `<case>_review.json`. `rawdata/` and `standard inspection GT data/` are never opened. |
| Korean integrity | Labels are Korean; a Hangul-capable TTF is required to generate the label appearance stream (`malgun.ttf` by default; override with `CERT_REVIEW_FONT`). After writing annotations.json and after attaching, confirm the Korean is intact: re-read the output PDF's `/Contents` strings and check the label glyph pixels in a pdfium smoke render (automated); the final visual check in a real viewer is delegated. |

---

## End-to-end flow summary

```
Phase A  cert-review (../cert-review/SKILL.md, unchanged) → <case>_review.json + xlsx
Phase B  [delegate annotation-locator] → .cache/<case>/<case>_annotations.json
            (주의/N/A/FAIL only, PASS excluded, Tier-A bbox, ≤50-char Korean label)
Phase C  python -m scripts.cli annotate --case <id>
            → output/reports/<case>/<stem>_annotated.pdf
              (native /Square + /Popup + /FreeText(+AP) annotations, all pages verbatim)
```
