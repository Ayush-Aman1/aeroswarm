"""Collision conserves mass and momentum (float32), plus a 1D worked example."""
import numpy as np
import pytest

from tests.validation import lbm2d


def test_bgk_conserves_mass_and_momentum_float32():
    rng = np.random.default_rng(0)
    n = 2000
    rho = rng.uniform(0.9, 1.1, (n, 1))
    ux, uy = rng.uniform(-0.08, 0.08, (n, 1)), rng.uniform(-0.08, 0.08, (n, 1))
    f = lbm2d.equilibrium(rho.reshape(n, 1), ux.reshape(n, 1), uy.reshape(n, 1))   # [9,n,1]
    f = (f * (1 + 0.02 * rng.standard_normal(f.shape))).astype(np.float32)           # off-equilibrium
    for tau in (0.52, 0.8, 1.7):
        g = lbm2d.bgk_collide(f, 1.0 / tau)
        assert g.dtype == np.float32
        r0, x0, y0 = [a.ravel() for a in lbm2d.macroscopic(f.astype(np.float64))]
        r1, x1, y1 = [a.ravel() for a in lbm2d.macroscopic(g.astype(np.float64))]
        np.testing.assert_allclose(r1, r0, atol=1e-6)
        np.testing.assert_allclose(r1 * x1, r0 * x0, atol=1e-6)
        np.testing.assert_allclose(r1 * y1, r0 * y0, atol=1e-6)


def test_equilibrium_moments():
    rho, ux, uy = np.array([[1.05]]), np.array([[0.05]]), np.array([[-0.03]])
    feq = lbm2d.equilibrium(rho, ux, uy, np.float64)
    r, x, y = lbm2d.macroscopic(feq)
    assert r[0, 0] == pytest.approx(1.05) and x[0, 0] == pytest.approx(0.05) and y[0, 0] == pytest.approx(-0.03)


def test_streaming_moves_populations():
    f = np.zeros((9, 5, 5), np.float32)
    f[1, 2, 2] = 1.0   # moving +x
    f[7, 2, 2] = 2.0   # moving (-1,-1)
    g = lbm2d.stream(f)
    assert g[1, 3, 2] == 1.0 and g[7, 1, 1] == 2.0 and g.sum() == 3.0


def test_1d_worked_example():
    """D1Q3 (w = 2/3, 1/6, 1/6, c_s^2 = 1/3), tau = 1, one collision from a hand-computed state.

    NOTE: docs/explainer.pdf (the guide's source for 'the' 1D worked example) was not provided with the
    repo, so this reproduces a standard textbook example computed by hand; see BLOCKERS.md.
    """
    w = np.array([2 / 3, 1 / 6, 1 / 6]); c = np.array([0, 1, -1])
    f = np.array([0.5, 0.3, 0.2])
    rho = f.sum(); u = (c * f).sum() / rho
    assert rho == pytest.approx(1.0) and u == pytest.approx(0.1)
    feq = w * rho * (1 + 3 * c * u + 4.5 * (c * u) ** 2 - 1.5 * u ** 2)
    # by hand: u = 0.1 -> feq0 = 2/3*(1-0.015) = 0.656666..., feq1 = 1/6*(1+0.3+0.045-0.015) = 0.221666...,
    #          feq2 = 1/6*(1-0.3+0.045-0.015) = 0.121666...
    assert feq == pytest.approx([0.656666666667, 0.221666666667, 0.121666666667], abs=1e-12)
    f_post = f + 1.0 * (feq - f)                       # tau = 1 -> f* = feq exactly
    assert f_post == pytest.approx(feq, abs=1e-15)
    assert f_post.sum() == pytest.approx(rho) and (c * f_post).sum() == pytest.approx(rho * u)
