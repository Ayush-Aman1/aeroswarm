"""Array backend: `xp` is cupy when a CUDA device works, numpy otherwise.

AEROSWARM_FORCE_CPU=1 forces numpy. If cupy is installed but the device fails to initialise the
failure is logged loudly (ERROR); execution only continues on numpy when
AEROSWARM_ALLOW_CPU_FALLBACK is not "0" (default: allowed). Missing cupy (e.g. on a Mac) is expected
and only logged at INFO.
"""
from __future__ import annotations

import logging
import os

import numpy as np
import scipy.ndimage as _scipy_ndimage

log = logging.getLogger("aeroswarm.backend")


def _flag(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("", "0", "false", "no")


def select_backend(force_cpu: bool | None = None, allow_fallback: bool | None = None):
    """Return (xp, ndimage, name). Exposed separately so tests can exercise the selection logic."""
    if force_cpu is None:
        force_cpu = _flag("AEROSWARM_FORCE_CPU")
    if allow_fallback is None:
        allow_fallback = _flag("AEROSWARM_ALLOW_CPU_FALLBACK", "1")
    if force_cpu:
        log.info("AEROSWARM_FORCE_CPU set: using numpy")
        return np, _scipy_ndimage, "numpy"
    try:
        import cupy  # type: ignore
    except ImportError:
        log.info("cupy not installed: using numpy")
        return np, _scipy_ndimage, "numpy"
    try:
        if cupy.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError("no CUDA device visible")
        cupy.zeros(1).sum().item()  # forces context creation + a real kernel launch
        import cupyx.scipy.ndimage as cndi  # type: ignore

        log.info("using cupy on %s", cupy.cuda.runtime.getDeviceProperties(0)["name"])
        return cupy, cndi, "cupy"
    except Exception as exc:  # noqa: BLE001 - we want to log whatever went wrong
        log.error("GPU BACKEND FAILED (%s: %s)", type(exc).__name__, exc)
        if not allow_fallback:
            raise
        log.error("CONTINUING ON NUMPY because AEROSWARM_ALLOW_CPU_FALLBACK is not 0")
        return np, _scipy_ndimage, "numpy"


xp, ndi, backend_name = select_backend()
is_gpu = backend_name == "cupy"


def to_numpy(a):
    """Copy any xp array (or array-like) to a host numpy array."""
    if is_gpu and not isinstance(a, np.ndarray):
        return xp.asnumpy(a)
    return np.asarray(a)
