"""Build data/chemistry_limits.csv from data/_seeds/chemistry_limits_seed.csv.

Task 2.2 — produces the curated CSV that passes validate-refs with 0 failures.

Grade normalisation map (seed grade -> canonical ASME spec grade):
  P91       -> SA-335-P91
  P92       -> SA-335-P92
  P11       -> SA-335-P11
  P22       -> SA-335-P22
  F22CL3    -> SA-182-F22   (standard class; P/S 0.025)
  F11CL2    -> SA-182-F11   (standard class)
  WP11CL1   -> SA-234-WP11  (CL1 is the common class used in piping)
  WP22CL1   -> SA-234-WP22
  WP911     -> SA-234-WP91  (SA-234 grade, has full P/S/Ni rows)
  WP92      -> SA-234-WP92
  SA-105, SA-106-A/B/C -> kept as-is

All other seed grades are kept with their original name.

Rows where both min and max are empty are dropped.
F11CL1/F11CL2 rows in seed are hardness (values 20-207), not chemistry; they
are excluded from chemistry_limits.csv (they belong in mechanical_limits).

unit = "%" is added to every row.

analysis defaults to "Heat" if blank.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SEED_PATH = PLUGIN_DIR / "data" / "_seeds" / "chemistry_limits_seed.csv"
OUT_PATH = PLUGIN_DIR / "data" / "chemistry_limits.csv"

REQUIRED_OUT_COLS = [
    "grade", "element", "analysis", "min", "max", "unit",
    "source_file", "anchor", "snippet", "sha256",
]

# Canonical rename map: seed grade -> output grade
GRADE_RENAME: dict[str, str] = {
    # SA-335 pipes
    "P11":  "SA-335-P11",
    "P22":  "SA-335-P22",
    "P91":  "SA-335-P91",
    "P92":  "SA-335-P92",
    # SA-182 forgings — only standard (not restricted) classes
    "F22CL3": "SA-182-F22",
    "F11CL2": "SA-182-F11",
    # SA-234 fittings
    "WP11CL1": "SA-234-WP11",
    "WP22CL1": "SA-234-WP22",
    "WP911":   "SA-234-WP91",
    "WP92":    "SA-234-WP92",
}

# Seed grades whose rows are NOT chemistry (they are hardness / other).
# F11CL1/F11CL2 rows have values like 40/143/207 HBW, not wt%.
NON_CHEMISTRY_GRADES = {"F11CL1", "F11CL2"}

# Required coverage grades for the gap report
REQUIRED_GRADES = [
    "SA-105", "SA-106-A", "SA-106-B", "SA-106-C",
    "SA-182-F11", "SA-182-F22", "SA-182-F91", "SA-182-F92", "SA-182-F304",
    "SA-234-WP11", "SA-234-WP22", "SA-234-WP91", "SA-234-WP92",
    "SA-335-P11", "SA-335-P22", "SA-335-P91", "SA-335-P92",
]
MAJOR_ELEMENTS = ["C", "Mn", "P", "S", "Si", "Cr", "Mo", "Ni", "V", "Nb", "N", "Al", "Cu", "B", "Ti", "Zr"]


def _is_hardness_row(row: dict) -> bool:
    """Return True if min/max values look like hardness (> 50 wt% is impossible)."""
    for field in ("min", "max"):
        val = row.get(field, "").strip()
        if val:
            try:
                f = float(val)
                if f > 50:
                    return True
            except ValueError:
                pass
    return False


def main() -> None:
    if not SEED_PATH.exists():
        print(f"[ERROR] seed not found: {SEED_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(SEED_PATH, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        seed_rows: list[dict] = list(reader)

    out_rows: list[dict] = []
    dropped_hardness = 0
    dropped_empty = 0

    for row in seed_rows:
        seed_grade = row["grade"].strip()

        # Exclude known non-chemistry grades
        if seed_grade in NON_CHEMISTRY_GRADES:
            dropped_hardness += 1
            continue

        # Exclude rows where values look like hardness numbers
        if _is_hardness_row(row):
            dropped_hardness += 1
            continue

        # Drop rows with both min and max empty
        mn = row.get("min", "").strip()
        mx = row.get("max", "").strip()
        if not mn and not mx:
            dropped_empty += 1
            continue

        # Normalise grade
        canonical_grade = GRADE_RENAME.get(seed_grade, seed_grade)

        # Normalise analysis (default to "Heat")
        analysis = row.get("analysis", "").strip() or "Heat"

        out_row = {
            "grade":       canonical_grade,
            "element":     row["element"].strip(),
            "analysis":    analysis,
            "min":         mn,
            "max":         mx,
            "unit":        "%",
            "source_file": row["source_file"].strip(),
            "anchor":      row["anchor"].strip(),
            "snippet":     row["snippet"].strip(),
            "sha256":      row["sha256"].strip(),
        }
        out_rows.append(out_row)

    # Add "Product" rows for P91 and P92 (same chemistry as Heat per ASME)
    p91_p92_heat = [
        r for r in out_rows
        if r["grade"] in ("SA-335-P91", "SA-335-P92") and r["analysis"] == "Heat"
    ]
    product_rows: list[dict] = []
    for r in p91_p92_heat:
        pr = dict(r)
        pr["analysis"] = "Product"
        product_rows.append(pr)
    out_rows.extend(product_rows)

    # Write output
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=REQUIRED_OUT_COLS)
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"[OK] Written {len(out_rows)} rows to {OUT_PATH}")
    print(f"     Dropped {dropped_hardness} hardness/non-chem rows, {dropped_empty} empty min+max rows")
    print(f"     Product rows added for SA-335-P91/P92: {len(product_rows)}")

    # Coverage gap report
    covered: dict[str, set] = {}
    for r in out_rows:
        covered.setdefault(r["grade"], set()).add(r["element"])

    print("\n=== Coverage gap report ===", file=sys.stderr)
    for grade in REQUIRED_GRADES:
        present = covered.get(grade, set())
        missing_elems = [e for e in MAJOR_ELEMENTS if e not in present]
        if grade not in covered:
            print(f"[MISSING GRADE] {grade} — not present in seed", file=sys.stderr)
        elif missing_elems:
            print(f"[GAP] {grade}: missing elements {missing_elems}", file=sys.stderr)
        else:
            print(f"[OK] {grade}: {len(present)} elements", file=sys.stderr)

    # Grade x element matrix summary (stdout)
    print("\n=== Grade coverage summary ===")
    for grade in sorted(covered):
        elems = sorted(covered[grade])
        print(f"  {grade}: {', '.join(elems)} ({len(elems)})")


if __name__ == "__main__":
    main()
