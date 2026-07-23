"""attachments.py — 기준 20 deterministic attachment index (Phase 4 input).

Joins the Phase 1.6 doctype sidecars (excluded enclosed-document runs with
related heat/PO identifiers) against the finished-product heat inventory from
``*_extracted.json`` INCLUDED pages, and writes ``<case>_attachments.json``
consumed by nde-reviewer / format-reviewer for requirement-vs-attachment
judgement.

Matching is exact string equality after normalisation (whitespace stripped,
upper-cased) — no fuzzy matching; unmatched related heats are reported in
``unmatched_heat_nos``, never auto-failed. Only ``related_confidence: "high"``
runs feed ``heat_coverage`` (the state-C PASS basis). Absent sidecars →
``sidecar_present: false`` (legacy behaviour: reviewers skip attachment
judgement). The doctype ``pages`` map stays the exclusion authority; this module
only reads the related metadata it already carries.

Constraint C1: JSON reading only (no OCR). Constraint C7: pathlib + utf-8.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.doctype import (
    _png_pages_by_stem,
    excluded_documents_for_case,
    excluded_pages_map,
    load_doctype,
)

ATTACHMENTS_SUFFIX = "_attachments.json"

_HEAT_NORM_RE = re.compile(r"\s+")


def _norm_heat(v: str | None) -> str:
    """Normalise a heat string for comparison: strip all whitespace, upper-case.

    Deliberately conservative — no 0/O or 1/I substitution (that would be fuzzy
    matching, which 기준 20 forbids). The verbatim form is kept for the record.
    """
    return _HEAT_NORM_RE.sub("", str(v or "")).upper()


def collect_finished_heats(case_cache: Path) -> list[str]:
    """Collect the verbatim finished-product ``heat_no`` values for a case.

    Reads every ``*_extracted.json`` header, skipping pages classified as
    enclosed non-MTC documents (same ``excluded_pages_map`` idiom as
    ``refpack.collect_inventory``) so raw-material / enclosed heats never enter
    the finished inventory. Order-stable de-dup; empty values dropped. Verbatim
    (unnormalised) — normalisation happens only at compare time.
    """
    case_cache = Path(case_cache)
    seen: set[str] = set()
    heats: list[str] = []
    for jp in sorted(case_cache.glob("*_extracted.json")):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        stem = jp.name[: -len("_extracted.json")]
        excluded = excluded_pages_map(case_cache, stem)
        for entry in data.get("page_extraction") or []:
            if not isinstance(entry, dict):
                continue
            page = entry.get("page")
            try:
                page_no = int(page)
            except (TypeError, ValueError):
                page_no = None
            if page_no is not None and page_no in excluded:
                continue
            header = entry.get("header") or {}
            heat = header.get("heat_no")
            if heat in (None, ""):
                continue
            heat = str(heat)
            if heat in seen:
                continue
            seen.add(heat)
            heats.append(heat)
    return heats


def _all_stems_covered(case_cache: Path) -> bool:
    """True only when every rendered stem (``png/`` inventory) has a doctype sidecar.

    ``bool(any *_doctype.json)`` would report ``sidecar_present: true`` for a
    partially-classified case (stem A covered, stem B not) — stem B's enclosed
    reports would then be invisible to ``attachments[]`` while the reviewer still
    believes coverage is complete, which could misfire a state-B "미첨부" for
    stem B's requirements. Coverage source mirrors ``check_doctype_case`` (same
    ``png/`` inventory) so the two gates agree; no rendered stems → not covered.
    """
    png_dir = case_cache / "png"
    if not png_dir.is_dir():
        return False
    stems = _png_pages_by_stem(png_dir)
    if not stems:
        return False
    return all(load_doctype(case_cache, stem) is not None for stem in stems)


def build_attachments_pack(case_id: str, cache_root: Path) -> dict:
    """Build and write the per-case 기준 20 attachment index.

    Returns a dict:
        {
          "schema_version": "1.0",
          "case_id": str,
          "sidecar_present": bool,      # any <stem>_doctype.json in the case cache
          "finished_heats": [str, ...], # verbatim finished-product heats
          "attachments": [              # one per excluded enclosed-document run
            {stem, doc_type, doc_type_ko, pages, page_range,
             related_heat_nos, related_po_items, related_confidence,
             matched_heat_nos,          # inventory verbatim, normalised match
             unmatched_heat_nos},       # related heats absent from inventory
            ...
          ],
          "heat_coverage": {            # only related_confidence "high" runs
            doc_type: {inventory_verbatim_heat: [page_range, ...]}
          },
          "output_path": str,
        }

    Raises FileNotFoundError when the case has no ``*_extracted.json`` (run
    prep-inputs + Phase-2 first) — same idiom as ``refpack.build_limits_pack``.
    A missing doctype sidecar is NOT an error: ``sidecar_present`` is false and
    ``attachments``/``heat_coverage`` are empty (legacy-cache behaviour).
    ``sidecar_present`` requires *every* rendered stem to carry a sidecar
    (``_all_stems_covered``) — a partially-classified case (one stem covered,
    another not) also reports ``false``, since an uncovered stem's enclosed
    reports would otherwise be invisible to ``attachments[]`` while callers
    believe 기준 20 judgement is safe to run.
    """
    cache_root = Path(cache_root)
    case_cache = cache_root / str(case_id)
    extracted = sorted(case_cache.glob("*_extracted.json"))
    if not extracted:
        raise FileNotFoundError(
            f"no *_extracted.json in {case_cache} (run prep-inputs + Phase-2 first)"
        )

    finished_heats = collect_finished_heats(case_cache)
    # inventory: normalised heat -> verbatim heat (first-seen wins).
    inv_by_norm: dict[str, str] = {}
    for h in finished_heats:
        inv_by_norm.setdefault(_norm_heat(h), h)

    sidecar_present = _all_stems_covered(case_cache)

    attachments: list[dict] = []
    heat_coverage: dict[str, dict[str, list[str]]] = {}

    for rec in excluded_documents_for_case(case_cache):
        related_heats = list(rec.get("related_heat_nos") or [])
        confidence = str(rec.get("related_confidence") or "low")
        page_range = rec.get("page_range", "")
        doc_type = rec.get("doc_type", "")

        matched: list[str] = []
        unmatched: list[str] = []
        matched_seen: set[str] = set()
        for rh in related_heats:
            inv_verbatim = inv_by_norm.get(_norm_heat(rh))
            if inv_verbatim is None:
                unmatched.append(rh)
            elif inv_verbatim not in matched_seen:
                matched_seen.add(inv_verbatim)
                matched.append(inv_verbatim)

        attachments.append({
            "stem": rec.get("stem", ""),
            "doc_type": doc_type,
            "doc_type_ko": rec.get("doc_type_ko", ""),
            "pages": rec.get("pages", []),
            "page_range": page_range,
            "related_heat_nos": related_heats,
            "related_po_items": list(rec.get("related_po_items") or []),
            "related_confidence": confidence,
            "matched_heat_nos": matched,
            "unmatched_heat_nos": unmatched,
        })

        # Coverage: only high-confidence runs contribute (결정 5-3). Union of
        # page_ranges across runs of the same doc_type per inventory heat.
        if confidence == "high" and matched:
            per_type = heat_coverage.setdefault(doc_type, {})
            for inv_verbatim in matched:
                ranges = per_type.setdefault(inv_verbatim, [])
                if page_range and page_range not in ranges:
                    ranges.append(page_range)

    pack = {
        "schema_version": "1.0",
        "case_id": str(case_id),
        "sidecar_present": sidecar_present,
        "finished_heats": finished_heats,
        "attachments": attachments,
        "heat_coverage": heat_coverage,
    }

    output_path = case_cache / f"{case_id}{ATTACHMENTS_SUFFIX}"
    case_cache.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pack["output_path"] = str(output_path).replace("\\", "/")
    return pack


__all__ = [
    "ATTACHMENTS_SUFFIX",
    "collect_finished_heats",
    "build_attachments_pack",
]
