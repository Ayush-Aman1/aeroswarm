import pytest

from tests.validation import cylinder_2d


@pytest.mark.slow
def test_cylinder_strouhal_in_window(tmp_path):
    r = cylinder_2d.run_and_report(tmp_path)
    assert cylinder_2d.ST_LOW <= r["strouhal"] <= cylinder_2d.ST_HIGH, r["strouhal"]
    assert r["tau"] > 0.51 and r["u_in"] <= 0.08
    assert (tmp_path / "cylinder_vorticity.png").stat().st_size > 5000
    assert abs(r["signal"]).max() > 1e-3        # shedding actually happened
