"""refpack (limits pack) regression tests.

Builds a self-contained fixture: a tmp work_dir holding a provenance source file
plus 7 reference CSVs (each row cites that source so load_csv accepts them), and a
cache dir with a synthetic *_extracted.json. Asserts relevant-row selection,
provenance preservation, and unrouted reporting — without the real dataset.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.refpack import build_limits_pack, collect_inventory

PROV = "ref.md"


def _src_text() -> str:
    # Every snippet used by the CSV rows below must appear here verbatim.
    return (
        "P22 chem max 2.5\n"
        "P91 chem max 9.5\n"
        "P22 mech TS 415\n"
        "P91 mech TS 585\n"
        "P22 HT normalize\n"
        "P91 HT normalize\n"
        "P22 nde RT\n"
        "P91 nde RT\n"
        "P91 mps Mn cap\n"
        "P22 route pattern\n"
        "P91 route pattern\n"
        "SA-335 edition 2019\n"
    )


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(header)]
    for r in rows:
        lines.append(",".join(r))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """Create work_dir (source + data CSVs) and cache_root. Returns (work, data)."""
    work = tmp_path / "work"
    data = work / "data"
    data.mkdir(parents=True)
    (work / PROV).write_text(_src_text(), encoding="utf-8")

    _write_csv(
        data / "grade_routing.csv",
        ["cert_grade_pattern", "asme_spec", "astm_spec", "ref_code_folder",
         "fallback_year", "mps_override_required", "source_file", "anchor", "snippet"],
        [
            [r"SA-?335\s*P22", "SA-335", "A335", "x", "2019", "N", PROV, "a1", "P22 route pattern"],
            [r"SA-?335\s*P91", "SA-335", "A335", "x", "2019", "Y", PROV, "a2", "P91 route pattern"],
        ],
    )
    _write_csv(
        data / "chemistry_limits.csv",
        ["grade", "element", "analysis", "min", "max", "unit", "source_file", "anchor", "snippet"],
        [
            ["SA-335-P22", "Cr", "Heat", "1.9", "2.6", "%", PROV, "c1", "P22 chem max 2.5"],
            ["SA-335-P91", "Cr", "Heat", "8.0", "9.5", "%", PROV, "c2", "P91 chem max 9.5"],
        ],
    )
    _write_csv(
        data / "mechanical_limits.csv",
        ["grade", "property", "unit", "min", "max", "specimen", "source_file", "anchor", "snippet"],
        [
            ["SA-335-P22", "TS", "MPa", "415", "", "", PROV, "m1", "P22 mech TS 415"],
            ["SA-335-P91", "TS", "MPa", "585", "", "", PROV, "m2", "P91 mech TS 585"],
        ],
    )
    _write_csv(
        data / "heat_treatment.csv",
        ["grade", "stage", "temp_min_C", "temp_max_C", "hold_min_per_25mm", "cooling",
         "required", "source_file", "anchor", "snippet"],
        [
            ["SA-335-P22", "Normalize", "900", "960", "", "air", "Y", PROV, "h1", "P22 HT normalize"],
            ["SA-335-P91", "Normalize", "1040", "1080", "", "air", "Y", PROV, "h2", "P91 HT normalize"],
        ],
    )
    _write_csv(
        data / "nde_rules.csv",
        ["grade", "material_type", "nde_method", "required", "notch_type",
         "notch_depth_rule", "source_file", "anchor", "snippet"],
        [
            ["P22", "ANY", "RT", "Y", "", "", PROV, "n1", "P22 nde RT"],
            ["P91", "ANY", "RT", "Y", "", "", PROV, "n2", "P91 nde RT"],
        ],
    )
    _write_csv(
        data / "mps_overrides.csv",
        ["mps_id", "grade", "category", "parameter", "operator", "value", "unit",
         "source_file", "anchor", "snippet"],
        [
            ["MPS-1", "SA-335-P91", "chem", "Mn_max", "<=", "0.6", "%", PROV, "o1", "P91 mps Mn cap"],
        ],
    )
    _write_csv(
        data / "code_edition_map.csv",
        ["spec", "referenced_edition", "available_edition", "ref_code_folder",
         "note", "source_file", "anchor", "snippet"],
        [
            ["SA-335", "2019", "2019", "x", "", PROV, "e1", "SA-335 edition 2019"],
        ],
    )
    return work, data


def _write_extracted(cache: Path, case_id: str, stem: str, headers: list[dict]) -> None:
    case_cache = cache / case_id
    case_cache.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "2.0",
        "case_id": case_id,
        "cert_file": f"cert/{stem}.pdf",
        "cert_sha256": "0" * 64,
        "channels": {"body": {"engine": "claude-vision", "pages": [1]}},
        "page_extraction": [
            {"page": i + 1, "header": h} for i, h in enumerate(headers)
        ],
    }
    (case_cache / f"{stem}_extracted.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def test_collect_inventory_dedupes(tmp_path: Path):
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-335", "grade": "P22"},
        {"spec": "ASME SA-335", "grade": "P22"},  # dup
        {"spec": "ASME SA-335", "grade": "P91"},
    ])
    inv = collect_inventory(cache / "9")
    grades = sorted(i["grade"] for i in inv)
    assert grades == ["P22", "P91"]


def _write_doctype(case_cache: Path, stem: str, pages: dict[int, str]) -> None:
    case_cache.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "1.0", "stem": stem,
               "pages": {str(p): t for p, t in pages.items()}, "uncertain_pages": []}
    (case_cache / f"{stem}_doctype.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_collect_inventory_excludes_raw_material_pages(tmp_path: Path):
    """T-4 (L2): an excluded raw-material page's header (SA516 plate) must not
    enter the inventory when a doctype sidecar marks it EXCLUDED."""
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-335", "grade": "P22"},          # p1 finished
        {"spec": "ASME SA-516", "grade": "Gr.70"},         # p2 raw material
    ])
    _write_doctype(cache / "9", "certA", {
        1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL",
    })
    inv = collect_inventory(cache / "9")
    grades = sorted(i["grade"] for i in inv)
    assert grades == ["P22"], "raw-material grade leaked into inventory"


def test_collect_inventory_no_sidecar_keeps_all(tmp_path: Path):
    """T-4: without a doctype sidecar the inventory is identical to before
    (backward compatibility — every page counts)."""
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-335", "grade": "P22"},
        {"spec": "ASME SA-516", "grade": "Gr.70"},
    ])
    inv = collect_inventory(cache / "9")
    grades = sorted(i["grade"] for i in inv)
    assert grades == ["Gr.70", "P22"]


def test_collect_inventory_excludes_string_page_key(tmp_path: Path):
    """T-4/E10: extracted entries whose `page` is a numeric STRING are matched
    against the excluded set after int() conversion."""
    cache = tmp_path / "cache"
    case_cache = cache / "9"
    case_cache.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": "2.0", "case_id": "9", "cert_file": "cert/certA.pdf",
        "cert_sha256": "0" * 64,
        "channels": {"body": {"engine": "claude-vision", "pages": [1, 2]}},
        "page_extraction": [
            {"page": "1", "header": {"spec": "ASME SA-335", "grade": "P22"}},
            {"page": "2", "header": {"spec": "ASME SA-516", "grade": "Gr.70"}},
        ],
    }
    (case_cache / "certA_extracted.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    _write_doctype(case_cache, "certA", {1: "MTC_FINISHED", 2: "MTC_RAW_MATERIAL"})
    inv = collect_inventory(case_cache)
    assert sorted(i["grade"] for i in inv) == ["P22"]


def test_limits_selects_only_relevant_rows(tmp_path: Path):
    work, data = _build_fixture(tmp_path)
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-335/SA-335M 2019", "grade": "P22"},
    ])

    pack = build_limits_pack("9", work, cache, data)
    limits = pack["limits"]

    # Only the P22 rows are selected (not P91).
    assert [r["grade"] for r in limits["chemistry_limits.csv"]] == ["SA-335-P22"]
    assert [r["grade"] for r in limits["mechanical_limits.csv"]] == ["SA-335-P22"]
    assert [r["grade"] for r in limits["heat_treatment.csv"]] == ["SA-335-P22"]
    assert [r["grade"] for r in limits["nde_rules.csv"]] == ["P22"]
    # P22 has no MPS override row in the fixture.
    assert limits["mps_overrides.csv"] == []
    # The routing row + the code-edition row for SA-335 are included.
    assert len(limits["grade_routing.csv"]) == 1
    assert [r["spec"] for r in limits["code_edition_map.csv"]] == ["SA-335"]
    assert pack["unrouted"] == []


def test_limits_preserves_provenance(tmp_path: Path):
    work, data = _build_fixture(tmp_path)
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-335", "grade": "P91"},
    ])
    pack = build_limits_pack("9", work, cache, data)
    for name, rows in pack["limits"].items():
        for r in rows:
            assert r.get("source_file"), f"{name} row lost source_file"
            assert r.get("anchor"), f"{name} row lost anchor"
            assert r.get("snippet"), f"{name} row lost snippet"


def test_limits_reports_unrouted(tmp_path: Path):
    work, data = _build_fixture(tmp_path)
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-999", "grade": "ZZ99"},  # no routing pattern
    ])
    pack = build_limits_pack("9", work, cache, data)
    assert "ZZ99" in pack["unrouted"]
    # Nothing routed -> every grade-scoped CSV is empty.
    assert pack["limits"]["chemistry_limits.csv"] == []


def test_limits_writes_output_file(tmp_path: Path):
    work, data = _build_fixture(tmp_path)
    cache = tmp_path / "cache"
    _write_extracted(cache, "9", "certA", [
        {"spec": "ASME SA-335", "grade": "P22"},
    ])
    pack = build_limits_pack("9", work, cache, data)
    out = cache / "9" / "9_limits.json"
    assert out.exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["case_id"] == "9"
    assert "limits" in saved


def test_limits_no_extraction_raises(tmp_path: Path):
    work, data = _build_fixture(tmp_path)
    cache = tmp_path / "cache"
    (cache / "9").mkdir(parents=True)
    try:
        build_limits_pack("9", work, cache, data)
    except FileNotFoundError:
        return
    raise AssertionError("expected FileNotFoundError when no extracted JSON")
