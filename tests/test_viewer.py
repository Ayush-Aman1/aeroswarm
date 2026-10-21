"""Viewer checks from pytest: unit tests (vitest) and that the committed build is complete."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

VIEWER = Path(__file__).resolve().parents[1] / "viewer"


def test_dist_is_complete():
    index = VIEWER / "dist" / "index.html"
    assert index.exists(), "viewer/dist missing: cd viewer && npm ci && npm run build"
    html = index.read_text()
    for ref in re.findall(r'(?:src|href)="/(assets/[^"]+)"', html):
        assert (VIEWER / "dist" / ref).stat().st_size > 1000, ref


def test_lockfile_pins_three():
    import json
    lock = json.loads((VIEWER / "package-lock.json").read_text())
    pkg = json.loads((VIEWER / "package.json").read_text())
    assert pkg["dependencies"]["three"] == lock["packages"]["node_modules/three"]["version"]


@pytest.mark.skipif(not (VIEWER / "node_modules").exists() or shutil.which("npx") is None,
                    reason="run `npm ci` in viewer/ to enable the JS unit tests")
def test_vitest_suite():
    r = subprocess.run(["npx", "vitest", "run"], cwd=VIEWER, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-1000:]
