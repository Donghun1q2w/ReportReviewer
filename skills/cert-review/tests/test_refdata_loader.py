"""Tests for scripts.refdata_loader.load_csv — provenance-gated CSV loading.

Self-contained: fixtures are synthesised under tmp_path, no dataset coupling
(do NOT add this file to conftest._DATASET_COUPLED).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.refdata_loader import load_csv
from scripts.source_validator import MissingProvenanceError

_HEADER = "grade,element,analysis,min,max,unit,source_file,anchor,snippet\n"


def test_load_csv_strict_raises_on_bad_snippet(tmp_path: Path):
    src = tmp_path / "other.md"
    src.write_text("nothing relevant here", encoding="utf-8")
    csv_path = tmp_path / "mechanical_limits.csv"  # not the waived filename
    csv_path.write_text(
        _HEADER + "SA-105,C,Heat,,0.35,%,other.md,Table1#C,0.35 max.\n",
        encoding="utf-8",
    )
    with pytest.raises(MissingProvenanceError):
        load_csv(csv_path, tmp_path)


def test_load_csv_waived_row_included_with_stderr_warning(tmp_path: Path, capsys):
    """A KNOWN_PROVENANCE_GAPS row (chemistry_limits.csv SA-105/C/Heat) loads
    normally despite the missing snippet, but a [WARN] is printed — the
    exception must never be silent."""
    src = tmp_path / "SA-105_SA-105M.md"
    src.write_text("unrelated garbled OCR text", encoding="utf-8")
    csv_path = tmp_path / "chemistry_limits.csv"
    csv_path.write_text(
        _HEADER + "SA-105,C,Heat,,0.35,%,SA-105_SA-105M.md,Table1#C,0.35 max.\n",
        encoding="utf-8",
    )
    rows = load_csv(csv_path, tmp_path)
    assert len(rows) == 1
    assert rows[0]["element"] == "C"
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "chemistry_limits.csv:L2" in err


def test_load_csv_mixed_waived_and_genuine_failure_still_raises(tmp_path: Path):
    """A waived row does not mask an unrelated genuine failure in the same file
    — strict loading still raises when a non-gap-listed row is bad."""
    src = tmp_path / "SA-105_SA-105M.md"
    src.write_text("unrelated garbled OCR text", encoding="utf-8")
    csv_path = tmp_path / "chemistry_limits.csv"
    csv_path.write_text(
        _HEADER
        + "SA-105,C,Heat,,0.35,%,SA-105_SA-105M.md,Table1#C,0.35 max.\n"
        + "SA-105,Ni,Heat,,0.40,%,SA-105_SA-105M.md,Table1#Ni,0.40 max.\n",
        encoding="utf-8",
    )
    with pytest.raises(MissingProvenanceError):
        load_csv(csv_path, tmp_path)


def test_load_csv_no_waiver_no_warning(tmp_path: Path, capsys):
    src, _dummy = tmp_path / "ref.md", None
    src.write_text("Mn 0.30 ~ 0.60", encoding="utf-8")
    csv_path = tmp_path / "mechanical_limits.csv"
    csv_path.write_text(
        _HEADER + "SA-106,Mn,Heat,0.30,0.60,%,ref.md,Table1#Mn,Mn 0.30 ~ 0.60\n",
        encoding="utf-8",
    )
    rows = load_csv(csv_path, tmp_path)
    assert len(rows) == 1
    assert capsys.readouterr().err == ""
