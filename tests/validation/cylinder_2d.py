"""2D cylinder validation (P2): Strouhal number from a probe behind the cylinder + vorticity PNG.

    python -m tests.validation.cylinder_2d [out_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from tests.validation import lbm2d

ST_LOW, ST_HIGH = 0.16, 0.22


def run_and_report(out_dir: Path | None = None, **kw) -> dict:
    snap = {}
    res = lbm2d.run_cylinder(snapshot_cb=lambda f, solid: snap.update(f=f.copy(), solid=solid.copy()), **kw)
    st = lbm2d.strouhal(res["signal"], res["diameter"], res["u_in"])
    res["strouhal"] = st
    if out_dir is not None:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        w = lbm2d.vorticity(snap["f"])
        w = np.ma.array(w, mask=snap["solid"])
        fig, ax = plt.subplots(figsize=(9, 3.6))
        ax.imshow(w.T, origin="lower", cmap="RdBu", vmin=-0.04, vmax=0.04)
        ax.set_title(f"D2Q9 cylinder, Re={res['reynolds']:g}, tau={res['tau']:.3f}: vorticity, St={st:.3f}")
        fig.savefig(out_dir / "cylinder_vorticity.png", dpi=110, bbox_inches="tight")
        plt.close(fig)
        res["png"] = str(out_dir / "cylinder_vorticity.png")
    return res


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("runs/validation")
    r = run_and_report(out)
    print(f"Strouhal = {r['strouhal']:.4f}  (pass window {ST_LOW}-{ST_HIGH}) -> "
          f"{'PASS' if ST_LOW <= r['strouhal'] <= ST_HIGH else 'FAIL'}; vorticity PNG: {r.get('png')}")
