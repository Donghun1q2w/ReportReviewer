"""doctype.py — Phase 1.6 per-page document-type classification support.

The doc-classifier agent records ``<stem>_doctype.json`` (one per cert stem)
mapping every rendered page to a document type. This module DETERMINISTICALLY
verifies and consumes that sidecar — it never classifies anything itself.

Exclusion is WHITELIST-based: a page is compared/reviewed as before unless its
label is one of the concrete ``EXCLUDED_DOC_TYPES``. A missing sidecar, a missing
field, an unparsable page key, or an unknown label all fall back to "included"
(so a legacy fresh cache without any doctype sidecar behaves exactly as before).

The single deterministic authority for exclusion is this sidecar's ``pages`` map:
even if the OCR agent forgets to stamp ``doc_type`` on an entry, the L2 inventory
filter (refpack) and L4 report injection (merge_reviews) still exclude correctly.

Taxonomy single source: ``DOC_TYPES`` / ``DOC_TYPE_LABELS_KO`` below. The same 13
labels are mirrored (kept in sync — see Definition of Done taxonomy check) in
``agents/doc-classifier.md``, ``references/extraction-schema.json`` (doc_type
enum) and ``references/review-criteria.md`` 기준 19. Code must import these
constants — never re-declare the label strings elsewhere.

Constraint C1: JSON reading only (no OCR). Constraint C7: pathlib + utf-8.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.tile_inputs import _stems_in_png_dir

DOCTYPE_SUFFIX = "_doctype.json"

# Contact-sheet subdirectory for Phase 1.6 (upright sheets, re-composed AFTER
# alignment — the Phase 1.5 "orient" sheets are pre-alignment pixels and must
# not be reused for document-type reading).
CLASSIFY_SHEETS_DIRNAME = "classify"

# Taxonomy single source (1.4절). Order is display order.
DOC_TYPES = (
    "MTC_FINISHED", "UNKNOWN",
    "MTC_RAW_MATERIAL", "PMI_REPORT", "APPEARANCE_DIMENSION_REPORT",
    "NDE_REPORT", "PHYSICAL_CHEMICAL_TEST_REPORT", "MICROSTRUCTURE_REPORT",
    "HEAT_TREATMENT_CHART", "REVIEWED_ANNOTATED_COPY",
    "COVER_LETTER", "MPS_COPY", "DRAWING",
)

# Whitelist: only these two labels keep a page in the review. Everything else
# (and only a KNOWN excluded label) drops the page from comparison.
INCLUDED_DOC_TYPES = frozenset({"MTC_FINISHED", "UNKNOWN"})
EXCLUDED_DOC_TYPES = frozenset(DOC_TYPES) - INCLUDED_DOC_TYPES

DOC_TYPE_LABELS_KO = {
    "MTC_FINISHED": "완제품 성적서",
    "UNKNOWN": "미상(완제품 성적서로 간주)",
    "MTC_RAW_MATERIAL": "원자재 성적서(동봉 Mill Cert)",
    "PMI_REPORT": "PMI 보고서(동봉)",
    "APPEARANCE_DIMENSION_REPORT": "외관·치수검사보고서(동봉)",
    "NDE_REPORT": "비파괴검사 보고서(동봉)",
    "PHYSICAL_CHEMICAL_TEST_REPORT": "이화학시험성적서(동봉)",
    "MICROSTRUCTURE_REPORT": "금속조직시험 보고서(동봉)",
    "HEAT_TREATMENT_CHART": "열처리로 온도차트(동봉)",
    "REVIEWED_ANNOTATED_COPY": "검토 주석본(입력 배제 대상)",
    "COVER_LETTER": "송부문서/커버레터",
    "MPS_COPY": "MPS 사본",
    "DRAWING": "도면",
}

# Excluded-ratio warning threshold: above this a stem gets a WARNING (not a
# gate failure) so the orchestrator re-checks boundary pages before proceeding.
WARN_EXCLUDED_RATIO = 0.6


def doctype_path(case_cache: Path, stem: str) -> Path:
    """Path of the doc-classifier agent's classification output for a cert stem."""
    return Path(case_cache) / f"{stem}{DOCTYPE_SUFFIX}"


