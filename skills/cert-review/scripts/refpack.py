"""refpack.py — per-case reference-limit pack (Phase-4 context diet).

Reads a case's ``_extracted.json`` page headers to build a (grade, class, spec)
inventory, routes each grade through the existing grade-routing table
(``compare_engine._grade_route`` + ``_resolve_grade_keys``), and selects only the
RELEVANT rows from the 7 reference CSVs. Every selected row is the verbatim CSV
row, so the 3 provenance fields (source_file/anchor/snippet) are preserved
(C2/C8). Grades that fail to route are reported in ``unrouted`` — never silently
dropped.

The output ``.cache/<case>/<case>_limits.json`` lets a Phase-4 reviewer compare
against a small, grade-scoped pack instead of scanning every CSV by hand. The
numbers still originate from the CSVs, so provenance integrity is unchanged.

Constraint C1: no OCR libraries. Reads ONLY the plugin .cache + data dirs and the
provenance source files referenced by the CSVs (via load_csv).
Constraint C7: pathlib throughout, encoding='utf-8' on all file I/O.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from scripts.compare_engine import _grade_route, _resolve_grade_keys
from scripts.doctype import excluded_pages_map
from scripts.refdata_loader import load_csv

# CSV file name -> the column that identifies the row's grade/spec scope.
_CSV_FILES = (
    "chemistry_limits.csv",
    "mechanical_limits.csv",
    "heat_treatment.csv",
    "nde_rules.csv",
    "mps_overrides.csv",
    "grade_routing.csv",
    "code_edition_map.csv",
)


def _spec_token(spec: str | None) -> str:
    """Extract the bare 'SA-###' / 'A###' token from a cert spec string."""
    if not spec:
        return ""
    m = re.search(r"S?A-?\d+", spec)
    return m.group(0) if m else ""


def _cert_grade_query(spec: str | None, grade: str | None) -> str:
    """Build a routable cert-grade string from a header (spec, grade) pair.

    The routing patterns key on 'SA-### Pxx' / 'SA-### Gr X' style strings, so we
    normalize two common header spellings:
      - a grade carrying no spec token (e.g. 'P22') gets the spec's SA token
        prepended -> 'SA-335 P22';
      - a compact carbon-steel grade (e.g. 'SA106C', 'A106B') is expanded to the
        'SA-### Gr X' form the routing table expects -> 'SA-106 Gr C'.
    This is pure query construction; the routing table itself is unchanged, and
    any grade that still fails to route is reported as ``unrouted``.
    """
    g = (grade or "").strip()
    spec_tok = _spec_token(spec)
    if not g:
        return spec_tok

    # Compact 'SA106C' / 'A106B' -> 'SA-106 Gr C' (carbon-steel single letter).
    compact = re.match(r"^S?A-?(\d+)\s*([A-Z])$", g, re.IGNORECASE)
    if compact:
        return f"SA-{compact.group(1)} Gr {compact.group(2).upper()}"

    if re.match(r"S?A-?\d+", g):
        return g
    if spec_tok:
        return f"{spec_tok} {g}"
    return g


def collect_inventory(case_cache: Path) -> list[dict]:
    """Collect the distinct (grade, class, spec) header tuples for a case.

    Returns a list of {"grade", "class", "spec"} dicts (order-stable, de-duped).
    Reads every ``*_extracted.json`` in the case cache dir.
    """
    case_cache = Path(case_cache)
    seen: set[tuple] = set()
    inventory: list[dict] = []
    for jp in sorted(case_cache.glob("*_extracted.json")):
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        # L2 (deterministic): drop pages classified as enclosed non-MTC
        # documents so raw-material grades (SA516 plate, etc.) never pollute
        # the finished-product routing/inventory. Authority is the
        # <stem>_doctype.json sidecar (entry.doc_type is NOT consulted here —
        # sidecar is the single source); absent sidecar → empty map → no skips.
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
            grade = header.get("grade")
            spec = header.get("spec")
            klass = header.get("class")
            key = (grade, klass, spec)
            if key in seen:
                continue
            seen.add(key)
            inventory.append({"grade": grade, "class": klass, "spec": spec})
    return inventory


def _bare_tail(cert_grade: str) -> str:
    """Return the bare grade tail (e.g. P22, F91, WPB, C) from a cert grade."""
    m = re.search(
        r"(P\d+[a-z]?|F\d+[a-z]?|WP[BCR]\b|WP\d+[A-Z0-9]*|B\d+)",
        cert_grade or "",
        re.IGNORECASE,
    )
    if m:
        return m.group(1).upper()
    # Single-letter grade (SA-106 Gr C -> 'C', SA-672 B70 already caught above).
    m2 = re.search(r"Gr(?:ade)?\.?\s*([A-Z]\d*)\b", cert_grade or "", re.IGNORECASE)
    if m2:
        return m2.group(1).upper()
    return ""


def _match_keys_for(routed: dict, cert_grade: str) -> dict:
    """Build the set of identifiers used to select rows for one routed grade."""
    keys = set(_resolve_grade_keys(routed, cert_grade))
    asme = (routed.get("asme_spec") or "").strip()
    astm = (routed.get("astm_spec") or "").strip()
    tail = _bare_tail(cert_grade)
    if tail:
        keys.add(tail)
    specs = {s for s in (asme, astm) if s}
    return {"keys": keys, "specs": specs, "asme": asme, "tail": tail}


def _row_matches(csv_name: str, row: dict, m: dict) -> bool:
    """Decide whether a CSV row is relevant to a routed grade's match set."""
    keys: set[str] = m["keys"]
    specs: set[str] = m["specs"]
    asme: str = m["asme"]

    if csv_name == "code_edition_map.csv":
        return (row.get("spec") or "").strip() in specs

    if csv_name == "grade_routing.csv":
        # The routing row itself is added separately; skip generic matching.
        return False

    if csv_name == "mps_overrides.csv":
        g = (row.get("grade") or "").strip()
        if g in keys:
            return True
        # '<spec>-X' is an explicit wildcard covering any grade under the spec
        # (e.g. 'SA-106-X'); a concrete grade like 'SA-335-P91' must NOT match a
        # different routed grade just because it shares the spec prefix.
        if asme and g == f"{asme}-X":
            return True
        return g in specs

    if csv_name == "nde_rules.csv":
        g = (row.get("grade") or "").strip()
        return g in keys

    # chemistry / mechanical / heat_treatment all key on the 'grade' column.
    g = (row.get("grade") or "").strip()
    return g in keys


