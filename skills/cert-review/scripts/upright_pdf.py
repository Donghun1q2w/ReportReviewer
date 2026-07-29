"""upright_pdf.py — annotate 직전 페이지 업라이트 정규화 (무손실 회전 matrix 전사).

The page-aligner/align-inputs pair makes the *rendered PNGs* upright for the
reviewers; this module makes the *annotate input PDF itself* upright, page by
page, so the NoRotate anchor math collapses to the identity (r == 0) and a
viewer's rotation-following edit chrome can no longer diverge from the label.

Only pages with page ``/Rotate`` != 0 or an align-inputs applied rotation != 0
are re-encoded (lossless: one rotation matrix transferred into the content
stream via pypdf's ``transfer_rotation_to_content``; embedded image XObject
streams are byte-identical). Already-upright pages pass through verbatim
(``PdfWriter(clone_from=...)``). This is NOT the banned raster burn-in: the
page is never rasterised and annotations stay native vector objects.

Error contract: encrypted sources raise ValueError (checked BEFORE any
metadata access -- pypdf would otherwise raise FileNotDecryptedError, which is
neither OSError nor ValueError); corrupt sources let pypdf's PyPdfError
family propagate. annotate_case owns the fallback for all three.

Cache: ``.cache/<case>/upright/<stem>_upright.pdf`` + sidecar json keyed by
schema_version + pypdf_version + source sha256 + applied-rotation map;
sidecar-last commit. Stale cache files are removed once a stem no longer
needs normalization. No direct PIL/pypdfium2 import (PIL loads transitively
via scripts.align_inputs; this module itself never rasterises).
Constraint C1: pypdf only, no OCR. C7: pathlib + encoding='utf-8'.
"""

from __future__ import annotations

import os
from pathlib import Path

import pypdf
from pypdf import PdfReader, PdfWriter

from scripts.align_inputs import VALID_ROTATIONS, _load_json, _write_json_atomic
from scripts.source_validator import compute_sha256_fresh

UPRIGHT_DIRNAME = "upright"
UPRIGHT_PDF_SUFFIX = "_upright.pdf"
UPRIGHT_SIDECAR_SUFFIX = "_upright.json"
UPRIGHT_META_KEY = "/CertReviewUpright"
UPRIGHT_SCHEMA_VERSION = "1.0"


def upright_paths(case_cache: Path, stem: str) -> tuple[Path, Path]:
    """(정규화 PDF 경로, 사이드카 경로) for a cert stem.

    Both live in a dedicated ``upright/`` subdirectory of the case cache so the
    derived artefacts never collide with the flat per-stem records
    (``*_orientation.json`` / ``*_alignment.json``) align_inputs writes there.
    """
    d = Path(case_cache) / UPRIGHT_DIRNAME
    return d / f"{stem}{UPRIGHT_PDF_SUFFIX}", d / f"{stem}{UPRIGHT_SIDECAR_SUFFIX}"


def page_upright_turns(reader: PdfReader, rotations: dict[int, int] | None) -> dict[int, int]:
    """정규화가 필요한 페이지의 {1-based page: t=(r+a)%360} 맵 (없으면 빈 dict).

    r 판정은 write_annotated_pdf(634-636)와 자구까지 동일해야 한다
    (r∉VALID_ROTATIONS → 0) — 클램프는 a와 결합하기 **전에** 적용한다
    (r=45·a=90 → t=90, U1이 고정). t==0(r=90,a=270)도 r≠0이므로 포함(/Rotate 스트립).
    """
    turns: dict[int, int] = {}
    for p, page in enumerate(reader.pages, start=1):
        r = int(page.get("/Rotate") or 0) % 360
        if r not in VALID_ROTATIONS:
            r = 0
        a = (rotations.get(p, 0) if rotations else 0) % 360
        if a not in VALID_ROTATIONS:   # applied_rotations가 이미 거르지만 이중 방어
            a = 0
        if r == 0 and a == 0:
            continue
        turns[p] = (r + a) % 360
    return turns


def write_upright_pdf(src: Path | str, dst: Path | str, turns: dict[int, int]) -> dict:
    """turns의 페이지만 t를 content로 전사(t==0은 /Rotate 스트립만)한 PDF를 원자적으로 기록.

    반환: {"n_pages": int, "baked": int, "stripped": int}
    암호화 PDF는 ValueError (defense in depth — ensure_upright_pdf가 먼저 거르지만
    이 함수 단독 공개 API 계약으로도 유지; U12가 직접 호출로 고정).
    """
    src, dst = Path(src), Path(dst)
    reader = PdfReader(str(src))
    if reader.is_encrypted:
        raise ValueError(f"encrypted PDF cannot be upright-normalized: {src.name}")
    writer = PdfWriter(clone_from=reader)
    baked = stripped = 0
    for p, t in sorted(turns.items()):
        if not 1 <= p <= len(writer.pages):
            continue  # 방어 — 현 호출 계약상 도달하지 않으나(U15가 직접 호출로 실증) 유지
        pg = writer.pages[p - 1]
        pg.rotation = t
        if t % 360 != 0:
            pg.transfer_rotation_to_content()   # /Rotate=0, 박스 스왑(90/270), matrix 전사
            baked += 1
        else:
            pg.rotation = 0                      # 스파이크 S6: 콘텐츠 불변, 스트립만
            stripped += 1
    writer.add_metadata({UPRIGHT_META_KEY: UPRIGHT_SCHEMA_VERSION})
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    with open(tmp, "wb") as fh:
        writer.write(fh)
    os.replace(tmp, dst)
    return {"n_pages": len(writer.pages), "baked": baked, "stripped": stripped}


