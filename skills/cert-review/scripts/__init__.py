"""cert-review-skill scripts package.

Hard constraints (enforced by tests/test_no_python_ocr.py):
- No Python OCR libraries (pytesseract, easyocr, paddleocr, paddlepaddle,
  gemini-* vision SDK, openai vision wrapper, pix2text, etc.)
- No read access to `standard inspection GT data/` from any module
  except eval_harness.py (which is the only module allowed by name).
- All findings and reference rows must carry 4 provenance fields
  (source_file, anchor, snippet, sha256).
"""

from __future__ import annotations

import os

# Read-time guard. Importing this package while GT_GUARD_DISABLE is unset
# enables a sys.audit hook that aborts on any open() to GT data.
if os.environ.get("CERT_REVIEW_GT_GUARD", "1") == "1":
    import sys
    _GT_MARKER = os.path.normpath("standard inspection GT data")
    _ALLOWED = {"eval_harness"}

    def _audit(event: str, args: tuple) -> None:
        if event != "open" or not args:
            return
        path = args[0]
        if not isinstance(path, (str, bytes, os.PathLike)):
            return
        try:
            norm = os.path.normpath(os.fspath(path))
        except TypeError:
            return
        if _GT_MARKER in norm:
            frame = sys._getframe(1)
            while frame is not None:
                mod = frame.f_globals.get("__name__", "")
                if any(mod.endswith(a) or a in mod for a in _ALLOWED):
                    return
                frame = frame.f_back
            raise PermissionError(
                f"Access to 'standard inspection GT data/' is forbidden "
                f"outside eval_harness (tried: {norm})"
            )

    sys.addaudithook(_audit)
