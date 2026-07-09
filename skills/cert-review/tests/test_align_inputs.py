"""Tests for align_inputs — deterministic page-rotation application.

Self-contained: synthesises marker-pixel PNGs with Pillow. The marker pixel
pins the rotation DIRECTION (clockwise semantics), not just the size swap.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from scripts.align_inputs import (
    align_case,
    alignment_path,
    applied_rotations,
    orientation_path,
    page_rotation,
    rotate_upright,
)


def _marker_png(path: Path, size=(10, 20)) -> None:
    """White image with a single black marker pixel at the top-left (0, 0)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    im = Image.new("RGB", size, "white")
    im.putpixel((0, 0), (0, 0, 0))
    im.save(path)


def _black_at(png: Path) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return (image size, position of the single black pixel)."""
    with Image.open(png) as im:
        im = im.convert("RGB")
        w, h = im.size
        for y in range(h):
            for x in range(w):
                if im.getpixel((x, y)) == (0, 0, 0):
                    return (w, h), (x, y)
    raise AssertionError(f"no black marker pixel in {png}")


def _write_orientation(case_cache: Path, stem: str, pages: dict) -> None:
    case_cache.mkdir(parents=True, exist_ok=True)
    orientation_path(case_cache, stem).write_text(
        json.dumps({"schema_version": "1.0", "stem": stem, "pages": pages}),
        encoding="utf-8",
    )


# --- rotate_upright (clockwise semantics) ------------------------------------

def test_rotate_upright_90_cw():
    im = Image.new("RGB", (10, 20), "white")
    im.putpixel((0, 0), (0, 0, 0))
    out = rotate_upright(im, 90)
    assert out.size == (20, 10)
    assert out.getpixel((19, 0)) == (0, 0, 0)  # top-left -> top-right under CW


def test_rotate_upright_180():
    im = Image.new("RGB", (10, 20), "white")
    im.putpixel((0, 0), (0, 0, 0))
    out = rotate_upright(im, 180)
    assert out.size == (10, 20)
    assert out.getpixel((9, 19)) == (0, 0, 0)


def test_rotate_upright_270_cw():
    im = Image.new("RGB", (10, 20), "white")
    im.putpixel((0, 0), (0, 0, 0))
    out = rotate_upright(im, 270)
    assert out.size == (20, 10)
    assert out.getpixel((0, 9)) == (0, 0, 0)  # top-left -> bottom-left under CCW-90


def test_rotate_upright_0_is_identity():
    im = Image.new("RGB", (10, 20), "white")
    assert rotate_upright(im, 0) is im


def test_rotate_upright_invalid_angle():
    with pytest.raises(ValueError):
        rotate_upright(Image.new("RGB", (4, 4)), 45)


# --- align_case ---------------------------------------------------------------

def test_align_rotates_only_flagged_pages(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    png_dir = case_cache / "png"
    _marker_png(png_dir / "certA_p01.png")
    _marker_png(png_dir / "certA_p02.png")
    _write_orientation(case_cache, "certA", {"1": 90, "2": 0})

    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert s["rotated"] == 1 and s["issues"] == []

    size, pos = _black_at(png_dir / "certA_p01.png")
    assert size == (20, 10) and pos == (19, 0)  # rotated CW
    size, pos = _black_at(png_dir / "certA_p02.png")
    assert size == (10, 20) and pos == (0, 0)  # untouched

    record = json.loads(alignment_path(case_cache, "certA").read_text(encoding="utf-8"))
    assert record["applied"] == {"1": 90}
    assert page_rotation(case_cache, "certA", 1) == 90
    assert page_rotation(case_cache, "certA", 2) == 0
    assert applied_rotations(case_cache, "certA") == {1: 90}


def test_align_is_idempotent(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    png_dir = case_cache / "png"
    _marker_png(png_dir / "certA_p01.png")
    _write_orientation(case_cache, "certA", {"1": 90})

    align_case("9", cache_root)
    first = (png_dir / "certA_p01.png").read_bytes()

    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert s["rotated"] == 0
    assert s["skipped_already_applied"] == 1
    assert (png_dir / "certA_p01.png").read_bytes() == first, "double rotation!"


def test_conflicting_redetection_is_ignored_with_issue(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    _marker_png(case_cache / "png" / "certA_p01.png")
    _write_orientation(case_cache, "certA", {"1": 90})
    align_case("9", cache_root)

    # A second detection pass on the (now upright) render says 180 — must not apply.
    _write_orientation(case_cache, "certA", {"1": 180})
    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert s["rotated"] == 0
    assert any("ignored" in i for i in s["issues"])
    size, pos = _black_at(case_cache / "png" / "certA_p01.png")
    assert size == (20, 10) and pos == (19, 0)  # still the first (90deg) state


def test_invalid_rotation_values_are_skipped(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    _marker_png(case_cache / "png" / "certA_p01.png")
    _write_orientation(case_cache, "certA", {"1": 45, "2": "east"})

    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert s["rotated"] == 0
    assert len(s["issues"]) == 2
    size, pos = _black_at(case_cache / "png" / "certA_p01.png")
    assert size == (10, 20) and pos == (0, 0)


def test_missing_png_reported_not_raised(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    (case_cache / "png").mkdir(parents=True)
    _write_orientation(case_cache, "certA", {"1": 90})

    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert s["rotated"] == 0
    assert any("PNG missing" in i for i in s["issues"])


def test_no_orientation_raises(tmp_path: Path):
    (tmp_path / ".cache" / "9").mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        align_case("9", tmp_path / ".cache")


def test_partial_failure_records_progress_and_rerun_is_safe(tmp_path: Path):
    """A corrupt page must not lose the record of pages already rotated —
    the re-run must not double-rotate them (review finding: crash window)."""
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    png_dir = case_cache / "png"
    _marker_png(png_dir / "certA_p01.png")
    (png_dir / "certA_p02.png").write_bytes(b"not a png")  # corrupt page
    _write_orientation(case_cache, "certA", {"1": 90, "2": 90})

    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert summary["ok"] is False
    assert s["rotated"] == 1
    assert s["failed_pages"] == ["2"]
    record = json.loads(alignment_path(case_cache, "certA").read_text(encoding="utf-8"))
    assert record["applied"] == {"1": 90}, "progress must be persisted despite the failure"

    # Operator fixes page 2 and re-runs: page 1 must NOT rotate again.
    _marker_png(png_dir / "certA_p02.png")
    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert summary["ok"] is True
    assert s["rotated"] == 1 and s["skipped_already_applied"] == 1
    size, pos = _black_at(png_dir / "certA_p01.png")
    assert size == (20, 10) and pos == (19, 0), "page 1 double-rotated!"
    size, pos = _black_at(png_dir / "certA_p02.png")
    assert size == (20, 10) and pos == (19, 0)


def test_interrupted_commit_is_completed_on_rerun(tmp_path: Path):
    """Crash between record write and PNG replace: the record is authoritative
    and the staged tmp must be committed, not re-rotated."""
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    png_dir = case_cache / "png"
    _marker_png(png_dir / "certA_p01.png")  # still unrotated (replace never ran)
    # Staged rotated pixels (what the crashed run produced in phase 1).
    with Image.open(png_dir / "certA_p01.png") as im:
        rotated = rotate_upright(im.convert("RGB"), 90)
    rotated.save(png_dir / "certA_p01.png.rot.tmp", format="PNG")
    alignment_path(case_cache, "certA").write_text(
        json.dumps({"schema_version": "1.0", "stem": "certA", "applied": {"1": 90}}),
        encoding="utf-8",
    )
    _write_orientation(case_cache, "certA", {"1": 90})

    summary = align_case("9", cache_root)
    s = summary["stems"][0]
    assert summary["ok"] is True
    assert s["rotated"] == 0 and s["skipped_already_applied"] == 1
    assert any("completed interrupted rotation" in i for i in s["issues"])
    assert not (png_dir / "certA_p01.png.rot.tmp").exists()
    size, pos = _black_at(png_dir / "certA_p01.png")
    assert size == (20, 10) and pos == (19, 0), "staged rotation not committed"


def test_uncovered_stem_fails_gate(tmp_path: Path):
    """A rendered stem without an orientation record must fail the gate."""
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    _marker_png(case_cache / "png" / "certA_p01.png")
    _marker_png(case_cache / "png" / "certB_p01.png")
    _write_orientation(case_cache, "certA", {"1": 0})

    summary = align_case("9", cache_root)
    assert summary["uncovered_stems"] == ["certB"]
    assert summary["ok"] is False


def test_sidecar_gains_rotations(tmp_path: Path):
    cache_root = tmp_path / ".cache"
    case_cache = cache_root / "9"
    _marker_png(case_cache / "png" / "certA_p01.png")
    (case_cache / "certA_prep.json").write_text(
        json.dumps({"pdf_sha256": "x" * 64, "dpi": 300, "rendered_pages": 1}),
        encoding="utf-8",
    )
    _write_orientation(case_cache, "certA", {"1": 270})

    align_case("9", cache_root)
    sidecar = json.loads((case_cache / "certA_prep.json").read_text(encoding="utf-8"))
    assert sidecar["rotations"] == {"1": 270}
    assert sidecar["dpi"] == 300  # existing fields preserved
