"""extraction completeness gate regression tests (Phase 2.5).

Also covers the cache-status freshness classifier (missing/stale/legacy/fresh)
that reuses the same coverage logic.
"""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter

from scripts.extraction_check import (
    cache_status_case,
    check_case,
    check_cases,
)
from scripts.prep_inputs import prep_case
from scripts.source_validator import compute_sha256

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"


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


# --- cache-status freshness classifier --------------------------------------

def _write_pdf(path: Path, pages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    with open(path, "wb") as fh:
        writer.write(fh)


def _build_rendered_case(tmp_path: Path, case_id: str, stem: str, pages: int) -> tuple[Path, Path, Path]:
    """Render a synthetic case via prep_case; return (work, cache, cert_pdf)."""
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    cert_pdf = work / CERT_CLEANUP_DIRNAME / case_id / f"{stem}.pdf"
    _write_pdf(cert_pdf, pages)
    prep_case(case_id, work, cache, dpi=100)
    return work, cache, cert_pdf


def _fill_extraction(cache: Path, case_id: str, stem: str, work: Path, pages: list[int]) -> None:
    """Overwrite the skeleton with a complete extraction (cert_file resolvable)."""
    case_cache = cache / case_id
    cert_rel = f"{CERT_CLEANUP_DIRNAME}/{case_id}/{stem}.pdf"
    cert_pdf = work / CERT_CLEANUP_DIRNAME / case_id / f"{stem}.pdf"
    data = {
        "schema_version": "2.0",
        "case_id": case_id,
        "cert_file": cert_rel,
        "cert_sha256": compute_sha256(cert_pdf),
        "channels": {"body": {"engine": "claude-vision", "pages": pages}},
        "page_extraction": [{"page": p, "header": {}} for p in pages],
    }
    (case_cache / f"{stem}_extracted.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def _mark_aligned(cache: Path, case_id: str, stem: str) -> None:
    """Simulate a completed Phase 1.5: align-inputs replaces the render's
    rotations=None marker with the (possibly empty) applied map."""
    sidecar = cache / case_id / f"{stem}_prep.json"
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    meta["rotations"] = {}
    sidecar.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_cache_status_fresh(tmp_path: Path):
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 2)
    _fill_extraction(cache, "9", "certA", work, [1, 2])
    _mark_aligned(cache, "9", "certA")
    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "fresh", res
    assert res["counts"]["fresh"] == 1


def test_cache_status_stale_while_alignment_pending(tmp_path: Path):
    """A render whose Phase 1.5 has not run yet (rotations=None) is never
    fresh, even with a complete extraction (--force rerun hole)."""
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 2)
    _fill_extraction(cache, "9", "certA", work, [1, 2])
    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "stale", res
    assert res["certs"][0]["alignment_pending"] is True


def test_cache_status_missing_when_extraction_empty(tmp_path: Path):
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 2)
    # Skeleton has empty page_extraction (prep_case writes it that way).
    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "missing", res


def test_cache_status_missing_when_json_absent(tmp_path: Path):
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 2)
    (cache / "9" / "certA_extracted.json").unlink()
    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "missing", res


def test_cache_status_stale_when_pdf_changes(tmp_path: Path):
    work, cache, cert_pdf = _build_rendered_case(tmp_path, "9", "certA", 2)
    _fill_extraction(cache, "9", "certA", work, [1, 2])
    # Mutate the source PDF so its sha256 diverges from the sidecar.
    _write_pdf(cert_pdf, 3)
    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "stale", res


def test_cache_status_stale_when_png_missing(tmp_path: Path):
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 2)
    _fill_extraction(cache, "9", "certA", work, [1, 2])
    (cache / "9" / "png" / "certA_p02.png").unlink()
    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "stale", res


def test_cache_status_legacy_backfills_sidecar(tmp_path: Path):
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 2)
    _fill_extraction(cache, "9", "certA", work, [1, 2])
    # Remove the sidecar -> a complete extraction with no sidecar is 'legacy'.
    (cache / "9" / "certA_prep.json").unlink()

    res = cache_status_case("9", cache, work)
    assert res["certs"][0]["status"] == "legacy", res
    assert res["certs"][0]["backfilled"] is True

    sidecar = cache / "9" / "certA_prep.json"
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["backfilled"] is True
    assert meta["dpi"] is None
    assert len(meta["pdf_sha256"]) == 64

    # After backfill, the same case reads as fresh.
    res2 = cache_status_case("9", cache, work)
    assert res2["certs"][0]["status"] == "fresh", res2


def test_cache_status_legacy_no_backfill_when_disabled(tmp_path: Path):
    work, cache, _ = _build_rendered_case(tmp_path, "9", "certA", 1)
    _fill_extraction(cache, "9", "certA", work, [1])
    (cache / "9" / "certA_prep.json").unlink()

    res = cache_status_case("9", cache, work, backfill=False)
    assert res["certs"][0]["status"] == "legacy", res
    assert not (cache / "9" / "certA_prep.json").exists()
