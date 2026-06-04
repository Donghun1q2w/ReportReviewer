"""Input-guard regression tests.

scripts/__init__.py installs a sys.audit hook (when CERT_REVIEW_GT_GUARD=1)
that forbids open() on two input sources during operation:
  - `standard inspection GT data/`  — allowed only from eval_harness.
  - `rawdata/`                       — forbidden everywhere, no exception.

These tests run a child interpreter with the guard enabled and assert that the
PermissionError fires BEFORE FileNotFoundError (the audit hook runs at the
moment open() is invoked, so a non-existent dummy path still raises
PermissionError). A normal cert-cleanup path must pass the guard (and then
raise FileNotFoundError because the dummy file does not exist).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SKILL_ROOT = PLUGIN_DIR.parent  # dir that contains the `scripts` package


def _run_snippet(body: str, module_name: str = "some_worker_module") -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter with the guard enabled.

    `module_name` controls the __name__ the open() call appears to originate
    from; the GT exemption keys on the module name ('eval_harness').
    """
    code = (
        "import os, runpy, sys\n"
        "os.environ['CERT_REVIEW_GT_GUARD'] = '1'\n"
        f"sys.path.insert(0, {str(SKILL_ROOT)!r})\n"
        f"__name__ = {module_name!r}\n"
        "import scripts  # installs the audit hook\n"
        + body
    )
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_gt_open_blocked_outside_eval_harness():
    proc = _run_snippet(
        "open(os.path.join('x', 'standard inspection GT data', 'nope.md'))\n",
        module_name="some_worker_module",
    )
    assert proc.returncode != 0
    assert "PermissionError" in proc.stderr, proc.stderr
    assert "GT data" in proc.stderr, proc.stderr


def test_rawdata_open_blocked_everywhere():
    proc = _run_snippet(
        "open(os.path.join('x', 'rawdata', 'case4', 'nope.pdf'))\n",
        module_name="some_worker_module",
    )
    assert proc.returncode != 0
    assert "PermissionError" in proc.stderr, proc.stderr
    assert "rawdata" in proc.stderr, proc.stderr


def test_rawdata_blocked_even_for_eval_harness():
    # rawdata has no exemption — even eval_harness may not read it.
    proc = _run_snippet(
        "open(os.path.join('x', 'rawdata', 'case4', 'nope.pdf'))\n",
        module_name="eval_harness",
    )
    assert proc.returncode != 0
    assert "PermissionError" in proc.stderr, proc.stderr


def test_normal_cert_path_passes_guard():
    # A cert-cleanup path is allowed; open() then fails with FileNotFoundError
    # (NOT PermissionError) because the dummy file does not exist.
    proc = _run_snippet(
        "open(os.path.join('x', 'standard inspection Cert cleanup data', '4', 'nope.pdf'))\n",
        module_name="some_worker_module",
    )
    assert proc.returncode != 0
    assert "PermissionError" not in proc.stderr, proc.stderr
    assert "FileNotFoundError" in proc.stderr, proc.stderr


def test_filename_containing_rawdata_substring_not_blocked():
    # 'myrawdata.pdf' is a filename, not a path segment — must NOT trip the guard.
    proc = _run_snippet(
        "open(os.path.join('x', 'cert', 'myrawdata.pdf'))\n",
        module_name="some_worker_module",
    )
    assert proc.returncode != 0
    assert "PermissionError" not in proc.stderr, proc.stderr
    assert "FileNotFoundError" in proc.stderr, proc.stderr
