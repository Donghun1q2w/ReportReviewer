"""Deterministic comparison engine — Phase 4.

Reads a case's extracted.json (Claude Vision body + pypdf annotations) and
compares each page against the 7 reference CSVs under data/.
Emits findings with evidence attached per C2/C8.

This module deliberately does NOT call any LLM, OCR library, or Gemini API
(C1). All branching is rule-based on the extraction schema and CSV rows.

Public API:
    compare_case(case_id, work_dir, cache_root, data_dir) -> dict
        - Loads extracted.json under <cache_root>/<case_id>/.
        - Loads the 7 reference CSVs via refdata_loader (which itself enforces
          provenance via source_validator).
        - Runs the 5 rule families (chemistry / mechanical / heat treatment /
          NDE / annotations) and filters out evidence-less findings.
        - Writes <cache_root>/<case_id>/<case_id>_findings.json and returns
          a result dict.

Constraints:
    - C1: No OCR libs (no imports of pytesseract/easyocr/fitz/etc.).
    - C2/C8: Every finding evidence entry must validate via
      source_validator.validate_finding. The body channel uses the cert PDF
      sha; ref_code and mps channels reuse the CSV row's provenance.
    - C4: Never reads the ground-truth directory (eval_harness is the only
      module permitted to touch it).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from .refdata_loader import load_csv, index_by
from .source_validator import filter_valid_findings, compute_sha256


# ---------------------------------------------------------------------------
# Annotation pattern dictionary
# ---------------------------------------------------------------------------

# Pattern -> (category, severity). Patterns are matched case-insensitively
# against literal substrings of the annotation text. Order matters:
# the first match wins, so the more-specific Reject patterns are listed first.
_ANNOTATION_PATTERNS: list[tuple[str, str, str]] = [
    # Reject: hard MPS / spec violation flagged in the annotation
    ("MPS requirement", "Chemistry", "Reject"),
    ("MPS 요건", "Chemistry", "Reject"),
    ("Pb(Lead)", "Chemistry", "Reject"),
    ("delta ferrite", "Microstructure", "Reject"),
    ("N/Al", "Chemistry", "Reject"),
    ("N/AL", "Chemistry", "Reject"),
    ("Cev", "Chemistry", "Question"),
    ("CEF", "Chemistry", "Question"),
    ("재발행", "DocumentError", "ActionRequired"),
    ("re-issue", "DocumentError", "ActionRequired"),
    # ActionRequired: missing test / data
    ("누락", "DocumentError", "ActionRequired"),
    ("missing", "DocumentError", "ActionRequired"),
    ("MT ", "NDE", "ActionRequired"),
    ("PT ", "NDE", "ActionRequired"),
    # Question: ambiguous markings
    ("???", "Other", "Question"),
    ("please explain", "Other", "Question"),
    # Minor: typo-only
    ("오기", "DocumentError", "Minor"),
    ("Typo", "DocumentError", "Minor"),
    ("typo", "DocumentError", "Minor"),
    ("불일치", "DocumentError", "ActionRequired"),
    ("삭제 요청", "DocumentError", "ActionRequired"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items()
            if k not in ("source_file", "anchor", "snippet", "sha256")}


def _csv_evidence(row: dict[str, Any], channel: str) -> dict[str, Any]:
    """Build an evidence entry from a CSV row's own provenance fields."""
    return {
        "channel": channel,
        "source_file": row["source_file"],
        "anchor": row["anchor"],
        "snippet": row["snippet"],
        "sha256": row["sha256"],
    }