def load_doctype(case_cache: Path, stem: str) -> dict | None:
    """Return the parsed doctype sidecar for a stem, or None (absent/invalid).

    Same forgiving idiom as ``align_inputs._load_json``: a missing file, a parse
    failure, or a non-dict payload all yield None so callers fall back to the
    include-everything behaviour.
    """
    path = doctype_path(case_cache, stem)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _page_labels(doctype: dict) -> dict[int, str]:
    """Parse a sidecar's ``pages`` map into ``{page:int -> label:str}``.

    Non-integer page keys are skipped (they cannot line up with a rendered
    ``_pNN.png``). Label validity is NOT enforced here — the gate reports
    unknown labels; the exclusion consumers below treat unknown labels as
    "included".
    """
    pages = doctype.get("pages")
    if not isinstance(pages, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in pages.items():
        try:
            page_no = int(key)
        except (TypeError, ValueError):
            continue
        out[page_no] = str(value)
    return out


def excluded_pages_map(case_cache: Path, stem: str) -> dict[int, str]:
    """Return ``{page:int -> doc_type}`` for a stem's EXCLUDED pages only.

    Sidecar absent/invalid → ``{}`` (every page stays in the review). A page
    whose label is not a known EXCLUDED type (an INCLUDED label, or an unknown
    string) is omitted — i.e. treated as included. This is the whitelist
    fallback that keeps legacy caches identical to current behaviour.
    """
    doctype = load_doctype(case_cache, stem)
    if not doctype:
        return {}
    out: dict[int, str] = {}
    for page_no, label in _page_labels(doctype).items():
        if label in EXCLUDED_DOC_TYPES:
            out[page_no] = label
    return out


def compress_pages(pages: list[int]) -> str:
    """Format a page list as compact ranges: ``[30,31,55] -> "p.30-31, p.55"``."""
    nums = sorted(set(int(p) for p in pages))
    if not nums:
        return ""
    runs: list[tuple[int, int]] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        runs.append((start, prev))
        start = prev = n
    runs.append((start, prev))
    parts = [f"p.{a}" if a == b else f"p.{a}-{b}" for a, b in runs]
    return ", ".join(parts)


def excluded_documents_for_case(case_cache: Path) -> list[dict]:
    """Build the ``excluded_documents[]`` list for a case from every doctype sidecar.

    Each stem's excluded pages are grouped into RUNS of consecutive pages
    sharing the same doc_type (a raw-material Mill Cert block, an NDE report
    block, …). Sorted by ``(stem, first page)``. No sidecar in the case → ``[]``.
    The advisory ``documents`` array a sidecar may carry is NOT consulted here —
    the ``pages`` map is the single authority.
    """
    case_cache = Path(case_cache)
    docs: list[dict] = []
    for jp in sorted(case_cache.glob(f"*{DOCTYPE_SUFFIX}")):
        stem = jp.name[: -len(DOCTYPE_SUFFIX)]
        excluded = excluded_pages_map(case_cache, stem)
        if not excluded:
            continue
        for pages, doc_type in _group_runs(excluded):
            ko = DOC_TYPE_LABELS_KO.get(doc_type, doc_type)
            docs.append({
                "stem": stem,
                "doc_type": doc_type,
                "doc_type_ko": ko,
                "pages": pages,
                "page_range": compress_pages(pages),
                "note": (
                    f"제외됨: {ko} — 완제품 성적서가 아닌 동봉 문서로 분류되어 "
                    f"비교 검토에서 제외"
                ),
            })
    docs.sort(key=lambda d: (d["stem"], d["pages"][0] if d["pages"] else 0))
    return docs


def _group_runs(excluded: dict[int, str]) -> list[tuple[list[int], str]]:
    """Group ``{page -> doc_type}`` into consecutive-same-type runs.

    A run breaks when the page number is not contiguous OR the doc_type changes,
    so two adjacent excluded blocks of different types stay separate documents.
    """
    runs: list[tuple[list[int], str]] = []
    cur_pages: list[int] = []
    cur_type: str | None = None
    for page_no in sorted(excluded):
        label = excluded[page_no]
        if (
            cur_type is not None
            and label == cur_type
            and cur_pages
            and page_no == cur_pages[-1] + 1
        ):
            cur_pages.append(page_no)
        else:
            if cur_pages:
                runs.append((cur_pages, cur_type))
            cur_pages = [page_no]
            cur_type = label
    if cur_pages:
        runs.append((cur_pages, cur_type))
    return runs


def _png_pages_by_stem(png_dir: Path) -> dict[str, set[int]]:
    """Rendered page numbers per stem, from ``_stems_in_png_dir`` (same source
    as the align-inputs coverage gate)."""
    out: dict[str, set[int]] = {}
    for stem, pngs in _stems_in_png_dir(png_dir).items():
        out[stem] = {int(p.stem.rsplit("_p", 1)[1]) for p in pngs}
    return out


def check_doctype_case(case_id: str, cache_root: Path) -> dict:
    """Phase 1.6 gate: verify every rendered stem has a valid doctype sidecar.

    Coverage source is the rendered PNG inventory (``_stems_in_png_dir``) — the
    same source the align-inputs gate uses, so the two gates agree on the stem
    set. Per stem the gate checks:
      - sidecar present (absent → ``uncovered_stems``, gate fail);
      - every rendered page is labelled and no extra page is labelled;
      - every label is one of ``DOC_TYPES`` (unknown → issue, gate fail);
      - at least one page is INCLUDED (all-excluded → issue asking for a human
        check — an entire file classified as non-finished is abnormal);
      - a WARNING (not a failure) when the excluded ratio exceeds
        ``WARN_EXCLUDED_RATIO`` on a stem of >=4 pages.

    Raises FileNotFoundError when the case has no rendered PNGs (run prep-inputs
    first) — same idiom as orient_sheets.build_orient_sheets.
    """
    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "png"
    if not png_dir.is_dir():
        raise FileNotFoundError(f"no rendered PNGs for case {case_id}: {png_dir}")

    png_by_stem = _png_pages_by_stem(png_dir)

    stems_out: list[dict] = []
    uncovered: list[str] = []
    case_warnings: list[str] = []

    for stem, png_pages in sorted(png_by_stem.items()):
        doctype = load_doctype(case_cache, stem)
        if doctype is None:
            uncovered.append(stem)
            continue

        labels = _page_labels(doctype)
        issues: list[str] = []
        warnings: list[str] = []

        # Coverage: labelled pages vs rendered pages.
        labelled_pages = set(labels)
        gaps = sorted(png_pages - labelled_pages)
        extras = sorted(labelled_pages - png_pages)
        if gaps:
            issues.append(f"pages without a doctype label: {gaps}")
        if extras:
            issues.append(f"labelled pages not rendered (extra): {extras}")

        included = 0
        excluded = 0
        by_type: dict[str, int] = {}
        invalid_labels: list[str] = []
        for page_no in sorted(png_pages & labelled_pages):
            label = labels[page_no]
            if label not in DOC_TYPES:
                invalid_labels.append(f"p{page_no}={label!r}")
                continue
            if label in INCLUDED_DOC_TYPES:
                included += 1
            else:
                excluded += 1
                by_type[label] = by_type.get(label, 0) + 1
        if invalid_labels:
            issues.append(f"invalid doctype labels: {invalid_labels}")

        pages_total = len(png_pages)
        # Anomaly gate A: an entire stem excluded is abnormal — ask for a human.
        if pages_total > 0 and included == 0:
            issues.append(
                "전 페이지가 비-완제품으로 분류됨 — 비정상, 사람 확인 필요"
            )
        # Anomaly gate B: high exclusion ratio → WARNING only (exit 0).
        if pages_total >= 4 and excluded / pages_total > WARN_EXCLUDED_RATIO:
            msg = (
                f"제외율 {excluded}/{pages_total} "
                f"(>{WARN_EXCLUDED_RATIO:.0%}) — 경계 페이지 재확인 권장"
            )
            warnings.append(msg)
            case_warnings.append(f"{stem}: {msg}")

        uncertain = doctype.get("uncertain_pages")
        uncertain_pages = uncertain if isinstance(uncertain, list) else []

        stems_out.append({
            "stem": stem,
            "pages_total": pages_total,
            "included": included,
            "excluded": excluded,
            "by_type": by_type,
            "uncertain_pages": uncertain_pages,
            "issues": issues,
            "warnings": warnings,
            "ok": not issues,
        })

    ok = not uncovered and all(s["ok"] for s in stems_out) and bool(stems_out)
    return {
        "case_id": str(case_id),
        "stems": stems_out,
        "uncovered_stems": uncovered,
        "warnings": case_warnings,
        "ok": ok,
    }


__all__ = [
    "DOCTYPE_SUFFIX",
    "CLASSIFY_SHEETS_DIRNAME",
    "DOC_TYPES",
    "INCLUDED_DOC_TYPES",
    "EXCLUDED_DOC_TYPES",
    "DOC_TYPE_LABELS_KO",
    "WARN_EXCLUDED_RATIO",
    "doctype_path",
    "load_doctype",
    "excluded_pages_map",
    "compress_pages",
    "excluded_documents_for_case",
    "check_doctype_case",
]
