import sys

import pytest

pytest.importorskip("lbmpy")
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pystencils 2.0 has no Windows CPU JIT: run Tier 1 under WSL2/Ubuntu")

from tests.validation.lbmpy_cylinder_2d import run_lbmpy_cylinder
from tests.validation import cylinder_2d


@pytest.mark.slow
def test_lbmpy_cylinder_strouhal_in_window():
    r = run_lbmpy_cylinder()
    assert abs(r["signal"]).max() > 1e-3                        # shedding actually happened
    assert cylinder_2d.ST_LOW <= r["strouhal"] <= cylinder_2d.ST_HIGH, r["strouhal"]
    assert r["tau"] > 0.51 and r["u_in"] <= 0.08
