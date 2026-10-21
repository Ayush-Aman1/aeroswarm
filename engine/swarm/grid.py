"""Uniform-grid neighbour search: cell id -> histogram -> exclusive scan -> scatter -> 27-cell loop.

The sequence (calcHash -> sort/scatter by cell -> findCellStart -> loop own + 26 neighbour cells) follows
the NVIDIA cuda-samples `particles` sample, https://github.com/NVIDIA/cuda-samples (BSD-3-Clause style
licence), re-implemented here with xp array primitives (numpy or cupy). The fused GPU kernel at the bottom
is a cupy RawKernel modelled on that sample's `collideCell`; it is UNTESTED on a Mac (no CUDA) and is
exercised by the `gpu`-marked test in tests/test_p3_swarm.py.

A naive O(N^2) path is kept for correctness tests and for the benchmark's naive-vs-grid comparison.
"""
from __future__ import annotations

import itertools

import numpy as np

from engine.backend import is_gpu, xp

OFFSETS = np.array(list(itertools.product((-1, 0, 1), repeat=3)), dtype=np.int64)   # 27 cells


class Grid:
    """Cells of edge `cell_m` covering `bounds_m`. Pass cell_m >= the interaction radius."""

    def __init__(self, bounds_m, cell_m: float):
        self.cell_m = float(cell_m)
        self.dims = tuple(int(np.ceil(b / cell_m)) for b in bounds_m)
        self.ncell = int(np.prod(self.dims))

    def cell_ijk(self, pos):
        ijk = xp.floor(pos / self.cell_m).astype(xp.int64)
        return xp.clip(ijk, 0, xp.asarray(self.dims, dtype=xp.int64) - 1)

    def flat(self, ijk):
        return (ijk[..., 0] * self.dims[1] + ijk[..., 1]) * self.dims[2] + ijk[..., 2]

    def build(self, pos):
        """-> dict(ijk, cid, counts, starts, order). order[starts[c]:starts[c]+counts[c]] = ids in cell c."""
        n = len(pos)
        ijk = self.cell_ijk(pos)
        cid = self.flat(ijk)
        counts = xp.bincount(cid, minlength=self.ncell)               # histogram
        starts = xp.cumsum(counts) - counts                           # exclusive scan
        # stable scatter of ids by cell: sort composite keys (cell, id) -> deterministic on numpy and cupy
        keys = cid * n + xp.arange(n, dtype=xp.int64)
        order = (xp.sort(keys) % n).astype(xp.int64)
        return dict(ijk=ijk, cid=cid, counts=counts, starts=starts, order=order)


def _d2(a, b):
    d = a - b
    return d[..., 0] * d[..., 0] + d[..., 1] * d[..., 1] + d[..., 2] * d[..., 2]


def pairs_grid(pos, r: float, grid: Grid):
    """All pairs (i<j) with |pi-pj|^2 < r^2 -> (i, j, d2), sorted by (i, j)."""
    pos = xp.asarray(pos, dtype=xp.float32)
    n = len(pos)
    if n < 2:
        z = xp.zeros(0, dtype=xp.int64)
        return z, z, xp.zeros(0, dtype=xp.float32)
    g = grid.build(pos)
    dims = xp.asarray(grid.dims, dtype=xp.int64)
    ids = xp.arange(n, dtype=xp.int64)
    I, J, D = [], [], []
    for off in xp.asarray(OFFSETS):
        nijk = g["ijk"] + off
        ok = ((nijk >= 0) & (nijk < dims)).all(axis=1)
        ncid = grid.flat(xp.where(ok[:, None], nijk, 0))
        cnt = xp.where(ok, g["counts"][ncid], 0)
        total = int(cnt.sum())
        if total == 0:
            continue
        i_rep = xp.repeat(ids, cnt)
        base = xp.repeat(g["starts"][ncid], cnt)
        within = xp.arange(total, dtype=xp.int64) - xp.repeat(xp.cumsum(cnt) - cnt, cnt)
        j = g["order"][base + within]
        keep = i_rep < j
        i_rep, j = i_rep[keep], j[keep]
        d2 = _d2(pos[i_rep], pos[j])
        keep = d2 < r * r
        I.append(i_rep[keep]); J.append(j[keep]); D.append(d2[keep])
    if not I:
        z = xp.zeros(0, dtype=xp.int64)
        return z, z, xp.zeros(0, dtype=xp.float32)
    i, j, d2 = xp.concatenate(I), xp.concatenate(J), xp.concatenate(D)
    o = xp.argsort(i * n + j)
    return i[o], j[o], d2[o]


