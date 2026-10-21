"""FluidX3D VTK snapshots -> float16 .npy frames on the city's 2 m grid, in SI units, rotated back.

    python -m tools.fluidx3d.convert <vtk_dir> <out_dir> --scenario scenarios/block_small.json --direction 45

Reads FluidX3D's legacy binary VTK (STRUCTURED_POINTS, big-endian float32 vectors, x fastest). A small
dedicated parser handles that exact format fast (a frame is ~90 MB); anything else falls back to pyvista.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
from scipy.ndimage import map_coordinates

from engine.scenario.schema import Layout, load_scenario
from tools.fluidx3d.case import Case

FRAME_RE = "frame_{:02d}.npy"


def read_vtk_vector(path: str | Path) -> tuple[np.ndarray, tuple[float, float, float], tuple[int, int, int]]:
    """-> (u [Nx,Ny,Nz,3] float32, spacing, dims). Cell (i,j,k) centre = (i+.5, j+.5, k+.5) * spacing."""
    raw = Path(path).read_bytes()
    marker = b"LOOKUP_TABLE default\n"
    pos = raw.find(marker)
    if pos < 0:
        return _read_pyvista(path)
    head = raw[:pos].decode("ascii", "replace")
    dims = tuple(int(v) for v in re.search(r"DIMENSIONS\s+(\d+)\s+(\d+)\s+(\d+)", head).groups())
    sp = tuple(float(v) for v in re.search(r"SPACING\s+(\S+)\s+(\S+)\s+(\S+)", head).groups())
    m = re.search(r"SCALARS\s+\S+\s+(\w+)\s+(\d+)", head)
    if "BINARY" not in head or m is None or m.group(1) != "float" or m.group(2) != "3":
        return _read_pyvista(path)
    n = dims[0] * dims[1] * dims[2]
    data = np.frombuffer(raw, dtype=">f4", count=n * 3, offset=pos + len(marker))
    u = data.reshape(dims[2], dims[1], dims[0], 3).transpose(2, 1, 0, 3).astype(np.float32)
    return u, sp, dims


def _read_pyvista(path):
    import pyvista as pv
    g = pv.read(str(path))
    dims = tuple(int(v) for v in g.dimensions)
    arr = np.asarray(g.point_data[g.point_data.keys()[0]], np.float32)
    u = arr.reshape(dims[2], dims[1], dims[0], 3).transpose(2, 1, 0, 3)
    return u, tuple(float(v) for v in g.spacing), dims


def write_vtk_fluidx3d(path: str | Path, u: np.ndarray, spacing: float) -> None:
    """Write [Nx,Ny,Nz,3] float32 in the exact format FluidX3D's write_vtk() produces (used by tests)."""
    nx, ny, nz, _ = u.shape
    origin = [spacing * (0.5 - 0.5 * n) for n in (nx, ny, nz)]
    header = ("# vtk DataFile Version 3.0\nFluidX3D test fixture\nBINARY\nDATASET STRUCTURED_POINTS\n"
              f"DIMENSIONS {nx} {ny} {nz}\nORIGIN {origin[0]:.6f} {origin[1]:.6f} {origin[2]:.6f}\n"
              f"SPACING {spacing:.6f} {spacing:.6f} {spacing:.6f}\nPOINT_DATA {nx * ny * nz}\n"
              "SCALARS data float 3\nLOOKUP_TABLE default\n")
    body = np.ascontiguousarray(u.transpose(2, 1, 0, 3)).astype(">f4").tobytes()
    Path(path).write_bytes(header.encode("ascii") + body)


def _inside_city(layout: Layout, X, Y, Z):
    m = np.zeros(X.shape, bool)
    for b in layout.buildings:
        m |= (X >= b.x) & (X <= b.x + b.w) & (Y >= b.y) & (Y <= b.y + b.d) & (Z <= b.h)
    return m


def convert_frame(vtk_path, case: Case, theta_deg: float, zmax_m: float = 80.0) -> np.ndarray:
    """One VTK snapshot -> float16 [nxc, nyc, nzs, 3] on the city grid (cell centres), city-frame SI velocities."""
    u, (sx, sy, sz), dims = read_vtk_vector(vtk_path)
    dx = case.dx_m
    if abs(sx - dx) > 1e-3 * dx:
        raise ValueError(f"VTK spacing {sx} m does not match the case dx_m {dx}")
    nxc, nyc = (int(round(v / dx)) for v in case.layout.area_m)
    nzs = int(round(zmax_m / dx))
    xs, ys, zs = (np.arange(nxc) + 0.5) * dx, (np.arange(nyc) + 0.5) * dx, (np.arange(nzs) + 0.5) * dx
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    t = np.deg2rad(theta_deg)
    # city -> dom (rotate by -theta about the city centre, then translate to the domain centre)
    rx, ry = X - case.city_c[0], Y - case.city_c[1]
    xd = case.dom_c[0] + np.cos(-t) * rx - np.sin(-t) * ry
    yd = case.dom_c[1] + np.sin(-t) * rx + np.cos(-t) * ry
    coords = np.stack([xd / dx - 0.5, yd / dx - 0.5, Z / dx - 0.5]).astype(np.float64)
    comps = [map_coordinates(u[..., k], coords, order=1, mode="nearest") for k in range(3)]
    c, s = np.cos(t), np.sin(t)
    out = np.stack([c * comps[0] - s * comps[1], s * comps[0] + c * comps[1], comps[2]], axis=-1)
    out[_inside_city(case.layout, X, Y, Z)] = 0.0
    return out.astype(np.float16)


def convert_run(vtk_dir, out_dir, case: Case, theta_deg: float, preset: str, zmax_m: float = 80.0,
                source: str = "fluidx3d", frame_dt_s: float | None = None) -> dict:
    vtk_dir, out_dir = Path(vtk_dir), Path(out_dir)
    files = sorted(vtk_dir.glob("u-*.vtk"))
    if not files:
        raise FileNotFoundError(f"no u-*.vtk snapshots in {vtk_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for k, f in enumerate(files):
        np.save(out_dir / FRAME_RE.format(k), convert_frame(f, case, theta_deg, zmax_m))
    nx, ny = (int(round(v / case.dx_m)) for v in case.layout.area_m)
    meta = dict(preset=preset, direction_deg=float(theta_deg) % 360, dx_m=case.dx_m, zmax_m=zmax_m, n_frames=len(files),
                frame_dt_s=float(frame_dt_s if frame_dt_s is not None else case.snap_steps * case.dt_s),
                shape=[nx, ny, int(round(zmax_m / case.dx_m)), 3], dtype="float16", source=source,
                area_m=list(case.layout.area_m), layout=case.layout.to_dict(), inflow=case.inflow.to_dict(),
                domain=dict(size_m=list(case.size_m), cells=list(case.shape), dom_c=list(case.dom_c)))
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=1))
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vtk_dir"); ap.add_argument("out_dir")
    ap.add_argument("--scenario", required=True); ap.add_argument("--direction", type=float, required=True)
    ap.add_argument("--zmax", type=float, default=80.0); ap.add_argument("--dx", type=float, default=2.0)
    a = ap.parse_args(argv)
    sc = load_scenario(a.scenario)
    meta = convert_run(a.vtk_dir, a.out_dir, Case(sc.layout, sc.inflow, dx_m=a.dx), a.direction, sc.name, a.zmax)
    print(f"converted {meta['n_frames']} frames -> {a.out_dir}")


if __name__ == "__main__":
    main()
