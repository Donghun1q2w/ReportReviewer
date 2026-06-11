"""extraction completeness gate regression tests (Phase 2.5)."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.extraction_check import check_case, check_cases


def _mk_case(tmp_path: Path, case_id: str, stem: str, pages: int) -> Path:
    case_dir = tmp_path / case_id
    png_dir = case_dir / "png"
    png_dir.mkdir(parents=True)
    for p in range(1, pages + 1):
        (png_dir / f"{stem}_p{p:02d}.png").write_bytes(b"\x89PNG")
    return case_dir


def _write_extracted(case_dir: Path, stem: str, pages: list[int], body_pages: list[int] | None = None) -> None:
    data = {
        "schema_version": "2.0",
        "case_id": case_dir.name,
        "cert_file": f"{stem}.pdf",
        "cert_sha256": "0" * 64,
        "channels": {"body": {"engine": "claude-vision", "pages": body_pages if body_pages is not None else pages}},
        "page_extraction": [{"page": p, "header": {}} for p in pages],
    }
    (case_dir / f"{stem}_extracted.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_no_pngs_fails(tmp_path: Path):
    (tmp_path / "9" / "png").mkdir(parents=True)
    res = check_case("9", tmp_path)
    assert not res["ok"]
    assert any("no rendered page PNGs" in i for i in res["issues"])


def test_missing_extracted_json_fails(tmp_path: Path):
    _mk_case(tmp_path, "9", "certA", 2)
    res = check_case("9", tmp_path)
    assert not res["ok"]
    assert any("extracted.json missing" in i for c in res["certs"] for i in c["issues"])


def test_empty_page_extraction_fails(tmp_path: Path):
    case_dir = _mk_case(tmp_path, "9", "certA", 2)
    _write_extracted(case_dir, "certA", [])
    res = check_case("9", tmp_path)
    assert not res["ok"]
    assert any("EMPTY" in i for c in res["certs"] for i in c["issues"])


def test_partial_coverage_fails_and_names_missing_pages(tmp_path: Path):
    case_dir = _mk_case(tmp_path, "9", "certA", 3)
    _write_extracted(case_dir, "certA", [1, 2])
    res = check_case("9", tmp_path)
    assert not res["ok"]
    cert = res["certs"][0]
    assert cert["missing_pages"] == [3]


def test_full_coverage_passes(tmp_path: Path):
    case_dir = _mk_case(tmp_path, "9", "certA", 3)
    _write_extracted(case_dir, "certA", [1, 2, 3])
    res = check_case("9", tmp_path)
    assert res["ok"], res


def test_body_pages_mismatch_fails(tmp_path: Path):
    case_dir = _mk_case(tmp_path, "9", "certA", 2)
    _write_extracted(case_dir, "certA", [1, 2], body_pages=[1])
    res = check_case("9", tmp_path)
    assert not res["ok"]
    assert any("channels.body.pages" in i for c in res["certs"] for i in c["issues"])


def test_zoom_crops_ignored(tmp_path: Path):
    case_dir = _mk_case(tmp_path, "9", "certA", 2)
    (case_dir / "png" / "zoom_p10_nde.png").write_bytes(b"\x89PNG")
    (case_dir / "png" / "c_chem.png").write_bytes(b"\x89PNG")
    _write_extracted(case_dir, "certA", [1, 2])
    res = check_case("9", tmp_path)
    assert res["ok"], res
    assert res["certs"][0]["png_pages"] == 2


def test_multi_cert_and_aggregate(tmp_path: Path):
    case_dir = _mk_case(tmp_path, "9", "certA", 2)
    for p in (1,):
        (case_dir / "png" / f"certB_p{p:02d}.png").write_bytes(b"\x89PNG")
    _write_extracted(case_dir, "certA", [1, 2])
    _write_extracted(case_dir, "certB", [1])
    _mk_case(tmp_path, "10", "certC", 1)  # no extracted.json -> fail

    agg = check_cases(["9", "10"], tmp_path)
    assert not agg["ok"]
    assert agg["n_failed"] == 1
    ok_by_case = {c["case_id"]: c["ok"] for c in agg["cases"]}
    assert ok_by_case == {"9": True, "10": False}
