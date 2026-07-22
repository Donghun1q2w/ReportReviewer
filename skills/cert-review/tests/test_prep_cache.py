"""prep-inputs render-cache gate regression tests.

The gate writes a sidecar (<stem>_prep.json) recording pdf_sha256/dpi/
rendered_pages and skips re-rendering when the sidecar matches and every PNG is
present. These tests build a tiny synthetic case (blank pages via pypdf) so they
run without the standard-inspection dataset, then assert: 2nd run skips, --force
forces a re-render, and a changed PDF re-renders.
"""

from __future__ import annotations

import json
from pathlib import Path

from pypdf import PdfWriter

from scripts.prep_inputs import prep_case

CERT_CLEANUP_DIRNAME = "standard inspection Cert cleanup data"


def _write_pdf(path: Path, pages: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=300)
    with open(path, "wb") as fh:
        writer.write(fh)


def _mk_case(work_dir: Path, case_id: str, stem: str, pages: int) -> Path:
    pdf = work_dir / CERT_CLEANUP_DIRNAME / case_id / f"{stem}.pdf"
    _write_pdf(pdf, pages)
    return pdf


def _png_mtimes(png_dir: Path) -> dict[str, float]:
    return {p.name: p.stat().st_mtime_ns for p in png_dir.glob("*.png")}


def test_first_run_renders_and_writes_sidecar(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)

    summary = prep_case("9", work, cache, dpi=100)
    cert = summary["certs"][0]
    assert cert["rendered"] is True
    assert cert["png_count"] == 2

    sidecar = cache / "9" / "certA_prep.json"
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["dpi"] == 100
    assert meta["rendered_pages"] == 2
    assert meta["backfilled"] is False
    assert len(meta["pdf_sha256"]) == 64


def test_second_run_skips_render(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)

    prep_case("9", work, cache, dpi=100)
    before = _png_mtimes(cache / "9" / "png")

    summary = prep_case("9", work, cache, dpi=100)
    cert = summary["certs"][0]
    assert cert["rendered"] is False
    assert any("[skip] certA unchanged" in n for n in summary["notes"])

    after = _png_mtimes(cache / "9" / "png")
    assert before == after, "PNGs must not be rewritten on a cache hit"


def test_force_rerenders(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)

    prep_case("9", work, cache, dpi=100)
    summary = prep_case("9", work, cache, dpi=100, force=True)
    assert summary["certs"][0]["rendered"] is True


def test_changed_pdf_rerenders(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)
    prep_case("9", work, cache, dpi=100)

    # Replace the PDF with a different page count -> sha256 changes.
    _mk_case(work, "9", "certA", 3)
    summary = prep_case("9", work, cache, dpi=100)
    cert = summary["certs"][0]
    assert cert["rendered"] is True
    assert cert["png_count"] == 3

    meta = json.loads((cache / "9" / "certA_prep.json").read_text(encoding="utf-8"))
    assert meta["rendered_pages"] == 3


def test_dpi_change_rerenders(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 1)
    prep_case("9", work, cache, dpi=100)

    summary = prep_case("9", work, cache, dpi=150)
    assert summary["certs"][0]["rendered"] is True
    meta = json.loads((cache / "9" / "certA_prep.json").read_text(encoding="utf-8"))
    assert meta["dpi"] == 150


def test_missing_png_forces_rerender(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)
    prep_case("9", work, cache, dpi=100)

    # Delete one rendered PNG -> incomplete set -> must re-render.
    (cache / "9" / "png" / "certA_p02.png").unlink()
    summary = prep_case("9", work, cache, dpi=100)
    assert summary["certs"][0]["rendered"] is True


def _write_alignment_records(case_cache: Path, stem: str) -> tuple[Path, Path]:
    from scripts.align_inputs import alignment_path, orientation_path

    opath = orientation_path(case_cache, stem)
    apath = alignment_path(case_cache, stem)
    opath.write_text(json.dumps({"pages": {"1": 90}}), encoding="utf-8")
    apath.write_text(json.dumps({"applied": {"1": 90}}), encoding="utf-8")
    return opath, apath


def _fill_extraction(cache: Path, case_id: str, stem: str, pages: list[int]) -> None:
    path = cache / case_id / f"{stem}_extracted.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["page_extraction"] = [{"page": p} for p in pages]
    data["channels"]["body"]["pages"] = list(pages)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_render_stamps_alignment_pending_and_align_clears_it(tmp_path: Path):
    from scripts.align_inputs import align_case, orientation_path

    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 1)
    prep_case("9", work, cache, dpi=100)

    sidecar = json.loads((cache / "9" / "certA_prep.json").read_text(encoding="utf-8"))
    assert sidecar["rotations"] is None, "fresh render must mark alignment pending"

    orientation_path(cache / "9", "certA").write_text(
        json.dumps({"pages": {"1": 0}}), encoding="utf-8"
    )
    align_case("9", cache)
    sidecar = json.loads((cache / "9" / "certA_prep.json").read_text(encoding="utf-8"))
    assert sidecar["rotations"] == {}, "align-inputs must clear the pending marker"


