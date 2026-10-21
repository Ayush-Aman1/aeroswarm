"""Tier 2 batch: for each layout preset x wind direction -> case file -> FluidX3D run -> VTK -> float16 .npy fields.

    python -m tools.fluidx3d.batch --dry-run                       # list jobs, VRAM and disk budget, change nothing
    python -m tools.fluidx3d.batch                                 # the 3 layout presets x 8 directions (resumable)
    python -m tools.fluidx3d.batch --scenarios scenarios/block_small.json --directions 0 90 --dx 4

FluidX3D itself is never modified in place: the tree is copied to third_party/FluidX3D_aeroswarm/, src/setup.cpp is
replaced by tools/fluidx3d/setup.cpp.template and the extension switches in src/defines.hpp are patched (see
patch_defines). The binary is built once; every job only rewrites aeroswarm_case.txt next to it.
`--solver fake` skips FluidX3D and writes VTKs from the synthetic wind - TEST ONLY, meta.source says so.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from engine.scenario.schema import load_scenario
from tools.fluidx3d.case import DIRECTIONS_DEG, Case, field_bytes
from tools.fluidx3d.convert import convert_run, write_vtk_fluidx3d

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).with_name("setup.cpp.template")
BUDGET_BYTES = 3 * 10**9
DEFAULT_PRESETS = ("block_small", "street_canyon", "tower_cluster")    # the three layouts; stress_1k reuses block_small's buildings


def patch_defines(text: str) -> str:
    """Extension switches needed by the setup: D3Q19, SRT, FP16S, EQUILIBRIUM_BOUNDARIES, SUBGRID on; BENCHMARK off."""
    def on(t, name):
        return re.sub(rf"^//\s*#define {name}\b", f"#define {name}", t, flags=re.M)
    def off(t, name):
        return re.sub(rf"^#define {name}\b", f"//#define {name}", t, flags=re.M)
    for n in ("EQUILIBRIUM_BOUNDARIES", "SUBGRID", "FP16S", "D3Q19", "SRT"):
        text = on(text, n)
    for n in ("BENCHMARK", "INTERACTIVE_GRAPHICS", "GRAPHICS", "FP16C"):
        text = off(text, n)
    return text


def prepare_tree(upstream: Path, work: Path, benchmark: bool = False) -> Path:
    if not (upstream / "src" / "lbm.cpp").exists():
        raise FileNotFoundError(f"FluidX3D clone not found at {upstream}: git clone --depth 1 "
                                f"https://github.com/ProjectPhysX/FluidX3D.git {upstream}")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    shutil.copytree(upstream / "src", work / "src")
    for f in ("FluidX3D.sln", "FluidX3D.vcxproj", "makefile", "make.sh", "LICENSE.md"):
        if (upstream / f).exists():
            shutil.copy2(upstream / f, work / f)
    d = (work / "src" / "defines.hpp").read_text()
    if benchmark:       # keep upstream BENCHMARK setup (peak MLUPs) but with FP16S, as the guide's benchmark mode
        d = re.sub(r"^//\s*#define FP16S\b", "#define FP16S", d, flags=re.M)
    else:
        d = patch_defines(d)
        shutil.copy2(TEMPLATE, work / "src" / "setup.cpp")
    (work / "src" / "defines.hpp").write_text(d)
    return work


def build(work: Path) -> Path:
    """Compile with the platform's recipe (same flags as FluidX3D's make.sh / solution). Returns the binary."""
    system = platform.system()
    (work / "bin").mkdir(exist_ok=True)
    if system == "Windows":
        vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
        msbuild = None
        if vswhere.exists():
            out = subprocess.run([str(vswhere), "-latest", "-requires", "Microsoft.Component.MSBuild", "-find",
                                  r"MSBuild\**\Bin\MSBuild.exe"], capture_output=True, text=True).stdout.split("\n")[0]
            msbuild = out.strip() or None
        msbuild = msbuild or shutil.which("msbuild")
        if not msbuild:
            raise RuntimeError("MSBuild not found: install Visual Studio 2022 with 'Desktop development with C++'")
        cmd = [msbuild, "FluidX3D.sln", "/p:Configuration=Release", "/p:Platform=x64", "/p:PlatformToolset=v143", "/m", "/v:m"]
        exe = work / "bin" / "FluidX3D.exe"
    else:
        srcs = sorted(str(p) for p in (work / "src").glob("*.cpp"))
        base = ["g++", *srcs, "-o", "bin/FluidX3D", "-std=c++17", "-pthread", "-O", "-Wno-comment", "-I./src/OpenCL/include"]
        cmd = base + (["-framework", "OpenCL"] if system == "Darwin" else ["-L./src/OpenCL/lib", "-lOpenCL"])
        exe = work / "bin" / "FluidX3D"
    print("building:", " ".join(cmd[:4]), "...", flush=True)
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    (work / "build.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0 or not exe.exists():
        raise RuntimeError(f"FluidX3D build failed (log: {work / 'build.log'}):\n" + (r.stdout + r.stderr)[-1500:])
    return exe


def run_real(exe: Path, case: Case, theta: float, vtk_dir: Path, log: Path, timeout_s: float) -> None:
    vtk_dir.mkdir(parents=True, exist_ok=True)
    for f in vtk_dir.glob("*"):
        f.unlink()
    (exe.parent / "aeroswarm_case.txt").write_text(case.case_text(theta, vtk_dir.resolve()))
    with open(log, "w") as fh:
        r = subprocess.run([str(exe)], cwd=exe.parent, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout_s)
    if not (vtk_dir / "DONE").exists():
        raise RuntimeError(f"FluidX3D did not finish (exit {r.returncode}); see {log}")


def run_fake(case: Case, theta: float, vtk_dir: Path) -> None:
    """TEST ONLY: VTK snapshots sampled from the Tier 3 synthetic wind, rotated into the lattice frame."""
    from engine.wind.synthetic import SyntheticWind
    vtk_dir.mkdir(parents=True, exist_ok=True)
    w = SyntheticWind(dt_s=0.05, dx_m=case.dx_m)
    w.reset(case.layout, case.inflow.__class__(case.inflow.speed_ms, theta, case.inflow.roughness))
    nx, ny, nz = case.shape
    xs, ys, zs = ((np.arange(n) + 0.5) * case.dx_m for n in (nx, ny, nz))
    X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
    cx, cy = np.vectorize(lambda a, b: case.to_city((a, b), theta))(X, Y)
    pts = np.stack([cx.ravel(), cy.ravel(), Z.ravel()], axis=1)
    for k in range(case.n_snaps):
        w.step(int(case.snap_interval_s / 0.05))
        v = np.asarray(w.sample(pts)).reshape(nx, ny, nz, 3)
        t = np.deg2rad(theta)       # city -> dom velocity rotation by -theta
        u = np.stack([np.cos(t) * v[..., 0] + np.sin(t) * v[..., 1], -np.sin(t) * v[..., 0] + np.cos(t) * v[..., 1],
                      v[..., 2]], axis=-1)
        write_vtk_fluidx3d(vtk_dir / f"u-{k:09d}.vtk", u.astype(np.float32), case.dx_m)
    (vtk_dir / "DONE").write_text("fake\n")


def jobs_for(scenarios: list[Path], directions, dx_m: float, zmax: float):
    for sp in scenarios:
        sc = load_scenario(sp)
        for th in directions:
            yield sc, Case(sc.layout, sc.inflow, dx_m=dx_m), float(th)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", nargs="*", default=None, help="default: scenarios/*.json")
    ap.add_argument("--directions", nargs="*", type=float, default=list(DIRECTIONS_DEG))
    ap.add_argument("--dx", type=float, default=2.0)
    ap.add_argument("--zmax", type=float, default=80.0)
    ap.add_argument("--out", default=str(ROOT / "data" / "fields"))
    ap.add_argument("--fluidx3d", default=str(ROOT / "third_party" / "FluidX3D"), help="clone of ProjectPhysX/FluidX3D")
    ap.add_argument("--work", default=str(ROOT / "third_party" / "FluidX3D_aeroswarm"))
    ap.add_argument("--binary", default=None, help="skip the build and use this FluidX3D binary (made from this template)")
    ap.add_argument("--solver", choices=["real", "fake"], default="real")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="recompute jobs that already have fields")
    ap.add_argument("--limit", type=int, default=None, help="stop after N jobs (testing)")
    ap.add_argument("--timeout-min", type=float, default=90.0, help="per-job wall-clock limit")
    ap.add_argument("--keep-vtk", action="store_true")
    ap.add_argument("--build-only", action="store_true", help="prepare + build the patched FluidX3D tree and exit")
    a = ap.parse_args(argv)
    if a.build_only:
        exe = build(prepare_tree(Path(a.fluidx3d), Path(a.work)))
        print("FluidX3D binary:", exe)
        return 0

    scen = [Path(p) for p in a.scenarios] if a.scenarios else [ROOT / "scenarios" / f"{n}.json" for n in DEFAULT_PRESETS]
    jobs = list(jobs_for(scen, a.directions, a.dx, a.zmax))
    out = Path(a.out)
    total = sum(field_bytes(sc.layout, a.dx, a.zmax) for sc, _, _ in jobs)
    print(f"{len(jobs)} job(s): {len(scen)} preset(s) x {len(a.directions)} direction(s); dx={a.dx} m, zmax={a.zmax} m")
    for sc, case, th in jobs[:1]:
        print(f"  lattice {case.shape} = {case.cells() / 1e6:.1f} M cells, ~{case.gpu_mb():.0f} MB VRAM (FP16S), "
              f"{case.total_steps()} steps, dt = {case.dt_s * 1e3:.2f} ms, lattice u_ref = {case.lbm_u_ref:.4f}")
        case.check()
    print(f"  field budget: {total / 1e9:.2f} GB of float16 frames (limit {BUDGET_BYTES / 1e9:.0f} GB)")
    if total > BUDGET_BYTES:
        print("ERROR: over the 3 GB budget - reduce --zmax, directions or presets", file=sys.stderr)
        return 2
    if a.dry_run:
        for sc, _, th in jobs:
            print(f"  would run {sc.name} @ {th:g} deg -> {out / sc.name / ('dir_%03d' % th)}")
        return 0

    exe = None
    if a.solver == "real":
        exe = (Path(a.binary) if a.binary else build(prepare_tree(Path(a.fluidx3d), Path(a.work)))).resolve()
        print("FluidX3D binary:", exe, flush=True)
    work = Path(a.work)
    done = failed = 0
    for n, (sc, case, th) in enumerate(jobs):
        if a.limit is not None and done + failed >= a.limit:
            break
        dest = out / sc.name / f"dir_{int(th):03d}"
        if (dest / "meta.json").exists() and not a.force:
            print(f"[{n + 1}/{len(jobs)}] {sc.name} @ {th:g}: exists, skipping")
            continue
        t0 = time.time()
        vtk = work / "export" / f"{sc.name}_{int(th):03d}"
        log = work / f"run_{sc.name}_{int(th):03d}.log"
        try:
            if a.solver == "real":
                run_real(exe, case, th, vtk, log, a.timeout_min * 60)
            else:
                run_fake(case, th, vtk)
            meta = convert_run(vtk, dest, case, th, sc.name, a.zmax, source="fluidx3d" if a.solver == "real" else "FAKE-TEST-ONLY")
            if not a.keep_vtk:
                shutil.rmtree(vtk, ignore_errors=True)
            done += 1
            print(f"[{n + 1}/{len(jobs)}] {sc.name} @ {th:g} deg: PASS {meta['n_frames']} frames, {time.time() - t0:.0f} s", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[{n + 1}/{len(jobs)}] {sc.name} @ {th:g} deg: FAIL {exc}", flush=True)
    size = sum(f.stat().st_size for f in out.rglob("*.npy")) if out.exists() else 0
    print(f"done {done}, failed {failed}; fields on disk: {size / 1e9:.2f} GB (limit 3 GB)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
