"""C1 regression: scripts/ must not import any Python OCR library.

Walks the scripts/ tree with AST parsing (no execution) and asserts none of
the forbidden top-level modules appears in any `import` or `from ... import`
statement.
"""

from __future__ import annotations

import ast
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PLUGIN_DIR / "scripts"

FORBIDDEN = {
    "pytesseract",
    "tesserocr",
    "easyocr",
    "paddleocr",
    "paddlepaddle",
    "rapidocr_onnxruntime",
    "pix2text",
    "doctr",
    "kraken",
    "calamari_ocr",
    "google.generativeai",  # gemini vision
    "google.genai",
    "vertexai",
    "openai",
    "anthropic",
    "pdfplumber",   # has OCR-adjacent text extraction modes; out of caution
    "pdfminer",     # not OCR but text extraction beyond pypdf scope
    "fitz",         # pymupdf — can do OCR via tesseract
    "pymupdf",
}


def _gather_imports(py_path: Path) -> set[str]:
    src = py_path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(py_path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
                found.add(node.module)
    return found


def test_no_python_ocr_imports():
    violations: list[str] = []
    for py in SCRIPTS_DIR.rglob("*.py"):
        if "_bootstrap" in py.parts and py.name.startswith("_"):
            continue
        imports = _gather_imports(py)
        for forb in FORBIDDEN:
            if forb in imports:
                violations.append(f"{py.relative_to(PLUGIN_DIR)}: forbidden import '{forb}'")
    assert not violations, "C1 violation — Python OCR libs detected:\n" + "\n".join(violations)


def test_gt_data_path_not_referenced_outside_eval():
    """C4: 'standard inspection GT data' must only appear in eval_harness.py."""
    needle = "standard inspection GT data"
    offenders: list[str] = []
    for py in SCRIPTS_DIR.rglob("*.py"):
        if py.name in {"eval_harness.py", "__init__.py"}:
            continue
        text = py.read_text(encoding="utf-8")
        if needle in text:
            offenders.append(str(py.relative_to(PLUGIN_DIR)))
    assert not offenders, "C4 violation — GT data referenced outside eval_harness:\n" + "\n".join(offenders)
