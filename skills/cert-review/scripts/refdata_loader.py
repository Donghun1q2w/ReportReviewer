"""Load CSV reference data with provenance enforcement (C2/C8).

The loader refuses any CSV row that fails source_validator's checks. Loading is
all-or-nothing per CSV file: if any row is invalid, the file fails to load and
the run aborts. A row listed in source_validator.KNOWN_PROVENANCE_GAPS (a small,
explicit, tracked allowlist for known-corrupted source OCR — see that module's
docstring) loads normally but prints a [WARN] naming the row and the reason, so
a provisional exception is never silent.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any

from .source_validator import (
    MissingProvenanceError,
    REQUIRED_FIELDS,
    validate_csv_row,
)


def load_csv(csv_path: Path, work_dir: Path, *, strict: bool = True) -> list[dict[str, Any]]:
    """Return list of validated rows.

    Each row dict includes the 3 provenance fields plus the data columns.
    If strict=True and any row fails validation, raises MissingProvenanceError.
    A row that only passes via a KNOWN_PROVENANCE_GAPS waiver is still returned
    (its data is used as-is) but logged with [WARN] to stderr, once per row,
    every call — see module docstring.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    waived: list[str] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing_headers = [c for c in REQUIRED_FIELDS if c not in (reader.fieldnames or [])]
        if missing_headers:
            raise MissingProvenanceError(
                f"{csv_path.name}: missing required header columns {missing_headers}"
            )
        for i, row in enumerate(reader, start=2):
            rid = f"{csv_path.name}:L{i}"
            res = validate_csv_row(row, work_dir, rid, csv_name=csv_path.name)
            if res.ok:
                rows.append(row)
                if res.waived:
                    waived.append(f"{rid} ({row.get('grade', '')}/{row.get('element', '')}): {res.waiver_reason}")
            else:
                errors.append(f"  {rid}: {res.reason}")

    if errors and strict:
        raise MissingProvenanceError(
            f"{csv_path.name}: {len(errors)} invalid row(s):\n" + "\n".join(errors)
        )
    if waived:
        print(
            f"[WARN] {csv_path.name}: {len(waived)} row(s) loaded via a "
            f"provisional KNOWN_PROVENANCE_GAPS provenance waiver:",
            file=sys.stderr,
        )
        for note in waived:
            print(f"  {note}", file=sys.stderr)
    return rows


def index_by(rows: list[dict[str, Any]], *keys: str) -> dict[tuple, dict[str, Any]]:
    """Index rows by a composite key (e.g. (grade, element, analysis))."""
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        out[tuple(r.get(k, "") for k in keys)] = r
    return out


__all__ = ["load_csv", "index_by"]