def pairs_naive(pos, r: float, chunk: int = 256):
    """Reference O(N^2) search, same output as pairs_grid."""
    pos = xp.asarray(pos, dtype=xp.float32)
    n = len(pos)
    I, J, D = [], [], []
    for s in range(0, n, chunk):
        a = pos[s:s + chunk, None, :]
        d2 = _d2(a, pos[None, :, :])                             # [c, n]
        ii, jj = xp.nonzero(d2 < r * r)
        ii = ii + s
        keep = ii < jj
        ii, jj = ii[keep], jj[keep]
        I.append(ii); J.append(jj); D.append(_d2(pos[ii], pos[jj]))
    i, j, d2 = xp.concatenate(I), xp.concatenate(J), xp.concatenate(D)
    o = xp.argsort(i * n + j)
    return i[o], j[o], d2[o]


# ------------------------------------------------------------------------------------ GPU kernel
SEPARATION_KERNEL_SRC = r"""
extern "C" __global__
void separation(const float* __restrict__ pos, const long long* __restrict__ order,
                const long long* __restrict__ starts, const long long* __restrict__ counts,
                float* __restrict__ acc, unsigned char* __restrict__ near_flag,
                int n, float cell, int nx, int ny, int nz, float r_sep, float k_sep, float d_near)
{
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    if (i >= n) return;
    float px = pos[3*i], py = pos[3*i+1], pz = pos[3*i+2];
    int cx = min(max((int)floorf(px / cell), 0), nx - 1);
    int cy = min(max((int)floorf(py / cell), 0), ny - 1);
    int cz = min(max((int)floorf(pz / cell), 0), nz - 1);
    float ax = 0.f, ay = 0.f, az = 0.f;
    unsigned char near = 0;
    for (int dz = -1; dz <= 1; ++dz) for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
        int X = cx + dx, Y = cy + dy, Z = cz + dz;
        if (X < 0 || Y < 0 || Z < 0 || X >= nx || Y >= ny || Z >= nz) continue;
        long long c = ((long long)X * ny + Y) * nz + Z;
        long long s = starts[c], e = s + counts[c];
        for (long long k = s; k < e; ++k) {
            int j = (int)order[k];
            if (j == i) continue;
            float rx = px - pos[3*j], ry = py - pos[3*j+1], rz = pz - pos[3*j+2];
            float d2 = rx*rx + ry*ry + rz*rz;
            if (d2 < r_sep * r_sep) {
                float d = fmaxf(sqrtf(d2), 0.1f);
                float m = k_sep * (1.f - d / r_sep) / d;
                ax += m * rx; ay += m * ry; az += m * rz;
                if (d2 < d_near * d_near) near = 1;
            }
        }
    }
    acc[3*i] = ax; acc[3*i+1] = ay; acc[3*i+2] = az;
    near_flag[i] = near;
}
"""
_kernel = None


def separation_gpu(pos, grid: Grid, r_sep: float, k_sep: float, d_near: float):
    """Fused neighbour loop on the GPU -> (accel [n,3] float32, near_flag [n] bool). Needs cupy."""
    global _kernel
    if not is_gpu:
        raise RuntimeError("separation_gpu needs the cupy backend (no CUDA device here)")
    if _kernel is None:
        _kernel = xp.RawKernel(SEPARATION_KERNEL_SRC, "separation")
    pos = xp.ascontiguousarray(pos, dtype=xp.float32)
    n = len(pos)
    g = grid.build(pos)
    acc = xp.zeros((n, 3), dtype=xp.float32)
    near = xp.zeros(n, dtype=xp.uint8)
    block = 128
    _kernel(((n + block - 1) // block,), (block,),
            (pos, g["order"], g["starts"], g["counts"], acc, near, np.int32(n), np.float32(grid.cell_m),
             np.int32(grid.dims[0]), np.int32(grid.dims[1]), np.int32(grid.dims[2]),
             np.float32(r_sep), np.float32(k_sep), np.float32(d_near)))
    return acc, near.astype(bool)
