"""Deployment portability: skip dataset-coupled integration tests when the
standard-inspection dataset is not present (e.g. a fresh clone of this repo).

Portable unit tests (test_no_python_ocr, test_source_validator) always run.
The three integration tests below read the dataset (GT_Answer.md, ref_code/MPS
source files for provenance); point CERT_REVIEW_WORKDIR at the dataset to run
them, otherwise they are skipped.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Default fallback is the original testbed path; overridable via env so the
# suite runs anywhere the dataset is mounted.
_DATASET = Path(
    os.environ.get(
        "CERT_REVIEW_WORKDIR",
        r"D:\001_Work\2026\033_성적서 검토\Certification_Examine\testbed\1. Standard Inspection",
    )
)

_DATASET_COUPLED = {
    "test_compare_engine.py",
    "test_eval_harness.py",
}


def pytest_collection_modifyitems(config, items):
    if _DATASET.exists():
        return
    skip = pytest.mark.skip(
        reason="standard-inspection dataset not present; set CERT_REVIEW_WORKDIR to run"
    )
    for item in items:
        if Path(str(item.fspath)).name in _DATASET_COUPLED:
            item.add_marker(skip)
