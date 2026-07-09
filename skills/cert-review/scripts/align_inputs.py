"""align_inputs.py — apply detected page rotations to rendered cert PNGs.

Counterpart of the `page-aligner` agent (Phase 1.5): the agent only DETECTS
each page's rotation from the orient_sheets contact sheets and records it in
``.cache/<case>/<stem>_orientation.json``; this module deterministically
APPLIES those rotations to the rendered page PNGs in ``.cache/<case>/png/``
(in place, Pillow transpose — 90-degree multiples are lossless) so that
tile-inputs, the OCR agent, crop and annotate all operate on upright pages.

Idempotency: applied rotations are recorded in ``<stem>_alignment.json``
(``{"applied": {"<page>": <deg>, ...}}``). A page already recorded there is
never rotated again, so re-running align-inputs cannot double-rotate. Each
page is rotated via a two-phase commit — rotate into ``<png>.rot.tmp``, append
the page to the (atomically replaced) alignment record, then ``os.replace``
the tmp over the PNG — so a crash at ANY point leaves a state a re-run
resolves correctly: tmp without record entry is discarded and redone; tmp
WITH a record entry is completed by finishing the replace. When prep_inputs
re-renders a stem (source PDF changed / --force) it deletes both the
orientation and alignment records, forcing a fresh detection pass.

Rotation semantics: ``<deg>`` is the CLOCKWISE rotation (0/90/180/270) that
makes the page upright. PIL's Transpose.ROTATE_* constants are
counter-clockwise, hence the inverted mapping below.

Cert pages only — the MPS channel (`mps_png/`) is out of scope by decision
(see docs/plans/2026-07-09_085623_page-orientation-alignment.md).

Constraint C1: image rotation only (Pillow), no OCR.
Constraint C7: pathlib throughout, encoding='utf-8' on all file I/O.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from scripts.prep_inputs import load_sidecar, sidecar_path
from scripts.tile_inputs import _stems_in_png_dir

ORIENTATION_SUFFIX = "_orientation.json"
ALIGNMENT_SUFFIX = "_alignment.json"

VALID_ROTATIONS = (0, 90, 180, 270)

# Clockwise degrees -> PIL transpose op (PIL ROTATE_* is counter-clockwise).
_CW_TO_TRANSPOSE = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def orientation_path(case_cache: Path, stem: str) -> Path:
    """Path of the page-aligner agent's detection output for a cert stem."""
    return Path(case_cache) / f"{stem}{ORIENTATION_SUFFIX}"


def alignment_path(case_cache: Path, stem: str) -> Path:
    """Path of the applied-rotation record for a cert stem."""
    return Path(case_cache) / f"{stem}{ALIGNMENT_SUFFIX}"


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_atomic(path: Path, payload: dict) -> None:
    """Write JSON via tmp + os.replace so a crash never truncates the record."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, path)


def applied_rotations(case_cache: Path, stem: str) -> dict[int, int]:
    """Full APPLIED rotation map for a stem: ``{page: deg_cw}`` (empty if none).

    Consumers that re-render from the source PDF (crop, annotate) use this to
    reproduce the aligned image space the reviewers actually saw. It reads the
    alignment record (what was done), not the orientation record (what was
    detected), so a detection that was never applied does not skew coordinates.
    """
    record = _load_json(alignment_path(case_cache, stem))
    if not record:
        return {}
    applied = record.get("applied")
    if not isinstance(applied, dict):
        return {}
    out: dict[int, int] = {}
    for key, value in applied.items():
        try:
            page_no = int(key)
            deg = int(value)
        except (TypeError, ValueError):
            continue
        if deg in VALID_ROTATIONS:
            out[page_no] = deg
    return out


def page_rotation(case_cache: Path, stem: str, page: int) -> int:
    """Clockwise rotation APPLIED to one page's rendered PNG (0 if none)."""
    return applied_rotations(case_cache, stem).get(int(page), 0)


def rotate_upright(image: Image.Image, deg_cw: int) -> Image.Image:
    """Rotate an image clockwise by a 90-degree multiple (lossless)."""
    if deg_cw == 0:
        return image
    try:
        op = _CW_TO_TRANSPOSE[deg_cw]
    except KeyError:
        raise ValueError(f"rotation must be one of {VALID_ROTATIONS}, got {deg_cw}")
    return image.transpose(op)


def _normalized_pages(orientation: dict) -> tuple[dict[str, int], list[str]]:
    """Validate the agent's page map -> ({page: deg}, [issues])."""
    pages = orientation.get("pages")
    issues: list[str] = []
    out: dict[str, int] = {}
    if not isinstance(pages, dict):
        return out, ["orientation has no 'pages' map"]
    for key, value in pages.items():
        try:
            page_no = int(key)
            deg = int(value)
        except (TypeError, ValueError):
            issues.append(f"page {key!r}: non-numeric rotation {value!r} (skipped)")
            continue
        if deg not in VALID_ROTATIONS:
            issues.append(f"page {page_no}: rotation {deg} not in {VALID_ROTATIONS} (skipped)")
            continue
        out[str(page_no)] = deg
    return out, issues


def _rot_tmp(png: Path) -> Path:
    """Two-phase-commit staging file for one page's rotated pixels."""
    return png.with_name(png.name + ".rot.tmp")