def test_force_rerender_goes_stale_until_realigned(tmp_path: Path):
    """--force on an UNCHANGED PDF must not stay 'fresh' with sideways PNGs
    (review finding: aligned-space artifacts vs re-rendered pixels)."""
    from scripts.align_inputs import align_case, orientation_path
    from scripts.extraction_check import cache_status_case

    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 1)
    prep_case("9", work, cache, dpi=100)
    orientation_path(cache / "9", "certA").write_text(
        json.dumps({"pages": {"1": 0}}), encoding="utf-8"
    )
    align_case("9", cache)
    _fill_extraction(cache, "9", "certA", [1])

    agg = cache_status_case("9", cache, work)
    assert agg["certs"][0]["status"] == "fresh"

    prep_case("9", work, cache, dpi=100, force=True)  # same sha256, new pixels
    _fill_extraction(cache, "9", "certA", [1])  # extraction preserved by prep
    agg = cache_status_case("9", cache, work)
    assert agg["certs"][0]["status"] == "stale"
    assert agg["certs"][0]["alignment_pending"] is True


def test_shrinking_pdf_purges_stale_page_artifacts(tmp_path: Path):
    """Replacing the PDF with fewer pages must not leave phantom page PNGs,
    tiles, or contact sheets from the previous render."""
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 3)
    prep_case("9", work, cache, dpi=100)

    tiles = cache / "9" / "tiles"
    orient = cache / "9" / "orient"
    tiles.mkdir()
    orient.mkdir()
    (tiles / "certA_p03_r0c0.png").write_bytes(b"x")
    (orient / "certA__sheet01.png").write_bytes(b"x")

    _mk_case(work, "9", "certA", 2)  # shrink 3 -> 2 pages
    summary = prep_case("9", work, cache, dpi=100)
    assert summary["certs"][0]["png_count"] == 2
    assert not (cache / "9" / "png" / "certA_p03.png").exists(), "phantom page survived"
    assert not (tiles / "certA_p03_r0c0.png").exists(), "stale tile survived"
    assert not (orient / "certA__sheet01.png").exists(), "stale sheet survived"


def test_rerender_deletes_doctype_and_classify_sheets(tmp_path: Path):
    """T-6: a re-render (changed PDF) must drop the stale <stem>_doctype.json
    and the classify/ contact sheets so a classification cannot outlive its
    pixels."""
    from scripts.doctype import doctype_path

    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)
    prep_case("9", work, cache, dpi=100)

    case_cache = cache / "9"
    dt = doctype_path(case_cache, "certA")
    dt.write_text(json.dumps({"pages": {"1": "MTC_FINISHED"}}), encoding="utf-8")
    classify = case_cache / "classify"
    classify.mkdir()
    (classify / "certA__sheet01.png").write_bytes(b"x")

    _mk_case(work, "9", "certA", 3)  # sha256 changes -> re-render
    summary = prep_case("9", work, cache, dpi=100)
    assert summary["certs"][0]["rendered"] is True
    assert not dt.exists(), "stale doctype sidecar survived a re-render"
    assert not (classify / "certA__sheet01.png").exists(), "stale classify sheet survived"


def test_cache_hit_preserves_doctype(tmp_path: Path):
    """T-6: a cache HIT (unchanged PDF) must keep the doctype sidecar."""
    from scripts.doctype import doctype_path

    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 2)
    prep_case("9", work, cache, dpi=100)

    dt = doctype_path(cache / "9", "certA")
    dt.write_text(json.dumps({"pages": {"1": "MTC_FINISHED"}}), encoding="utf-8")

    summary = prep_case("9", work, cache, dpi=100)
    assert summary["certs"][0]["rendered"] is False
    assert dt.exists(), "cache hit must keep the doctype classification"


def test_cache_hit_preserves_alignment_records(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 1)
    prep_case("9", work, cache, dpi=100)
    opath, apath = _write_alignment_records(cache / "9", "certA")

    summary = prep_case("9", work, cache, dpi=100)
    assert summary["certs"][0]["rendered"] is False
    assert opath.exists() and apath.exists(), "cache hit must keep aligned state"


def test_rerender_resets_alignment_records(tmp_path: Path):
    work = tmp_path / "work"
    cache = tmp_path / "cache"
    _mk_case(work, "9", "certA", 1)
    prep_case("9", work, cache, dpi=100)
    opath, apath = _write_alignment_records(cache / "9", "certA")

    # Changed PDF -> sha256 mismatch -> re-render -> fresh (unaligned) PNGs.
    _mk_case(work, "9", "certA", 2)
    summary = prep_case("9", work, cache, dpi=100)
    assert summary["certs"][0]["rendered"] is True
    assert not opath.exists() and not apath.exists(), (
        "stale rotation records must not survive a re-render"
    )
