"""cert-review-skill scripts package.

Hard constraints (enforced by tests/test_no_python_ocr.py):
- No Python OCR libraries (pytesseract, easyocr, paddleocr, paddlepaddle,
  gemini-* vision SDK, openai vision wrapper, pix2text, etc.)
- No read access to `standard inspection GT data/` from any module
  except eval_harness.py (which is the only module allowed by name).
- No read access to `rawdata/` from ANY module during operation — the
  rawdata originals carry live reviewer annotations (de-facto ground truth)
  that must never leak into findings.
- All findings and reference rows must carry 3 provenance fields
  (source_file, anchor, snippet).
"""

from __future__ import annotations

import os

# Input guard. Importing this package while CERT_REVIEW_GT_GUARD is set to "1"
# (the default) enables a sys.audit hook that aborts on any open() targeting a
# forbidden input source:
#   - `standard inspection GT data/` — allowed only from eval_harness.
#   - `rawdata/`                      — forbidden everywhere (no exceptions),
#     because rawdata originals contain live reviewer FreeText annotations that
#     are essentially the answer key.
# Markers are matched as PATH SEGMENTS (os.sep-delimited) so a filename that
# merely contains the substring 'rawdata' does not trigger a false positive.
if os.environ.get("CERT_REVIEW_GT_GUARD", "1") == "1":
    import sys

    _GT_MARKER = "standard inspection gt data"
    _RAWDATA_MARKER = "rawdata"
    _GT_ALLOWED = {"eval_harness"}

    def _path_segments(norm: str) -> list[str]:
        # Split on both separators so the check works regardless of platform
        # and regardless of how the caller spelled the path.
        return [seg for seg in norm.replace("\\", "/").split("/") if seg]

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
        if isinstance(norm, bytes):
            norm = norm.decode("utf-8", "ignore")
        lowered = norm.lower()
        segments = [seg.lower() for seg in _path_segments(lowered)]

        # rawdata is forbidden for EVERYONE — match as a path segment.
        if _RAWDATA_MARKER in segments:
            raise PermissionError(
                f"Access to 'rawdata/' is forbidden during operation "
                f"(tried: {norm})"
            )

        # GT data is forbidden outside eval_harness — match the multi-word
        # marker as a contiguous path segment.
        if _GT_MARKER in segments:
            frame = sys._getframe(1)
            while frame is not None:
                mod = frame.f_globals.get("__name__", "")
                if any(mod.endswith(a) or a in mod for a in _GT_ALLOWED):
                    return
                frame = frame.f_back
            raise PermissionError(
                f"Access to 'standard inspection GT data/' is forbidden "
                f"outside eval_harness (tried: {norm})"
            )

    sys.addaudithook(_audit)