def align_case(case_id: str, cache_root: Path) -> dict:
    """Apply every stem's detected rotations to its rendered page PNGs.

    Reads each ``<stem>_orientation.json`` in ``.cache/<case>/`` and rotates
    the pages of ``.cache/<case>/png/<stem>_pNN.png`` in place. Records the
    applied map in ``<stem>_alignment.json``. Idempotent and crash-safe: each
    page commits in two phases (rotate to ``.rot.tmp`` -> record the page ->
    ``os.replace`` over the PNG), so an interrupted run never double-rotates —
    a re-run completes half-committed pages and redoes uncommitted ones.

    The returned summary carries the Phase 1.5 gate verdict: ``ok`` is False
    when any rendered stem lacks an orientation record (``uncovered_stems``)
    or any flagged page could not be rotated (``failed_pages``) — the
    orchestrator must not proceed to tiling/OCR in that state.
    Raises FileNotFoundError when the case has no orientation records at all
    (delegate page-aligner first).
    """
    case_cache = Path(cache_root) / str(case_id)
    png_dir = case_cache / "png"

    orientation_files = sorted(case_cache.glob(f"*{ORIENTATION_SUFFIX}"))
    if not orientation_files:
        raise FileNotFoundError(
            f"no {ORIENTATION_SUFFIX} for case {case_id} under {case_cache} "
            f"(run orient-sheets and delegate page-aligner first)"
        )

    stems_out: list[dict] = []
    for opath in orientation_files:
        stem = opath.name[: -len(ORIENTATION_SUFFIX)]
        orientation = _load_json(opath) or {}
        pages, issues = _normalized_pages(orientation)

        apath = alignment_path(case_cache, stem)
        record = _load_json(apath) or {}
        applied = record.get("applied") if isinstance(record.get("applied"), dict) else {}
        payload = {"schema_version": "1.0", "stem": stem, "applied": applied}

        rotated = 0
        skipped = 0
        failed_pages: list[str] = []
        for page_key, deg in sorted(pages.items(), key=lambda kv: int(kv[0])):
            if deg == 0:
                continue
            png = png_dir / f"{stem}_p{int(page_key):02d}.png"
            tmp = _rot_tmp(png)
            if page_key in applied:
                # Half-committed page (crash between record write and replace):
                # the record is authoritative — finish the replace.
                if tmp.exists():
                    os.replace(tmp, png)
                    issues.append(f"page {page_key}: completed interrupted rotation")
                skipped += 1
                try:
                    prev = int(applied[page_key])
                except (TypeError, ValueError):
                    prev = None
                if prev != deg:
                    issues.append(
                        f"page {page_key}: already aligned by {applied[page_key]!r}deg; "
                        f"new detection {deg}deg ignored (re-render to re-detect)"
                    )
                continue
            if not png.exists():
                issues.append(f"page {page_key}: PNG missing ({png.name})")
                failed_pages.append(page_key)
                continue
            # Phase 1: rotate into a staging file (a stale tmp from a crash
            # before the record write is simply overwritten — the PNG is
            # still the unrotated original, so redoing is safe).
            try:
                with Image.open(png) as im:
                    upright = rotate_upright(im.convert("RGB"), deg)
                upright.save(tmp, format="PNG")  # explicit: .rot.tmp has no PIL ext
            except (OSError, ValueError) as e:
                issues.append(f"page {page_key}: rotation failed ({e})")
                failed_pages.append(page_key)
                tmp.unlink(missing_ok=True)
                continue
            # Phase 2: record the page, then commit the pixels.
            applied[page_key] = deg
            _write_json_atomic(apath, payload)
            os.replace(tmp, png)
            rotated += 1

        _write_json_atomic(apath, payload)

        # Mirror the applied map into the render sidecar: prep-inputs stamps
        # rotations=None on every (re-)render, so this dict doubles as the
        # "Phase 1.5 completed for this render" marker the cache gate checks.
        scar_path = sidecar_path(case_cache, stem)
        sidecar = load_sidecar(scar_path)
        if sidecar is not None:
            sidecar["rotations"] = applied
            scar_path.write_text(
                json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
            )

        stems_out.append({
            "stem": stem,
            "pages_detected": len(pages),
            "rotated": rotated,
            "skipped_already_applied": skipped,
            "applied_total": len(applied),
            "failed_pages": failed_pages,
            "issues": issues,
        })

    # Phase 1.5 coverage gate: every rendered stem needs an orientation record.
    oriented = {s["stem"] for s in stems_out}
    uncovered = sorted(set(_stems_in_png_dir(png_dir)) - oriented) if png_dir.is_dir() else []

    ok = not uncovered and all(not s["failed_pages"] for s in stems_out)
    return {
        "case_id": str(case_id),
        "stems": stems_out,
        "uncovered_stems": uncovered,
        "ok": ok,
    }


__all__ = [
    "ORIENTATION_SUFFIX",
    "ALIGNMENT_SUFFIX",
    "VALID_ROTATIONS",
    "orientation_path",
    "alignment_path",
    "applied_rotations",
    "page_rotation",
    "rotate_upright",
    "align_case",
]
