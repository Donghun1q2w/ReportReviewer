"""Load CSV reference data with provenance enforcement (C2/C8).

The loader refuses any CSV row that fails source_validator's checks. Loading is
all-or-nothing per CSV file: if any row is invalid, the file fails to load and
the run aborts.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .source_validator import (
    MissingProvenanceError,
    REQUIRED_FIELDS,
    validate_csv_row,
)


def load_csv(csv_path: Path, work_dir: Path, *, strict: bool = True) -> list[dict[str, Any]]:
    """Return list of validated rows.

    Each row dict includes the 4 provenance fields plus the data columns.
    If strict=True and any row fails validation, raises MissingProvenanceError.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing_headers = [c for c in REQUIRED_FIELDS if c not in (reader.fieldnames or [])]
        if missing_headers:
            raise MissingProvenanceError(
                f"{csv_path.name}: missing required header columns {missing_headers}"
            )
        for i, row in enumerate(reader, start=2):
            rid = f"{csv_path.name}:L{i}"
            res = validate_csv_row(row, work_dir, rid)
            if res.ok:
                rows.append(row)
            else:
                errors.append(f"  {rid}: {res.reason}")

    if errors and strict:
        raise MissingProvenanceError(
            f"{csv_path.name}: {len(errors)} invalid row(s):\n" + "\n".join(errors)
        )
    return rows


def index_by(rows: list[dict[str, Any]], *keys: str) -> dict[tuple, dict[str, Any]]:
    """Index rows by a composite key (e.g. (grade, element, analysis))."""
    out: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        out[tuple(r.get(k, "") for k in keys)] = r
    return out


__all__ = ["load_csv", "index_by"]
