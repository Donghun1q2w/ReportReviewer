"""merge_parts.py — merge chunked Vision OCR fragments into <stem>_extracted.json.

Large certs (SKILL.md Phase 2: split threshold 8 pages) are extracted by parallel
subagents that each write a fragment under .cache/<case>/parts/:

    <stem>__pSSS-EEE.json
    {"stem": str, "pages_covered": [int, ...], "page_extraction": [entry, ...]}

This module deterministically merges those fragments back into the skeleton
<stem>_extracted.json (written by prep_inputs), filling page_extraction and
channels.body.pages. Top-level skeleton fields (cert_file, cert_sha256, ...) are
preserved. When two fragments carry the same page number the lexicographically
later fragment file wins and the collision is reported as an issue.

Constraint C1: no OCR here — pure JSON reshaping. The completeness gate stays
Phase 2.5 check-extraction; merge does not validate coverage beyond reporting.
"""

from __future__ import annotations

import json
from pathlib import Path

_FRAGMENT_SEP = "__p"


def fragment_stem(fragment_path: Path) -> str:
    """Return the cert stem encoded in a fragment filename."""
    return fragment_path.stem.rsplit(_FRAGMENT_SEP, 1)[0]


def discover_stems(parts_dir: Path) -> list[str]:
    """Return sorted unique cert stems that have at least one fragment."""
    if not parts_dir.is_dir():
        return []
    return sorted({
        fragment_stem(p)
        for p in parts_dir.glob(f"*{_FRAGMENT_SEP}*.json")
        if p.is_file()
    })


def merge_stem(
    case_cache: Path,
    stem: str,
    extracted_at: str | None = None,
) -> dict:
    """Merge all fragments of one cert stem into its skeleton extracted.json.

    Returns {"stem", "fragments", "pages", "written", "issues": [str, ...]}.
    Raises FileNotFoundError when the skeleton or fragments are absent.
    """
    case_cache = Path(case_cache)
    parts_dir = case_cache / "parts"
    skeleton_path = case_cache / f"{stem}_extracted.json"

    fragments = sorted(parts_dir.glob(f"{stem}{_FRAGMENT_SEP}*.json"))
    if not fragments:
        raise FileNotFoundError(f"no fragments for stem '{stem}' under {parts_dir}")
    if not skeleton_path.exists():
        raise FileNotFoundError(
            f"skeleton not found: {skeleton_path} (run prep-inputs first)"
        )

    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))

    issues: list[str] = []
    by_page: dict[int, dict] = {}

    for frag_path in fragments:
        try:
            frag = json.loads(frag_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            issues.append(f"{frag_path.name}: invalid JSON ({e})")
            continue

        frag_stem = frag.get("stem")
        if frag_stem and frag_stem != stem:
            issues.append(f"{frag_path.name}: stem mismatch '{frag_stem}'")
            continue

        for entry in frag.get("page_extraction") or []:
            page = entry.get("page")
            if not isinstance(page, int):
                issues.append(f"{frag_path.name}: entry without integer page")
                continue
            if page in by_page:
                issues.append(
                    f"page {page} duplicated; later fragment {frag_path.name} wins"
                )
            by_page[page] = entry

    pages = sorted(by_page)
    skeleton["page_extraction"] = [by_page[p] for p in pages]
    channels = skeleton.setdefault("channels", {})
    channels["body"] = {"engine": "claude-vision", "pages": pages}
    if extracted_at is not None:
        skeleton["extracted_at"] = extracted_at

    skeleton_path.write_text(
        json.dumps(skeleton, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "stem": stem,
        "fragments": len(fragments),
        "pages": pages,
        "written": str(skeleton_path).replace("\\", "/"),
        "issues": issues,
    }


def merge_case(
    case_id: str,
    cache_root: Path,
    stem: str | None = None,
    extracted_at: str | None = None,
) -> dict:
    """Merge fragments for one case (all stems, or a single stem).

    Returns {"case_id", "stems": [merge_stem result, ...], "issues": [str, ...]}.
    """
    case_cache = Path(cache_root) / case_id
    parts_dir = case_cache / "parts"

    stems = [stem] if stem else discover_stems(parts_dir)
    if not stems:
        raise FileNotFoundError(f"no fragment files under {parts_dir}")

    results = [merge_stem(case_cache, s, extracted_at=extracted_at) for s in stems]
    return {
        "case_id": case_id,
        "stems": results,
        "issues": [i for r in results for i in r["issues"]],
    }


__all__ = ["merge_case", "merge_stem", "discover_stems", "fragment_stem"]
