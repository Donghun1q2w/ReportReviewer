"""Pure domain helpers for grade routing and reference-limit normalization.

The deterministic finding orchestration (compare_case + the per-category
_check_* rule families + the findings.json renderer) has been removed in favor
of the LLM compliance path (compliance_report.build_compliance_report). What
remains here are the small, side-effect-free domain helpers that encode
ASME/ASTM rules and are still useful (and unit-tested) on their own:

    _grade_route          — match a cert grade against grade_routing.csv rows.
    _resolve_grade_keys   — derive the chemistry/mech/HT CSV lookup keys.
    _a106_adjusted_mn_max — A106/SA-106 Table 1 C/Mn footnote (Mn ceiling).
    _to_mpa               — normalize a strength limit (MPa / ksi / psi) to MPa.
    _is_wider_range       — pick the least-restrictive of two reference rows.

These functions perform NO file I/O, NO LLM/OCR calls, and read NO ground-truth.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Primitive
# ---------------------------------------------------------------------------

def _try_float(x: Any) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Reference-row helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Grade routing
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# A106 / SA-106 Table 1 C/Mn footnote
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


__all__ = [
    "_grade_route",
    "_resolve_grade_keys",
    "_a106_adjusted_mn_max",
    "_to_mpa",
    "_is_wider_range",
]
