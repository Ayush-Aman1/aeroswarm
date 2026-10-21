import json
import numpy as np
import pytest

from experiments import run_experiments as E


def fake_rows():
    rows = []
    for seed in (1, 2, 3):
        for routing, shift in (("naive", 0.0), ("aware", -5.0)):
            rows.append(dict(tier="synthetic", scenario="block_small", routing=routing, seed=seed, completed=50,
                             mean_delivery_s=40 + seed + shift, energy_mean=600 + 10 * seed + 3 * shift,
                             drift_mean=2.0, drift_max=9.0, near_collisions=40 + seed))
    return rows


def test_aggregate_pairs_by_seed_and_flags_significance():
    cond, paired = E.aggregate(fake_rows())
    assert len(cond) == 2 and cond[0]["n_seeds"] == 3
    d = {p["metric"]: p for p in paired}
    assert d["mean_delivery_s"]["diff_mean"] == pytest.approx(-5.0)
    assert d["mean_delivery_s"]["diff_ci95"] == pytest.approx(0.0, abs=1e-9)      # constant shift: zero spread
    assert d["mean_delivery_s"]["significant"] and not d["drift_mean"]["significant"]
    assert d["mean_delivery_s"]["rel_change_pct"] == pytest.approx(-5.0 / 42 * 100)


def test_report_and_plots_are_labelled_cpu_only(tmp_path):
    cond, paired = E.aggregate(fake_rows())
    E.plots(cond, tmp_path, "test machine")
    class A: seeds = [1, 2, 3]; duration = 300.0
    E.write_report(tmp_path, cond, paired, ["lbmpy / x: not available"], "test machine", A, 12.0)
    text = (tmp_path / "RESULTS.md").read_text()
    assert "CPU tiers only" in text and "Tier 3 - synthetic wind" in text and "Skipped" in text
    assert (tmp_path / "synthetic_comparison.png").stat().st_size > 5000


def test_availability_gates():
    assert E.available("synthetic", "block_small", None)[0]
    assert not E.available("fluidx3d", "no_such_layout", None)[0]
    assert not E.available("quantum", "x", None)[0]


@pytest.mark.slow
def test_end_to_end_tiny_run(tmp_path):
    rows = E.main(["--tiers", "synthetic", "--scenarios", "block_small", "--seeds", "1", "2", "--duration", "40",
                   "--workers", "2", "--out", str(tmp_path)])
    assert len(rows) == 4 and (tmp_path / "RESULTS.md").exists() and (tmp_path / "paired_differences.csv").exists()
    assert json.loads((tmp_path / "runs/synthetic/block_small/naive_s1/summary.json").read_text())["seed"] == 1
