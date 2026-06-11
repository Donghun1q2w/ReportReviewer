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