def build_limits_pack(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
    data_dir: Path,
) -> dict:
    """Build and write the per-case reference-limit pack.

    Returns a dict:
        {
          "case_id": str,
          "inventory": [{grade, class, spec}, ...],
          "limits": {csv_name: [row, ...], ...},   # relevant rows, provenance kept
          "unrouted": [str, ...],                   # grades that failed routing
          "output_path": str,
        }

    Raises FileNotFoundError if the case has no extracted JSON.
    """
    work_dir = Path(work_dir)
    cache_root = Path(cache_root)
    data_dir = Path(data_dir)

    case_cache = cache_root / str(case_id)
    extracted = sorted(case_cache.glob("*_extracted.json"))
    if not extracted:
        raise FileNotFoundError(
            f"no *_extracted.json in {case_cache} (run prep-inputs + Phase-2 first)"
        )

    inventory = collect_inventory(case_cache)

    # Load all CSVs once (provenance-validated).
    csv_rows: dict[str, list[dict]] = {}
    for name in _CSV_FILES:
        path = data_dir / name
        csv_rows[name] = load_csv(path, work_dir) if path.exists() else []

    routing = csv_rows.get("grade_routing.csv", [])

    # Route each distinct grade and accumulate match sets + the routing rows.
    match_sets: list[dict] = []
    routing_rows: list[dict] = []
    routing_seen: set[int] = set()
    unrouted: list[str] = []
    unrouted_seen: set[str] = set()

    for item in inventory:
        grade = item.get("grade")
        cert_grade = _cert_grade_query(item.get("spec"), grade)
        routed = _grade_route(cert_grade, routing) if cert_grade else None
        if routed is None:
            label = (grade or "").strip() or "(blank grade)"
            if label not in unrouted_seen:
                unrouted_seen.add(label)
                unrouted.append(label)
            continue
        match_sets.append(_match_keys_for(routed, cert_grade))
        rid = id(routed)
        if rid not in routing_seen:
            routing_seen.add(rid)
            routing_rows.append(routed)

    # Select relevant rows per CSV (preserving full provenance rows).
    limits: dict[str, list[dict]] = {}
    for name in _CSV_FILES:
        if name == "grade_routing.csv":
            limits[name] = routing_rows
            continue
        selected: list[dict] = []
        for row in csv_rows[name]:
            if any(_row_matches(name, row, m) for m in match_sets):
                selected.append(row)
        limits[name] = selected

    output_path = case_cache / f"{case_id}_limits.json"
    pack = {
        "case_id": str(case_id),
        "inventory": inventory,
        "limits": limits,
        "unrouted": unrouted,
    }
    case_cache.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    pack["output_path"] = str(output_path).replace("\\", "/")
    return pack


__all__ = [
    "collect_inventory",
    "build_limits_pack",
]
