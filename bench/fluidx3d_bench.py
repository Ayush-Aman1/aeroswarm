#!/usr/bin/env python3
"""FluidX3D's own benchmark mode (BENCHMARK define, 256^3, FP16S): peak MLUPs vs the bandwidth ceiling.

    python -m bench.fluidx3d_bench [--bandwidth-gbs 336] [--out dir] [--binary path]
Builds a copy of third_party/FluidX3D with the upstream benchmark setup (FP16S on), runs it and parses the
final "Peak MLUPs/s" line. Bytes per cell update for D3Q19 + FP16S: 2 x 19 x 2 B DDFs + 1 B flags = 77 B.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import time
from pathlib import Path

from bench.mlups import device_info
from tools.fluidx3d import batch

ROOT = Path(__file__).resolve().parents[1]
BYTES_PER_CELL_FP16S = 2 * 19 * 2 + 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--binary", default=None)
    ap.add_argument("--bandwidth-gbs", type=float, default=None)
    ap.add_argument("--timeout-min", type=float, default=30)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    name, bw, target = device_info()
    work = ROOT / "third_party" / "FluidX3D_benchmark"
    exe = Path(a.binary) if a.binary else batch.build(batch.prepare_tree(ROOT / "third_party" / "FluidX3D", work, benchmark=True))
    log = work / "benchmark.log"
    t0 = time.time()
    with open(log, "w") as fh:
        subprocess.run([str(exe)], cwd=exe.parent, stdout=fh, stderr=subprocess.STDOUT, timeout=a.timeout_min * 60, stdin=subprocess.DEVNULL)
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", log.read_text(errors="replace"))
    m = re.search(r"Peak MLUPs/s\s*=\s*(\d+)", text)
    if not m:
        raise SystemExit(f"no 'Peak MLUPs/s' line in {log}")
    mlups = float(m.group(1))
    dev = re.search(r"Device Name\s*\|\s*([^|]+?)\s*\|", text)
    dev = dev.group(1) if dev else name
    bw = a.bandwidth_gbs or bw or batch_known(dev)
    ceiling = bw * 1e9 / BYTES_PER_CELL_FP16S * 1e-6 if bw else float("nan")
    row = dict(tier="2-fluidx3d", device=dev, grid="256x256x256", mlups=mlups, ceiling_mlups=round(ceiling, 1),
               pct_of_ceiling=round(100 * mlups / ceiling, 2) if ceiling == ceiling else "", bytes_per_cell=BYTES_PER_CELL_FP16S,
               wall_s=round(time.time() - t0))
    out = Path(a.out or f"experiments/results/{'gpu' if target == 'gpu' else 'mac'}")
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "mlups_fluidx3d.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row)); w.writeheader(); w.writerow(row)
    print(row)
    return row


def batch_known(dev: str) -> float:
    from bench.mlups import KNOWN_BANDWIDTH_GBS
    return KNOWN_BANDWIDTH_GBS.get(dev, 0.0)


if __name__ == "__main__":
    main()
