"""The dashboard layout's ordering rules (web/dashlayout.js, docs/AS_BUILT.md
§20) run in Node: tests/js/dash_layout.test.js. Skipped if Node isn't installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "js" / "dash_layout.test.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is not installed")
def test_dash_layout_rules():
    result = subprocess.run(["node", str(SCRIPT)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr or result.stdout
    assert "all checks pass" in result.stdout