def _try_float(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _is_wider_range(r: dict, prev: dict) -> bool:
    """True if row `r` is less restrictive than `prev` (lower min / higher max).

    Used to deduplicate reference rows that share a (grade, element, analysis)
    key but encode different sub-type limits. The widest range wins so a
    base-type material is judged against the base limit, not a stricter variant.
    Provenance stays intact because a single real row is kept (not merged).
    """
    rmin = _try_float(r.get("min"))
    pmin = _try_float(prev.get("min"))
    rmax = _try_float(r.get("max"))
    pmax = _try_float(prev.get("max"))
    rmin = rmin if rmin is not None else float("-inf")
    pmin = pmin if pmin is not None else float("-inf")
    rmax = rmax if rmax is not None else float("inf")
    pmax = pmax if pmax is not None else float("inf")
    return (rmin < pmin) or (rmin == pmin and rmax > pmax)


def _to_mpa(value: float | None, unit: str | None) -> float | None:
    """Normalize a strength limit to MPa.

    Reference rows store strength in MPa or 'ksi'. Some 'ksi' rows actually
    carry the psi figure (e.g. SA-106 '70 000 [485]'), so values > 1000 under a
    ksi label are treated as psi. Without this, MPa cert readings are compared
    against ksi/psi limit numbers and produce false pass/fail verdicts.
    """
    if value is None:
        return None
    u = (unit or "").strip().lower()
    if u == "ksi":
        return value * 0.00689476 if value > 1000 else value * 6.89476
    return value  # MPa (or unitless) — already comparable


def _grade_route(cert_grade: str, routing: list[dict]) -> dict | None:
    """Match cert_grade against routing.cert_grade_pattern regex; return row."""
    if not cert_grade:
        return None
    for row in routing:
        pat = row.get("cert_grade_pattern", "")
        if not pat:
            continue
        try:
            if re.search(pat, cert_grade, flags=re.IGNORECASE):
                return row
        except re.error:
            continue
    return None


def _resolve_grade_keys(routed: dict, cert_grade: str) -> list[str]:
    """Return the list of grade strings to look up in chemistry/mech/HT CSVs.

    The reference CSVs use varied keys: 'SA-335-P92', 'P92', etc. To keep
    rule logic simple we try a small set of candidates derived from the
    routed spec + the bare grade-letter portion of the cert grade.
    """
    candidates: list[str] = []
    asme = (routed.get("asme_spec") or "").strip()
    # Extract trailing 'PXX'/'FXX'/'WPxx' token from cert_grade for short keys.
    tail_match = re.search(r"(P\d+[a-z]?|F\d+[a-z]?|WP[BCR]\b|WP\d+[A-Z0-9]*)", cert_grade or "", re.IGNORECASE)
    tail = tail_match.group(1).upper() if tail_match else ""
    if asme and tail:
        candidates.append(f"{asme}-{tail}")
    if tail:
        candidates.append(tail)
    # Carbon-steel grades carry no P/F/WP tail (e.g. SA-106 Gr C, SA-672 B70).
    # Derive '<asme>-<letter/token>' from a 'Gr(ade) X' or trailing token so the
    # reference CSVs ('SA-106-C', ...) resolve. Without this, A106/A105/A672
    # certs yield no grade keys and skip every deterministic check.
    if not tail:
        gr = re.search(r"Gr(?:ade)?\.?\s*([A-Z]\d*)\b", cert_grade or "", re.IGNORECASE)
        if asme and gr:
            candidates.append(f"{asme}-{gr.group(1).upper()}")
    # Bare-spec grades (e.g. SA-105) key by the spec alone.
    if asme and asme not in candidates:
        candidates.append(asme)
    # MPS_overrides uses 'SA-335-P92' style only
    return candidates


def _mps_overrides_for(grade_keys: list[str], mps_index: dict[str, list[dict]]) -> list[dict]:
    out: list[dict] = []
    for k in grade_keys:
        out.extend(mps_index.get(k, []))
    return out


def _rel_or_abs(path: Path, work_dir: Path) -> str:
    """Return a POSIX-style path relative to work_dir when possible, else absolute.

    source_validator resolves `(work_dir / source_file)`; an absolute source_file
    wins that join, so falling back to absolute keeps provenance valid even when
    the cache lives outside the working directory (e.g. pytest tmp dirs).
    """
    try:
        return str(path.resolve().relative_to(work_dir.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve()).replace("\\", "/")


def _body_evidence(
    page_no: int,
    anchor_path: str,
    value_token: str,
    extracted_rel: str,
    extracted_sha: str,
) -> dict[str, Any]:
    """Body-channel evidence anchored to the Vision-OCR record (extracted.json).

    The raw scanned cert PDF has no extractable text, so the canonical proof of
    what was read is the extracted.json. `value_token` MUST be a json.dumps() of
    the raw extracted value so it appears verbatim in that file (C2/C8).
    """
    return {
        "channel": "body",
        "source_file": extracted_rel,
        "anchor": f"p.{page_no}#{anchor_path}",
        "snippet": value_token,
        "sha256": extracted_sha,
    }


# ---------------------------------------------------------------------------
# Rule families
# ---------------------------------------------------------------------------

# A106 / SA-106 Table 1, Footnote A/B: for each 0.01% that carbon is below the
# specified C max, the Mn max rises 0.06%, capped at 1.35% (Gr.A) / 1.65% (Gr.B,C).
# Mapping: grade -> (specified C max, Mn cap).
_A106_CMN: dict[str, tuple[float, float]] = {
    "SA-106-A": (0.25, 1.35),
    "SA-106-B": (0.30, 1.65),
    "SA-106-C": (0.35, 1.65),
}


def _a106_adjusted_mn_max(c_actual: float | None, grade: str, base_mn_max: float | None) -> float | None:
    """Return the Footnote-adjusted Mn max for an A106/SA-106 grade, else None.

    base_mn_max is the Table 1 Mn max from the reference CSV. When carbon is
    below the specified C max the allowance raises the Mn ceiling (capped).
    """
    info = _A106_CMN.get(grade)
    if info is None or c_actual is None or base_mn_max is None:
        return None
    c_max, cap = info
    if c_actual >= c_max:
        return base_mn_max
    units = int((c_max - c_actual) / 0.01 + 1e-9)  # floor of 0.01% steps
    return min(base_mn_max + units * 0.06, cap)


def _check_chemistry(
    page_extraction: list[dict],
    grade_keys: list[str],
    chem_csv: list[dict],
    mps_csv: list[dict],
    cert_rel_path: str,
    extracted_rel: str,
    extracted_sha: str,
) -> list[dict]:
    findings: list[dict] = []

    # Index code limits by (grade, element, analysis). Some grades carry
    # multiple rows for the same key (e.g. SA-335 P91 Type 1 Cr 8.00-9.50 vs
    # Type 2 Cr 9.00-9.50). Keep the WIDEST (least restrictive) range so a
    # base-type material is not falsely rejected against a stricter sub-type.
    code_idx: dict[tuple[str, str, str], dict] = {}
    for r in chem_csv:
        if r["grade"] not in grade_keys:
            continue
        key = (r["grade"], r["element"], r["analysis"])
        prev = code_idx.get(key)
        if prev is None or _is_wider_range(r, prev):
            code_idx[key] = r

    # Index MPS overrides for grade by element token of parameter
    mps_by_elem: dict[str, dict] = {}
    for r in mps_csv:
        if r["grade"] not in grade_keys:
            continue
        if r["category"] not in ("Chemistry", "TraceElement"):
            continue
        param = r["parameter"]
        m = re.match(r"([A-Za-z]+)(?:_(?:max|min))?", param)
        if not m:
            continue
        elem = m.group(1)
        mps_by_elem[elem] = r

    fid_counter = 0
    for page in page_extraction:
        page_no = page.get("page")
        chem = page.get("chemistry")
        if not chem:
            continue
        analysis = chem.get("analysis_type") or "Heat"
        elements = chem.get("elements") or {}
        # Carbon for this page/analysis — used by the A106 C/Mn footnote.
        _c_payload = elements.get("C") if isinstance(elements.get("C"), dict) else elements.get("c")
        c_actual = _try_float(_c_payload.get("value") if isinstance(_c_payload, dict) else None)
        for elem, payload in elements.items():
            raw_val = payload.get("value") if isinstance(payload, dict) else None
            val = _try_float(raw_val)
            if val is None:
                continue
            unit = (payload.get("unit") if isinstance(payload, dict) else "") or "%"

            body_ev = _body_evidence(
                page_no, f"chemistry.{elem}",
                json.dumps(raw_val),
                extracted_rel, extracted_sha,
            )

            # --- MPS override (takes priority for violation) ---
            mps_row = mps_by_elem.get(elem)
            mps_violation = False
            mps_value: float | None = None
            if mps_row is not None:
                op = mps_row["operator"]
                mps_value = _try_float(mps_row["value"])
                if mps_value is not None:
                    if op == "<=" and val > mps_value:
                        mps_violation = True
                    elif op == ">=" and val < mps_value:
                        mps_violation = True
                    elif op == "range":
                        vmin, vmax = _parse_range(mps_row["value"])
                        if vmin is not None and val < vmin:
                            mps_violation = True
                        if vmax is not None and val > vmax:
                            mps_violation = True

            if mps_violation:
                fid_counter += 1
                op_mps = mps_row["operator"]
                vmin_mps = vmax_mps = None
                if op_mps == "<=":
                    vmax_mps = mps_value
                elif op_mps == ">=":
                    vmin_mps = mps_value
                elif op_mps == "range":
                    vmin_mps, vmax_mps = _parse_range(mps_row["value"])
                findings.append({
                    "finding_id": f"CHEM-MPS-{fid_counter:03d}",
                    "category": "Chemistry",
                    "severity": "Reject",
                    "material_grade": grade_keys[0] if grade_keys else None,
                    "heat_no": None,
                    "cert_pdf": cert_rel_path,
                    "page_ref": f"p.{page_no}",
                    "issue_summary": (
                        f"{elem}={val}{unit} violates MPS limit "
                        f"({mps_row['operator']} {mps_row['value']}{mps_row.get('unit','%') or '%'})"
                    ),
                    "details": (
                        f"MPS-ID {mps_row['mps_id']} for grade {mps_row['grade']} "
                        f"requires {mps_row['parameter']} {mps_row['operator']} {mps_row['value']}; "
                        f"observed {val}{unit} on page {page_no}."
                    ),
                    "structured": {
                        "element": elem,
                        "measured": val,
                        "min": vmin_mps,
                        "max": vmax_mps,
                        "unit": unit,
                        "spec": f"MPS {mps_row['mps_id']}",
                    },
                    "required_action": "Reject lot; request re-test or replacement.",
                    "evidence": [body_ev, _csv_evidence(mps_row, "mps")],
                })
                # Don't double-flag against code if MPS already failed.
                continue

            # --- Code limit (chemistry_limits.csv) ---
            for g in grade_keys:
                key = (g, elem, analysis)
                if key not in code_idx:
                    # try Heat as fallback if analysis differs
                    key = (g, elem, "Heat")
                if key in code_idx:
                    row = code_idx[key]
                    cmin = _try_float(row["min"])
                    cmax = _try_float(row["max"])
                    # A106/SA-106 Footnote: raise the Mn ceiling when C is low.
                    if elem == "Mn":
                        adj = _a106_adjusted_mn_max(c_actual, g, cmax)
                        if adj is not None:
                            cmax = adj
                    violated = False
                    if cmin is not None and val < cmin:
                        violated = True
                    if cmax is not None and val > cmax:
                        violated = True
                    if violated:
                        fid_counter += 1
                        findings.append({
                            "finding_id": f"CHEM-CODE-{fid_counter:03d}",
                            "category": "Chemistry",
                            "severity": "Reject",
                            "material_grade": g,
                            "heat_no": None,
                            "cert_pdf": cert_rel_path,
                            "page_ref": f"p.{page_no}",
                            "issue_summary": (
                                f"{elem}={val}{unit} out of code range "
                                f"[{row['min']}, {row['max']}]"
                            ),
                            "details": (
                                f"{g} {elem} ({analysis}) per code range "
                                f"[{row['min']}, {row['max']}]{row['unit']}; "
                                f"observed {val}{unit}."
                            ),
                            "structured": {
                                "element": elem,
                                "measured": val,
                                "min": cmin,
                                "max": cmax,
                                "unit": unit,
                                "spec": g,
                            },
                            "required_action": "Reject heat; verify ladle analysis vs cert.",
                            "evidence": [body_ev, _csv_evidence(row, "ref_code")],
                        })
                    break  # use the first matching grade key

    return findings


def _parse_range(s: str) -> tuple[float | None, float | None]:
    if not s:
        return (None, None)
    m = re.match(r"\s*([0-9.]+)\s*-\s*([0-9.]+)\s*", s)
    if not m:
        return (None, None)
    return (_try_float(m.group(1)), _try_float(m.group(2)))


def _check_mechanical(
    page_extraction: list[dict],
    grade_keys: list[str],
    mech_csv: list[dict],
    mps_csv: list[dict],
    cert_rel_path: str,
    extracted_rel: str,
    extracted_sha: str,
) -> list[dict]:
    findings: list[dict] = []
    code_idx: dict[tuple[str, str], dict] = {}
    for r in mech_csv:
        if r["grade"] not in grade_keys:
            continue
        key = (r["grade"], r["property"])
        prev = code_idx.get(key)
        # Strength rows may appear in both MPa and ksi; prefer the MPa row so the
        # comparison anchors on SI. When only ksi exists it is converted below.
        if prev is None or (r.get("unit") or "").strip().lower() == "mpa":
            code_idx[key] = r

    mps_idx: dict[str, dict] = {}
    for r in mps_csv:
        if r["grade"] not in grade_keys:
            continue
        if r["category"] != "Mechanical":
            continue
        mps_idx[r["parameter"]] = r

    # Map extraction schema fields -> property key
    prop_map = [
        ("TS_MPa", "TS", "MPa", "TS_min"),
        ("YS_MPa", "YS", "MPa", "YS_min"),
        ("EL_pct", "EL", "%", "EL_min"),
        ("RA_pct", "RA", "%", "RA_min"),
    ]

    fid = 0
    for page in page_extraction:
        page_no = page.get("page")
        mech = page.get("mechanical")
        if not mech:
            continue
        for schema_key, prop, unit, mps_param in prop_map:
            raw_val = mech.get(schema_key)
            val = _try_float(raw_val)
            if val is None:
                continue
            body_ev = _body_evidence(
                page_no, f"mechanical.{prop}",
                json.dumps(raw_val),
                extracted_rel, extracted_sha,
            )
            # MPS first
            if mps_param in mps_idx:
                row = mps_idx[mps_param]
                op = row["operator"]
                vmin = _try_float(row["value"])
                if op == ">=" and vmin is not None and val < vmin:
                    fid += 1
                    findings.append({
                        "finding_id": f"MECH-MPS-{fid:03d}",
                        "category": "Mechanical",
                        "severity": "Reject",
                        "material_grade": grade_keys[0] if grade_keys else None,
                        "heat_no": None,
                        "cert_pdf": cert_rel_path,
                        "page_ref": f"p.{page_no}",
                        "issue_summary": f"{prop}={val}{unit} < MPS min {row['value']}{row['unit']}",
                        "details": f"MPS {row['mps_id']} requires {prop} >= {row['value']}{row['unit']}.",
                        "structured": {
                            "property": prop,
                            "measured": f"{val}{unit}",
                            "spec": f">= {row['value']}{row['unit']} (MPS {row['mps_id']})",
                        },
                        "required_action": "Reject heat; re-test or replace.",
                        "evidence": [body_ev, _csv_evidence(row, "mps")],
                    })
                    continue
            # Code
            for g in grade_keys:
                key = (g, prop)
                if key in code_idx:
                    row = code_idx[key]
                    cmin = _try_float(row["min"])
                    cmax = _try_float(row["max"])
                    # Strength limits may be stored in ksi/psi; the cert reading
                    # is MPa. Normalize the limit to MPa before comparing.
                    if prop in ("TS", "YS"):
                        cmin = _to_mpa(cmin, row.get("unit"))
                        cmax = _to_mpa(cmax, row.get("unit"))
                    if cmin is not None and val < cmin:
                        fid += 1
                        findings.append({
                            "finding_id": f"MECH-CODE-{fid:03d}",
                            "category": "Mechanical",
                            "severity": "Reject",
                            "material_grade": g,
                            "heat_no": None,
                            "cert_pdf": cert_rel_path,
                            "page_ref": f"p.{page_no}",
                            "issue_summary": f"{prop}={val}{unit} < code min {row['min']}{row['unit']}",
                            "details": f"{g} {prop} min per code is {row['min']}{row['unit']}.",
                            "structured": {
                                "property": prop,
                                "measured": f"{val}{unit}",
                                "spec": f"min {row['min']}{row['unit']} ({g})",
                            },
                            "required_action": "Reject heat; re-test.",
                            "evidence": [body_ev, _csv_evidence(row, "ref_code")],
                        })
                    elif cmax is not None and val > cmax:
                        fid += 1
                        findings.append({
                            "finding_id": f"MECH-CODE-{fid:03d}",
                            "category": "Mechanical",
                            "severity": "Reject",
                            "material_grade": g,
                            "heat_no": None,
                            "cert_pdf": cert_rel_path,
                            "page_ref": f"p.{page_no}",
                            "issue_summary": f"{prop}={val}{unit} > code max {row['max']}{row['unit']}",
                            "details": f"{g} {prop} max per code is {row['max']}{row['unit']}.",
                            "structured": {
                                "property": prop,
                                "measured": f"{val}{unit}",
                                "spec": f"max {row['max']}{row['unit']} ({g})",
                            },
                            "required_action": "Reject heat; re-test.",
                            "evidence": [body_ev, _csv_evidence(row, "ref_code")],
                        })
                    break
    return findings


def _check_heat_treatment(
    page_extraction: list[dict],
    grade_keys: list[str],
    ht_csv: list[dict],
    mps_csv: list[dict],
    cert_rel_path: str,
    extracted_rel: str,
    extracted_sha: str,
) -> list[dict]:
    findings: list[dict] = []
    code_idx: dict[tuple[str, str], dict] = {}
    for r in ht_csv:
        if r["grade"] in grade_keys:
            code_idx[(r["grade"], r["stage"])] = r

    # MPS HT entries: parameter like 'Normalizing_temp', operator='range', value='1050-1080'
    mps_ht: list[dict] = [
        r for r in mps_csv
        if r["grade"] in grade_keys and r["category"] == "HeatTreatment"
    ]

    fid = 0
    for page in page_extraction:
        page_no = page.get("page")
        stages = page.get("heat_treatment") or []
        for stage_obj in stages:
            stage = stage_obj.get("stage") or ""
            raw_temp = stage_obj.get("temp_C")
            temp = _try_float(raw_temp)
            if temp is None:
                continue
            body_ev = _body_evidence(
                page_no, f"heat_treatment.{stage}",
                json.dumps(raw_temp),
                extracted_rel, extracted_sha,
            )

            # MPS overrides for HT
            for row in mps_ht:
                param = row["parameter"].lower()
                if stage.lower().replace(" ", "") in param.replace("_", ""):
                    vmin, vmax = _parse_range(row["value"])
                    out_of_range = False
                    if vmin is not None and temp < vmin:
                        out_of_range = True
                    if vmax is not None and temp > vmax:
                        out_of_range = True
                    if out_of_range:
                        fid += 1
                        findings.append({
                            "finding_id": f"HT-MPS-{fid:03d}",
                            "category": "HeatTreatment",
                            "severity": "Reject",
                            "material_grade": grade_keys[0] if grade_keys else None,
                            "heat_no": None,
                            "cert_pdf": cert_rel_path,
                            "page_ref": f"p.{page_no}",
                            "issue_summary": f"{stage} temp={temp}C outside MPS range {row['value']}{row['unit']}",
                            "details": f"MPS {row['mps_id']} requires {row['parameter']} in {row['value']}{row['unit']}.",
                            "structured": {
                                "stage": stage,
                                "measured": f"{temp}C",
                                "spec": f"{row['value']}{row['unit']} (MPS {row['mps_id']})",
                            },
                            "required_action": "Reject lot; re-heat-treat if permitted.",
                            "evidence": [body_ev, _csv_evidence(row, "mps")],
                        })

            # Code limits
            for g in grade_keys:
                key = (g, stage)
                if key in code_idx:
                    row = code_idx[key]
                    cmin = _try_float(row["temp_min_C"])
                    cmax = _try_float(row["temp_max_C"])
                    violated = False
                    if cmin is not None and temp < cmin:
                        violated = True
                    if cmax is not None and temp > cmax:
                        violated = True
                    if violated:
                        fid += 1
                        findings.append({
                            "finding_id": f"HT-CODE-{fid:03d}",
                            "category": "HeatTreatment",
                            "severity": "Reject",
                            "material_grade": g,
                            "heat_no": None,
                            "cert_pdf": cert_rel_path,
                            "page_ref": f"p.{page_no}",
                            "issue_summary": (
                                f"{stage} temp={temp}C outside code range "
                                f"[{row['temp_min_C']}, {row['temp_max_C']}]"
                            ),
                            "details": f"{g} {stage} per code: min={row['temp_min_C']}, max={row['temp_max_C']}.",
                            "structured": {
                                "stage": stage,
                                "measured": f"{temp}C",
                                "spec": f"[{row['temp_min_C']}, {row['temp_max_C']}]C ({g})",
                            },
                            "required_action": "Reject lot; re-heat-treat if permitted.",
                            "evidence": [body_ev, _csv_evidence(row, "ref_code")],
                        })
                    break
    return findings


def _check_nde(
    page_extraction: list[dict],
    grade_keys: list[str],
    material_type: str,
    nde_csv: list[dict],
    cert_rel_path: str,
) -> list[dict]:
    findings: list[dict] = []
    # Required NDE per (grade, material_type, method)
    required_rules: list[dict] = []
    for r in nde_csv:
        if r["grade"] in grade_keys and r["required"] == "Y":
            if material_type and r["material_type"] != material_type:
                continue
            required_rules.append(r)

    if not required_rules:
        return findings

    # Aggregate which methods were performed across all pages
    performed_methods: dict[str, tuple[int, dict]] = {}
    for page in page_extraction:
        nde = page.get("nde")
        if not nde:
            continue
        for method, payload in nde.items():
            if isinstance(payload, dict) and payload.get("performed"):
                performed_methods.setdefault(method.upper(), (page.get("page"), payload))

    fid = 0
    seen: set[str] = set()
    for rule in required_rules:
        method = rule["nde_method"].upper()
        if method in seen:
            continue
        seen.add(method)
        if method not in performed_methods:
            fid += 1
            # A *missing* test cannot be cited from the cert positively, so the
            # provenance rests entirely on the nde_rules CSV row that mandates it.
            first_page = page_extraction[0].get("page") if page_extraction else 1
            severity = "Reject" if material_type == "STOCK" else "ActionRequired"
            findings.append({
                "finding_id": f"NDE-{fid:03d}",
                "category": "NDE",
                "severity": severity,
                "material_grade": rule["grade"],
                "heat_no": None,
                "cert_pdf": cert_rel_path,
                "page_ref": f"p.{first_page}",
                "issue_summary": f"Required {method} for {rule['grade']} ({material_type}) not performed",
                "details": (
                    f"nde_rules.csv requires {method} for grade {rule['grade']} "
                    f"material_type={rule['material_type']} but cert has no record."
                ),
                "structured": {
                    "location": method,
                    "item_name": f"{rule['grade']} ({material_type})",
                    "spec": f"nde_rules.csv: {method} required",
                },
                "required_action": f"Request {method} test report from mill.",
                "evidence": [_csv_evidence(rule, "ref_code")],
            })
    return findings


def _check_annotations(
    annotations: list[dict],
    grade: str | None,
    extracted_path: Path,
    work_dir: Path,
    cache_root: Path,
    case_id: str,
    cert_rel_path: str = "",
) -> list[dict]:
    """Pattern-based extraction from annotation text.

    The evidence for an annotation is the extracted.json itself (because the
    annotation text lives there verbatim and the validator can prove the
    snippet exists). The cert PDF is not used as evidence here because pypdf
    cannot reliably extract annotation overlay text.
    """
    findings: list[dict] = []
    if not extracted_path.exists():
        return findings

    # extracted.json's own provenance
    extracted_rel = _rel_or_abs(extracted_path, work_dir)
    extracted_sha = compute_sha256(extracted_path)

    fid = 0
    seen_snippets: set[str] = set()

    def _classify(text: str) -> tuple[str, str] | None:
        low = text
        for needle, cat, sev in _ANNOTATION_PATTERNS:
            if needle.lower() in low.lower():
                return (cat, sev)
        return None

    for ann in annotations or []:
        text = (ann.get("text") or "").strip()
        if not text:
            continue
        cls = _classify(text)
        if cls is None:
            continue
        cat, sev = cls
        # Snippet must appear in extracted.json — use a short literal slice
        snippet = text if len(text) <= 80 else text[:80]
        if snippet in seen_snippets:
            continue
        seen_snippets.add(snippet)
        page_no = ann.get("page", 1)
        fid += 1
        findings.append({
            "finding_id": f"ANN-{fid:03d}",
            "category": cat,
            "severity": sev,
            "material_grade": grade,
            "heat_no": None,
            "cert_pdf": cert_rel_path,
            "page_ref": f"p.{page_no}",
            "issue_summary": f"Annotation flag: {snippet[:60]}",
            "details": f"PDF annotation (subtype={ann.get('subtype')}) on page {page_no}: {text}",
            "structured": {
                "location": f"page {page_no} annotation",
                "mtc_value": None,
                "correct_value": None,
                "item_name": ann.get("subtype"),
            },
            "required_action": "Address per reviewer comment.",
            "evidence": [{
                "channel": "annotations",
                "source_file": extracted_rel,
                "anchor": f"channels.annotations.items[page={page_no}]",
                "snippet": snippet,
                "sha256": extracted_sha,
            }],
        })

    return findings


# ---------------------------------------------------------------------------
# LLM-authored findings: resolve provenance + merge
# ---------------------------------------------------------------------------

# Canonical schema keys for a finding (also the order the engine emits).
_CANONICAL_KEYS = (
    "finding_id",
    "category",
    "severity",
    "material_grade",
    "heat_no",
    "cert_pdf",
    "page_ref",
    "issue_summary",
    "details",
    "required_action",
    "structured",
    "evidence",
)

# Matching primitives — mirror eval_harness but kept self-contained (C: compare
# must NOT import eval_harness). The regexes/normalizers are intentionally the
# same shape so dedup behaves consistently with how eval scores matches.
_GRADE_NORM_RE = re.compile(r"[^A-Za-z0-9]")
_PAGE_RE = re.compile(r"(?:p\.?\s*)?(\d+)(?:\s*[-~]\s*(\d+))?", re.IGNORECASE)
_KEY_TOKEN_RE = re.compile(r"[A-Za-z]+\d+[A-Za-z]*|\d+(?:\.\d+)?|[A-Za-z]{1,3}\b")
# Word tokenizer incl. Hangul syllables — used as a dedup fallback when neither
# finding exposes a latin/numeric key token (e.g. Korean-only annotations).
_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _summary_jaccard(a: str, b: str) -> float:
    ta = set(_WORD_RE.findall((a or "").lower()))
    tb = set(_WORD_RE.findall((b or "").lower()))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _grade_token(s: str | None) -> str:
    """Collapse a grade string to a comparable token: uppercase alphanumerics.

    'SA-335 P92' -> 'SA335P92', 'P91' -> 'P91', None/'' -> ''.
    """
    if not s:
        return ""
    return _GRADE_NORM_RE.sub("", s).upper()


def _page_ints(s) -> set[int]:
    """Parse 'p.5', 'p.3-4', 'p.5~6', or a bare int/str into a set of page ints."""
    if not s and s != 0:
        return set()
    s = str(s)
    out: set[int] = set()
    for m in _PAGE_RE.finditer(s):
        start = int(m.group(1))
        if m.group(2):
            end = int(m.group(2))
            lo, hi = (start, end) if start <= end else (end, start)
            out.update(range(lo, hi + 1))
        else:
            out.add(start)
    return out


def _key_tokens(s: str | None) -> set[str]:
    """Extract 'key' tokens (numbers + element/grade-like words) for dedup.

    These are the discriminating tokens that two findings about the SAME issue
    share — e.g. a chemical element symbol ('Pb', 'Cr'), a grade ('P92'), or a
    numeric value ('0.004', '5'). Pure prose words are ignored so that two
    differently-worded summaries of the same defect still collide.
    """
    if not s:
        return set()
    out: set[str] = set()
    for tok in _KEY_TOKEN_RE.findall(s):
        t = tok.strip().lower()
        if t:
            out.add(t)
    return out


def _resolve_llm_findings(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
) -> list[dict[str, Any]]:
    """Read <cache>/<case>/<case>_llm_findings.json (if present) and normalize.

    For every evidence entry the engine RESOLVES full provenance deterministically
    (Claude only authors `channel` + optional `cert_stem` + `snippet`):
      - source_file = the extracted.json located by cert_stem (or the case's first
        *_extracted.json), expressed via _rel_or_abs.
      - sha256      = compute_sha256 of that extracted.json.
      - anchor      = 'channels.<channel>'.
      - snippet     = kept verbatim as authored (so source_validator can prove it).

    Returns the RAW (unfiltered) list; provenance filtering happens later in
    compare_case via the shared filter_valid_findings so an invented snippet is
    dropped honestly. Findings whose evidence cannot be resolved to any
    extracted.json get evidence entries with a missing source_file, which the
    validator will then drop.
    """
    case_cache = cache_root / case_id
    llm_path = case_cache / f"{case_id}_llm_findings.json"
    if not llm_path.exists():
        return []

    try:
        with open(llm_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []

    raw_findings = doc.get("findings") or []
    extracted_files = sorted(case_cache.glob("*_extracted.json"))

    # Pre-index extracted.json files by stem (full + the part before
    # '_extracted') so cert_stem may be given with or without the suffix.
    by_stem: dict[str, Path] = {}
    for p in extracted_files:
        full_stem = p.stem  # e.g. 'PU240..._cert_extracted'
        by_stem[full_stem.lower()] = p
        if full_stem.lower().endswith("_extracted"):
            by_stem[full_stem[: -len("_extracted")].lower()] = p
    default_extracted = extracted_files[0] if extracted_files else None

    def _resolve_extracted(cert_stem: str | None) -> Path | None:
        if cert_stem:
            key = str(cert_stem).strip().lower()
            if key in by_stem:
                return by_stem[key]
            # tolerate a caller passing the bare stem of a filename w/ extension
            key2 = Path(key).stem
            if key2 in by_stem:
                return by_stem[key2]
            # substring fallback: first extracted.json whose stem contains it
            for stem, path in by_stem.items():
                if key and key in stem:
                    return path
        return default_extracted

    out: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_findings, start=1):
        if not isinstance(raw, dict):
            continue
        finding_id = raw.get("finding_id") or f"LLM-{i}"
        evidence_in = raw.get("evidence") or []
        resolved_ev: list[dict[str, Any]] = []
        for ev in evidence_in:
            if not isinstance(ev, dict):
                continue
            channel = ev.get("channel") or "annotations"
            snippet = ev.get("snippet") or ""
            ext_path = _resolve_extracted(ev.get("cert_stem"))
            if ext_path is not None and ext_path.exists():
                source_file = _rel_or_abs(ext_path, work_dir)
                sha = compute_sha256(ext_path)
            else:
                # No extracted.json to anchor on; leave source_file empty so the
                # validator drops it (provenance cannot be invented).
                source_file = ""
                sha = ""
            resolved_ev.append({
                "channel": channel,
                "source_file": source_file,
                "anchor": f"channels.{channel}",
                "snippet": snippet,
                "sha256": sha,
            })

        finding = {
            "finding_id": finding_id,
            "category": raw.get("category"),
            "severity": raw.get("severity"),
            "material_grade": raw.get("material_grade"),
            "heat_no": raw.get("heat_no"),
            "cert_pdf": raw.get("cert_pdf"),
            "page_ref": raw.get("page_ref"),
            "issue_summary": raw.get("issue_summary"),
            "details": raw.get("details"),
            "required_action": raw.get("required_action"),
            "structured": raw.get("structured") if isinstance(raw.get("structured"), dict) else {},
            "evidence": resolved_ev,
        }
        out.append(finding)

    return out


# ---------------------------------------------------------------------------
# Dedup (deterministic + resolved-LLM findings)
# ---------------------------------------------------------------------------

def _evidence_richness(f: dict[str, Any]) -> int:
    """Score a finding by how much resolvable evidence it carries.

    Used by _dedup to prefer the finding with richer evidence. Counts evidence
    entries that have all four provenance fields populated.
    """
    score = 0
    for ev in f.get("evidence") or []:
        if all(ev.get(k) for k in ("source_file", "anchor", "snippet", "sha256")):
            score += 1
    return score


def _is_deterministic(f: dict[str, Any]) -> bool:
    """A finding authored by the rule engine (not the LLM resolver)."""
    fid = str(f.get("finding_id") or "")
    return not fid.upper().startswith("LLM-")


def _dedup(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicate findings.

    Two findings are duplicates when they share ALL of:
      - category (exact)
      - normalized material_grade token (_grade_token)
      - overlapping page int-set (_page_ints over page_ref) — if BOTH have pages;
        if either has no page constraint, this dimension is treated as a match
      - a shared key number/element token (_key_tokens over
        issue_summary + structured values), or both empty.

    On collision, keep the finding with richer evidence; tie -> prefer the
    deterministic finding. Stable: kept findings retain input order.
    """
    kept: list[dict[str, Any]] = []
    for f in findings:
        f_cat = f.get("category")
        f_grade = _grade_token(f.get("material_grade"))
        f_pages = _page_ints(f.get("page_ref"))
        f_keys = _key_tokens(f.get("issue_summary"))
        for v in (f.get("structured") or {}).values():
            f_keys |= _key_tokens(str(v) if v is not None else "")

        dup_index = -1
        for idx, g in enumerate(kept):
            # Same category + grade + page-overlap + shared key. NOTE: we do NOT
            # merge the same issue across different pages/certs — GT is
            # inconsistent about that (the same defect on two physical certs is
            # two findings, e.g. case 4 F4-6/F4-7, while the same defect across
            # pages of one cert may be one finding). Merge/split is decided at
            # generation time, not here.
            if g.get("category") != f_cat:
                continue
            if _grade_token(g.get("material_grade")) != f_grade:
                continue
            g_pages = _page_ints(g.get("page_ref"))
            if f_pages and g_pages and not (f_pages & g_pages):
                continue
            g_keys = _key_tokens(g.get("issue_summary"))
            for v in (g.get("structured") or {}).values():
                g_keys |= _key_tokens(str(v) if v is not None else "")
            shared_key = bool(f_keys & g_keys)
            if not shared_key and not f_keys and not g_keys:
                # Neither finding exposes a discriminating latin/numeric token
                # (e.g. Korean-only annotations). Fall back to summary
                # similarity so genuinely distinct issues are NOT merged,
                # while near-identical restatements still collapse.
                shared_key = _summary_jaccard(
                    f.get("issue_summary", ""), g.get("issue_summary", "")
                ) >= 0.6
            if not shared_key:
                continue
            dup_index = idx
            break

        if dup_index < 0:
            kept.append(f)
            continue

        # Collision: decide which to keep.
        existing = kept[dup_index]
        r_new = _evidence_richness(f)
        r_old = _evidence_richness(existing)
        if r_new > r_old:
            kept[dup_index] = f
        elif r_new == r_old:
            # tie -> prefer deterministic
            if _is_deterministic(existing):
                pass  # keep existing
            elif _is_deterministic(f):
                kept[dup_index] = f
            # else both LLM: keep existing (first-seen, stable)
        # else existing richer -> keep existing
    return kept


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compare_case(
    case_id: str,
    work_dir: Path,
    cache_root: Path,
    data_dir: Path,
) -> dict[str, Any]:
    """Run all rule families against a case's extracted.json.

    Returns dict with case_id, findings, dropped_findings, stats. Writes
    findings.json to <cache_root>/<case_id>/.
    """
    case_cache = cache_root / case_id
    case_cache.mkdir(parents=True, exist_ok=True)

    # 1. Load all reference CSVs (provenance-validated).
    routing = load_csv(data_dir / "grade_routing.csv", work_dir)
    chem_csv = load_csv(data_dir / "chemistry_limits.csv", work_dir)
    mech_csv = load_csv(data_dir / "mechanical_limits.csv", work_dir)
    ht_csv = load_csv(data_dir / "heat_treatment.csv", work_dir)
    nde_csv = load_csv(data_dir / "nde_rules.csv", work_dir)
    mps_csv = load_csv(data_dir / "mps_overrides.csv", work_dir)

    # Index MPS by grade for fast scanning
    mps_by_grade: dict[str, list[dict]] = {}
    for r in mps_csv:
        mps_by_grade.setdefault(r["grade"], []).append(r)

    # 2. Find all extracted.json files in case cache
    extracted_files = sorted(case_cache.glob("*_extracted.json"))
    if not extracted_files:
        return {
            "case_id": case_id,
            "findings": [],
            "dropped_findings": [],
            "stats": {"by_category": {}, "by_severity": {}, "total": 0, "dropped": 0},
            "note": "no extracted.json found",
        }

    all_raw_findings: list[dict] = []

    for ext_path in extracted_files:
        with open(ext_path, "r", encoding="utf-8") as f:
            ext = json.load(f)
        cert_file = ext.get("cert_file", "")
        extracted_rel = _rel_or_abs(ext_path, work_dir)
        extracted_sha = compute_sha256(ext_path)
        page_extraction = ext.get("page_extraction") or []
        channels = ext.get("channels") or {}
        annotations = (channels.get("annotations") or {}).get("items") or []

        # Determine grade (most common) and material_type guess
        grades = [
            (p.get("header") or {}).get("grade")
            for p in page_extraction
            if (p.get("header") or {}).get("grade")
        ]
        cert_grade = max(set(grades), key=grades.count) if grades else None

        routed = _grade_route(cert_grade or "", routing)
        if routed is None:
            grade_keys: list[str] = []
        else:
            grade_keys = _resolve_grade_keys(routed, cert_grade or "")

        # Heuristic material_type (default MILL; STOCK if 'STOCK' in remarks)
        material_type = "MILL"
        for p in page_extraction:
            for rk in p.get("remarks") or []:
                if "STOCK" in rk.upper():
                    material_type = "STOCK"
                    break

        # Run rule families
        chem_findings = _check_chemistry(
            page_extraction, grade_keys, chem_csv, mps_csv, cert_file, extracted_rel, extracted_sha,
        )
        mech_findings = _check_mechanical(
            page_extraction, grade_keys, mech_csv, mps_csv, cert_file, extracted_rel, extracted_sha,
        )
        ht_findings = _check_heat_treatment(
            page_extraction, grade_keys, ht_csv, mps_csv, cert_file, extracted_rel, extracted_sha,
        )
        nde_findings = _check_nde(
            page_extraction, grade_keys, material_type, nde_csv, cert_file,
        )
        # NOTE: the crude pattern-based annotation matcher (_check_annotations)
        # is DISABLED in the pipeline. Comment-derived findings now come solely
        # from the optional LLM-authored file (resolved below). The function
        # remains defined for import/back-compat but is no longer invoked.
        # ann_findings = _check_annotations(
        #     annotations, cert_grade, ext_path, work_dir, cache_root,
        #     case_id, cert_file,
        # )

        all_raw_findings.extend(chem_findings)
        all_raw_findings.extend(mech_findings)
        all_raw_findings.extend(ht_findings)
        all_raw_findings.extend(nde_findings)
        # all_raw_findings.extend(ann_findings)  # disabled — see note above

    # 2b. Merge OPTIONAL LLM/hand-authored findings (provenance resolved here),
    #     added BEFORE filtering so they pass the SAME provenance gate.
    llm_findings = _resolve_llm_findings(case_id, work_dir, cache_root)
    all_raw_findings.extend(llm_findings)

    # 3. Provenance-filter (deterministic + resolved-LLM together).
    valid, dropped = filter_valid_findings(all_raw_findings, work_dir)

    # 3b. Dedup the surviving findings (category + grade + page overlap + key
    #     token), preferring richer evidence and, on a tie, the deterministic one.
    valid = _dedup(valid)

    # 4. Stats
    by_cat: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for f in valid:
        by_cat[f["category"]] = by_cat.get(f["category"], 0) + 1
        by_sev[f["severity"]] = by_sev.get(f["severity"], 0) + 1

    result = {
        "case_id": case_id,
        "findings": valid,
        "dropped_findings": dropped,
        "stats": {
            "by_category": by_cat,
            "by_severity": by_sev,
            "total": len(valid),
            "dropped": len(dropped),
        },
    }

    out_path = case_cache / f"{case_id}_findings.json"
    out_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return result


__all__ = [
    "compare_case",
    "_grade_route",
    "_check_chemistry",
    "_check_mechanical",
    "_check_heat_treatment",
    "_check_nde",
    "_check_annotations",
    "_resolve_llm_findings",
    "_dedup",
    "_grade_token",
    "_page_ints",
    "_key_tokens",
]
