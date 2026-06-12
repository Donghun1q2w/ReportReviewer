"""Tests for scripts.merge_parts — chunked fragment merge into extracted.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.merge_parts import discover_stems, fragment_stem, merge_case, merge_stem


def _entry(page: int, grade: str = "P11") -> dict:
    return {
        "page": page,
        "header": {"grade": grade},
        "remarks": [],
        "confidence": "high",
    }


def _setup_case(tmp_path: Path, case_id: str = "99") -> Path:
    case_cache = tmp_path / case_id
    parts = case_cache / "parts"
    parts.mkdir(parents=True)
    skeleton = {
        "schema_version": "2.0",
        "case_id": case_id,
        "cert_file": "standard inspection Cert cleanup data/99/big_cert.pdf",
        "cert_sha256": "0" * 64,
        "extracted_at": None,
        "channels": {"body": {"engine": "claude-vision", "pages": []}},
        "page_extraction": [],
    }
    (case_cache / "big_cert_extracted.json").write_text(
        json.dumps(skeleton), encoding="utf-8"
    )
    return case_cache


def _write_fragment(case_cache: Path, name: str, pages: list[int], stem: str = "big_cert") -> None:
    frag = {
        "stem": stem,
        "pages_covered": pages,
        "page_extraction": [_entry(p) for p in pages],
    }
    (case_cache / "parts" / name).write_text(json.dumps(frag), encoding="utf-8")


def test_merge_fills_skeleton_and_preserves_toplevel(tmp_path):
    case_cache = _setup_case(tmp_path)
    _write_fragment(case_cache, "big_cert__p001-002.json", [1, 2])
    _write_fragment(case_cache, "big_cert__p003-004.json", [3, 4])

    result = merge_stem(case_cache, "big_cert", extracted_at="2026-06-12T00:00:00+00:00")

    assert result["pages"] == [1, 2, 3, 4]
    assert result["issues"] == []

    merged = json.loads((case_cache / "big_cert_extracted.json").read_text(encoding="utf-8"))
    assert merged["cert_sha256"] == "0" * 64  # skeleton preserved
    assert merged["channels"]["body"]["pages"] == [1, 2, 3, 4]
    assert [e["page"] for e in merged["page_extraction"]] == [1, 2, 3, 4]
    assert merged["extracted_at"] == "2026-06-12T00:00:00+00:00"


def test_duplicate_page_later_fragment_wins_with_issue(tmp_path):
    case_cache = _setup_case(tmp_path)
    _write_fragment(case_cache, "big_cert__p001-002.json", [1, 2])
    frag = {
        "stem": "big_cert",
        "pages_covered": [2, 3],
        "page_extraction": [_entry(2, grade="P22"), _entry(3)],
    }
    (case_cache / "parts" / "big_cert__p002-003.json").write_text(
        json.dumps(frag), encoding="utf-8"
    )

    result = merge_stem(case_cache, "big_cert")

    assert result["pages"] == [1, 2, 3]
    assert any("duplicated" in i for i in result["issues"])
    merged = json.loads((case_cache / "big_cert_extracted.json").read_text(encoding="utf-8"))
    page2 = next(e for e in merged["page_extraction"] if e["page"] == 2)
    assert page2["header"]["grade"] == "P22"  # later fragment wins


def test_missing_skeleton_raises(tmp_path):
    case_cache = tmp_path / "99"
    (case_cache / "parts").mkdir(parents=True)
    _write_fragment(case_cache, "big_cert__p001-002.json", [1, 2])
    with pytest.raises(FileNotFoundError, match="skeleton"):
        merge_stem(case_cache, "big_cert")


def test_no_fragments_raises(tmp_path):
    case_cache = _setup_case(tmp_path)
    with pytest.raises(FileNotFoundError, match="no fragments"):
        merge_stem(case_cache, "other_cert")


def test_discover_stems_and_merge_case(tmp_path):
    case_cache = _setup_case(tmp_path)
    _write_fragment(case_cache, "big_cert__p001-002.json", [1, 2])

    assert discover_stems(case_cache / "parts") == ["big_cert"]
    assert fragment_stem(Path("big_cert__p001-002.json")) == "big_cert"

    summary = merge_case("99", tmp_path)
    assert summary["case_id"] == "99"
    assert len(summary["stems"]) == 1
    assert summary["stems"][0]["pages"] == [1, 2]