def _remove_stale_cache(up_pdf: Path, up_scar: Path) -> list[str]:
    """정규화가 더는 불필요한 stem의 고아 캐시 제거 (gap_hunter#3 대응).

    잠금 등으로 제거 실패해도 호출자는 원본 경로 반환을 계속한다(note만 남김).
    """
    removed: list[str] = []
    for stale in (up_pdf, up_scar):
        try:
            if stale.exists():
                stale.unlink()
                removed.append(stale.name)
        except OSError:
            return [f"stale upright cache could not be removed (locked?): {stale.name}"]
    if removed:
        return [f"stale upright cache removed: {', '.join(removed)}"]
    return []


def ensure_upright_pdf(
    pdf_path: Path | str, case_cache: Path | str, rotations: dict[int, int] | None
) -> tuple[Path, bool, list[str]]:
    """캐시 게이트 래퍼. 반환: (annotate가 읽을 경로, 정규화 사용 여부, 노트들).

    - 암호화 소스 → ValueError("encrypted" 포함) — metadata 접근 **전에** 검사
      (contrarian#1: FileNotDecryptedError는 OSError/ValueError가 아님).
    - 손상 소스 → PdfReader에서 PyPdfError 계열 자연 전파 (caller 폴백).
    - 마커 보유 소스(정규화 출력물 재입력) → (입력, False) — 이중 회전 차단.
    - 정규화 불필요(turns 빔) → (입력, False); 스테일 캐시가 있으면 제거.
    - 캐시 유효(schema+pypdf 버전+sha256+rotations 일치) → (캐시, True), 재기록 없음.
    - 그 외 → 재생성 후 사이드카 최종 기록(commit marker), (캐시, True).
    """
    pdf_path, case_cache = Path(pdf_path), Path(case_cache)
    reader = PdfReader(str(pdf_path))            # 손상 PDF → PdfStreamError 등 (caller 폴백)
    if reader.is_encrypted:
        raise ValueError(f"encrypted PDF cannot be upright-normalized: {pdf_path.name}")
    meta = reader.metadata
    if meta is not None and meta.get(UPRIGHT_META_KEY):
        return pdf_path, False, ["source carries upright marker; normalization skipped"]
    turns = page_upright_turns(reader, rotations)
    up_pdf, up_scar = upright_paths(case_cache, pdf_path.stem)
    if not turns:
        return pdf_path, False, _remove_stale_cache(up_pdf, up_scar)
    src_sha = compute_sha256_fresh(pdf_path)
    rot_ser = {str(k): int(v) for k, v in sorted((rotations or {}).items())}
    sidecar = _load_json(up_scar)
    if (
        sidecar
        and up_pdf.exists()
        and sidecar.get("schema_version") == UPRIGHT_SCHEMA_VERSION
        and sidecar.get("pypdf_version") == pypdf.__version__   # contrarian#2: 기록을 강제로 승격
        and sidecar.get("source_sha256") == src_sha
        and sidecar.get("rotations") == rot_ser
    ):
        return up_pdf, True, [f"upright cache hit ({len(turns)} page(s) normalized)"]
    summary = write_upright_pdf(pdf_path, up_pdf, turns)
    _write_json_atomic(up_scar, {
        "schema_version": UPRIGHT_SCHEMA_VERSION,
        "stem": pdf_path.stem,
        "source_path": str(pdf_path).replace("\\", "/"),
        "source_sha256": src_sha,
        "rotations": rot_ser,
        "turns": {str(k): int(v) for k, v in sorted(turns.items())},
        "n_pages": summary["n_pages"],
        "pypdf_version": pypdf.__version__,
    })
    return up_pdf, True, [
        f"upright normalized {summary['baked']} page(s)"
        + (f" (+{summary['stripped']} rotate-strip)" if summary["stripped"] else "")
    ]


__all__ = [
    "UPRIGHT_DIRNAME", "UPRIGHT_PDF_SUFFIX", "UPRIGHT_SIDECAR_SUFFIX",
    "UPRIGHT_META_KEY", "UPRIGHT_SCHEMA_VERSION",
    "upright_paths", "page_upright_turns", "write_upright_pdf", "ensure_upright_pdf",
]
